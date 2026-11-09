#!/usr/bin/env python3
"""Build a lead list of Ghanaian real estate agencies with Scrapling.

Rules enforced in code:
  * robots.txt is checked before every request (pages it disallows are skipped).
  * Plain HTTP fetches only (no stealth/anti-bot bypass, no logins); pages that
    redirect to a login/sign-in URL are skipped.
  * Nothing is guessed: a field is filled only if the value appears on a page,
    and every field records the URL it came from.
  * Phone/email are taken only from the agency's own website, or from a
    directory page that is an agency/company profile (never an individual
    agent's listing).
  * Duplicates across sources are merged by website domain / normalised name.

Usage:  python3 scrape_agencies.py [--limit 25] [--out ghana_real_estate_agencies.csv]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse, unquote
from urllib import robotparser

from scrapling.fetchers import Fetcher

UA = "KortexaLeadBot/1.0 (+business contact research; respects robots.txt)"
DELAY = 2.0  # seconds between requests to the same host

# ---------------------------------------------------------------- sources ---
# Directory seed pages. `profile` is a regex for links to agency/company
# profile pages found on the seed page.
DIRECTORIES = [
    {"name": "GREDA", "seeds": ["https://greda.com.gh/members/", "https://greda.com.gh/our-members/"],
     "profile": r"greda\.com\.gh/(member|members|directory)/[^/?#]+/?$"},
    {"name": "meqasa", "seeds": ["https://meqasa.com/real-estate-agents-in-ghana",
                                 "https://meqasa.com/agents"],
     "profile": r"meqasa\.com/(agents?|companies|real-estate-agents?)/[^?#]+"},
    {"name": "jiji", "seeds": ["https://jiji.com.gh/real-estate-agents"],
     "profile": r"jiji\.com\.gh/(shop|company)/[^?#]+"},
    {"name": "tonaton", "seeds": ["https://tonaton.com/real-estate-agents"],
     "profile": r"tonaton\.com/(shop|company)/[^?#]+"},
]

CONTACT_PATHS = ["", "contact", "contact-us", "contactus", "about", "about-us"]

SOCIAL = {
    "facebook": r"(?:facebook\.com|fb\.com)/(?!sharer|share|dialog|plugins|tr\b)[^\s\"'<>?#]+",
    "instagram": r"instagram\.com/(?!p/|share)[^\s\"'<>?#]+",
    "linkedin": r"linkedin\.com/(?:company|school)/[^\s\"'<>?#]+",
    "tiktok": r"tiktok\.com/@[^\s\"'<>?#]+",
    "x": r"(?:twitter\.com|x\.com)/(?!intent|share|home)[A-Za-z0-9_]{1,15}",
}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Ghana numbers: +233 / 233 / 0 followed by 9 digits (spaces/dashes allowed)
PHONE_RE = re.compile(r"(?:\+?233|0)[\s-]?\(?\d{2}\)?[\s-]?\d{3}[\s-]?\d{4}")
WA_RE = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=)\+?(\d{9,15})")
LOGIN_HINT = re.compile(r"/(login|signin|sign-in|account/login|auth)\b", re.I)
AGENCY_HINT = re.compile(r"\b(realty|real estate|properties|property|estates?|homes|"
                         r"developers?|agency|housing|ltd|limited|company)\b", re.I)
CITIES = ["Accra", "Kumasi", "Tema", "Takoradi", "Cape Coast", "Tamale", "Ho", "Koforidua",
          "East Legon", "Airport Residential", "Cantonments", "Spintex", "Osu", "Labone",
          "Dzorwulu", "Adenta", "Kasoa", "Madina", "Achimota", "Sunyani", "Sakumono",
          "Teshie", "Nungua", "Dansoman", "Weija", "Oyarifa", "Trasacco", "Roman Ridge"]

FIELDS = ["agency_name", "city_area", "website", "phone", "whatsapp", "email",
          "facebook", "instagram", "linkedin", "tiktok", "x"]


@dataclass
class Agency:
    data: dict = field(default_factory=dict)      # field -> value
    sources: dict = field(default_factory=dict)   # field -> url

    def put(self, key, value, url):
        if value and not self.data.get(key):
            self.data[key] = value.strip()
            self.sources[key] = url

    def row(self):
        r = {k: self.data.get(k, "") for k in FIELDS}
        for k in FIELDS:
            r[f"{k}_source"] = self.sources.get(k, "")
        return r


# ---------------------------------------------------------------- fetching --
_robots: dict[str, robotparser.RobotFileParser | None] = {}
_last_hit: dict[str, float] = {}


def allowed(url: str) -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = robotparser.RobotFileParser()
        try:
            r = Fetcher.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=20)
            if r.status == 200:
                rp.parse(r.body.decode("utf-8", "ignore").splitlines() if isinstance(r.body, bytes)
                         else str(r.body).splitlines())
            else:
                rp.parse([])  # no robots.txt -> everything allowed
            _robots[base] = rp
        except Exception as e:  # unreachable: treat as not allowed
            print(f"  ! robots.txt unreachable for {base}: {e}", file=sys.stderr)
            _robots[base] = None
    rp = _robots[base]
    return bool(rp) and rp.can_fetch(UA, url)


def fetch(url: str):
    if not allowed(url):
        print(f"  - skipped (robots.txt / unreachable): {url}", file=sys.stderr)
        return None
    host = urlparse(url).netloc
    wait = DELAY - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()
    try:
        page = Fetcher.get(url, headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
    except Exception as e:
        print(f"  ! fetch failed {url}: {e}", file=sys.stderr)
        return None
    if page.status != 200 or LOGIN_HINT.search(str(page.url)):
        print(f"  - skipped (status {page.status} / login): {url}", file=sys.stderr)
        return None
    return page


# -------------------------------------------------------------- extraction --
def norm_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw)
    if d.startswith("0") and len(d) == 10:
        d = "233" + d[1:]
    return "+" + d if d.startswith("233") and len(d) == 12 else ""


def page_html(page) -> str:
    return page.html_content if hasattr(page, "html_content") else str(page.body)


def extract_contacts(page, url: str, ag: Agency, allow_contacts: bool, own_domain: str = ""):
    html = page_html(page)
    hrefs = [unquote(h) for h in page.css("a::attr(href)").getall()]
    blob = html + "\n" + "\n".join(hrefs)

    for key, pat in SOCIAL.items():
        m = re.search(pat, blob, re.I)
        if m:
            ag.put(key, "https://" + m.group(0).rstrip("/\\").split("\\")[0], url)

    if not allow_contacts:
        return
    m = WA_RE.search(blob)
    if m:
        ag.put("whatsapp", "+" + m.group(1), url)
    tels = [norm_phone(h[4:]) for h in hrefs if h.lower().startswith("tel:")]
    tels += [norm_phone(x) for x in PHONE_RE.findall(page.get_all_text(separator=" "))]
    tels = [t for t in tels if t]
    if tels:
        ag.put("phone", tels[0], url)
    mails = [h[7:].split("?")[0] for h in hrefs if h.lower().startswith("mailto:")]
    mails += EMAIL_RE.findall(html)
    mails = [e for e in mails if not re.search(r"\.(png|jpg|jpeg|gif|webp|svg)$|example\.|sentry|wixpress", e, re.I)]
    # Prefer an address on the agency's own domain (a business mailbox).
    if own_domain:
        mails.sort(key=lambda e: 0 if e.lower().endswith(own_domain) else 1)
    if mails:
        ag.put("email", mails[0].lower(), url)


def find_city(text: str) -> str:
    for c in CITIES:
        if re.search(rf"\b{re.escape(c)}\b", text):
            return c
    return ""


def external_site(page, dir_host: str) -> str:
    skip = ("facebook.", "instagram.", "twitter.", "x.com", "linkedin.", "tiktok.", "youtube.",
            "wa.me", "whatsapp.", "google.", "apple.com", dir_host)
    for h in page.css("a::attr(href)").getall():
        if h.startswith("http") and not any(s in h for s in skip):
            p = urlparse(h)
            return f"{p.scheme}://{p.netloc}"
    return ""


def name_of(page) -> str:
    for sel in ("h1::text", "meta[property='og:title']::attr(content)", "title::text"):
        v = page.css(sel).get()
        if v and v.strip():
            return re.split(r"\s[|\-–]\s", v.strip())[0]
    return ""


# ------------------------------------------------------------------ crawl ---
def from_directories(limit: int) -> list[Agency]:
    found: list[Agency] = []
    for d in DIRECTORIES:
        for seed in d["seeds"]:
            page = fetch(seed)
            if not page:
                continue
            links = {urljoin(seed, h) for h in page.css("a::attr(href)").getall()}
            links = [l for l in links if re.search(d["profile"], l)]
            print(f"[{d['name']}] {seed}: {len(links)} profile links", file=sys.stderr)
            for link in sorted(links):
                if len(found) >= limit * 3:  # over-collect; dedupe trims later
                    break
                prof = fetch(link)
                if not prof:
                    continue
                name = name_of(prof)
                if not name or not AGENCY_HINT.search(name + " " + prof.get_all_text()[:400]):
                    continue  # not clearly an agency/company profile
                ag = Agency()
                ag.put("agency_name", name, link)
                ag.put("city_area", find_city(prof.get_all_text(separator=" ")), link)
                ag.put("website", external_site(prof, urlparse(link).netloc), link)
                # Directory contacts only for company profiles (GREDA = company register).
                extract_contacts(prof, link, ag, allow_contacts=True)
                found.append(ag)
            break  # first working seed per directory is enough
    return found


def enrich_from_website(ag: Agency):
    site = ag.data.get("website")
    if not site:
        return
    domain = urlparse(site).netloc.removeprefix("www.")
    for path in CONTACT_PATHS:
        url = urljoin(site.rstrip("/") + "/", path)
        page = fetch(url)
        if not page:
            continue
        # Own-site values take priority over directory values.
        tmp = Agency()
        extract_contacts(page, url, tmp, allow_contacts=True, own_domain=domain)
        tmp.put("city_area", find_city(page.get_all_text(separator=" ")), url)
        for k, v in tmp.data.items():
            if k in ("phone", "email", "whatsapp") and ag.sources.get(k, "").find(domain) == -1:
                ag.data.pop(k, None)
            ag.put(k, v, tmp.sources[k])
        if all(ag.data.get(k) for k in ("phone", "email")):
            break


def key_of(ag: Agency) -> str:
    site = ag.data.get("website", "")
    if site:
        return urlparse(site).netloc.removeprefix("www.").lower()
    n = ag.data.get("agency_name", "").lower()
    n = re.sub(r"\b(ltd|limited|llc|co|company|gh|ghana|the)\b|[^a-z0-9 ]", " ", n)
    return " ".join(n.split())


def dedupe(agencies: list[Agency]) -> list[Agency]:
    out: dict[str, Agency] = {}
    names: dict[str, str] = {}
    for ag in agencies:
        k = key_of(ag)
        nk = key_of(Agency({"agency_name": ag.data.get("agency_name", "")}))
        k = names.get(nk, k)
        if k in out:
            for f, v in ag.data.items():
                out[k].put(f, v, ag.sources[f])
        else:
            out[k] = ag
            names[nk] = k
    return list(out.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--out", default="ghana_real_estate_agencies.csv")
    a = ap.parse_args()

    agencies = dedupe(from_directories(a.limit))
    # Prefer agencies with a website (own-site contacts are the most reliable).
    agencies.sort(key=lambda g: 0 if g.data.get("website") else 1)
    agencies = agencies[: a.limit]
    for ag in agencies:
        print(f"  enriching {ag.data.get('agency_name')}", file=sys.stderr)
        enrich_from_website(ag)
    agencies = dedupe(agencies)

    cols = FIELDS + [f"{k}_source" for k in FIELDS]
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for ag in agencies:
            w.writerow(ag.row())
    print(f"wrote {len(agencies)} agencies to {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
