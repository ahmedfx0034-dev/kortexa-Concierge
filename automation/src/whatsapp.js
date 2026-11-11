// WhatsApp Business Cloud API client (Meta's official API).
// Docs: https://developers.facebook.com/docs/whatsapp/cloud-api

import crypto from "node:crypto";

export const WINDOW_MS = 24 * 60 * 60 * 1000;

/** True while the lead's 24-hour customer-service window is open, i.e. they
 * messaged us in the last 24 hours. Inside it we may send any free-form text;
 * outside it WhatsApp only allows approved templates. */
export function windowOpen(lead, now = Date.now()) {
  return !!lead.lastInboundAt && now - lead.lastInboundAt < WINDOW_MS;
}

/** Check Meta's X-Hub-Signature-256 header against the raw request body. */
export function validSignature(rawBody, header, appSecret) {
  if (!appSecret) return true; // not configured: accept (log a warning at startup)
  if (!header || !header.startsWith("sha256=")) return false;
  const expected = crypto.createHmac("sha256", appSecret).update(rawBody).digest("hex");
  const got = header.slice(7);
  return got.length === expected.length && crypto.timingSafeEqual(Buffer.from(got), Buffer.from(expected));
}

/** Pull inbound messages and delivery statuses out of a webhook payload. */
export function parseWebhook(body) {
  const messages = [], statuses = [];
  for (const entry of body?.entry || []) {
    for (const change of entry.changes || []) {
      const v = change.value || {};
      const names = Object.fromEntries((v.contacts || []).map((c) => [c.wa_id, c.profile?.name || ""]));
      for (const m of v.messages || []) {
        let text = "";
        if (m.type === "text") text = m.text?.body || "";
        else if (m.type === "button") text = m.button?.text || "";
        else if (m.type === "interactive") text = m.interactive?.button_reply?.title || m.interactive?.list_reply?.title || "";
        else text = `[${m.type} message]`;
        messages.push({ id: m.id, from: m.from, profileName: names[m.from] || "", at: Number(m.timestamp) * 1000 || Date.now(), type: m.type, text });
      }
      for (const s of v.statuses || []) {
        statuses.push({ id: s.id, status: s.status, to: s.recipient_id, error: s.errors?.[0]?.title || s.errors?.[0]?.message || "" });
      }
    }
  }
  return { messages, statuses };
}

export class WhatsApp {
  constructor(cfg, { dryRun, fetchImpl = globalThis.fetch, log = console } = {}) {
    this.cfg = cfg;
    this.dryRun = dryRun;
    this.fetch = fetchImpl;
    this.log = log;
  }

  async #post(payload) {
    if (this.dryRun) {
      this.log.info?.("[dry-run] would send", JSON.stringify(payload));
      return { id: "dryrun-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8) };
    }
    const url = `https://graph.facebook.com/${this.cfg.apiVersion}/${this.cfg.phoneNumberId}/messages`;
    const res = await this.fetch(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.cfg.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ messaging_product: "whatsapp", recipient_type: "individual", ...payload }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      const e = json.error || {};
      const err = new Error(`WhatsApp API ${res.status}: ${e.message || "request failed"}${e.code ? ` (code ${e.code})` : ""}`);
      err.code = e.code;
      throw err;
    }
    return { id: json.messages?.[0]?.id || "" };
  }

  /** Free-form text. Only allowed inside the 24-hour window. */
  sendText(to, body) {
    return this.#post({ to, type: "text", text: { preview_url: true, body } });
  }

  /** An approved template with body variables ({{1}}, {{2}}, ...). */
  sendTemplate(to, name, params = []) {
    const template = { name, language: { code: this.cfg.templateLanguage } };
    if (params.length) template.components = [{ type: "body", parameters: params.map((text) => ({ type: "text", text: String(text) })) }];
    return this.#post({ to, type: "template", template });
  }

  markRead(messageId) {
    if (this.dryRun) return Promise.resolve();
    return this.#post({ status: "read", message_id: messageId }).catch(() => {});
  }
}
