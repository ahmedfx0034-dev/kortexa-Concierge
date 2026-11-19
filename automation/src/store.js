// A small JSON-file database. Fine for a few thousand leads.
// Writes go to a temp file first, then replace the real file, so a crash
// mid-write never corrupts your data.

import fs from "node:fs";
import path from "node:path";

const EMPTY = () => ({ leads: {}, messages: [], sentLog: [], processedIds: [] });

export class Store {
  constructor(file) {
    this.file = file;
    this.data = EMPTY();
    this.saving = Promise.resolve();
    if (file && fs.existsSync(file)) {
      this.data = Object.assign(EMPTY(), JSON.parse(fs.readFileSync(file, "utf8")));
    }
  }

  save() {
    if (!this.file) return Promise.resolve();
    const snapshot = JSON.stringify(this.data, null, 1);
    this.saving = this.saving.then(async () => {
      await fs.promises.mkdir(path.dirname(this.file), { recursive: true });
      const tmp = this.file + ".tmp";
      await fs.promises.writeFile(tmp, snapshot);
      await fs.promises.rename(tmp, this.file);
    });
    return this.saving;
  }

  // ---- leads -------------------------------------------------------
  lead(waId) { return this.data.leads[waId] || null; }
  leads() { return Object.values(this.data.leads); }

  upsertLead(waId, fields) {
    const now = Date.now();
    const cur = this.data.leads[waId];
    this.data.leads[waId] = cur
      ? { ...cur, ...fields, updatedAt: now }
      : {
          waId, name: "", city: "", email: "", notes: "",
          status: "new",         // new | active | demo | won | lost | opted_out
          followupStep: 0,       // automatic follow-ups sent since their last message
          lastInboundAt: 0, lastOutboundAt: 0,
          paused: false,         // true = no automatic messages to this lead
          draft: null,           // AI-suggested reply waiting for approval
          createdAt: now, updatedAt: now,
          ...fields,
        };
    return this.data.leads[waId];
  }

  // ---- messages ----------------------------------------------------
  addMessage(msg) {
    const m = { id: msg.id || "local-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8), at: Date.now(), status: "", ...msg };
    this.data.messages.push(m);
    return m;
  }
  messagesFor(waId) { return this.data.messages.filter((m) => m.waId === waId); }
  updateMessageStatus(id, status, error) {
    const m = this.data.messages.find((x) => x.id === id);
    if (m) { m.status = status; if (error) m.error = error; }
    return m;
  }

  // ---- dedupe webhook deliveries (Meta can deliver the same event twice) ----
  seen(messageId) {
    if (this.data.processedIds.includes(messageId)) return true;
    this.data.processedIds.push(messageId);
    if (this.data.processedIds.length > 5000) this.data.processedIds.splice(0, 1000);
    return false;
  }

  // ---- daily cap -----------------------------------------------------
  logSend() {
    this.data.sentLog.push(Date.now());
    const cutoff = Date.now() - 2 * 86400000;
    this.data.sentLog = this.data.sentLog.filter((t) => t > cutoff);
  }
  sentInLast24h() {
    const cutoff = Date.now() - 86400000;
    return this.data.sentLog.filter((t) => t > cutoff).length;
  }
}
