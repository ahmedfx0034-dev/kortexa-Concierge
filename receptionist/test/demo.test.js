import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import { systemPrompt, parseReply, viewingSlots } from "../src/prompt.js";
import { LLM } from "../src/llm.js";
import { createApp, Limiter, cleanMessages } from "../src/server.js";

const agency = JSON.parse(fs.readFileSync(new URL("../config/agency.json", import.meta.url)));
const THU = Date.UTC(2026, 10, 12, 9); // Thursday 12 Nov 2026

test("viewing slots: same day with 2 hours notice, skip Sunday, 12-hour times", () => {
  const slots = viewingSlots(agency, THU); // Thu 9:00 UTC: today 1pm and 4pm, then Fri, Sat (Sun skipped)
  assert.deepEqual(slots.slice(0, 3), ["today, Thursday 12 November at 1pm", "today, Thursday 12 November at 4pm", "Friday 13 November at 10am"]);
  assert.equal(slots.length, 8);
  assert.ok(!slots.some((s) => s.includes("Sunday")));
});

test("prompt lists only known facts and marks unknowns", () => {
  const p = systemPrompt(agency, THU);
  assert.match(p, /Price: \$320,000/);
  assert.ok(!/video tour/i.test(p), "no video instructions");
  assert.match(p, /Tone: Warm, polished and professional/);
  assert.match(p, /Office: Ivory Crest House/);
  assert.ok(!/: NOT KNOWN/.test(p), "demo agency has an answer for every detail");
  assert.match(systemPrompt({ ...agency, commission: "" }, THU), /Commission or agency fees: NOT KNOWN/);
  assert.ok(!/Bedrooms: \n/.test(p));
  assert.match(p, /Today is Thursday,? 12 November 2026/);
  assert.match(p, /you are the agency's AI assistant/);
});

test("action tags are stripped and turned into actions", () => {
  const r = parseReply("See you then! **Enjoy**\n[[BOOKED:east-legon-4bed|Friday 13 November at 10am|Kofi]]", agency);
  assert.equal(r.text, "See you then! Enjoy");
  assert.deepEqual(r.actions.map((a) => a.type), ["booked"]);
  assert.equal(r.actions[0].name, "Kofi");
  assert.deepEqual(parseReply("Sure [[HANDOFF]]", agency).actions, [{ type: "handoff" }]);
});

test("messages are cleaned and limited", () => {
  assert.throws(() => cleanMessages([]), /No message/);
  assert.throws(() => cleanMessages([{ role: "assistant", content: "hi" }]), /No message/);
  assert.equal(cleanMessages([{ role: "system", content: "x".repeat(900) }])[0].content.length, 600);
  assert.equal(cleanMessages([{ role: "system", content: "hack" }])[0].role, "user", "visitors can't inject system messages");
});

test("limiter blocks fast senders and daily overuse", () => {
  const l = new Limiter({ perWindow: 2, windowMs: 1000, perDay: 3 });
  assert.equal(l.allow("a", 0), null);
  assert.equal(l.allow("a", 1), null);
  assert.match(l.allow("a", 2), /very fast/);
  assert.equal(l.allow("b", 3), null);
  assert.match(l.allow("c", 4), /lot of visitors/);
});

test("end to end: chat and summary through a fake AI", async () => {
  const calls = [];
  const fakeFetch = async (url, opts) => {
    const body = JSON.parse(opts.body);
    calls.push({ url, body, auth: opts.headers.Authorization });
    const isSummary = body.messages[0].content.startsWith("Read this WhatsApp conversation");
    const content = isSummary ? 'Sure: {"name":"Kofi","budget":"$250k","seriousness":"hot"}' : "Yes, it's available! [[HANDOFF]]";
    return { ok: true, status: 200, json: async () => ({ choices: [{ message: { content } }] }) };
  };
  const llm = new LLM({ baseUrl: "https://ai.example/v1/", model: "m", apiKey: "k", fetchImpl: fakeFetch });
  const server = http.createServer(createApp({ agency, llm, now: () => THU })).listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const chat = await (await fetch(base + "/api/chat", { method: "POST", body: JSON.stringify({ messages: [{ role: "user", content: "Is it available?" }] }) })).json();
    assert.equal(chat.text, "Yes, it's available!");
    assert.equal(chat.actions[0].type, "handoff");
    assert.equal(calls[0].url, "https://ai.example/v1/chat/completions");
    assert.equal(calls[0].auth, "Bearer k");
    assert.equal(calls[0].body.messages[0].role, "system");

    const sum = await (await fetch(base + "/api/summary", { method: "POST", body: JSON.stringify({ messages: [{ role: "user", content: "I'm Kofi" }, { role: "assistant", content: "Thanks Kofi!" }] }) })).json();
    assert.equal(sum.name, "Kofi");

    const page = await fetch(base + "/");
    assert.equal(page.status, 200);
    assert.equal((await fetch(base + "/../package.json")).status, 404);
  } finally { server.close(); }
});

test("rate-limit and missing-key errors are readable", async () => {
  const llm429 = new LLM({ baseUrl: "https://x", model: "m", apiKey: "k", fetchImpl: async () => ({ ok: false, status: 429, json: async () => ({}) }) });
  await assert.rejects(llm429.chat([]), /free AI plan's limit/);
  const server = http.createServer(createApp({ agency, llm: null })).listen(0);
  try {
    const r = await fetch(`http://127.0.0.1:${server.address().port}/api/chat`, { method: "POST", body: "{}" });
    assert.equal(r.status, 503);
  } finally { server.close(); }
});

test("busy main model falls back once to the backup model", async () => {
  const seen = [];
  const fetchImpl = async (url, o) => {
    const b = JSON.parse(o.body); seen.push([b.model, b.reasoning_effort]);
    return b.model === "main"
      ? { ok: false, status: 503, json: async () => ({ error: { message: "high demand" } }) }
      : { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: "Hi from backup" } }] }) };
  };
  const llm = new LLM({ baseUrl: "https://x", model: "main", apiKey: "k", reasoningEffort: "none", fallbackModel: "backup", fetchImpl });
  assert.equal(await llm.chat([{ role: "user", content: "hi" }]), "Hi from backup");
  assert.deepEqual(seen, [["main", "none"], ["backup", undefined]]);
});

test("agency style settings change how the AI is told to write", async () => {
  const { styleText } = await import("../src/prompt.js");
  const custom = { ...agency, style: { tone: "Very formal", replyLength: "One sentence", extraRules: ["Always greet with 'Akwaaba'", ""] } };
  const s = styleText(custom);
  assert.match(s, /One sentence\. Tone: Very formal\./);
  assert.match(s, /- Always greet with 'Akwaaba'/);
  assert.match(styleText({}), /friendly, plain English/, "defaults when no style is set");
});

test("a slow main model gives up after firstTryMs and the backup answers", async () => {
  const { LLM } = await import("../src/llm.js");
  const fetchImpl = (url, o) => {
    const model = JSON.parse(o.body).model;
    if (model === "slow") return new Promise((_, rej) => o.signal.addEventListener("abort", () => rej(Object.assign(new Error("aborted"), { name: "AbortError" }))));
    return Promise.resolve({ ok: true, status: 200, json: async () => ({ choices: [{ message: { content: "fast answer" } }] }) });
  };
  const llm = new LLM({ baseUrl: "http://x", model: "slow", fallbackModel: "quick", apiKey: "k", fetchImpl, firstTryMs: 50 });
  const t = Date.now();
  assert.equal(await llm.chat([{ role: "user", content: "hi" }]), "fast answer");
  assert.ok(Date.now() - t < 1000);
  assert.equal(llm.last.model, "quick");
});

test("backup race: busy main error switches at once; a real error is reported; slow main loses", async () => {
  const { LLM } = await import("../src/llm.js");
  const reply = (content) => Promise.resolve({ ok: true, status: 200, json: async () => ({ choices: [{ message: { content } }] }) });
  const make = (main) => new LLM({ baseUrl: "http://x", model: "main", fallbackModel: "backup", apiKey: "k", firstTryMs: 50,
    fetchImpl: (u, o) => (JSON.parse(o.body).model === "main" ? main(o) : reply("backup answer")) });
  const busy = make(() => Promise.resolve({ ok: false, status: 503, json: async () => ({}) }));
  assert.equal(await busy.chat([{ role: "user", content: "hi" }]), "backup answer");
  const bad = () => Promise.resolve({ ok: false, status: 400, json: async () => ({ error: { message: "bad key" } }) });
  const broken = new LLM({ baseUrl: "http://x", model: "main", fallbackModel: "backup", apiKey: "k", firstTryMs: 50, fetchImpl: bad });
  await assert.rejects(broken.chat([{ role: "user", content: "hi" }]), /bad key/, "both fail: the error is reported");
  const slow = make(() => new Promise((r) => setTimeout(() => r({ ok: true, status: 200, json: async () => ({ choices: [{ message: { content: "late" } }] }) }), 300)));
  assert.equal(await slow.chat([{ role: "user", content: "hi" }]), "backup answer");
  const fast = make(() => reply("main answer"));
  assert.equal(await fast.chat([{ role: "user", content: "hi" }]), "main answer");
  assert.equal(fast.last.model, "main");
});
