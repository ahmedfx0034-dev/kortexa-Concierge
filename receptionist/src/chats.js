// Remembers each customer's WhatsApp conversation and lead details.
// Saved to a JSON file when DATA_FILE is set; otherwise kept in memory only
// (fine for a demo, but lost when the server restarts).

import fs from "node:fs";
import path from "node:path";

const KEEP_MESSAGES = 40;

export class Chats {
  constructor(file) {
    this.file = file || "";
    this.data = { chats: {}, seen: [] };
    if (this.file && fs.existsSync(this.file)) this.data = { chats: {}, seen: [], ...JSON.parse(fs.readFileSync(this.file, "utf8")) };
    this.saving = Promise.resolve();
  }

  get(waId) {
    return (this.data.chats[waId] ||= {
      waId, name: "", messages: [],
      aiPaused: false,     // true after a hand-off: a human answers instead
      optedOut: false,     // customer asked us to stop
      booking: null,       // {listing, slot, name, at, reminded}
      lead: null,          // details captured from the chat (budget, timeline, ...)
      score: 0, temperature: "", missing: [],   // qualification
      nudges: 0,           // follow-ups sent since their last message
      buyerMessages: 0,
      summary: null,
      needsHuman: false,
      createdAt: Date.now(), updatedAt: Date.now(),
    });
  }

  all() { return Object.values(this.data.chats).sort((a, b) => b.updatedAt - a.updatedAt); }

  add(waId, role, content) {
    const c = this.get(waId);
    c.messages.push({ role, content, at: Date.now() });
    if (c.messages.length > KEEP_MESSAGES) c.messages.splice(0, c.messages.length - KEEP_MESSAGES);
    c.updatedAt = Date.now();
    return c;
  }

  /** True if this WhatsApp message id was already handled (Meta can deliver twice). */
  seen(id) {
    if (this.data.seen.includes(id)) return true;
    this.data.seen.push(id);
    if (this.data.seen.length > 3000) this.data.seen.splice(0, 1000);
    return false;
  }

  save() {
    if (!this.file) return Promise.resolve();
    const snapshot = JSON.stringify(this.data);
    this.saving = this.saving.then(async () => {
      await fs.promises.mkdir(path.dirname(this.file), { recursive: true });
      await fs.promises.writeFile(this.file + ".tmp", snapshot);
      await fs.promises.rename(this.file + ".tmp", this.file);
    }).catch((e) => console.error("save failed:", e.message));
    return this.saving;
  }
}
