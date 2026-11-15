#!/usr/bin/env node
// Make a personalised receptionist demo for an agency.
//
//   npm run make-demo -- "Prime Homes Ltd" Accra
//   npm run make-demo -- "Prime Homes Ltd" Kumasi --code primehomes --name Esi
//
// Cities with sample listings: Accra, Tema, Kumasi, Takoradi (others use Accra).
// Set PUBLIC_URL and DEMO_WHATSAPP_NUMBER to print ready-to-send links.

import { makeDemo, Demos, demoLinks } from "../src/demos.js";

const args = process.argv.slice(2);
const flag = (name) => { const i = args.indexOf(`--${name}`); return i >= 0 ? args.splice(i, 2)[1] : undefined; };
const code = flag("code"), receptionistName = flag("name");
const [name, city = "Accra"] = args;

if (!name) {
  console.log('Usage: npm run make-demo -- "Agency name" [City] [--code shortcode] [--name ReceptionistName]');
  process.exit(1);
}

const demos = new Demos();
const demo = makeDemo({ name, city, code, ...(receptionistName ? { receptionistName } : {}) });
if (demos.get(demo.code) && demos.get(demo.code).agencyName !== demo.agencyName) {
  console.error(`The code "${demo.code}" is already used by ${demos.get(demo.code).agencyName}. Pick another with --code.`);
  process.exit(1);
}
demos.save(demo);

const links = demoLinks(demo, { baseUrl: process.env.PUBLIC_URL || "https://YOUR-SERVER", whatsappNumber: process.env.DEMO_WHATSAPP_NUMBER || "" });
console.log(`\nDemo ready for ${demo.agencyName} (${demo.city}), code: ${demo.code}`);
console.log(`  Web link:      ${links.web}`);
console.log(links.whatsapp ? `  WhatsApp link: ${links.whatsapp}` : `  WhatsApp:      text "${links.whatsappText}" to your demo number (set DEMO_WHATSAPP_NUMBER to get a link)`);
console.log(`\nRestart the server (or redeploy) so it loads the new demo.\n`);
