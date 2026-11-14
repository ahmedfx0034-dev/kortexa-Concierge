// What happens when a customer sends the agency a WhatsApp message.

import { systemPrompt, parseReply, SUMMARY_PROMPT } from "./prompt.js";

const STOP = /^\s*(stop|unsubscribe|stop messaging( me)?)\s*[.!]*\s*$/i;
const START = /^\s*(start|resume)\s*[.!]*\s*$/i;

export class Receptionist {
  constructor({ agency, llm, wa, chats, limiter, now = () => Date.now(), log = console }) {
    Object.assign(this, { agency, llm, wa, chats, limiter, now, log });
    this.queues = new Map(); // one message at a time per customer, in order
  }

  /** Handle one incoming WhatsApp message. Messages from the same person run in order. */
  handle(msg) {
    const prev = this.queues.get(msg.from) || Promise.resolve();
    const next = prev.then(() => this.#handle(msg)).catch((e) => this.log.error("receptionist:", e.message));
    this.queues.set(msg.from, next);
    next.finally(() => { if (this.queues.get(msg.from) === next) this.queues.delete(msg.from); });
    return next;
  }

  async #reply(c, text) {
    await this.wa.sendText(c.waId, text);
    this.chats.add(c.waId, "assistant", text);
  }

  async #handle(msg) {
    if (this.chats.seen(msg.id)) return;
    const c = this.chats.get(msg.from);
    if (msg.name && !c.name) c.name = msg.name;

    if (STOP.test(msg.text)) {
      c.optedOut = true;
      this.chats.add(c.waId, "user", msg.text);
      await this.#reply(c, "Okay, you won't get any more messages from us. Reply START anytime if you change your mind.");
      return this.chats.save();
    }
    if (c.optedOut) {
      if (!START.test(msg.text)) return this.chats.save();
      c.optedOut = false;
    }

    if (!msg.text) {
      this.chats.add(c.waId, "user", `[sent a ${msg.type}]`);
      if (!c.aiPaused) await this.#reply(c, "Thanks! I can only read text messages for now. Could you type your question?");
      return this.chats.save();
    }

    this.chats.add(c.waId, "user", msg.text);
    if (c.aiPaused) { c.needsHuman = true; return this.chats.save(); } // a person is handling this chat

    const tooMany = this.limiter.allow(c.waId, this.now());
    if (tooMany) { this.log.warn(`limit for ${c.waId}: ${tooMany}`); return this.chats.save(); }

    this.wa.markReadTyping(msg.id);
    let parsed;
    try {
      const history = c.messages.map(({ role, content }) => ({ role, content }));
      parsed = parseReply(await this.llm.chat([{ role: "system", content: systemPrompt(this.agency, this.now()) }, ...history]), this.agency);
    } catch (e) {
      this.log.error("AI failed:", e.message);
      c.needsHuman = true;
      await this.#reply(c, `Sorry, I'm having a little trouble right now. ${cap(this.agency.agentName)} will reply to you shortly.`).catch(() => {});
      return this.chats.save();
    }

    if (parsed.text) await this.#reply(c, parsed.text);
    for (const a of parsed.actions) {
      if (a.type === "video") {
        await this.wa.sendVideo(c.waId, a.url, a.title).catch((e) => this.log.error("video failed:", e.message));
        this.chats.add(c.waId, "assistant", `[shared the video tour of ${a.title}]`);
      } else if (a.type === "booked") {
        c.booking = { listing: a.listing, slot: a.slot, name: a.name, at: this.now() };
        c.needsHuman = true; // the agent should confirm the viewing
      } else if (a.type === "handoff") {
        c.aiPaused = true;
        c.needsHuman = true;
      }
    }
    await this.chats.save();
    if (c.booking || c.aiPaused) await this.summarize(c);
  }

  /** Ask the AI for a short lead summary the agent can read at a glance. */
  async summarize(c) {
    try {
      const transcript = c.messages.map((m) => `${m.role === "user" ? "BUYER" : "RECEPTIONIST"}: ${m.content}`).join("\n");
      const raw = await this.llm.chat([{ role: "system", content: SUMMARY_PROMPT }, { role: "user", content: transcript }], { maxTokens: 300, temperature: 0 });
      const m = raw.match(/\{[\s\S]*\}/);
      if (m) { c.summary = JSON.parse(m[0]); await this.chats.save(); }
    } catch (e) { this.log.error("summary failed:", e.message); }
  }
}

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
