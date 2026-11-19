// Privacy policy page, required by Meta before a WhatsApp app can be published.
// Served at /privacy (also used as the "data deletion instructions" URL).

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function privacyPage({ operator = "Kortexa", contactEmail = "", updated = "16 November 2026" } = {}) {
  const contact = contactEmail
    ? `email <a href="mailto:${esc(contactEmail)}">${esc(contactEmail)}</a> or send a WhatsApp message to the number you chatted with`
    : "send a WhatsApp message to the number you chatted with";
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy Policy · ${esc(operator)} AI Receptionist</title>
<style>
:root{--bg:#fbfaf7;--fg:#1c1b19;--muted:#5e5b55;--line:#e3dfd6;--accent:#1f6f54;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#121513;--fg:#e9ece9;--muted:#a3aba6;--line:#2a312d;--accent:#5fc59a;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:680px;margin:0 auto;padding:32px max(18px,env(safe-area-inset-left)) 56px}
h1{font-size:26px;line-height:1.25;margin:0 0 4px}h2{font-size:18px;margin:28px 0 6px}
.sub{color:var(--muted);margin:0 0 20px}p,li{color:var(--fg)}ul{padding-left:20px}a{color:var(--accent)}
.box{border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-top:8px}
</style></head><body><main>
<h1>Privacy Policy</h1>
<p class="sub">${esc(operator)} AI Receptionist · Last updated ${esc(updated)}</p>

<p>This policy explains what happens to your information when you chat with the AI receptionist run by ${esc(operator)} on WhatsApp or on our web demo. The receptionist answers questions about property listings and helps book viewings. It is an AI assistant, not a person.</p>

<h2>What we collect</h2>
<ul>
<li>Your WhatsApp phone number and the profile name you show on WhatsApp.</li>
<li>The messages you send and the replies the receptionist sends you.</li>
<li>Details you choose to share in the chat, such as your name, budget, timeline, how you plan to pay and a viewing time.</li>
</ul>

<h2>How we use it</h2>
<ul>
<li>To reply to your messages and answer your questions.</li>
<li>To book a viewing you ask for and send you a reminder about it.</li>
<li>To show the agency's team a short summary of your enquiry so a person can follow up.</li>
</ul>
<p>We do not sell your information, and we do not use it for advertising.</p>

<h2>Services that process your information</h2>
<ul>
<li><b>Meta (WhatsApp Business Platform)</b> delivers the messages between you and the receptionist.</li>
<li><b>Google (Gemini AI)</b> writes the receptionist's replies. Your messages are sent to Google for this.</li>
<li><b>Render</b> hosts the server the receptionist runs on.</li>
</ul>

<h2>How long we keep it</h2>
<p>This receptionist is a demonstration. Conversations are kept in the server's temporary memory and are erased whenever the server restarts, which normally happens within days. We do not keep a long-term copy.</p>

<h2>Your choices</h2>
<ul>
<li>Reply <b>STOP</b> at any time and the receptionist will not message you again. Reply <b>START</b> to allow messages again.</li>
<li>You can ask us to tell you what we hold about you, or to delete it.</li>
</ul>

<h2 id="delete">How to delete your data</h2>
<div class="box">To have your conversation and details deleted, ${contact} with the word <b>DELETE</b>. We will remove your information within 7 days and confirm when it's done.</div>

<h2>Contact</h2>
<p>For any privacy question, ${contact}.</p>
</main></body></html>`;
}
