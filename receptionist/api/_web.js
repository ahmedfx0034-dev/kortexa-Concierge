// The web chat on Vercel: the same /api/agency, /api/chat and /api/summary
// handlers as the Render server (src/server.js), without WhatsApp. Vercel never
// sleeps, so the chat page opens instantly. Files starting with "_" aren't URLs.
import { createApp, Limiter, llmFromEnv, loadAgency } from "../src/server.js";
import { Demos } from "../src/demos.js";

export default createApp({
  agency: loadAgency(),
  llm: llmFromEnv(),
  limiter: new Limiter({ perDay: Number(process.env.DAILY_LIMIT) || 800 }),
  demos: new Demos(),
});
