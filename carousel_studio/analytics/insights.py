"""Pull Instagram Graph API insights for published drafts and keep time-stamped snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    import httpx
except ImportError:  # the httpx2 distribution
    import httpx2 as httpx  # type: ignore

from .. import store
from ..config import get_settings
from . import paths

METRICS = ["reach", "saved", "shares", "likes", "comments", "profile_visits",
           "follows", "total_interactions", "views"]


class InsightsError(RuntimeError):
    pass


class InsightsPermissionError(InsightsError):
    pass


def _creds():
    s = get_settings()
    if not s.ig_user_id:
        raise InsightsError("IG_USER_ID is not set")
    if not s.ig_access_token:
        raise InsightsError("IG_ACCESS_TOKEN is not set")
    return s, s.ig_user_id, s.ig_access_token


def _get(client, url: str, token: str, params: Optional[dict] = None) -> dict:
    try:
        r = client.get(url, params=params or {}, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        raise InsightsError(f"Network error calling Instagram: {e}") from e
    try:
        body = r.json()
    except Exception:
        body = {}
    if r.status_code >= 400 or (isinstance(body, dict) and "error" in body):
        err = body.get("error", {}) if isinstance(body, dict) else {}
        msg = err.get("error_user_msg") or err.get("message") or r.text[:300]
        code = err.get("code")
        if err.get("type") == "OAuthException" and code in (10, 200):
            raise InsightsPermissionError(
                "Instagram refused the insights request (OAuthException code "
                f"{code}). The access token needs the 'instagram_manage_insights' permission "
                f"(plus instagram_basic). Re-generate the token with it. Details: {msg}")
        if code in (10, 200):
            raise InsightsPermissionError(
                f"Instagram permission error (code {code}): the token probably lacks "
                f"'instagram_manage_insights'. Details: {msg}")
        e = InsightsError(f"Instagram API error {r.status_code}: {msg}" + (f" (code {code})" if code else ""))
        e.code = code  # type: ignore[attr-defined]
        raise e
    return body


def _parse_insights(body: dict) -> dict:
    out = {}
    for item in body.get("data", []) or []:
        name = item.get("name")
        val = None
        if "total_value" in item:
            val = item["total_value"].get("value")
        elif item.get("values"):
            val = item["values"][0].get("value")
        if name:
            out[name] = val
    return out


def fetch_insights(draft, client=None, metrics=None) -> dict:
    """Metrics for one published draft. Unsupported metrics come back as None and are listed in 'missing'."""
    media_id = getattr(draft, "ig_media_id", None)
    if not media_id:
        raise InsightsError("Draft has no ig_media_id (it has not been published)")
    s, _uid, tok = _creds()
    base = f"https://graph.facebook.com/{s.graph_api_version}"
    metrics = list(metrics or METRICS)
    own = client is None
    c = client or httpx.Client(timeout=30)
    try:
        got: dict = {}
        try:
            got = _parse_insights(_get(c, f"{base}/{media_id}/insights", tok, {"metric": ",".join(metrics)}))
        except InsightsPermissionError:
            raise
        except InsightsError:
            for m in metrics:
                try:
                    got.update(_parse_insights(_get(c, f"{base}/{media_id}/insights", tok, {"metric": m})))
                except InsightsPermissionError:
                    raise
                except InsightsError:
                    pass
        result = {m: got.get(m) for m in metrics}
        try:
            fb = _get(c, f"{base}/{media_id}", tok, {"fields": "like_count,comments_count,timestamp"})
        except InsightsPermissionError:
            raise
        except InsightsError:
            fb = {}
        if result.get("likes") is None and fb.get("like_count") is not None:
            result["likes"] = fb["like_count"]
        if result.get("comments") is None and fb.get("comments_count") is not None:
            result["comments"] = fb["comments_count"]
        result["timestamp"] = fb.get("timestamp")
        result["missing"] = [m for m in metrics if result.get(m) is None]
        return result
    finally:
        if own:
            c.close()


def parse_time(s) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        dt = s
    else:
        try:
            dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except ValueError:
            try:  # Graph API style +0000
                dt = datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%S%z")
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def posted_at(draft, fetched_ts=None) -> Optional[datetime]:
    return (parse_time(getattr(draft, "published_at", None)) or parse_time(fetched_ts)
            or parse_time(getattr(draft, "updated_at", None)))


def snapshot_all(now: Optional[datetime] = None, client=None) -> dict:
    """Snapshot every published draft into data/analytics/metrics.json."""
    now = now or datetime.now(timezone.utc)
    data = paths.read_json("metrics.json", {})
    done, errors = [], {}
    own = client is None
    c = client or httpx.Client(timeout=30)
    try:
        for d in store.list_drafts():
            if getattr(d.status, "value", d.status) != "published" or not d.ig_media_id:
                continue
            try:
                m = fetch_insights(d, client=c)
            except InsightsPermissionError:
                raise
            except InsightsError as e:
                errors[d.id] = str(e)
                continue
            pa = posted_at(d, m.get("timestamp"))
            rec = data.setdefault(d.id, {"snapshots": []})
            rec["style"] = d.style
            rec["media_id"] = d.ig_media_id
            rec["experiment_arm"] = getattr(d, "experiment_arm", None)
            rec["posted_at"] = pa.isoformat() if pa else None
            hours = round((now - pa).total_seconds() / 3600, 2) if pa else None
            metrics = {k: v for k, v in m.items() if k not in ("timestamp", "missing")}
            rec["snapshots"].append({"at": now.isoformat(timespec="seconds"),
                                     "hours_since_post": hours, "metrics": metrics,
                                     "missing": m["missing"]})
            done.append(d.id)
    finally:
        if own:
            c.close()
    paths.write_json("metrics.json", data)
    return {"snapshotted": done, "errors": errors}


def account_snapshot(now: Optional[datetime] = None, client=None) -> dict:
    now = now or datetime.now(timezone.utc)
    s, uid, tok = _creds()
    own = client is None
    c = client or httpx.Client(timeout=30)
    try:
        body = _get(c, f"https://graph.facebook.com/{s.graph_api_version}/{uid}", tok,
                    {"fields": "followers_count,media_count"})
    finally:
        if own:
            c.close()
    entry = {"at": now.isoformat(timespec="seconds"),
             "followers_count": body.get("followers_count"),
             "media_count": body.get("media_count")}
    hist = paths.read_json("account.json", [])
    hist.append(entry)
    paths.write_json("account.json", hist)
    return entry
