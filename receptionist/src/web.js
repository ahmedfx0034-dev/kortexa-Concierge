// The web chat's API (/api/agency, /api/chat, /api/summary), with no WhatsApp code,
// so it can run on its own on Vercel as well as inside the Render server.
// The conversation lives in the visitor's browser and is sent with each message.

import { LLM, LLMError } from "./llm.js";
import { systemPrompt, parseReply, summaryPrompt, summarise } from "./prompt.js";

const MAX_TURNS = 30;        // messages per conversation
const MAX_CHARS = 600;       // per message

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
  if (input.length > MAX_TURNS) throw new LLMError("This chat is full. Tap ⋮ then Clear chat to begin a new one.", 400);
  const msgs = input.map((m) => ({
    role: m?.role === "assistant" ? "assistant" : "user",
    content: String(m?.content ?? "").slice(0, MAX_CHARS).trim(),
  })).filter((m) => m.content);
  if (!msgs.length || (endWithUser && msgs[msgs.length - 1].role !== "user")) throw new LLMError("No message to answer.", 400);
  return msgs;
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

export function send(res, code, body) {
  res.writeHead(code, { "Content-Type": "application/json", "Cache-Control": "no-store" });
  res.end(JSON.stringify(body));
}

export function readJson(req) {
  return new Promise((resolve, reject) => {
    // Hosts like Vercel may have read and parsed the body already.
    if (req.body && typeof req.body === "object" && !Buffer.isBuffer(req.body)) return resolve(req.body);
    if (typeof req.body === "string" || Buffer.isBuffer(req.body)) { try { return resolve(JSON.parse(String(req.body) || "{}")); } catch { return reject(new LLMError("Bad request.", 400)); } }
    let size = 0; const chunks = [];
    req.on("data", (c) => { size += c.length; if (size > 64 * 1024) { reject(new LLMError("Message too large.", 413)); req.destroy(); } else chunks.push(c); });
    req.on("end", () => { try { resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}")); } catch { reject(new LLMError("Bad request.", 400)); } });
    req.on("error", reject);
  });
}

export const ipOf = (req) => String(req.headers["x-forwarded-for"] || req.socket?.remoteAddress || "").split(",")[0].trim();

/**
 * Returns `handle(req, res, url)`: answers the web chat's API and returns true,
 * or returns false for any other URL. Errors from the AI become readable messages.
 */
export function webApi({ agency, llm, limiter = new Limiter(), demos = null, now = () => Date.now(), log = console }) {
  const agencyFor = (code) => (code && demos?.get(code)) || agency;
  return async function handle(req, res, url = new URL(req.url, "http://x")) {
    const isChat = url.pathname === "/api/chat", isSummary = url.pathname === "/api/summary";
    if (!(url.pathname === "/api/agency" && req.method === "GET") && !((isChat || isSummary) && req.method === "POST")) return false;
    try {
      // Speed check: /api/agency?speed=1 times one tiny AI answer (which model, how long).
      if (url.pathname === "/api/agency" && url.searchParams.get("speed") && llm) {
        const tooMany = limiter.allow(ipOf(req), now());
        if (tooMany) { send(res, 429, { error: tooMany }); return true; }
        try { await llm.chat([{ role: "user", content: "Reply with the word OK." }], { maxTokens: 10, temperature: 0 }); send(res, 200, { ok: true, ...llm.last }); }
        catch (e) { send(res, 200, { ok: false, error: e.message }); }
        return true;
      }
      if (url.pathname === "/api/agency") {
        const code = url.searchParams.get("demo");
        if (code && !demos?.get(code)) { send(res, 404, { error: "No demo with that code." }); return true; }
        const { agencyName, receptionistName, isDemo = false, kind = "real-estate" } = agencyFor(code);
        const items = agencyFor(code).products || agencyFor(code).listings || [];
        send(res, 200, { agencyName, receptionistName, isDemo, kind, listings: items.map(({ id, title, name, price }) => ({ id, title: title || name, price })) });
        return true;
      }
      if (!llm) { send(res, 503, { error: "The AI isn't connected yet. Add LLM_API_KEY to the server settings." }); return true; }
      const tooMany = limiter.allow(ipOf(req), now());
      if (tooMany) { send(res, 429, { error: tooMany }); return true; }
      const body = await readJson(req);
      const messages = cleanMessages(body.messages, { endWithUser: isChat });
      const ag = agencyFor(body.demo);

      if (isChat) {
        const raw = await llm.chat([{ role: "system", content: systemPrompt(ag, now()) }, ...messages]);
        send(res, 200, parseReply(raw, ag));
        return true;
      }
      const transcript = messages.map((m) => `${m.role === "user" ? (ag.kind === "furniture" ? "CUSTOMER" : "BUYER") : "RECEPTIONIST"}: ${m.content}`).join("\n");
      const raw = await llm.chat([{ role: "system", content: summaryPrompt(ag) }, { role: "user", content: transcript }], { maxTokens: 300, temperature: 0 });
      const match = raw.match(/\{[\s\S]*\}/);
      let summary = null;
      try { summary = match ? JSON.parse(match[0]) : null; } catch { /* handled below */ }
      if (!summary) { send(res, 502, { error: "Couldn't make the summary. Try again." }); return true; }
      send(res, 200, { ...summary, ...summarise(ag, summary, summary.viewing || summary.visit ? true : null) });
      return true;
    } catch (e) {
      if (!(e instanceof LLMError)) log.error(e);
      if (!res.headersSent) send(res, e.status || 500, { error: e instanceof LLMError ? e.message : "Something went wrong. Try again." });
      return true;
    }
  };
}

/** A whole request handler for hosts that only run the web chat API (Vercel). */
export function webHandler(opts) {
  const handle = webApi(opts);
  return async (req, res) => { if (!(await handle(req, res))) send(res, 404, { error: "Not found" }); };
}
