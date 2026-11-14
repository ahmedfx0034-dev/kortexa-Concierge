// Builds the receptionist's instructions from config/agency.json, and reads
// the special tags the AI uses to trigger things in the chat.

const DAY = 86400000;

/** Viewing slots for the next few days, in Ghana time (UTC+0, no daylight saving): [{label, at}]. */
export function viewingSlotTimes(agency, now = Date.now()) {
  const slots = [];
  const days = agency.viewingDaysAhead || 3;
  const minNotice = (agency.minNoticeHours ?? 2) * 3600000;
  for (let d = 0; d <= days; d++) {
    const date = new Date(now + d * DAY);
    if (date.getUTCDay() === 0) continue; // closed on Sunday
    const label = (d === 0 ? "today, " : "") + date.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
    for (const t of agency.viewingTimes || []) {
      const [h, m] = t.split(":").map(Number);
      const at = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate(), h, m || 0);
      if (at - now >= minNotice) slots.push({ label: `${label} at ${to12h(t)}`, at });
    }
  }
  return slots;
}

export const viewingSlots = (agency, now) => viewingSlotTimes(agency, now).map((s) => s.label);

/** Turn the slot text the AI booked back into a time, so reminders can be sent. */
export function slotTime(agency, label, now = Date.now()) {
  const norm = (s) => String(s).toLowerCase().replace(/^today,\s*/, "").replace(/\s+/g, " ").trim();
  return viewingSlotTimes(agency, now).find((s) => norm(s.label) === norm(label))?.at || null;
}

function to12h(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  const suffix = h >= 12 ? "pm" : "am";
  const hour = h % 12 || 12;
  return m ? `${hour}:${String(m).padStart(2, "0")}${suffix}` : `${hour}${suffix}`;
}

function listingText(l) {
  const known = [
    ["Title", l.title], ["Area", l.area], ["Type", l.type], ["Sale or rent", l.forSaleOrRent], ["Price", l.price],
    ["Bedrooms", l.bedrooms], ["Bathrooms", l.bathrooms], ["Land size", l.landSize], ["Parking", l.parking],
    ["Furnishing", l.furnished], ["Features", l.features], ["Payment terms", l.terms],
  ];
  const notApplicable = l.type && /land/i.test(l.type) ? new Set(["Bedrooms", "Bathrooms", "Parking", "Furnishing", "Payment terms"]) : new Set(["Payment terms"]);
  const lines = known.filter(([, v]) => v !== "" && v != null).map(([k, v]) => `  ${k}: ${v}`);
  const unknown = known.filter(([k, v]) => (v === "" || v == null) && !notApplicable.has(k)).map(([k]) => k.toLowerCase());
  return `- Listing id "${l.id}":\n${lines.join("\n")}` +
    `\n  Has a video tour: ${l.video ? "yes" : "no (offer a viewing instead)"}` +
    (unknown.length ? `\n  NOT KNOWN (never guess these): ${unknown.join(", ")}` : "");
}

export function systemPrompt(agency, now = Date.now()) {
  const today = new Date(now).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  return `You are ${agency.receptionistName}, the WhatsApp receptionist for ${agency.agencyName}, a real estate agency in ${agency.city}, Ghana. You are an AI assistant. If anyone asks whether you are a person or a bot, say honestly that you are the agency's AI assistant.

Today is ${today}. Office hours: ${agency.officeHours}.${agency.officeAddress ? ` Office: ${agency.officeAddress}.` : ""}
Commission or agency fees: ${agency.commission || "NOT KNOWN, say the agent will explain"}.

LISTINGS (the only properties you can talk about):
${agency.listings.map(listingText).join("\n")}

AVAILABLE VIEWING SLOTS (offer only these):
${viewingSlots(agency, now).map((s) => "- " + s).join("\n")}

YOUR JOB, in this order:
1. Answer the buyer's question about a listing using ONLY the facts above. If they ask what's available, briefly suggest the listings that match what they want (sale or rent, area, bedrooms, budget). Only mention a listing's video tour if it has one. If a detail is NOT KNOWN or not listed, say ${agency.agentName} will confirm it. Never invent prices, sizes, features, discounts or availability of other properties.
2. CAPTURE AND QUALIFY: while helping, find out these things, one question at a time and in a natural order (never as a form):
   a) their name
   b) buying or renting, and what they want (type, bedrooms, area)
   c) their budget
   d) when they want to move in or buy
   e) how they will pay (cash, mortgage, installments; for rent: can they pay the advance)
   f) whether it's to live in or an investment
   Skip anything they already told you. If a listing doesn't fit their budget or needs, say so honestly and suggest the closest one that does.
3. Once you know what they want, offer two or three viewing slots from the list, starting with the soonest. When they pick one and you know their name, confirm it. If they hesitate, find out why (price, location, timing, spouse needs to see it) and answer from the facts.
4. If they ask for something you can't handle (negotiating price, legal or payment questions, complaints, other properties), say ${agency.agentName} will get back to them shortly.

STYLE: WhatsApp messages. Short: 1 to 3 sentences. Friendly, plain English as used in Ghana. At most one emoji. No markdown, no bullet lists, no asterisks. Ask only one question per message, and don't repeat a question they skipped: move on to the next useful one and come back to it later. If they write in another language, reply in that language.

ACTIONS: add these tags on their own line at the very end of your message when needed. The buyer never sees them.
- [[VIDEO:listing-id]] sends the listing's video tour. Only for listings marked "Has a video tour: yes". ALWAYS add it to your FIRST reply that talks about such a listing, and again whenever they ask for photos or a video of it. Say something like "Here's a short video tour" in that message.
- [[BOOKED:listing-id|slot exactly as written above|buyer's name]] only once the buyer has clearly chosen a slot and you know their name.
- [[HANDOFF]] when ${agency.agentName} needs to take over.`;
}

const TAG = /\[\[(VIDEO|BOOKED|HANDOFF)(?::([^\]]*))?\]\]/g;

/** Strip action tags from the AI's text and return them as structured actions. */
export function parseReply(raw, agency) {
  const actions = [];
  const text = String(raw || "").replace(TAG, (_, kind, arg = "") => {
    if (kind === "VIDEO") {
      const l = agency.listings.find((x) => x.id === arg.trim());
      if (l?.video) actions.push({ type: "video", url: l.video, title: l.title });
    } else if (kind === "BOOKED") {
      const [listingId, slot, name] = arg.split("|").map((s) => (s || "").trim());
      const l = agency.listings.find((x) => x.id === listingId);
      if (slot) actions.push({ type: "booked", listing: l?.title || listingId, slot, name });
    } else if (kind === "HANDOFF") actions.push({ type: "handoff" });
    return "";
  }).replace(/\*\*/g, "").replace(/\n{3,}/g, "\n\n").trim();
  // Never send the same action twice in one reply.
  const seen = new Set();
  return { text, actions: actions.filter((a) => { const k = JSON.stringify(a); return seen.has(k) ? false : seen.add(k); }) };
}

export const LEAD_PROMPT = `Read this WhatsApp conversation between a real estate agency's AI receptionist and a buyer or tenant. Extract what the BUYER said. Return ONLY a JSON object, no other text. Use "" when not mentioned, never guess.
{"name":"","looking_for":"buy|rent|","property_type":"","areas":"","bedrooms":"","budget":"","timeline":"","timeline_months":null,"payment":"","purpose":"live|invest|","interested_listing":"","objections":"","viewing":"","next_step":"one short sentence telling the agent what to do next"}
timeline_months = how many months until they want to move or buy, as a number (0 = now/this month), or null if unknown.`;

/** Kept for the web demo page. */
export const SUMMARY_PROMPT = LEAD_PROMPT;

/**
 * Lead score from the facts the buyer gave, so "hot" means the same thing every time.
 * 100 points: budget 20, timeline 25 (sooner = more), payment 15, needs 10, name 5, viewing booked 25.
 */
export function scoreLead(lead = {}, booking = null) {
  const has = (v) => v != null && String(v).trim() !== "";
  let score = 0;
  const missing = [];
  if (has(lead.name)) score += 5; else missing.push("name");
  if (has(lead.looking_for) && (has(lead.property_type) || has(lead.bedrooms) || has(lead.areas))) score += 10; else missing.push("what they want");
  if (has(lead.budget)) score += 20; else missing.push("budget");
  const m = typeof lead.timeline_months === "number" ? lead.timeline_months : null;
  if (m !== null) score += m <= 1 ? 25 : m <= 3 ? 18 : m <= 6 ? 10 : 4;
  else if (has(lead.timeline)) score += 8;
  else missing.push("timeline");
  if (has(lead.payment)) score += 15; else missing.push("payment");
  if (booking) score += 25;
  const temperature = score >= 70 ? "hot" : score >= 40 ? "warm" : "cold";
  return { score, temperature, missing };
}

/** Instruction used when the buyer has gone quiet, so the AI writes a follow-up. */
export function nudgeInstruction(kind, lead = {}) {
  const missing = scoreLead(lead).missing;
  const base = kind === "last"
    ? "This is the last follow-up you are allowed to send, because WhatsApp only allows free messages within 24 hours of their last message."
    : "The buyer stopped replying a few hours ago.";
  return `[Note from the system, not from the buyer] ${base} Write ONE short, friendly follow-up message (1 to 2 sentences) that gives them an easy reason to reply. ` +
    `Pick what fits best: offer a viewing slot from the list, mention one helpful fact about the listing they liked (or the closest match to what they want), or ask ${missing.length ? `about their ${missing[0]}` : "if they'd like to book a viewing"}. ` +
    `Don't say you are following up "as a reminder", don't be pushy, don't repeat your last message, and don't use any action tags except [[VIDEO:...]] if they haven't seen that video yet.`;
}
