// Drafts WhatsApp replies to agencies with Claude.
// Needs ANTHROPIC_API_KEY in the environment.
// Product facts come from kortexa-facts.md (or KORTEXA_FACTS_FILE), which you edit.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Anthropic from "@anthropic-ai/sdk";

const here = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_FACTS = path.join(here, "..", "kortexa-facts.md");

const SYSTEM = `You write WhatsApp replies for Kortexa, on behalf of {sender}. You are talking to a real estate agency in Ghana that replied to Kortexa's outreach.

<facts>
{facts}
</facts>

Only state facts from the <facts> block. Never invent prices, clients, results, testimonials, features or numbers. Never call anything free. If they ask something the facts don't cover, say {sender} will confirm it.

How to write (persuasive copy principles):
- Lead with their problem, not the product. Speak to the deeper problem behind what they mention, and challenge the limiting belief described in the facts.
- Emotion first, then the logical reason.
- Talk one-to-one: use "you", not "agencies" in general.
- Keep the stakes low: all they have to do is the one easy step in the facts.
- If they raise an objection, answer it with the matching benefit from the facts.
- Be upfront and respect their time. No hype.
- End with one clear, easy next step from "What we want them to do" in the facts.{booking}

Style: WhatsApp, not email. 1 to 4 short sentences. Plain English as used in Ghana business chat. At most one emoji. No markdown, no lists, no sign-off. Never pressure. If they write in another language, reply in that language.

Pick the intent that best describes their LATEST message:
- "question": they asked something or are chatting.
- "interested": they want to know more, want a seat, or replied YES. Send the booking link and the workshop date.
- "booked": they confirmed they booked a call or want to pay for a seat. Thank them and confirm the next step.
- "not_interested": they declined. Thank them politely and don't push.
- "stop": they asked not to be messaged. Reply with one short line confirming they won't be contacted again.
- "needs_human": prices, contracts, complaints, legal or payment questions, or anything you can't answer from the facts. Tell them {sender} will get back to them shortly.`;

const SCHEMA = {
  type: "object",
  properties: {
    reply: { type: "string", description: "The WhatsApp message to send." },
    intent: { type: "string", enum: ["question", "interested", "booked", "not_interested", "stop", "needs_human"] },
    meeting_time: { type: "string", description: "Any agreed day/time or commitment in their words, or an empty string." },
  },
  required: ["reply", "intent", "meeting_time"],
  additionalProperties: false,
};

export class ReplyWriter {
  constructor(cfg, { client, facts } = {}) {
    this.cfg = cfg;
    this.client = client || new Anthropic();
    const factsText = facts ?? fs.readFileSync(process.env.KORTEXA_FACTS_FILE || DEFAULT_FACTS, "utf8");
    this.system = SYSTEM.replace("{facts}", factsText.trim())
      .replaceAll("{sender}", cfg.senderName)
      .replace("{booking}", cfg.bookingLink ? ` When they want to talk, share this link so they can pick a time: ${cfg.bookingLink}` : "");
  }

  /** Returns {reply, intent, meeting_time}, or null when no usable reply came back. */
  async draft(lead, history) {
    const transcript = history
      .slice(-30)
      .map((m) => `${m.direction === "in" ? "AGENCY" : "KORTEXA"}: ${m.text}`)
      .join("\n");
    const content =
      `Agency: ${lead.name || "unknown name"}${lead.city ? ` (${lead.city})` : ""}\n` +
      (lead.notes ? `Notes from earlier outreach: ${lead.notes}\n` : "") +
      `\nConversation so far (oldest first):\n${transcript}\n\nWrite Kortexa's next WhatsApp reply.`;

    const response = await this.client.beta.messages.create({
      model: this.cfg.model,
      max_tokens: 4000,
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      output_config: { effort: "low", format: { type: "json_schema", schema: SCHEMA } },
      system: this.system,
      messages: [{ role: "user", content }],
    });

    if (response.stop_reason === "refusal" || response.stop_reason === "max_tokens") return null;
    const text = response.content.filter((b) => b.type === "text").map((b) => b.text).join("");
    try {
      const out = JSON.parse(text);
      if (!out.reply || !SCHEMA.properties.intent.enum.includes(out.intent)) return null;
      return out;
    } catch {
      return null;
    }
  }
}
