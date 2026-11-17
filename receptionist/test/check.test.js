import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import { Chats } from "../src/chats.js";
import { createApp } from "../src/server.js";
import { runChecks, subscribeApp } from "../src/check.js";

const agency = JSON.parse(fs.readFileSync(new URL("../config/agency.json", import.meta.url)));
const quiet = { error() {}, warn() {}, info() {} };
const wa = { token: "TOK", phoneNumberId: "555", apiVersion: "v23.0", dryRun: false, sendText: async () => ({ id: "x" }), markReadTyping: async () => {} };
const llm = { chat: async () => "OK" };
const reply = (body, ok = true, status = 200) => ({ ok, status, json: async () => body });

function fakeFetch({ phone, subs } = {}) {
  const calls = [];
  const fn = async (url, opts = {}) => {
    calls.push({ url, ...opts });
    if (url.includes("/subscribed_apps")) return subs ? subs(opts) : reply({ data: [{ whatsapp_business_api_data: { name: "Concierge", id: "1" } }] });
    return phone ? phone() : reply({ display_phone_number: "+233 24 123 4567", verified_name: "Acme" });
  };
  fn.calls = calls;
  return fn;
}
const find = (results, part) => results.find((r) => r.name.includes(part));
const base = { llm, wa, appSecret: "s", verifyToken: "v", adminPassword: "pw", wabaId: "waba1", version: "t" };

test("all good: nothing is failing and the token detail shows the phone number", async () => {
  const results = await runChecks({ ...base, fetchImpl: fakeFetch() });
  assert.ok(results.every((r) => r.ok !== false), JSON.stringify(results));
  assert.match(find(results, "token").detail, /\+233 24 123 4567/);
});

test("expired token shows Meta's message", async () => {
  const fetchImpl = fakeFetch({ phone: () => reply({ error: { message: "Session has expired" } }, false, 401) });
  const t = find(await runChecks({ ...base, fetchImpl }), "token");
  assert.equal(t.ok, false);
  assert.match(t.detail, /Session has expired/);
});

test("no subscribed apps offers the connect action; missing WABA id is 'not checked'", async () => {
  const empty = fakeFetch({ subs: () => reply({ data: [] }) });
  const c = find(await runChecks({ ...base, fetchImpl: empty }), "connected");
  assert.equal(c.ok, false);
  assert.equal(c.action, "subscribe");
  const n = find(await runChecks({ ...base, wabaId: "", fetchImpl: fakeFetch() }), "connected");
  assert.equal(n.ok, null);
});

test("missing AI is reported", async () => {
  const a = find(await runChecks({ ...base, llm: null, fetchImpl: fakeFetch() }), "AI");
  assert.equal(a.ok, false);
});

test("subscribeApp POSTs to the right URL with the Bearer token", async () => {
  const f = fakeFetch();
  await subscribeApp({ wa, wabaId: "waba1", fetchImpl: f });
  assert.equal(f.calls[0].method, "POST");
  assert.equal(f.calls[0].url, "https://graph.facebook.com/v23.0/waba1/subscribed_apps");
  assert.equal(f.calls[0].headers.Authorization, "Bearer TOK");
});

test("/check needs the admin login, records bad signatures, and can connect WhatsApp", async () => {
  const fetchImpl = fakeFetch();
  const app = createApp({ agency, llm, chats: new Chats(""), wa, log: quiet, appSecret: "secret", verifyToken: "v", adminPassword: "pw", wabaId: "waba1", fetchImpl });
  const server = http.createServer(app).listen(0);
  const url = `http://127.0.0.1:${server.address().port}`;
  const auth = { Authorization: "Basic " + Buffer.from("admin:pw").toString("base64") };
  const text = async (res) => (await res.text()).replaceAll("&#39;", "'");
  try {
    assert.equal((await fetch(url + "/check")).status, 401);
    assert.equal((await fetch(url + "/check", { headers: auth })).status, 200);

    await fetch(url + "/webhook", { method: "POST", body: "{}", headers: { "x-hub-signature-256": "sha256=bad" } });
    assert.match(await text(await fetch(url + "/check", { headers: auth })), /signature didn't match/);

    const before = fetchImpl.calls.length;
    const res = await fetch(url + "/check/subscribe", { method: "POST", headers: auth });
    assert.match(await text(res), /Done: the WhatsApp account is now connected/);
    assert.ok(fetchImpl.calls.slice(before).some((c) => c.method === "POST" && c.url.endsWith("/waba1/subscribed_apps")));
  } finally { server.close(); }
});
