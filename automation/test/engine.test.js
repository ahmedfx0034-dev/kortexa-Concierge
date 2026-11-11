import { test } from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { normalizeGhana, isGhanaMobile } from "../src/phone.js";
import { parseCsv } from "../src/csv.js";
import { Store } from "../src/store.js";
import { Engine, nextAction, withinSendingHours } from "../src/engine.js";
import { parseWebhook, validSignature, windowOpen } from "../src/whatsapp.js";
import { createApp } from "../src/server.js";

const DAY = 86400000;
const cfg = {
  sendOpener: true,
  templates: { opener: "op", followup1: "f1", followup2: "f2" },
  followups: { firstAfterDays: 2, secondAfterDays: 5, sendFromHour: 0, sendUntilHour: 24, dailyCap: 100 },
  ai: { mode: "auto" },
  whatsapp: {}, dryRun: true, adminPassword: "pw",
};

function fakeWa() {
  const sent = [];
  return {
    sent,
    sendText: async (to, body) => { sent.push({ to, body }); return { id: "out" + sent.length }; },
    sendTemplate: async (to, name, params) => { sent.push({ to, template: name, params }); return { id: "out" + sent.length }; },
    markRead: () => {},
  };
}
const quiet = { error() {}, warn() {}, info() {} };

test("normalizes Ghana numbers", () => {
  assert.equal(normalizeGhana("+233 24 123 4567"), "233241234567");
  assert.equal(normalizeGhana("0241234567"), "233241234567");
  assert.equal(normalizeGhana("+2330241234567"), "233241234567");
  assert.equal(normalizeGhana("12345"), "");
  assert.ok(isGhanaMobile("233241234567"));
  assert.ok(!isGhanaMobile("233302123456"));
});

test("parses the dashboard CSV export", () => {
  const rows = parseCsv('id,agency,whatsapp,notes\n3,"4myrent, Ltd",+233559921000,"said ""call me"""\n');
  assert.deepEqual(rows[0], { id: "3", agency: "4myrent, Ltd", whatsapp: "+233559921000", notes: 'said "call me"' });
});

test("follow-up schedule", () => {
  const now = Date.now();
  const base = { status: "active", followupStep: 0, lastInboundAt: now - 3 * DAY, lastOutboundAt: now - 3 * DAY + 1000, paused: false };
  assert.equal(nextAction({ ...base, status: "new" }, now, cfg).kind, "opener");
  assert.equal(nextAction(base, now, cfg).kind, "followup1");
  assert.equal(nextAction({ ...base, lastOutboundAt: now - DAY }, now, cfg), null, "too soon");
  assert.equal(nextAction({ ...base, followupStep: 1, lastInboundAt: now - 10 * DAY, lastOutboundAt: now - 6 * DAY }, now, cfg).kind, "followup2");
  assert.equal(nextAction({ ...base, followupStep: 2, lastOutboundAt: now - 30 * DAY }, now, cfg), null, "sequence ends");
  assert.equal(nextAction({ ...base, lastInboundAt: now }, now, cfg), null, "they wrote last");
  for (const status of ["opted_out", "demo", "won", "lost"]) assert.equal(nextAction({ ...base, status }, now, cfg), null);
  assert.equal(nextAction({ ...base, paused: true }, now, cfg), null);
});

test("sending hours use Ghana time (UTC)", () => {
  const c = { followups: { sendFromHour: 9, sendUntilHour: 18 } };
  assert.ok(withinSendingHours(Date.UTC(2026, 10, 11, 10), c));
  assert.ok(!withinSendingHours(Date.UTC(2026, 10, 11, 20), c));
});

test("STOP opts a lead out and confirms once", async () => {
  const store = new Store(null), wa = fakeWa();
  const engine = new Engine({ store, wa, ai: null, cfg, log: quiet });
  store.upsertLead("233241234567", { status: "active" });
  await engine.onInbound({ id: "m1", from: "233241234567", text: "STOP", at: Date.now() });
  await engine.onInbound({ id: "m1", from: "233241234567", text: "STOP", at: Date.now() }); // duplicate delivery
  assert.equal(store.lead("233241234567").status, "opted_out");
  assert.equal(wa.sent.length, 1);
  assert.equal((await engine.tick()).sent, 0);
});

test("AI auto mode replies, books demos and holds back on needs_human", async () => {
  const store = new Store(null), wa = fakeWa();
  let next = { reply: "Great, does Thursday 10am work?", intent: "interested", meeting_time: "" };
  const ai = { draft: async () => next };
  const engine = new Engine({ store, wa, ai, cfg, log: quiet });
  await engine.onInbound({ id: "a", from: "233200000001", profileName: "Prime Homes", text: "Tell me more", at: Date.now() });
  assert.equal(wa.sent.at(-1).body, "Great, does Thursday 10am work?");
  assert.equal(store.lead("233200000001").name, "Prime Homes");

  next = { reply: "Booked for Thursday 10am!", intent: "booked", meeting_time: "Thursday 10am" };
  await engine.onInbound({ id: "b", from: "233200000001", text: "Thursday 10 is fine", at: Date.now() });
  assert.equal(store.lead("233200000001").status, "demo");

  next = { reply: "Ahmed will confirm pricing on the call.", intent: "needs_human", meeting_time: "" };
  const before = wa.sent.length;
  await engine.onInbound({ id: "c", from: "233200000001", text: "How much is it?", at: Date.now() });
  assert.equal(wa.sent.length, before, "not sent automatically");
  assert.ok(store.lead("233200000001").draft);
});

test("manual reply is refused outside the 24-hour window", async () => {
  const store = new Store(null), wa = fakeWa();
  const engine = new Engine({ store, wa, ai: null, cfg, log: quiet });
  store.upsertLead("233200000002", { status: "active", lastInboundAt: Date.now() - 2 * DAY });
  assert.ok(!windowOpen(store.lead("233200000002")));
  await assert.rejects(engine.replyManually("233200000002", "hi"), /24-hour window/);
});

test("tick sends opener then follow-ups and respects the daily cap", async () => {
  const store = new Store(null), wa = fakeWa();
  const engine = new Engine({ store, wa, ai: null, cfg: { ...cfg, followups: { ...cfg.followups, dailyCap: 1 } }, log: quiet });
  store.upsertLead("233200000003", { name: "A" });
  store.upsertLead("233200000004", { name: "B" });
  const r = await engine.tick();
  assert.equal(r.sent, 1);
  assert.equal(r.skipped, "daily cap reached");
  assert.deepEqual(wa.sent[0], { to: "233200000003", template: "op", params: ["A"] });
});

test("webhook parsing and signature check", () => {
  const body = { entry: [{ changes: [{ value: {
    contacts: [{ wa_id: "233241234567", profile: { name: "Kofi" } }],
    messages: [{ id: "wamid.1", from: "233241234567", timestamp: "1700000000", type: "text", text: { body: "Hello" } }],
    statuses: [{ id: "wamid.out", status: "delivered", recipient_id: "233241234567" }],
  } }] }] };
  const { messages, statuses } = parseWebhook(body);
  assert.equal(messages[0].text, "Hello");
  assert.equal(messages[0].profileName, "Kofi");
  assert.equal(statuses[0].status, "delivered");
  const raw = Buffer.from(JSON.stringify(body));
  const sig = "sha256=" + crypto.createHmac("sha256", "secret").update(raw).digest("hex");
  assert.ok(validSignature(raw, sig, "secret"));
  assert.ok(!validSignature(raw, sig, "other"));
});

test("CSV import keeps existing leads and maps statuses", () => {
  const { importCsv, store } = createApp({ cfg, store: new Store(null), wa: fakeWa(), log: quiet });
  const csv = "id,agency,whatsapp,status,notes\n1,Alpha,+233241111111,replied,hi\n2,Beta,0242222222,demo,\n3,Bad,123,replied,\n";
  assert.deepEqual(importCsv(csv), { added: 2, skipped: 0, invalid: 1, total: 3 });
  assert.equal(store.lead("233242222222").status, "demo");
  assert.equal(importCsv(csv).skipped, 2);
});
