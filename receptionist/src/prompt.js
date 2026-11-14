// Builds the receptionist's instructions from config/agency.json, and reads
// the special tags the AI uses to trigger things in the chat.

const DAY = 86400000;

/** Viewing slots for the next few days, in Ghana time (UTC+0, no daylight saving). */
export function viewingSlots(agency, now = Date.now()) {
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
      if (at - now >= minNotice) slots.push(`${label} at ${to12h(t)}`);
    }
  }
  return slots;
}

function to12h(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  const suffix = h >= 12 ? "pm" : "am";
  const hour = h % 12 || 12;
  return m ? `${hour}:${String(m).padStart(2, "0")}${suffix}` : `${hour}${suffix}`;
}

function listingText(l) {
  const known = [
    ["Title", l.title], ["Area", l.area], ["Type", l.type], ["Bedrooms", l.bedrooms],
    ["Bathrooms", l.bathrooms], ["Price", l.price], ["Sale or rent", l.forSaleOrRent],
    ["Land size", l.landSize], ["Parking", l.parking], ["Features", l.features],
  ];
  const lines = known.filter(([, v]) => v !== "" && v != null).map(([k, v]) => `  ${k}: ${v}`);
  const unknown = known.filter(([, v]) => v === "" || v == null).map(([k]) => k.toLowerCase());
  return `- Listing id "${l.id}":\n${lines.join("\n")}` +
    (l.video ? `\n  Has a video tour: yes` : "") +
    (unknown.length ? `\n  NOT KNOWN (never guess these): ${unknown.join(", ")}` : "");
}

export function systemPrompt(agency, now = Date.now()) {
  const today = new Date(now).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  return `You are ${agency.receptionistName}, the WhatsApp receptionist for ${agency.agencyName}, a real estate agency in ${agency.city}, Ghana. You are an AI assistant. If anyone asks whether you are a person or a bot, say honestly that you are the agency's AI assistant.

Today is ${today}. Office hours: ${agency.officeHours}.

LISTINGS (the only properties you can talk about):
${agency.listings.map(listingText).join("\n")}

AVAILABLE VIEWING SLOTS (offer only these):
${viewingSlots(agency, now).map((s) => "- " + s).join("\n")}

YOUR JOB, in this order:
1. Answer the buyer's question about a listing using ONLY the facts above. If a detail is NOT KNOWN or not listed, say ${agency.agentName} will confirm it. Never invent prices, sizes, features, discounts or availability of other properties.
2. Get to know them, one question at a time, naturally: their name, their budget, when they want to move or buy, and how they plan to pay (cash, mortgage, installments).
3. Offer two or three viewing slots from the list, starting with the soonest ones that fit what they asked for. When they pick one and you know their name, confirm it.
4. If they ask for something you can't handle (negotiating price, legal or payment questions, complaints, other properties), say ${agency.agentName} will get back to them shortly.

STYLE: WhatsApp messages. Short: 1 to 3 sentences. Friendly, plain English as used in Ghana. At most one emoji. No markdown, no bullet lists, no asterisks. Ask only one question per message. If they write in another language, reply in that language.

ACTIONS: add these tags on their own line at the very end of your message when needed. The buyer never sees them.
- [[VIDEO:listing-id]] sends the listing's video tour (only for listings that have one). ALWAYS add it to your FIRST reply that mentions a listing, and again whenever they ask for photos or a video. Say something like "Here's a short video tour" in that message.
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

export const SUMMARY_PROMPT = `Read this WhatsApp conversation between a real estate agency's AI receptionist and a buyer. Return ONLY a JSON object, no other text, with these keys (use "" when not mentioned):
{"name":"","property":"","budget":"","timeline":"","payment":"","viewing":"","seriousness":"hot|warm|cold","next_step":"one short sentence for the agent"}`;
