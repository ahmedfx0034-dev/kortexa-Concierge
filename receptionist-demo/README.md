# AI Receptionist Demo

A demo you can send to real estate agencies. It looks like a WhatsApp chat
with a made-up agency. The agency pretends to be a buyer, and an AI
receptionist answers:

- answers questions about the listing (only facts you wrote down, never guesses)
- asks the buyer's name, budget, timeline and how they'll pay
- shares the listing's video tour in the chat
- offers real viewing times for the next few days and books one
- passes the chat to a human when it can't help
- "See what the agent receives" shows the lead summary the agency would get

It runs on a **free AI plan** (Google Gemini by default). It stores no
conversations on the server: each visitor's chat stays in their own browser.

## 1. Get a free AI key (no bank card)

1. Go to **aistudio.google.com** and sign in with a Google account.
2. Click **Get API key** → **Create API key**.
3. Copy the key. Treat it like a password.

On Google's free plan there is a daily limit, and Google may use the chats to
improve its AI. That's fine for this demo because it only contains a made-up
agency. Don't use the free plan for a real agency's customers.

**Other free options** (change three settings, no code changes):

| Service | LLM_BASE_URL | Example LLM_MODEL |
|---|---|---|
| Google Gemini (default) | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-2.5-flash` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| OpenRouter (free models) | `https://openrouter.ai/api/v1` | a model ending in `:free` |

Model names change over time. If the AI replies with "model not found", check
the service's model list and update `LLM_MODEL`.

## 2. Change the demo agency

Edit [`config/agency.json`](config/agency.json): agency name, receptionist
name, office hours, viewing times and listings. Leave a detail empty (`""`) if
you don't know it. The AI will say the agent will confirm it instead of making
something up.

## 3. Run it

Needs Node.js 20 or newer. No packages to install.

```bash
cd receptionist-demo
LLM_API_KEY=your-key npm start
# open http://localhost:3000
```

## 4. Put it online for free

Any host that runs Node.js works, because the demo keeps nothing on disk. For
example, on **Render** (free plan):

1. New → Web Service → connect this GitHub repository.
2. Root directory: `receptionist-demo`. Start command: `npm start`.
3. Environment: add `LLM_API_KEY` (and `LLM_MODEL` / `LLM_BASE_URL` if you
   changed service).
4. Send agencies the link Render gives you.

Render's free plan "sleeps" when nobody visits for a while, so the first
message after a quiet period can take up to a minute. Open the link yourself
just before a sales call.

## Settings

| Setting | What it does | Default |
|---|---|---|
| `LLM_API_KEY` | Your free AI key | (required) |
| `LLM_BASE_URL` | Which AI service | Google Gemini |
| `LLM_MODEL` | Which model | `gemini-2.5-flash` |
| `DAILY_LIMIT` | Max AI messages per day for the whole demo | `800` |
| `PORT` | Web port | `3000` |
| `AGENCY_FILE` | Use a different agency file | `config/agency.json` |

Each visitor can send about 40 messages per 10 minutes, and a chat can hold 30
messages before they need to tap Restart. That stops one person from using up
the free daily limit.

## Tests

```bash
npm test
```
