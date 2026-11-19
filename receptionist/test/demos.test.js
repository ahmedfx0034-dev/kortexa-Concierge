import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import http from "node:http";
import { demoCode, makeDemo, Demos, demoCodeIn, demoLinks } from "../src/demos.js";
import { systemPrompt } from "../src/prompt.js";
import { Receptionist } from "../src/receptionist.js";
import { Chats } from "../src/chats.js";
import { Limiter, createApp } from "../src/server.js";

const agency = JSON.parse(fs.readFileSync(new URL("../config/agency.json", import.meta.url)));
const quiet = { error() {}, warn() {}, info() {} };
const tmpDemos = () => new Demos(fs.mkdtempSync(path.join(os.tmpdir(), "demos-")));

test("demo codes are short and typeable", () => {
  assert.equal(demoCode("4myrent Limited"), "4myrent");
  assert.equal(demoCode("Prime Homes Ltd."), "prime");
  assert.equal(demoCode("A&C Groups"), "a-c");
  assert.equal(demoCode("Real Estate Agency"), "real-estate-agency", "falls back when every word is generic");
  assert.equal(demoCodeIn("DEMO 4myrent"), "4myrent");
  assert.equal(demoCodeIn("demo: prime"), "prime");
  assert.equal(demoCodeIn("I'd like a demo of the house"), null);
});

test("a demo uses the agency name and that city's sample listings", () => {
  const d = makeDemo({ name: "Ach Estate", city: "kumasi" });
  assert.equal(d.city, "Kumasi");
  assert.ok(d.isDemo);
  assert.ok(d.listings.every((l) => /Kumasi/.test(l.area)));
  assert.ok(d.listings.every((l) => !("video" in l)), "no videos");
  assert.equal(makeDemo({ name: "X", city: "Ho" }).city, "Accra", "unknown city falls back to Accra");
  assert.throws(() => makeDemo({ name: " " }), /required/);
  const p = systemPrompt(d, Date.UTC(2026, 10, 16, 9));
  assert.match(p, /THIS IS A DEMO: Ach Estate/);
  assert.match(p, /WhatsApp receptionist for Ach Estate/);
});

test("demos save, load and make links", () => {
  const demos = tmpDemos();
  demos.save(makeDemo({ name: "Prime Homes Ltd", city: "Accra" }));
  assert.equal(new Demos(demos.dir).get("PRIME").agencyName, "Prime Homes Ltd");
  const links = demoLinks(demos.get("prime"), { baseUrl: "https://x.onrender.com/", whatsappNumber: "+233 20 000 0000" });
  assert.equal(links.web, "https://x.onrender.com/d/prime");
  assert.equal(links.whatsapp, "https://wa.me/233200000000?text=DEMO%20prime");
});

test("WhatsApp: DEMO code switches the chat to that agency and starts fresh", async () => {
  const demos = tmpDemos();
  demos.save(makeDemo({ name: "Prime Homes Ltd", city: "Tema" }));
  const sent = [], prompts = [];
  const wa = { sendText: async (to, t) => { sent.push(t); return {}; }, markReadTyping: async () => {} };
  const llm = { chat: async (m) => { prompts.push(m[0].content); return "Hi! We have a 4-bedroom in Community 25."; } };
  const chats = new Chats("");
  const r = new Receptionist({ agency, llm, wa, chats, limiter: new Limiter(), demos, log: quiet });
  const msg = (id, text) => ({ id, from: "233241234567", name: "Kofi", type: "text", text, at: Date.now() });

  await r.handle(msg("a", "Hello"));
  assert.match(prompts[0], /Ivory Crest Realty/, "no code: the default demo agency");
  await r.handle(msg("b", "DEMO prime"));
  assert.match(sent.at(-1), /Welcome to Prime Homes Ltd\. I'm Anna/);
  const c = chats.get("233241234567");
  assert.equal(c.demo, "prime");
  assert.equal(c.messages.length, 1, "history cleared, only the welcome");
  await r.handle(msg("c", "What do you have?"));
  assert.match(prompts.at(-1), /receptionist for Prime Homes Ltd/);
  assert.match(prompts.at(-1), /Community 25, Tema/);
  await r.handle(msg("d", "DEMO nope"));
  assert.match(sent.at(-1), /couldn't find a demo called "nope"/);
  assert.equal(c.demo, "prime", "a wrong code doesn't change the demo");
});

test("web: /d/<code> page and API use the agency's demo", async () => {
  const demos = tmpDemos();
  demos.save(makeDemo({ name: "Prime Homes Ltd", city: "Kumasi" }));
  const prompts = [];
  const llm = { chat: async (m) => { prompts.push(m[0].content); return "Hello from Prime!"; } };
  const server = http.createServer(createApp({ agency, llm, demos, log: quiet })).listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    assert.equal((await fetch(base + "/d/prime")).status, 200);
    assert.equal((await fetch(base + "/d/unknown")).status, 404);
    const info = await (await fetch(base + "/api/agency?demo=prime")).json();
    assert.equal(info.agencyName, "Prime Homes Ltd");
    assert.equal(info.isDemo, true);
    await fetch(base + "/api/chat", { method: "POST", body: JSON.stringify({ demo: "prime", messages: [{ role: "user", content: "hi" }] }) });
    assert.match(prompts[0], /Prime Homes Ltd/);
    assert.match(prompts[0], /Ahodwo, Kumasi/);
  } finally { server.close(); }
});

test("privacy policy page is served for Meta app publishing", async () => {
  const server = http.createServer(createApp({ agency, llm: null, log: quiet })).listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    for (const p of ["/privacy", "/data-deletion"]) {
      const r = await fetch(base + p);
      assert.equal(r.status, 200);
      const html = await r.text();
      assert.match(html, /Privacy Policy/);
      assert.match(html, /How to delete your data/);
      assert.match(html, /Google \(Gemini AI\)/);
    }
  } finally { server.close(); }
});
