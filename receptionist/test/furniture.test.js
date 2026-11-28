import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { systemPrompt, summaryPrompt, summarise, parseReply, LEAD_PROMPT } from "../src/prompt.js";
import { webApi } from "../src/web.js";

const shop = {
  kind: "furniture", isDemo: true, agencyName: "Woodworks", receptionistName: "Anna", city: "Accra", officeHours: "Mon to Sat",
  agentName: "our design team", viewingTimes: ["09:00"], viewingDaysAhead: 2, policies: "60% deposit.",
  products: [{ id: "kitchen", name: "Kitchen cabinets", price: "From GH₵18,000", leadTime: "" }],
};
const house = JSON.parse(fs.readFileSync(new URL("../config/agency.json", import.meta.url)));

test("furniture businesses get a furniture script, not real estate", () => {
  const p = systemPrompt(shop, Date.UTC(2026, 10, 30, 6));
  assert.match(p, /furniture and kitchen cabinet maker in Accra/);
  assert.match(p, /Price: From GH₵18,000/);
  assert.match(p, /NOT KNOWN \(never guess these\): lead time/);
  assert.match(p, /free site measurement/);
  assert.match(p, /60% deposit/);
  assert.ok(!/LISTINGS|bedrooms|mortgage/i.test(p), "no real-estate wording");
  assert.match(systemPrompt(house), /LISTINGS/, "real estate unchanged");
});

test("furniture summary: own prompt, score and rows; real estate keeps its rows", () => {
  assert.match(summaryPrompt(shop), /"wants"/);
  assert.equal(summaryPrompt(house), LEAD_PROMPT);
  const s = summarise(shop, { name: "Ama", wants: "kitchen", size: "3 m", location: "Spintex", budget: "GH₵20k", timeline_months: 1 }, true);
  assert.equal(s.score, 100);
  assert.deepEqual(s.rows[0], ["Lead score", "100/100 · hot"]);
  assert.ok(s.rows.some(([k]) => k === "Size"));
  assert.ok(summarise(house, {}).rows.some(([k]) => k === "Looking to"));
  assert.equal(parseReply("Booked!\n[[BOOKED:kitchen|Monday at 9am|Ama]]", shop).actions[0].listing, "Kitchen cabinets");
});

test("web API: /api/agency tells the page it's a furniture business", async () => {
  const handle = webApi({ agency: house, llm: null, demos: { get: (c) => (c === "wood" ? shop : null) } });
  let out = "";
  const res = { writeHead() {}, end(b) { out = b; } };
  await handle({ method: "GET", url: "/api/agency?demo=wood", headers: {} }, res);
  const info = JSON.parse(out);
  assert.equal(info.kind, "furniture");
  assert.equal(info.listings[0].title, "Kitchen cabinets");
});
