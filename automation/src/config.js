// All settings come from environment variables (see .env.example).
// Nothing secret is ever hard-coded here.

const env = process.env;

const num = (v, d) => (v === undefined || v === "" || Number.isNaN(Number(v)) ? d : Number(v));
const bool = (v, d = false) => (v === undefined || v === "" ? d : /^(1|true|yes|on)$/i.test(v));

export const config = {
  port: num(env.PORT, 3000),
  dataFile: env.DATA_FILE || "./data/store.json",

  // Admin page login (HTTP basic auth). Username is always "admin".
  adminPassword: env.ADMIN_PASSWORD || "",

  // WhatsApp Business Cloud API (Meta). Leave WHATSAPP_TOKEN empty to run in
  // dry-run mode: messages are logged and stored, never actually sent.
  whatsapp: {
    token: env.WHATSAPP_TOKEN || "",
    phoneNumberId: env.WHATSAPP_PHONE_NUMBER_ID || "",
    appSecret: env.WHATSAPP_APP_SECRET || "",
    verifyToken: env.WHATSAPP_VERIFY_TOKEN || "",
    apiVersion: env.WHATSAPP_API_VERSION || "v23.0",
    templateLanguage: env.WHATSAPP_TEMPLATE_LANGUAGE || "en",
  },

  // Names of the message templates you got approved in WhatsApp Manager.
  // Each takes one body variable, {{1}} = agency name.
  templates: {
    opener: env.TEMPLATE_OPENER || "kortexa_continue",
    followup1: env.TEMPLATE_FOLLOWUP_1 || "kortexa_followup_1",
    followup2: env.TEMPLATE_FOLLOWUP_2 || "kortexa_followup_2",
  },

  // Send the "opener" template to newly imported leads automatically.
  sendOpener: bool(env.SEND_OPENER, true),

  followups: {
    // Days of silence (after our last message) before each automatic follow-up.
    firstAfterDays: num(env.FOLLOWUP_1_DAYS, 2),
    secondAfterDays: num(env.FOLLOWUP_2_DAYS, 5),
    // Only send between these local hours (Ghana is UTC+0 all year).
    sendFromHour: num(env.SEND_FROM_HOUR, 9),
    sendUntilHour: num(env.SEND_UNTIL_HOUR, 18),
    // How often the scheduler checks for due follow-ups.
    checkEveryMinutes: num(env.CHECK_EVERY_MINUTES, 15),
    // Never send more than this many automatic messages per day.
    dailyCap: num(env.DAILY_CAP, 200),
  },

  // AI replies with Claude. "off" = humans reply from the admin page.
  // "draft" = Claude writes a suggested reply you approve. "auto" = Claude replies itself.
  ai: {
    mode: (env.AI_MODE || "draft").toLowerCase(),
    model: env.CLAUDE_MODEL || "claude-opus-5-5",
    senderName: env.SENDER_NAME || "the Kortexa team",
    bookingLink: env.BOOKING_LINK || "",
  },

  // Start the server without a real WhatsApp token (messages are only logged).
  get dryRun() {
    return !this.whatsapp.token || !this.whatsapp.phoneNumberId || bool(env.DRY_RUN);
  },
};
