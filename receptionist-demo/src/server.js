// Receptionist demo server: serves the chat page and passes messages to the AI.
// The conversation lives in the visitor's browser and is sent with each
// message, so the server stores nothing and can run on free hosting.

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { LLM, LLMError } from "./llm.js";
import { systemPrompt, parseReply, SUMMARY_PROMPT } from "./prompt.js";

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

export function createApp({ agency, llm, limiter = new Limiter(), now = () => Date.now(), log = console }) {
  const send = (res, code, body) => {
    res.writeHead(code, { "Content-Type": "application/json", "Cache-Control": "no-store" });
    res.end(JSON.stringify(body));
  };
  const readJson = (req) => new Promise((resolve, reject) => {
    let size = 0; const chunks = [];
    req.on("data", (c) => { size += c.length; if (size > 64 * 1024) { reject(new LLMError("Message too large.", 413)); req.destroy(); } else chunks.push(c); });
    req.on("end", () => { try { resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}")); } catch { reject(new LLMError("Bad request.", 400)); } });
    req.on("error", reject);
  });
  const ipOf = (req) => String(req.headers["x-forwarded-for"] || req.socket.remoteAddress || "").split(",")[0].trim();

  return async function handler(req, res) {
    const url = new URL(req.url, "http://x");
    try {
      if (url.pathname === "/health") return send(res, 200, { ok: true, aiReady: !!llm });

      if (url.pathname === "/api/agency" && req.method === "GET") {
        const { agencyName, receptionistName, listings } = agency;
        return send(res, 200, { agencyName, receptionistName, listings: listings.map(({ id, title, price }) => ({ id, title, price })) });
      }

      if ((url.pathname === "/api/chat" || url.pathname === "/api/summary") && req.method === "POST") {
        if (!llm) return send(res, 503, { error: "The AI isn't connected yet. Add LLM_API_KEY to the server settings." });
        const tooMany = limiter.allow(ipOf(req), now());
        if (tooMany) return send(res, 429, { error: tooMany });
        const messages = cleanMessages((await readJson(req)).messages, { endWithUser: url.pathname === "/api/chat" });

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
        return send(res, 200, summary);
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

// ---- start when run directly ----------------------------------------------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const env = process.env;
  const agency = JSON.parse(fs.readFileSync(env.AGENCY_FILE || path.join(here, "..", "config", "agency.json"), "utf8"));
  const llm = env.LLM_API_KEY
    ? new LLM({
        baseUrl: env.LLM_BASE_URL || "https://generativelanguage.googleapis.com/v1beta/openai",
        model: env.LLM_MODEL || "gemini-2.5-flash",
        apiKey: env.LLM_API_KEY,
      })
    : null;
  const limiter = new Limiter({ perDay: Number(env.DAILY_LIMIT) || 800 });
  const port = Number(env.PORT) || 3000;
  http.createServer(createApp({ agency, llm, limiter })).listen(port, () => {
    console.log(`Receptionist demo on http://localhost:${port}`);
    if (!llm) console.warn("LLM_API_KEY is not set: the chat page loads, but the AI won't answer.");
  });
}
