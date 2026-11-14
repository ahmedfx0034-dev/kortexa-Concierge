// What happens when a customer sends the agency a WhatsApp message, plus the
// viewing reminders that run on a timer. (No follow-ups to buyers who go quiet.)

import { systemPrompt, parseReply, LEAD_PROMPT, scoreLead, slotTime } from "./prompt.js";

const HOUR = 3600000;
const WINDOW = 24 * HOUR; // WhatsApp: free messages only within 24h of the customer's last message
const STOP = /^\s*(stop|unsubscribe|stop messaging( me)?)\s*[.!]*\s*$/i;
const START = /^\s*(start|resume)\s*[.!]*\s*$/i;

export const DEFAULTS = {
  reminderHours: 3,       // viewing reminder this long before the viewing
  extractEvery: 2,        // refresh the lead details every N buyer messages
};

export function stageOf(c) {
  if (c.optedOut) return "Opted out";
  if (c.aiPaused) return "With agent";
  if (c.booking) return "Viewing booked";
  if (c.temperature === "hot") return "Qualified";
  return "Qualifying";
}

export class Receptionist {
  constructor({ agency, llm, wa, chats, limiter, now = () => Date.now(), log = console, settings = {} }) {
    Object.assign(this, { agency, llm, wa, chats, limiter, now, log });
    this.settings = { ...DEFAULTS, ...settings };
    this.queues = new Map(); // one job at a time per customer, in order
  }

  /** Run jobs for the same customer one after another. */
  #enqueue(waId, job) {
    const prev = this.queues.get(waId) || Promise.resolve();
    const next = prev.then(job).catch((e) => this.log.error("receptionist:", e.message));
    this.queues.set(waId, next);
    next.finally(() => { if (this.queues.get(waId) === next) this.queues.delete(waId); });
    return next;
  }

  handle(msg) { return this.#enqueue(msg.from, () => this.#handle(msg)); }

  async #reply(c, text, kind = "reply") {
    await this.wa.sendText(c.waId, text);
    const m = this.chats.add(c.waId, "assistant", text);
    m.messages[m.messages.length - 1].kind = kind;
  }

  #history(c) { return c.messages.map(({ role, content }) => ({ role, content })); }

  async #handle(msg) {
    if (this.chats.seen(msg.id)) return;
    const c = this.chats.get(msg.from);
    if (msg.name && !c.name) c.name = msg.name;

    if (STOP.test(msg.text)) {
      c.optedOut = true;
      this.chats.add(c.waId, "user", msg.text);
      await this.#reply(c, "Okay, you won't get any more messages from us. Reply START anytime if you change your mind.", "optout");
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
    c.buyerMessages = (c.buyerMessages || 0) + 1;
    if (c.aiPaused) { c.needsHuman = true; return this.chats.save(); } // a person is handling this chat

    const tooMany = this.limiter.allow(c.waId, this.now());
    if (tooMany) { this.log.warn(`limit for ${c.waId}: ${tooMany}`); return this.chats.save(); }

    this.wa.markReadTyping(msg.id);
    let parsed;
    try {
      parsed = parseReply(await this.llm.chat([{ role: "system", content: systemPrompt(this.agency, this.now()) }, ...this.#history(c)]), this.agency);
    } catch (e) {
      this.log.error("AI failed:", e.message);
      c.needsHuman = true;
      await this.#reply(c, `Sorry, I'm having a little trouble right now. ${cap(this.agency.agentName)} will reply to you shortly.`).catch(() => {});
      return this.chats.save();
    }

    if (parsed.text) await this.#reply(c, parsed.text);
    const bookedNow = await this.#runActions(c, parsed.actions);
    await this.chats.save();
    if (bookedNow || c.aiPaused || c.buyerMessages % this.settings.extractEvery === 0) await this.updateLead(c);
  }

  async #runActions(c, actions) {
    let booked = false;
    for (const a of actions) {
      if (a.type === "video") {
        await this.wa.sendVideo(c.waId, a.url, a.title).catch((e) => this.log.error("video failed:", e.message));
        this.chats.add(c.waId, "assistant", `[shared the video tour of ${a.title}]`);
      } else if (a.type === "booked") {
        c.booking = { listing: a.listing, slot: a.slot, name: a.name, at: slotTime(this.agency, a.slot, this.now()), bookedAt: this.now(), reminded: false };
        c.needsHuman = true; // the agent should confirm the viewing
        booked = true;
      } else if (a.type === "handoff") {
        c.aiPaused = true;
        c.needsHuman = true;
      }
    }
    return booked;
  }

  /** CAPTURE + QUALIFY: pull the buyer's details out of the chat and score them. */
  async updateLead(c) {
    try {
      const transcript = c.messages.map((m) => `${m.role === "user" ? "BUYER" : "RECEPTIONIST"}: ${m.content}`).join("\n");
      const raw = await this.llm.chat([{ role: "system", content: LEAD_PROMPT }, { role: "user", content: transcript }], { maxTokens: 400, temperature: 0 });
      const m = raw.match(/\{[\s\S]*\}/);
      if (!m) return;
      c.lead = JSON.parse(m[0]);
      if (c.lead.name && !c.name) c.name = c.lead.name;
    } catch (e) { this.log.error("lead update failed:", e.message); }
    Object.assign(c, scoreLead(c.lead || {}, c.booking));
    c.summary = c.lead; // older inbox field
    await this.chats.save();
  }

  /** Remind people about booked viewings. Called on a timer. */
  async tick(now = this.now()) {
    let sent = 0;
    for (const c of this.chats.all()) {
      if (c.optedOut || c.aiPaused) continue;
      const lastIn = [...c.messages].reverse().find((m) => m.role === "user");
      if (!lastIn) continue;
      const windowLeft = lastIn.at + WINDOW - now;

      // Viewing reminder (any hour, it's about their appointment)
      const b = c.booking;
      if (b?.at && !b.reminded && now >= b.at - this.settings.reminderHours * HOUR && now < b.at) {
        await this.#enqueue(c.waId, async () => {
          if (windowLeft > 0) {
            const time = new Date(b.at).toLocaleTimeString("en-GB", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "UTC" });
            await this.#reply(c, `Hi${b.name ? " " + b.name : ""}, a quick reminder of your viewing of the ${b.listing} today at ${time}. ${cap(this.agency.agentName)} will share the exact meeting point. Reply here if anything changes.`, "reminder");
            sent++;
          } else {
            c.needsHuman = true; // outside the free window: the agent should call instead
            c.agentNote = "Viewing soon, but WhatsApp's free 24-hour window has closed. Call them to confirm.";
          }
          b.reminded = true;
          await this.chats.save();
        });
        continue;
      }

    }
    return { sent };
  }
}

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
