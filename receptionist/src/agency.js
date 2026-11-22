import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** The default agency (config/agency.json, or AGENCY_FILE). */
export function loadAgency(env = process.env) {
  return JSON.parse(fs.readFileSync(env.AGENCY_FILE || path.join(here, "..", "config", "agency.json"), "utf8"));
}
