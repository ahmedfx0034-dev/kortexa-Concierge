// The web chat on Vercel: only the chat API (src/web.js), no WhatsApp code.
// Vercel never sleeps, so the chat page opens instantly. Files starting with "_" aren't URLs.
import { webHandler, Limiter, llmFromEnv } from "../src/web.js";
import { loadAgency } from "../src/agency.js";
import { Demos } from "../src/demos.js";

export default webHandler({
  agency: loadAgency(),
  llm: llmFromEnv(),
  limiter: new Limiter({ perDay: Number(process.env.DAILY_LIMIT) || 800 }),
  demos: new Demos(),
});
