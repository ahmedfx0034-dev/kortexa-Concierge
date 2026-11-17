// /check: one page that tells you, in plain English, whether every part of the
// WhatsApp receptionist is working, and fixes the most common setup gap
// (the WhatsApp account not being connected to the Meta app).

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Calls Meta's Graph API with the receptionist's own token. */
async function graph(fetchImpl, { token, apiVersion }, path, method = "GET") {
  const res = await fetchImpl(`https://graph.facebook.com/${apiVersion}/${path}`, { method, headers: { Authorization: `Bearer ${token}` } });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error?.message || `Meta answered ${res.status}`);
  return json;
}

/** Run every check. Each result: {name, ok: true|false|null, detail, fix?}. null = not checked. */
export async function runChecks({ llm, wa, appSecret, verifyToken, adminPassword, wabaId, version, fetchImpl = globalThis.fetch }) {
  const out = [];
  out.push({ name: "Version running", ok: true, detail: version || "unknown (local)" });

  if (!llm) out.push({ name: "AI (Gemini)", ok: false, detail: "No AI key.", fix: "Add LLM_API_KEY in Render → Environment." });
  else {
    try {
      const t = await llm.chat([{ role: "user", content: "Reply with the word OK." }], { maxTokens: 20, temperature: 0 });
      out.push({ name: "AI (Gemini)", ok: true, detail: `Answered: "${t.trim().slice(0, 40)}"` });
    } catch (e) {
      out.push({ name: "AI (Gemini)", ok: false, detail: e.message, fix: "Check LLM_API_KEY in Render (a fresh key from aistudio.google.com)." });
    }
  }

  const cfg = { token: wa?.token, apiVersion: wa?.apiVersion || "v23.0" };
  if (!wa || wa.dryRun) out.push({ name: "WhatsApp token", ok: false, detail: "WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID is missing.", fix: "Add both in Render → Environment." });
  else {
    try {
      const p = await graph(fetchImpl, cfg, `${wa.phoneNumberId}?fields=display_phone_number,verified_name`);
      out.push({ name: "WhatsApp token", ok: true, detail: `Works for ${p.display_phone_number || "the number"}${p.verified_name ? ` (${p.verified_name})` : ""}.` });
    } catch (e) {
      out.push({ name: "WhatsApp token", ok: false, detail: e.message, fix: "Generate a new token in Meta and paste it into WHATSAPP_TOKEN in Render. If the message mentions the phone number, check WHATSAPP_PHONE_NUMBER_ID." });
    }
  }

  out.push(appSecret
    ? { name: "App secret", ok: true, detail: "Set. If the event list below shows 'rejected', it doesn't match Meta's: copy it again, or delete it to switch the check off." }
    : { name: "App secret", ok: null, detail: "Not set, so messages aren't checked for a Meta signature. That's fine for testing." });
  out.push(verifyToken ? { name: "Webhook verify phrase", ok: true, detail: "Set." } : { name: "Webhook verify phrase", ok: false, detail: "Not set.", fix: "Add WHATSAPP_VERIFY_TOKEN in Render." });
  out.push(adminPassword ? { name: "Admin password", ok: true, detail: "Set." } : { name: "Admin password", ok: false, detail: "Not set." });

  if (!wabaId) out.push({ name: "WhatsApp account connected to the app", ok: null, detail: "Can't check: WHATSAPP_BUSINESS_ACCOUNT_ID isn't set.", fix: "Add WHATSAPP_BUSINESS_ACCOUNT_ID in Render (Meta shows it as 'Messaging account ID' on Step 1)." });
  else if (wa && !wa.dryRun) {
    try {
      const r = await graph(fetchImpl, cfg, `${wabaId}/subscribed_apps`);
      const apps = (r.data || []).map((a) => a.whatsapp_business_api_data?.name || a.whatsapp_business_api_data?.id || "an app");
      out.push(apps.length
        ? { name: "WhatsApp account connected to the app", ok: true, detail: `Connected: ${apps.join(", ")}.` }
        : { name: "WhatsApp account connected to the app", ok: false, detail: "Not connected, so Meta won't send messages to the receptionist.", fix: "Tap the 'Connect WhatsApp to this app' button below.", action: "subscribe" });
    } catch (e) {
      out.push({ name: "WhatsApp account connected to the app", ok: false, detail: e.message, fix: "Check WHATSAPP_BUSINESS_ACCOUNT_ID, and that the token has whatsapp_business_management permission." });
    }
  }
  return out;
}

export async function subscribeApp({ wa, wabaId, fetchImpl = globalThis.fetch }) {
  return graph(fetchImpl, { token: wa.token, apiVersion: wa.apiVersion || "v23.0" }, `${wabaId}/subscribed_apps`, "POST");
}

export function checkPage(results, events, { notice = "" } = {}) {
  const icon = (ok) => (ok === true ? "✅" : ok === false ? "❌" : "⚪");
  const rows = results.map((r) => `<li class="${r.ok === false ? "bad" : ""}"><span>${icon(r.ok)}</span><div><b>${esc(r.name)}</b><p>${esc(r.detail)}</p>${r.fix ? `<p class="fix">👉 ${esc(r.fix)}</p>` : ""}${r.action === "subscribe" ? '<form method="post" action="/check/subscribe"><button>Connect WhatsApp to this app</button></form>' : ""}</div></li>`).join("");
  const ev = events.length
    ? events.slice().reverse().map((e) => `<li><span>${e.ok ? "📩" : "⛔"}</span><div><b>${esc(new Date(e.at).toLocaleString("en-GB", { timeZone: "Africa/Accra", hour: "2-digit", minute: "2-digit", second: "2-digit", day: "numeric", month: "short" }))}</b><p>${esc(e.text)}</p></div></li>`).join("")
    : '<li><span>⚪</span><div><p>Nothing from Meta since the server last started. Send a WhatsApp message to the number, then refresh this page.</p></div></li>';
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Receptionist check</title>
<style>
:root{--bg:#f6f5f1;--card:#fff;--fg:#17201c;--muted:#5f6763;--line:#dedad1;--bad:#b83a28;--accent:#1f6f54;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#101412;--card:#171d1a;--fg:#e7ece9;--muted:#9aa5a0;--line:#2a332f;--bad:#ef7a66;--accent:#5fc59a;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:640px;margin:0 auto;padding:20px max(16px,env(safe-area-inset-left)) 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:24px 0 8px}.sub{color:var(--muted);margin:0 0 12px}
ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
li{display:flex;gap:10px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
li.bad{border-color:var(--bad)}li>span{font-size:18px}li p{margin:2px 0 0;color:var(--muted);overflow-wrap:anywhere}li p.fix{color:var(--fg)}
button{margin-top:8px;font:inherit;padding:8px 14px;border-radius:8px;border:0;background:var(--accent);color:#fff;cursor:pointer}
.notice{background:var(--card);border:1px solid var(--accent);border-radius:10px;padding:10px 12px;margin-bottom:12px}
a{color:var(--accent)}
</style></head><body><main>
<h1>Receptionist check</h1><p class="sub">Refresh this page after changing a setting or sending a test message.</p>
${notice ? `<div class="notice">${esc(notice)}</div>` : ""}
<ul>${rows}</ul>
<h2>Latest deliveries from Meta</h2><ul>${ev}</ul>
<p class="sub" style="margin-top:16px"><a href="/inbox">Open the inbox</a></p>
</main></body></html>`;
}
