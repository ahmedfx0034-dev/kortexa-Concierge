// WhatsApp Business Cloud API (Meta's official API).
// Docs: https://developers.facebook.com/docs/whatsapp/cloud-api

import crypto from "node:crypto";

/** Check Meta's X-Hub-Signature-256 header against the raw request body. */
export function validSignature(rawBody, header, appSecret) {
  if (!appSecret) return true; // not configured: a warning is printed at startup
  if (!header || !header.startsWith("sha256=")) return false;
  const expected = crypto.createHmac("sha256", appSecret).update(rawBody).digest("hex");
  const got = header.slice(7);
  return got.length === expected.length && crypto.timingSafeEqual(Buffer.from(got), Buffer.from(expected));
}

/** Pull customer messages out of a webhook delivery. */
export function parseWebhook(body) {
  const messages = [];
  for (const entry of body?.entry || []) {
    for (const change of entry.changes || []) {
      const v = change.value || {};
      const names = Object.fromEntries((v.contacts || []).map((c) => [c.wa_id, c.profile?.name || ""]));
      for (const m of v.messages || []) {
        let text = "";
        if (m.type === "text") text = m.text?.body || "";
        else if (m.type === "button") text = m.button?.text || "";
        else if (m.type === "interactive") text = m.interactive?.button_reply?.title || m.interactive?.list_reply?.title || "";
        messages.push({ id: m.id, from: m.from, name: names[m.from] || "", type: m.type, text, at: Number(m.timestamp) * 1000 || Date.now() });
      }
    }
  }
  return messages;
}

/** Delivery updates for messages we sent (sent / delivered / read / failed). */
export function parseStatuses(body) {
  const out = [];
  for (const entry of body?.entry || []) {
    for (const change of entry.changes || []) {
      for (const s of change.value?.statuses || []) {
        const err = s.errors?.[0];
        out.push({ id: s.id, status: s.status, to: s.recipient_id, error: err ? `${err.title || err.message || "error"}${err.code ? ` (code ${err.code})` : ""}` : "" });
      }
    }
  }
  return out;
}

export class WhatsApp {
  constructor({ token, phoneNumberId, apiVersion = "v23.0" }, { fetchImpl = globalThis.fetch, log = console } = {}) {
    this.token = token;
    this.phoneNumberId = phoneNumberId;
    this.apiVersion = apiVersion;
    this.fetch = fetchImpl;
    this.log = log;
    this.dryRun = !token || !phoneNumberId;
  }

  async #post(payload) {
    if (this.dryRun) {
      this.log.info?.("[dry-run] would send", JSON.stringify(payload));
      return { id: "dryrun-" + Date.now() };
    }
    const res = await this.fetch(`https://graph.facebook.com/${this.apiVersion}/${this.phoneNumberId}/messages`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ messaging_product: "whatsapp", ...payload }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(`WhatsApp API ${res.status}: ${json.error?.message || "request failed"}`);
    return { id: json.messages?.[0]?.id || "" };
  }

  sendText(to, body) {
    return this.#post({ recipient_type: "individual", to, type: "text", text: { preview_url: false, body } });
  }

  /** Blue ticks plus a "typing…" bubble while the AI writes. Never fails the reply. */
  markReadTyping(messageId) {
    return this.#post({ status: "read", message_id: messageId, typing_indicator: { type: "text" } })
      .catch(() => this.#post({ status: "read", message_id: messageId }).catch(() => {}));
  }
}
