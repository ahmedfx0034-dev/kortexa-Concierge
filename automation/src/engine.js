// The follow-up engine: what happens when an agency messages us, and which
// automatic follow-ups are due. Kept free of HTTP so it is easy to test.

import { windowOpen } from "./whatsapp.js";

const DAY = 86400000;
const STOP_WORDS = /^\s*(stop|unsubscribe|stop messaging|remove me|don'?t message|do not message|no more messages?)\b/i;
const CLOSED = new Set(["opted_out", "won", "lost", "demo"]);

/** Decide the next automatic message for a lead, or null. Pure function. */
export function nextAction(lead, now, cfg) {
  if (!lead || lead.paused || CLOSED.has(lead.status)) return null;
  if (lead.status === "new") return cfg.sendOpener ? { kind: "opener", template: cfg.templates.opener } : null;
  // They wrote last: a person (or the AI) should answer, not a follow-up template.
  if (lead.lastInboundAt > lead.lastOutboundAt) return null;
  const silentFor = now - Math.max(lead.lastOutboundAt, lead.lastInboundAt);
  if (lead.followupStep === 0 && silentFor >= cfg.followups.firstAfterDays * DAY)
    return { kind: "followup1", template: cfg.templates.followup1 };
  if (lead.followupStep === 1 && silentFor >= cfg.followups.secondAfterDays * DAY)
    return { kind: "followup2", template: cfg.templates.followup2 };
  return null;
}

export function withinSendingHours(now, cfg) {
  const h = new Date(now).getUTCHours(); // Ghana = UTC+0, no daylight saving
  return h >= cfg.followups.sendFromHour && h < cfg.followups.sendUntilHour;
}

export class Engine {
  constructor({ store, wa, ai, cfg, log = console }) {
    Object.assign(this, { store, wa, ai, cfg, log });
  }

  async #send(lead, { text, template, kind, by }) {
    const res = template
      ? await this.wa.sendTemplate(lead.waId, template, [lead.name || "there"])
      : await this.wa.sendText(lead.waId, text);
    this.store.addMessage({ id: res.id, waId: lead.waId, direction: "out", kind, by, text: text || `[template: ${template}]`, status: "sent" });
    lead.lastOutboundAt = Date.now();
    this.store.logSend();
    return res;
  }

  /** Send a free-form reply typed (or approved) on the admin page. */
  async replyManually(waId, text, by = "you") {
    const lead = this.store.lead(waId);
    if (!lead) throw new Error("Unknown lead");
    if (!windowOpen(lead)) throw new Error("The 24-hour window has closed. WhatsApp only allows an approved template now.");
    await this.#send(lead, { text, kind: "reply", by });
    lead.draft = null;
    if (lead.status === "new") lead.status = "active";
    await this.store.save();
  }

  /** Handle one inbound WhatsApp message. */
  async onInbound(msg) {
    if (this.store.seen(msg.id)) return;
    const lead = this.store.lead(msg.from) || this.store.upsertLead(msg.from, { name: msg.profileName, source: "inbound" });
    this.store.addMessage({ id: msg.id, waId: msg.from, direction: "in", text: msg.text, at: msg.at });
    lead.lastInboundAt = msg.at || Date.now();
    lead.followupStep = 0;
    if (!lead.name && msg.profileName) lead.name = msg.profileName;
    this.wa.markRead?.(msg.id);

    if (STOP_WORDS.test(msg.text)) {
      lead.status = "opted_out";
      lead.draft = null;
      await this.#send(lead, { text: "Understood. You won't receive any more messages from Kortexa. Thank you!", kind: "optout", by: "system" }).catch((e) => this.log.error("opt-out confirm failed:", e.message));
      return this.store.save();
    }
    if (lead.status === "new" || lead.status === "lost") lead.status = "active";
    await this.store.save();

    if (this.cfg.ai.mode === "off" || !this.ai || lead.status === "opted_out") return;
    let out = null;
    try { out = await this.ai.draft(lead, this.store.messagesFor(lead.waId)); }
    catch (e) { this.log.error("AI draft failed:", e.message); }
    if (!out) return;

    if (out.intent === "stop") lead.status = "opted_out";
    else if (out.intent === "not_interested") lead.status = "lost";
    else if (out.intent === "booked") { lead.status = "demo"; lead.meetingTime = out.meeting_time; }
    const needsHuman = out.intent === "needs_human";
    if (needsHuman) lead.needsHuman = true;

    // Auto mode sends straight away, except when the AI asks for a human.
    if (this.cfg.ai.mode === "auto" && !needsHuman && windowOpen(lead)) {
      try { await this.#send(lead, { text: out.reply, kind: "ai", by: "ai" }); lead.draft = null; }
      catch (e) { this.log.error("AI reply send failed:", e.message); lead.draft = { text: out.reply, intent: out.intent, at: Date.now() }; }
    } else {
      lead.draft = { text: out.reply, intent: out.intent, at: Date.now() };
    }
    await this.store.save();
  }

  onStatus(s) {
    const m = this.store.updateMessageStatus(s.id, s.status, s.error);
    if (m && s.status === "failed") this.log.warn(`Message to ${s.to} failed: ${s.error}`);
  }

  /** Send every follow-up that is due. Called on a timer. */
  async tick(now = Date.now()) {
    if (!withinSendingHours(now, this.cfg)) return { sent: 0, skipped: "outside sending hours" };
    let sent = 0;
    for (const lead of this.store.leads()) {
      if (this.store.sentInLast24h() >= this.cfg.followups.dailyCap) return { sent, skipped: "daily cap reached" };
      const action = nextAction(lead, now, this.cfg);
      if (!action) continue;
      try {
        await this.#send(lead, { template: action.template, kind: action.kind, by: "auto" });
        if (action.kind === "opener") lead.status = "active";
        else lead.followupStep += 1;
        sent++;
      } catch (e) {
        this.log.error(`Follow-up to ${lead.waId} failed:`, e.message);
        // 131050 = user stopped marketing messages; 131026 = not on WhatsApp.
        if (e.code === 131050) lead.status = "opted_out";
        else if (e.code === 131026) { lead.paused = true; lead.notes = (lead.notes ? lead.notes + " | " : "") + "Not reachable on WhatsApp"; }
      }
      await this.store.save();
    }
    return { sent };
  }
}
