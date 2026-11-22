// Receptionist demo server: serves the chat page and passes messages to the AI.
// The conversation lives in the visitor's browser and is sent with each
// message, so the server stores nothing and can run on free hosting.

import http from "node:http";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { LLM, LLMError } from "./llm.js";
import { systemPrompt, parseReply, SUMMARY_PROMPT, scoreLead } from "./prompt.js";
import { WhatsApp, parseWebhook, parseStatuses, validSignature } from "./whatsapp.js";
import { Chats } from "./chats.js";
import { Receptionist } from "./receptionist.js";
import { inboxPage } from "./inbox.js";
import { Demos } from "./demos.js";
import { privacyPage } from "./legal.js";
import { runChecks, subscribeApp, checkPage } from "./check.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(here, "..", "public");
const MAX_TURNS = 30;        // messages per conversation
const MAX_CHARS = 600;       // per message
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon" };

/** Simple per-visitor and per-day limits so the free AI plan isn't used up by one person. */
export class Limiter {
  constructor({ perWindow = 40, windowMs = 10 * 60000, perDay = 800 } = {}) {
    Object.assign(this, { perWindow, windowMs, perDay });
    this.hits = new Map();
    this.day = "";
    this.dayCount = 0;
  }
  allow(ip, now = Date.now()) {
    const today = new Date(now).toISOString().slice(0, 10);
    if (today !== this.day) { this.day = today; this.dayCount = 0; this.hits.clear(); }
    if (this.dayCount >= this.perDay) return "The demo has had a lot of visitors today. Please try again tomorrow.";
    const list = (this.hits.get(ip) || []).filter((t) => now - t < this.windowMs);
    if (list.length >= this.perWindow) return "You're sending messages very fast. Please wait a few minutes.";
    list.push(now);
    this.hits.set(ip, list);
    this.dayCount++;
    return null;
  }
}

export function cleanMessages(input, { endWithUser = true } = {}) {
  if (!Array.isArray(input) || !input.length) throw new LLMError("No message to answer.", 400);
  if (input.length > MAX_TURNS) throw new LLMError("This demo chat is full. Tap Restart to begin a new one.", 400);
  const msgs = input.map((m) => ({
    role: m?.role === "assistant" ? "assistant" : "user",
    content: String(m?.content ?? "").slice(0, MAX_CHARS).trim(),
  })).filter((m) => m.content);
  if (!msgs.length || (endWithUser && msgs[msgs.length - 1].role !== "user")) throw new LLMError("No message to answer.", 400);
  return msgs;
}

export function createApp({ agency, llm, limiter = new Limiter(), now = () => Date.now(), log = console,
  wa = null, chats = null, receptionist = null, demos = null, verifyToken = "", appSecret = "", adminPassword = "",
  wabaId = "", appId = "", version = "", fetchImpl = globalThis.fetch }) {
  const events = []; // last webhook deliveries, shown on /check
  const note = (ok, text) => { events.push({ at: now(), ok, text }); if (events.length > 15) events.shift(); };
  const agencyFor = (code) => (code && demos?.get(code)) || agency;
  const send = (res, code, body) => {
    res.writeHead(code, { "Content-Type": "application/json", "Cache-Control": "no-store" });
    res.end(JSON.stringify(body));
  };
  const readJson = (req) => new Promise((resolve, reject) => {
    // Hosts like Vercel may have read and parsed the body already.
    if (req.body && typeof req.body === "object" && !Buffer.isBuffer(req.body)) return resolve(req.body);
    if (typeof req.body === "string" || Buffer.isBuffer(req.body)) { try { return resolve(JSON.parse(String(req.body) || "{}")); } catch { return reject(new LLMError("Bad request.", 400)); } }
    let size = 0; const chunks = [];
    req.on("data", (c) => { size += c.length; if (size > 64 * 1024) { reject(new LLMError("Message too large.", 413)); req.destroy(); } else chunks.push(c); });
    req.on("end", () => { try { resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}")); } catch { reject(new LLMError("Bad request.", 400)); } });
    req.on("error", reject);
  });
  const readRaw = (req) => new Promise((resolve, reject) => {
    let size = 0; const chunks = [];
    req.on("data", (c) => { size += c.length; if (size > 1024 * 1024) { reject(new LLMError("Too large.", 413)); req.destroy(); } else chunks.push(c); });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
  const authed = (req) => {
    if (!adminPassword) return false;
    const [scheme, b64] = String(req.headers.authorization || "").split(" ");
    if (scheme !== "Basic" || !b64) return false;
    const pass = Buffer.from(b64, "base64").toString().split(":").slice(1).join(":");
    return pass.length === adminPassword.length && crypto.timingSafeEqual(Buffer.from(pass), Buffer.from(adminPassword));
  };
  const ipOf = (req) => String(req.headers["x-forwarded-for"] || req.socket?.remoteAddress || "").split(",")[0].trim();

  return async function handler(req, res) {
    const url = new URL(req.url, "http://x");
    try {
      if (url.pathname === "/health") return send(res, 200, { ok: true, aiReady: !!llm, whatsapp: wa ? (wa.dryRun ? "dry-run" : "live") : "off" });

      // Privacy policy (Meta needs this URL to publish the app; also the data deletion instructions).
      if ((url.pathname === "/privacy" || url.pathname === "/data-deletion") && req.method === "GET") {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        return res.end(privacyPage({ operator: process.env.PRIVACY_OPERATOR || "Kortexa", contactEmail: process.env.PRIVACY_CONTACT_EMAIL || "" }));
      }

      // ---- WhatsApp webhook (Meta calls these) --------------------------------
      if (url.pathname === "/webhook" && req.method === "GET") {
        const ok = verifyToken && url.searchParams.get("hub.mode") === "subscribe" && url.searchParams.get("hub.verify_token") === verifyToken;
        res.writeHead(ok ? 200 : 403, { "Content-Type": "text/plain" });
        return res.end(ok ? url.searchParams.get("hub.challenge") || "" : "Verify token does not match");
      }
      if (url.pathname === "/webhook" && req.method === "POST") {
        const raw = await readRaw(req);
        if (!validSignature(raw, req.headers["x-hub-signature-256"], appSecret)) {
          log.warn?.("Webhook rejected: signature doesn't match WHATSAPP_APP_SECRET (check the App secret in Render)");
          note(false, "Rejected: the signature didn't match WHATSAPP_APP_SECRET. Copy the App secret again, or delete it in Render.");
          return send(res, 401, { error: "Bad signature" });
        }
        send(res, 200, { ok: true }); // answer Meta right away, then work
        let body; try { body = JSON.parse(raw.toString("utf8")); } catch { log.warn?.("Webhook: delivery wasn't valid JSON"); return; }
        const incoming = parseWebhook(body);
        const statuses = parseStatuses(body);
        log.info?.(`Webhook: delivery received (${incoming.length} message(s), ${statuses.length} status update(s))`);
        note(true, `Received ${incoming.length} message(s)${incoming.length ? ` from …${incoming.map((m) => String(m.from).slice(-4)).join(", …")}` : ""} and ${statuses.length} status update(s)` +
          statuses.filter((s) => s.status === "failed").map((s) => `. Reply failed: ${s.error || "unknown error"}`).join(""));
        for (const s of statuses) if (s.status === "failed") log.warn?.(`WhatsApp delivery failed to …${String(s.to).slice(-4)}: ${s.error || "unknown error"}`);
        if (!receptionist) { if (incoming.length) log.warn?.("Message received but the AI isn't connected (LLM_API_KEY missing)."); return; }
        if (incoming.length) log.info?.(`WhatsApp: received ${incoming.length} message(s) from …${incoming.map((m) => String(m.from).slice(-4)).join(", …")}`);
        for (const m of incoming) receptionist.handle(m);
        return;
      }

      // ---- Self-check page (password protected) -----------------------------
      if (url.pathname === "/check" || url.pathname === "/check/subscribe") {
        if (!adminPassword) return send(res, 503, { error: "Set ADMIN_PASSWORD to use the check page." });
        if (!authed(req)) { res.writeHead(401, { "WWW-Authenticate": 'Basic realm="Check", charset="UTF-8"' }); return res.end("Login required"); }
        let notice = "";
        if (url.pathname === "/check/subscribe" && req.method === "POST") {
          try { await subscribeApp({ wa, wabaId, fetchImpl }); notice = "Done: the WhatsApp account is now connected to this app. Send a WhatsApp message to test."; }
          catch (e) { notice = "Couldn't connect: " + e.message; }
        }
        const results = await runChecks({ llm, wa, appSecret, verifyToken, adminPassword, wabaId, appId, version, fetchImpl });
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
        return res.end(checkPage(results, events, { notice }));
      }

      // ---- Inbox for the agency (password protected) ------------------------
      if (url.pathname === "/inbox" || url.pathname.startsWith("/inbox/")) {
        if (!adminPassword || !chats) return send(res, 503, { error: "Set ADMIN_PASSWORD to use the inbox." });
        if (!authed(req)) { res.writeHead(401, { "WWW-Authenticate": 'Basic realm="Inbox", charset="UTF-8"' }); return res.end("Login required"); }
        if (url.pathname === "/inbox" && req.method === "GET") {
          res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
          return res.end(inboxPage(chats.all(), { agency, demos, notice: url.searchParams.get("notice") || "", now: now() }));
        }
        const m = /^\/inbox\/(\d{8,15})\/(pause|resume|done|reply)$/.exec(url.pathname);
        if (m && req.method === "POST") {
          const c = chats.get(m[1]);
          const form = new URLSearchParams((await readRaw(req)).toString("utf8"));
          let notice = "";
          if (m[2] === "pause") { c.aiPaused = true; notice = "AI paused for this chat."; }
          if (m[2] === "resume") { c.aiPaused = false; c.needsHuman = false; notice = "AI is answering this chat again."; }
          if (m[2] === "done") { c.needsHuman = false; notice = "Marked as handled."; }
          if (m[2] === "reply") {
            const text = (form.get("text") || "").trim().slice(0, 2000);
            const lastIn = [...c.messages].reverse().find((x) => x.role === "user");
            if (!text) notice = "Type a message first.";
            else if (!lastIn || now() - lastIn.at > 86400000) notice = "Can't send: WhatsApp only allows free replies within 24 hours of their last message.";
            else {
              try { await wa.sendText(c.waId, text); chats.add(c.waId, "assistant", text); c.aiPaused = true; c.needsHuman = false; notice = "Sent. AI is paused for this chat so you can continue."; }
              catch (e) { notice = "Couldn't send: " + e.message; }
            }
          }
          await chats.save();
          res.writeHead(303, { Location: "/inbox?notice=" + encodeURIComponent(notice) + "#c" + c.waId });
          return res.end();
        }
        return send(res, 404, { error: "Not found" });
      }

      if (url.pathname === "/api/agency" && req.method === "GET") {
        const code = url.searchParams.get("demo");
        if (code && !demos?.get(code)) return send(res, 404, { error: "No demo with that code." });
        const { agencyName, receptionistName, listings, isDemo = false } = agencyFor(code);
        return send(res, 200, { agencyName, receptionistName, isDemo, listings: listings.map(({ id, title, price }) => ({ id, title, price })) });
      }

      // Personalised demo pages: /d/<code> shows the same chat page for that agency.
      const dm = /^\/d\/([a-z0-9-]{2,24})\/?$/.exec(url.pathname);
      if (dm && req.method === "GET") {
        if (!demos?.get(dm[1])) return send(res, 404, { error: "No demo with that code." });
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        return fs.createReadStream(path.join(PUBLIC, "index.html")).pipe(res);
      }

      if ((url.pathname === "/api/chat" || url.pathname === "/api/summary") && req.method === "POST") {
        if (!llm) return send(res, 503, { error: "The AI isn't connected yet. Add LLM_API_KEY to the server settings." });
        const tooMany = limiter.allow(ipOf(req), now());
        if (tooMany) return send(res, 429, { error: tooMany });
        const body = await readJson(req);
        const messages = cleanMessages(body.messages, { endWithUser: url.pathname === "/api/chat" });
        const agency = agencyFor(body.demo);

        if (url.pathname === "/api/chat") {
          const raw = await llm.chat([{ role: "system", content: systemPrompt(agency, now()) }, ...messages]);
          return send(res, 200, parseReply(raw, agency));
        }
        const transcript = messages.map((m) => `${m.role === "user" ? "BUYER" : "RECEPTIONIST"}: ${m.content}`).join("\n");
        const raw = await llm.chat([{ role: "system", content: SUMMARY_PROMPT }, { role: "user", content: transcript }], { maxTokens: 300, temperature: 0 });
        const match = raw.match(/\{[\s\S]*\}/);
        let summary = null;
        try { summary = match ? JSON.parse(match[0]) : null; } catch { /* handled below */ }
        if (!summary) return send(res, 502, { error: "Couldn't make the summary. Try again." });
        return send(res, 200, { ...summary, ...scoreLead(summary, summary.viewing ? true : null) });
      }

      if (req.method === "GET") {
        const file = path.normalize(path.join(PUBLIC, url.pathname === "/" ? "index.html" : url.pathname));
        if (!file.startsWith(PUBLIC) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return send(res, 404, { error: "Not found" });
        res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
        return fs.createReadStream(file).pipe(res);
      }
      return send(res, 404, { error: "Not found" });
    } catch (e) {
      if (!(e instanceof LLMError)) log.error(e);
      if (!res.headersSent) send(res, e.status || 500, { error: e instanceof LLMError ? e.message : "Something went wrong. Try again." });
    }
  };
}

/** The AI client from environment settings (null when there's no key). */
export function llmFromEnv(env = process.env) {
  return env.LLM_API_KEY
    ? new LLM({
        baseUrl: env.LLM_BASE_URL || "https://generativelanguage.googleapis.com/v1beta/openai",
        model: env.LLM_MODEL || "gemini-3.5-flash",
        apiKey: env.LLM_API_KEY,
        reasoningEffort: env.LLM_REASONING_EFFORT ?? "none",
        fallbackModel: env.LLM_FALLBACK_MODEL ?? "gemini-flash-lite-latest",
      })
    : null;
}

export function loadAgency(env = process.env) {
  return JSON.parse(fs.readFileSync(env.AGENCY_FILE || path.join(here, "..", "config", "agency.json"), "utf8"));
}

// ---- start when run directly ----------------------------------------------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const env = process.env;
  const agency = loadAgency(env);
  const llm = llmFromEnv(env);
  const limiter = new Limiter({ perDay: Number(env.DAILY_LIMIT) || 800 });
  const wa = new WhatsApp({ token: env.WHATSAPP_TOKEN, phoneNumberId: env.WHATSAPP_PHONE_NUMBER_ID, apiVersion: env.WHATSAPP_API_VERSION || "v23.0" });
  const chats = new Chats(env.DATA_FILE || "");
  const demos = new Demos();
  const receptionist = llm ? new Receptionist({ agency, llm, wa, chats, limiter, demos }) : null;
  const port = Number(env.PORT) || 3000;
  http.createServer(createApp({
    agency, llm, limiter, wa, chats, receptionist, demos,
    verifyToken: env.WHATSAPP_VERIFY_TOKEN || "", appSecret: env.WHATSAPP_APP_SECRET || "", adminPassword: env.ADMIN_PASSWORD || "",
    wabaId: env.WHATSAPP_BUSINESS_ACCOUNT_ID || "", appId: env.WHATSAPP_APP_ID || "", version: (env.RENDER_GIT_COMMIT || "").slice(0, 7),
  })).listen(port, () => {
    console.log(`Receptionist running on http://localhost:${port} (${demos.list().length} personalised demos loaded)`);
    if (!llm) console.warn("LLM_API_KEY is not set: the AI won't answer.");
    if (wa.dryRun) console.warn("WhatsApp is in dry-run mode: replies are printed here, not sent. Set WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID.");
    if (!env.WHATSAPP_APP_SECRET) console.warn("WHATSAPP_APP_SECRET is not set: webhook signatures are NOT checked.");
    if (!env.ADMIN_PASSWORD) console.warn("ADMIN_PASSWORD is not set: the /inbox page is off.");
    if (!env.DATA_FILE) console.warn("DATA_FILE is not set: chats are kept in memory and lost on restart.");
  });
  // Viewing reminders, checked every 5 minutes.
  if (receptionist) setInterval(() => receptionist.tick().then((r) => r.sent && console.log(`Sent ${r.sent} viewing reminder(s).`)), 5 * 60000);
}
