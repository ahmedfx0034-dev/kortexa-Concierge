// Personalised demos: one receptionist per agency you pitch, made from the
// agency's name and city plus sample listings for that city.
// Each demo is a JSON file in config/demos/<code>.json.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const DEMOS_DIR = path.join(here, "..", "config", "demos");
const SAMPLES_FILE = path.join(here, "..", "config", "sample-listings.json");

/** "4myrent Limited" -> "4myrent" ; "A&C Groups" -> "a-c-groups". Short, typeable demo code. */
export function demoCode(name) {
  const stop = /\b(limited|ltd|company|co|gh|ghana|group|groups|real estate|realty|properties|property|estates?|homes?|agency|consult|services|international|developers?|the|and)\b\.?/gi;
  const base = String(name).toLowerCase().replace(/&/g, " ").replace(stop, " ").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const fallback = String(name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return (base || fallback).slice(0, 24).replace(/-+$/, "") || "demo";
}

export function makeDemo({ name, city = "Accra", receptionistName = "Anna", code }, samples = JSON.parse(fs.readFileSync(SAMPLES_FILE, "utf8"))) {
  if (!name || !String(name).trim()) throw new Error("Agency name is required.");
  const cityKey = Object.keys(samples).find((k) => k.toLowerCase() === String(city).toLowerCase()) || "Accra";
  const listings = samples[cityKey].map((l) => ({ ...l }));
  return {
    code: code || demoCode(name),
    isDemo: true,
    agencyName: String(name).trim(),
    receptionistName,
    city: cityKey,
    officeAddress: "",
    agentName: `the ${String(name).trim()} team`,
    officeHours: "Monday to Saturday, 9am to 5pm",
    viewingTimes: ["10:00", "13:00", "16:00"],
    viewingDaysAhead: 3,
    minNoticeHours: 2,
    commission: "",
    style: {
      tone: "Warm, polished and professional, like the front desk of a premium agency. Friendly but never too casual.",
      replyLength: "1 to 3 short sentences",
      extraRules: [],
    },
    listings,
  };
}

export class Demos {
  constructor(dir = DEMOS_DIR, json = process.env.DEMOS_JSON || "") {
    this.dir = dir;
    this.byCode = new Map();
    // Hosts without the demo files (they aren't in the public repo) can pass them
    // as one setting: DEMOS_JSON = [ {...demo}, {...demo} ].
    if (json) {
      try { for (const d of [].concat(JSON.parse(json))) if (d?.code) this.byCode.set(String(d.code).toLowerCase(), d); }
      catch { console.warn("DEMOS_JSON isn't valid JSON, so it was ignored."); }
    }
    if (fs.existsSync(dir)) {
      for (const f of fs.readdirSync(dir).filter((f) => f.endsWith(".json"))) {
        const d = JSON.parse(fs.readFileSync(path.join(dir, f), "utf8"));
        this.byCode.set(d.code, d);
      }
    }
  }
  get(code) { return code ? this.byCode.get(String(code).toLowerCase()) || null : null; }
  list() { return [...this.byCode.values()]; }
  save(demo) {
    fs.mkdirSync(this.dir, { recursive: true });
    fs.writeFileSync(path.join(this.dir, `${demo.code}.json`), JSON.stringify(demo, null, 2) + "\n");
    this.byCode.set(demo.code, demo);
    return demo;
  }
}

/** Finds "DEMO primehomes" (or "demo: primehomes") at the start of a WhatsApp message. */
export function demoCodeIn(text) {
  const m = /^\s*demo\s*[:\-]?\s*([a-z0-9-]{2,24})\b/i.exec(String(text || ""));
  return m ? m[1].toLowerCase() : null;
}

export function demoLinks(demo, { baseUrl = "", whatsappNumber = "" } = {}) {
  const num = String(whatsappNumber).replace(/\D/g, "");
  return {
    web: `${baseUrl.replace(/\/+$/, "")}/d/${demo.code}`,
    whatsapp: num ? `https://wa.me/${num}?text=${encodeURIComponent(`DEMO ${demo.code}`)}` : "",
    whatsappText: `DEMO ${demo.code}`,
  };
}
