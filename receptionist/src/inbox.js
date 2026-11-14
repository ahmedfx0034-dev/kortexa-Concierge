// The agency's inbox page: every WhatsApp chat, bookings, lead summaries,
// and buttons to take over from the AI.

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const when = (t) => (t ? new Date(t).toLocaleString("en-GB", { timeZone: "Africa/Accra", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
const pretty = (n) => { const m = /^233(\d{2})(\d{3})(\d{4})$/.exec(n); return m ? `+233 ${m[1]} ${m[2]} ${m[3]}` : "+" + n; };

function chatCard(c, now) {
  const lastIn = [...c.messages].reverse().find((m) => m.role === "user");
  const windowOpen = lastIn && now - lastIn.at < 86400000;
  const tags = [
    c.needsHuman ? '<span class="tag hot">Needs you</span>' : "",
    c.booking ? '<span class="tag ok">Viewing booked</span>' : "",
    c.aiPaused ? '<span class="tag">AI paused</span>' : '<span class="tag ok">AI answering</span>',
    c.optedOut ? '<span class="tag bad">Opted out</span>' : "",
  ].join("");
  const s = c.summary;
  const summary = s ? `<dl>${[["Budget", s.budget], ["Timeline", s.timeline], ["Payment", s.payment], ["Viewing", s.viewing], ["Lead", s.seriousness], ["Next step", s.next_step]]
    .map(([k, v]) => `<dt>${k}</dt><dd>${esc(v || "—")}</dd>`).join("")}</dl>` : "";
  const booking = c.booking ? `<p class="booking">📅 <b>${esc(c.booking.slot)}</b> · ${esc(c.booking.listing)} · ${esc(c.booking.name)}</p>` : "";
  const msgs = c.messages.slice(-12).map((m) => `<div class="m ${m.role === "user" ? "in" : "out"}">${esc(m.content)}<time>${when(m.at)}</time></div>`).join("");
  const id = esc(c.waId);
  return `<section class="chat" id="c${id}">
  <header><div><b>${esc(c.name || pretty(c.waId))}</b><span>${pretty(c.waId)} · ${when(c.updatedAt)}</span></div><div class="tags">${tags}</div></header>
  ${booking}${summary}
  <details${c.needsHuman ? " open" : ""}><summary>Conversation (${c.messages.length})</summary><div class="msgs">${msgs}</div></details>
  <div class="actions">
    ${c.aiPaused ? `<form method="post" action="/inbox/${id}/resume"><button>Let AI answer again</button></form>` : `<form method="post" action="/inbox/${id}/pause"><button>Pause AI</button></form>`}
    ${c.needsHuman ? `<form method="post" action="/inbox/${id}/done"><button>Mark handled</button></form>` : ""}
  </div>
  ${windowOpen ? `<form method="post" action="/inbox/${id}/reply" class="reply"><input name="text" placeholder="Reply as the agent (pauses the AI)" aria-label="Reply"><button class="primary">Send</button></form>`
    : `<p class="note">More than 24 hours since their last message, so WhatsApp only allows approved template messages. Call them instead.</p>`}
</section>`;
}

export function inboxPage(chats, { agency, notice = "", now = Date.now() }) {
  const needs = chats.filter((c) => c.needsHuman).length;
  const booked = chats.filter((c) => c.booking).length;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30"><title>${esc(agency.agencyName)} · Inbox</title>
<style>
:root{--bg:#f3f1ec;--card:#fff;--fg:#15201c;--muted:#66706b;--line:#dcd6cb;--accent:#1f8a5b;--hot:#b55400;--bad:#b83a28;--in:#fff;--out:#d6f1c6;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0d1513;--card:#151f1b;--fg:#e8eeeb;--muted:#93a19b;--line:#2a3632;--accent:#4fc68c;--hot:#f0a35e;--bad:#ef7a66;--in:#1d2925;--out:#1f4a36;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:760px;margin:0 auto;padding:16px max(16px,env(safe-area-inset-left)) 40px}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 16px}
.notice{background:var(--card);border:1px solid var(--accent);border-radius:10px;padding:8px 12px;margin-bottom:12px}
.chat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:12px}
.chat header{display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px}.chat header span{display:block;color:var(--muted);font-size:13px}
.tags{display:flex;flex-wrap:wrap;gap:4px;align-items:flex-start}.tag{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;padding:2px 8px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.tag.hot{color:var(--hot);border-color:var(--hot)}.tag.ok{color:var(--accent);border-color:var(--accent)}.tag.bad{color:var(--bad);border-color:var(--bad)}
.booking{margin:8px 0 0}dl{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:8px 0 0;font-size:14px}dt{color:var(--muted)}dd{margin:0}
details{margin-top:8px}summary{cursor:pointer;color:var(--muted);font-size:14px}.msgs{display:flex;flex-direction:column;gap:4px;margin-top:6px}
.m{max-width:85%;padding:6px 10px;border-radius:10px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}.m.in{background:var(--in);border:1px solid var(--line);align-self:flex-start}.m.out{background:var(--out);align-self:flex-end}
.m time{display:block;font-size:11px;color:var(--muted)}.actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
button{font:inherit;font-size:14px;padding:6px 12px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--fg);cursor:pointer}button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.reply{display:flex;gap:6px;margin-top:8px}.reply input{flex:1;min-width:0;font:inherit;padding:7px 10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--fg)}
.note{color:var(--muted);font-size:13px;margin:8px 0 0}.empty{color:var(--muted);text-align:center;padding:40px}
</style></head><body><main>
<h1>${esc(agency.agencyName)} · WhatsApp inbox</h1>
<p class="sub">${chats.length} chats · ${needs} need you · ${booked} viewings booked · refreshes every 30 seconds</p>
${notice ? `<div class="notice">${esc(notice)}</div>` : ""}
${chats.length ? chats.map((c) => chatCard(c, now)).join("") : '<p class="empty">No WhatsApp chats yet. Send a message to the business number to test it.</p>'}
</main></body></html>`;
}
