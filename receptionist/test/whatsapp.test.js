import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import crypto from "node:crypto";
import { Receptionist } from "../src/receptionist.js";
import { Chats } from "../src/chats.js";
import { Limiter, createApp } from "../src/server.js";
import { parseWebhook, validSignature, WhatsApp } from "../src/whatsapp.js";

const agency = JSON.parse(fs.readFileSync(new URL("../config/agency.json", import.meta.url)));
const quiet = { error() {}, warn() {}, info() {} };

function fakeWa() {
  const sent = [];
  return { sent, dryRun: false,
    sendText: async (to, body) => { sent.push({ to, text: body }); return { id: "o" + sent.length }; },
    sendVideo: async (to, link) => { sent.push({ to, video: link }); return { id: "o" + sent.length }; },
    markReadTyping: async () => {} };
}
function fakeLlm(replies) {
  const calls = [];
  return { calls, chat: async (messages) => { calls.push(messages); const r = replies.shift(); if (r instanceof Error) throw r; return r ?? '{"name":"Kofi","seriousness":"hot"}'; } };
}
const inbound = (id, text, from = "233241234567") => ({ id, from, name: "Kofi", type: text === null ? "image" : "text", text: text ?? "", at: Date.now() });

function setup(replies) {
  const wa = fakeWa(), llm = fakeLlm(replies), chats = new Chats("");
  const r = new Receptionist({ agency, llm, wa, chats, limiter: new Limiter(), log: quiet });
  return { wa, llm, chats, r };
}

test("answers in WhatsApp, sends the video, keeps the conversation", async () => {
  const { wa, llm, chats, r } = setup(["Yes, it's available!\n[[VIDEO:east-legon-4bed]]", "Great, what's your name?"]);
  await r.handle(inbound("m1", "Is the East Legon house available?"));
  await r.handle(inbound("m2", "Yes please"));
  assert.deepEqual(wa.sent.map((s) => s.text || "video"), ["Yes, it's available!", "video", "Great, what's your name?"]);
  assert.equal(llm.calls[1][0].role, "system");
  assert.equal(llm.calls[1].filter((m) => m.role === "user").length, 2, "second call sees the whole chat");
  assert.equal(chats.get("233241234567").name, "Kofi");
});

test("duplicate deliveries are ignored", async () => {
  const { wa, r } = setup(["Hi!", "Should not be sent"]);
  await r.handle(inbound("dup", "Hello"));
  await r.handle(inbound("dup", "Hello"));
  assert.equal(wa.sent.length, 1);
});

test("booking is recorded and summarised for the agent", async () => {
  const { chats, r } = setup(["Booked for Friday!\n[[BOOKED:east-legon-4bed|Friday 13 November at 10am|Kofi]]", '{"name":"Kofi","budget":"$250k","seriousness":"hot"}']);
  await r.handle(inbound("b1", "Friday 10am, I'm Kofi"));
  const c = chats.get("233241234567");
  assert.equal(c.booking.slot, "Friday 13 November at 10am");
  assert.equal(c.summary.budget, "$250k");
  assert.ok(c.needsHuman);
});

test("hand-off pauses the AI so a person can answer", async () => {
  const { wa, chats, r } = setup(["The agent will get back to you shortly.\n[[HANDOFF]]", "{}"]);
  await r.handle(inbound("h1", "Can you reduce the price?"));
  await r.handle(inbound("h2", "Hello?"));
  assert.equal(wa.sent.length, 1, "no AI reply after hand-off");
  assert.ok(chats.get("233241234567").aiPaused);
});

test("STOP opts out, START opts back in", async () => {
  const { wa, chats, r } = setup(["Welcome back!"]);
  await r.handle(inbound("s1", "STOP"));
  await r.handle(inbound("s2", "hello"));
  assert.equal(wa.sent.length, 1);
  assert.ok(chats.get("233241234567").optedOut);
  await r.handle(inbound("s3", "start"));
  assert.equal(wa.sent.at(-1).text, "Welcome back!");
});

test("non-text messages get a polite note; AI errors fall back to a human", async () => {
  const { wa, chats, r } = setup([new Error("quota")]);
  await r.handle(inbound("i1", null));
  assert.match(wa.sent[0].text, /only read text/);
  await r.handle(inbound("e1", "Hi"));
  assert.match(wa.sent[1].text, /reply to you shortly/);
  assert.ok(chats.get("233241234567").needsHuman);
});

test("webhook: verify, signature check, and messages reach the receptionist", async () => {
  const handled = [];
  const app = createApp({ agency, llm: {}, receptionist: { handle: (m) => handled.push(m) }, chats: new Chats(""), wa: fakeWa(), verifyToken: "vt", appSecret: "sec", adminPassword: "pw", log: quiet });
  const server = http.createServer(app).listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    assert.equal(await (await fetch(base + "/webhook?hub.mode=subscribe&hub.verify_token=vt&hub.challenge=123")).text(), "123");
    assert.equal((await fetch(base + "/webhook?hub.mode=subscribe&hub.verify_token=no&hub.challenge=1")).status, 403);
    const body = JSON.stringify({ entry: [{ changes: [{ value: { contacts: [{ wa_id: "233241234567", profile: { name: "Kofi" } }], messages: [{ id: "w1", from: "233241234567", timestamp: "1700000000", type: "text", text: { body: "Hi" } }] } }] }] });
    const sig = "sha256=" + crypto.createHmac("sha256", "sec").update(body).digest("hex");
    assert.equal((await fetch(base + "/webhook", { method: "POST", body, headers: { "x-hub-signature-256": "sha256=bad" } })).status, 401);
    assert.equal((await fetch(base + "/webhook", { method: "POST", body, headers: { "x-hub-signature-256": sig } })).status, 200);
    assert.equal(handled[0].text, "Hi");
    assert.equal((await fetch(base + "/inbox")).status, 401);
    const inbox = await fetch(base + "/inbox", { headers: { Authorization: "Basic " + Buffer.from("admin:pw").toString("base64") } });
    assert.equal(inbox.status, 200);
  } finally { server.close(); }
});

test("WhatsApp client builds the right requests", async () => {
  const reqs = [];
  const wa = new WhatsApp({ token: "t", phoneNumberId: "123" }, { fetchImpl: async (url, o) => { reqs.push({ url, body: JSON.parse(o.body) }); return { ok: true, json: async () => ({ messages: [{ id: "x" }] }) }; } });
  await wa.sendText("233241234567", "hi");
  await wa.sendVideo("233241234567", "https://v.mp4", "Tour");
  assert.equal(reqs[0].url, "https://graph.facebook.com/v23.0/123/messages");
  assert.deepEqual(reqs[1].body.video, { link: "https://v.mp4", caption: "Tour" });
  assert.ok(validSignature(Buffer.from("x"), "sha256=" + crypto.createHmac("sha256", "s").update("x").digest("hex"), "s"));
  assert.equal(parseWebhook({}).length, 0);
});

// ---- capture, qualify, reminders -----------------------------------------------
import { scoreLead } from "../src/prompt.js";
const H = 3600000;

test("lead score: facts add up to hot, warm or cold", () => {
  assert.equal(scoreLead({}).temperature, "cold");
  assert.deepEqual(scoreLead({}).missing, ["name", "what they want", "budget", "timeline", "payment"]);
  const warm = scoreLead({ name: "Esi", looking_for: "rent", bedrooms: "2", budget: "$2,000", timeline_months: 4 });
  assert.equal(warm.temperature, "warm");
  const hot = scoreLead({ name: "Kofi", looking_for: "buy", property_type: "house", budget: "$300k", timeline_months: 1, payment: "cash" });
  assert.equal(hot.score, 75);
  assert.equal(hot.temperature, "hot");
  assert.equal(scoreLead({ name: "x" }, { slot: "x" }).score, 30, "booking adds 25");
});

test("lead details are captured every 2 buyer messages", async () => {
  const { chats, r } = setup(["Hi! What are you looking for?", "Nice. What's your budget?", '{"name":"Esi","looking_for":"rent","bedrooms":"2","budget":"$2,000","timeline_months":1,"payment":"cash"}']);
  await r.handle(inbound("c1", "Hello"));
  assert.equal(chats.get("233241234567").lead, null);
  await r.handle(inbound("c2", "2 bedroom to rent"));
  const c = chats.get("233241234567");
  assert.equal(c.lead.budget, "$2,000");
  assert.equal(c.temperature, "hot");
});

function nurtureSetup(replies, startAt) {
  let clock = startAt;
  const wa = fakeWa(), llm = fakeLlm(replies), chats = new Chats("");
  const r = new Receptionist({ agency, llm, wa, chats, limiter: new Limiter(), log: quiet, now: () => clock });
  return { wa, llm, chats, r, setClock: (t) => { clock = t; } };
}

test("no follow-ups: quiet buyers are never chased", async () => {
  const t0 = Date.UTC(2026, 10, 16, 9);
  const { wa, chats, r } = nurtureSetup(["Hi! Are you buying or renting?", "SHOULD NOT SEND"], t0);
  await r.handle(inbound("n1", "Hi"));
  chats.get("233241234567").messages.forEach((m) => { m.at = t0; });
  for (const h of [2, 5, 20, 23]) assert.equal((await r.tick(t0 + h * H)).sent, 0);
  assert.equal(wa.sent.length, 1);
});

test("viewing reminder goes out 3 hours before, once", async () => {
  const t0 = Date.UTC(2026, 10, 16, 8); // Monday 8am
  const { wa, chats, r } = nurtureSetup(["Booked!\n[[BOOKED:east-legon-4bed|today, Monday 16 November at 1pm|Kofi]]", "{}"], t0);
  await r.handle(inbound("v1", "Today 1pm please, I'm Kofi"));
  const c = chats.get("233241234567");
  assert.equal(c.booking.at, Date.UTC(2026, 10, 16, 13));
  c.messages.forEach((m) => { m.at = t0; });
  assert.equal((await r.tick(Date.UTC(2026, 10, 16, 9))).sent, 0);
  assert.equal((await r.tick(Date.UTC(2026, 10, 16, 10, 5))).sent, 1);
  assert.match(wa.sent.at(-1).text, /reminder of your viewing of the 4-bedroom house in East Legon today at 1:00 pm/);
  assert.equal((await r.tick(Date.UTC(2026, 10, 16, 11))).sent, 0, "only once");
});
