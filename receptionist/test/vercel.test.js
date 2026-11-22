import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";

test("Vercel: api files share one handler and accept an already-parsed body", async () => {
  delete process.env.LLM_API_KEY;
  const chat = (await import("../api/chat.js")).default;
  const agency = (await import("../api/agency.js")).default;
  assert.equal(chat, agency, "same handler");
  const server = http.createServer(agency).listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const info = await (await fetch(base + "/api/agency")).json();
    assert.equal(info.agencyName, "Ivory Crest Realty");
    const r = await fetch(base + "/api/chat", { method: "POST", body: JSON.stringify({ messages: [{ role: "user", content: "Hi" }] }) });
    assert.equal(r.status, 503, "no key: readable error, not a crash");
  } finally { server.close(); }
  const cfg = JSON.parse(fs.readFileSync(new URL("../vercel.json", import.meta.url)));
  assert.equal(cfg.outputDirectory, "public");
});

test("pre-parsed request bodies (Vercel) reach the AI", async () => {
  const { createApp } = await import("../src/server.js");
  const agencyCfg = JSON.parse(fs.readFileSync(new URL("../config/agency.json", import.meta.url)));
  const app = createApp({ agency: agencyCfg, llm: { chat: async () => "Hello from Anna" }, log: { error() {} } });
  let out = "";
  const req = { method: "POST", url: "/api/chat", headers: {}, body: { messages: [{ role: "user", content: "Hi" }] } };
  const res = { headersSent: false, writeHead(code) { this.code = code; }, end(b) { out = b; } };
  await app(req, res);
  assert.equal(res.code, 200);
  assert.equal(JSON.parse(out).text, "Hello from Anna");
});

test("demos can come from the DEMOS_JSON setting", async () => {
  const { Demos } = await import("../src/demos.js");
  const d = new Demos("/nonexistent", JSON.stringify([{ code: "O2A", agencyName: "O2A" }]));
  assert.equal(d.get("o2a").agencyName, "O2A");
  assert.equal(new Demos("/nonexistent", "not json").list().length, 0);
});
