// Kortexa follow-up server: receives WhatsApp webhooks, sends automatic
// follow-ups, and serves a small admin inbox at /admin.

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { config } from "./config.js";
import { Store } from "./store.js";
import { WhatsApp, parseWebhook, validSignature, windowOpen } from "./whatsapp.js";
import { Engine } from "./engine.js";
import { parseCsv } from "./csv.js";
import { normalizeGhana, pretty } from "./phone.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const ADMIN_HTML = path.join(here, "..", "public", "admin.html");
const MAX_BODY = 2 * 1024 * 1024;

export function createApp({ cfg = config, store, wa, ai, log = console } = {}) {
  store ??= new Store(cfg.dataFile);
  wa ??= new WhatsApp(cfg.whatsapp, { dryRun: cfg.dryRun, log });
  const engine = new Engine({ store, wa, ai, cfg, log });

  const send = (res, code, body, type = "application/json") => {
    res.writeHead(code, { "Content-Type": type, "Cache-Control": "no-store" });
    res.end(type === "application/json" ? JSON.stringify(body) : body);
  };
  const readBody = (req) => new Promise((resolve, reject) => {
    const chunks = []; let size = 0;
    req.on("data", (c) => { size += c.length; if (size > MAX_BODY) { reject(new Error("Body too large")); req.destroy(); } else chunks.push(c); });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
  const authed = (req) => {
    if (!cfg.adminPassword) return false;
    const [scheme, b64] = (req.headers.authorization || "").split(" ");
    if (scheme !== "Basic" || !b64) return false;
    const pass = Buffer.from(b64, "base64").toString().split(":").slice(1).join(":");
    const a = crypto.createHash("sha256").update(pass).digest(), b = crypto.createHash("sha256").update(cfg.adminPassword).digest();
    return crypto.timingSafeEqual(a, b);
  };
  const leadView = (l) => ({
    ...l, pretty: pretty(l.waId), windowOpen: windowOpen(l),
    messages: store.messagesFor(l.waId).slice(-50),
  });

  function importCsv(text) {
    const rows = parseCsv(text);
    let added = 0, skipped = 0, invalid = 0;
    for (const r of rows) {
      const waId = normalizeGhana(r.whatsapp || r.phone || r.number || "");
      if (!waId) { invalid++; continue; }
      if (store.lead(waId)) { skipped++; continue; }
      const st = (r.status || "").toLowerCase();
      store.upsertLead(waId, {
        name: r.agency || r.name || "", city: r.city || "", email: r.email || "",
        notes: [r.notes, r.address].filter(Boolean).join(" | "),
        status: st === "demo" ? "demo" : st === "won" ? "won" : "new",
        source: "outreach-csv",
      });
      added++;
    }
    return { added, skipped, invalid, total: rows.length };
  }

  const handler = async (req, res) => {
    const url = new URL(req.url, "http://x");
    const p = url.pathname;
    try {
      if (p === "/health") return send(res, 200, { ok: true, dryRun: cfg.dryRun, aiMode: cfg.ai.mode });

      // --- Meta webhook verification ------------------------------------
      if (p === "/webhook" && req.method === "GET") {
        const ok = url.searchParams.get("hub.mode") === "subscribe" && cfg.whatsapp.verifyToken && url.searchParams.get("hub.verify_token") === cfg.whatsapp.verifyToken;
        return ok ? send(res, 200, url.searchParams.get("hub.challenge") || "", "text/plain") : send(res, 403, { error: "Verify token does not match" });
      }
      // --- Meta webhook events --------------------------------------------
      if (p === "/webhook" && req.method === "POST") {
        const raw = await readBody(req);
        if (!validSignature(raw, req.headers["x-hub-signature-256"], cfg.whatsapp.appSecret)) return send(res, 401, { error: "Bad signature" });
        send(res, 200, { ok: true }); // answer Meta fast; process afterwards
        let body; try { body = JSON.parse(raw.toString("utf8")); } catch { return; }
        const { messages, statuses } = parseWebhook(body);
        statuses.forEach((s) => engine.onStatus(s));
        for (const m of messages) await engine.onInbound(m).catch((e) => log.error("inbound failed:", e));
        if (statuses.length) await store.save();
        return;
      }

      // --- Admin (password protected) -------------------------------------
      if (p === "/" ) { res.writeHead(302, { Location: "/admin" }); return res.end(); }
      if (p === "/admin" || p.startsWith("/api/")) {
        if (!cfg.adminPassword) return send(res, 503, { error: "Set ADMIN_PASSWORD to use the admin page." });
        if (!authed(req)) {
          res.writeHead(401, { "WWW-Authenticate": 'Basic realm="Kortexa admin", charset="UTF-8"' });
          return res.end("Login required");
        }
      }
      if (p === "/admin") return send(res, 200, fs.readFileSync(ADMIN_HTML, "utf8"), "text/html; charset=utf-8");

      if (p === "/api/state" && req.method === "GET") {
        const leads = store.leads().sort((a, b) => Math.max(b.lastInboundAt, b.lastOutboundAt, b.createdAt) - Math.max(a.lastInboundAt, a.lastOutboundAt, a.createdAt));
        return send(res, 200, {
          dryRun: cfg.dryRun, aiMode: cfg.ai.mode, sentLast24h: store.sentInLast24h(), dailyCap: cfg.followups.dailyCap,
          templates: cfg.templates, leads: leads.map(leadView),
        });
      }
      if (p === "/api/import" && req.method === "POST") {
        const result = importCsv((await readBody(req)).toString("utf8"));
        await store.save();
        return send(res, 200, result);
      }
      if (p === "/api/tick" && req.method === "POST") return send(res, 200, await engine.tick());

      const m = /^\/api\/leads\/(\d{8,15})(\/reply)?$/.exec(p);
      if (m && req.method === "POST") {
        const lead = store.lead(m[1]);
        if (!lead) return send(res, 404, { error: "No lead with that number" });
        const body = JSON.parse((await readBody(req)).toString("utf8") || "{}");
        if (m[2]) {
          if (!body.text || !String(body.text).trim()) return send(res, 400, { error: "Message is empty" });
          await engine.replyManually(lead.waId, String(body.text).trim());
          return send(res, 200, leadView(lead));
        }
        const allowed = ["status", "paused", "notes", "name", "city", "needsHuman"];
        for (const k of allowed) if (k in body) lead[k] = body[k];
        if ("draft" in body && body.draft === null) lead.draft = null;
        if (body.status === "new") lead.followupStep = 0;
        await store.save();
        return send(res, 200, leadView(lead));
      }
      if (p === "/api/leads" && req.method === "POST") {
        const body = JSON.parse((await readBody(req)).toString("utf8") || "{}");
        const waId = normalizeGhana(body.whatsapp);
        if (!waId) return send(res, 400, { error: "That doesn't look like a valid WhatsApp number." });
        if (store.lead(waId)) return send(res, 409, { error: "This number is already a lead." });
        const lead = store.upsertLead(waId, { name: body.name || "", city: body.city || "", notes: body.notes || "", source: "manual" });
        await store.save();
        return send(res, 200, leadView(lead));
      }
      return send(res, 404, { error: "Not found" });
    } catch (e) {
      log.error(e);
      if (!res.headersSent) send(res, 400, { error: e.message });
    }
  };

  return { handler, engine, store, importCsv };
}

// ---- start when run directly ----------------------------------------------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  let ai = null;
  if (config.ai.mode !== "off") {
    if (!process.env.ANTHROPIC_API_KEY && !process.env.ANTHROPIC_AUTH_TOKEN) {
      console.warn("AI_MODE is", config.ai.mode, "but ANTHROPIC_API_KEY is not set. AI replies are off.");
    } else {
      const { ReplyWriter } = await import("./ai.js");
      ai = new ReplyWriter(config.ai);
    }
  }
  const { handler, engine } = createApp({ ai });
  http.createServer(handler).listen(config.port, () => {
    console.log(`Kortexa follow-up server on :${config.port}`);
    if (config.dryRun) console.log("DRY RUN: WhatsApp credentials are missing, so messages are logged, not sent.");
    if (!config.whatsapp.appSecret) console.warn("WHATSAPP_APP_SECRET is not set: webhook signatures are NOT checked.");
    if (!config.adminPassword) console.warn("ADMIN_PASSWORD is not set: the admin page is disabled.");
  });
  const run = () => engine.tick().then((r) => r.sent && console.log(`Sent ${r.sent} follow-up(s).`)).catch((e) => console.error("tick failed:", e));
  setTimeout(run, 5000);
  setInterval(run, config.followups.checkEveryMinutes * 60000);
}
