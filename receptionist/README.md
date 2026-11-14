# AI WhatsApp Receptionist

An AI receptionist that answers a real estate agency's WhatsApp messages,
using a **free AI plan** (Google Gemini by default). This copy is set up as a
demo for a made-up agency, "Spintex Homes (Demo)", so you can let agencies
text it and see how it works.

When a buyer texts the WhatsApp number, the receptionist:

- answers questions about the listings (only facts in `config/agency.json`, never guesses)
- asks their name, budget, timeline and how they'll pay
- sends the listing's video tour as a WhatsApp video
- offers real viewing times for the next few days and books one
- hands the chat to a person when it can't help (price negotiation, complaints…)
- respects STOP (and START to opt back in)

### Capture, qualify, nurture

- **Capture:** every 2 buyer messages (and when a viewing is booked) the AI
  pulls out their details: buying or renting, type, bedrooms, area, budget,
  timeline, payment, live-in or investment, which listing they liked, and any
  concerns.
- **Qualify:** each lead gets a score out of 100 from those facts (budget 20,
  timeline 25 (sooner scores higher), payment 15, needs 10, name 5, viewing booked 25):
  70+ is **hot**, 40+ **warm**, below that **cold**. The inbox shows what's
  still missing so the AI (or the agent) knows what to ask next.
- **Nurture:** if a buyer goes quiet, the AI sends one friendly follow-up after
  2 hours and a last one about 20 hours after their last message (only between
  8am and 8pm). After 24 hours it stops, because WhatsApp only allows free
  messages within 24 hours of the customer's last message. Booked viewings get a
  reminder 3 hours before. If that's outside the 24 hours, the inbox tells the
  agent to call instead.

The agency sees everything in a password-protected **inbox** at `/inbox`:
each chat, viewings booked, a lead summary (budget, timeline, payment, hot/warm/cold),
and buttons to pause the AI and reply themselves.

## What it costs

| Part | Cost |
|---|---|
| WhatsApp replies to people who text first | Free (within 24 hours of their message) |
| AI (Gemini free plan) | Free, with a daily limit |
| Hosting | Free plans exist (see below) |
| Phone number | A number not already on the WhatsApp app: a new SIM, or Meta's free test number for trying it out |

On Gemini's free plan, Google may use the chats to improve its AI. Fine for this
demo with a made-up agency, but not for a real agency's customers. For a paying
client, switch to a paid AI plan.

## Setup

### 1. Free AI key
1. Go to **aistudio.google.com**, sign in, click **Get API key → Create API key**.
2. Keep the key private, like a password.

### 2. WhatsApp (Meta)
1. Go to **developers.facebook.com** → My Apps → **Create app** → type **Business**.
2. Add the **WhatsApp** product. Meta gives you a **free test phone number**.
   - The test number can only message up to **5 phone numbers** that you add
     and verify under "To". Good for trying it yourself and showing a few agencies.
   - To let anyone text it, add your own number in WhatsApp Manager instead
     (a number not on the normal WhatsApp app). Meta checks your display name first.
3. From the WhatsApp → API Setup page, copy the **Phone number ID**.
4. Create a **permanent token**: Business settings → System users → add one →
   Generate token with `whatsapp_business_messaging` and `whatsapp_business_management`.
   (The token on the API Setup page expires after 24 hours.)
5. App settings → Basic → copy the **App secret**.

### 3. Put it online (needs a public https address)
Example with **Render** (free plan):
1. New → Web Service → connect this GitHub repository.
2. Root directory: `receptionist`. Start command: `npm start`.
3. Add the settings below under Environment.
4. Copy your Render address, e.g. `https://your-app.onrender.com`.

Render's free plan sleeps after about 15 minutes with no visitors. The first
WhatsApp message after that can take up to a minute to answer. Meta keeps
retrying, so no message is lost. Render's free plan also has no permanent disk,
so the inbox empties when the server restarts. For a demo that's fine. For a
real client, use a host with a disk and set `DATA_FILE`.

### 4. Connect the webhook
In your Meta app → WhatsApp → Configuration:
- Callback URL: `https://your-app.onrender.com/webhook`
- Verify token: the same text as `WHATSAPP_VERIFY_TOKEN`
- Click Verify and save, then **subscribe to `messages`**.

Now text the number from your phone. The AI should answer within a few seconds.

## Settings

| Setting | What it is |
|---|---|
| `LLM_API_KEY` | Your free Gemini key |
| `LLM_BASE_URL` | AI service (default: Google Gemini) |
| `LLM_MODEL` | AI model (default `gemini-3.5-flash`; if you get "model not found" or "no longer available", pick a current one from Google's list) |
| `LLM_REASONING_EFFORT` | How much the AI "thinks" first. `none` (default) answers in about a second |
| `LLM_FALLBACK_MODEL` | Backup model tried once when Google is busy (default `gemini-flash-lite-latest`) |
| `WHATSAPP_TOKEN` | Permanent token from step 2 |
| `WHATSAPP_PHONE_NUMBER_ID` | Phone number ID from step 2 |
| `WHATSAPP_APP_SECRET` | App secret (proves messages really come from Meta) |
| `WHATSAPP_VERIFY_TOKEN` | Any secret text you make up, also typed into Meta |
| `ADMIN_PASSWORD` | Password for `/inbox` (username: `admin`) |
| `DATA_FILE` | Optional: file to keep chats across restarts, e.g. `./data/chats.json` |
| `DAILY_LIMIT` | Max AI replies per day for everyone (default 800) |

Without `WHATSAPP_TOKEN` it runs in **dry-run mode**: it receives messages and
prints the replies instead of sending them. Useful for testing.

**Other free AI services** (no code changes, just settings):

| Service | LLM_BASE_URL |
|---|---|
| Google Gemini (default) | `https://generativelanguage.googleapis.com/v1beta/openai` |
| Groq | `https://api.groq.com/openai/v1` |
| OpenRouter (models ending in `:free`) | `https://openrouter.ai/api/v1` |

## Change the agency

Edit [`config/agency.json`](config/agency.json): name, receptionist name, office
hours, viewing times and listings. Leave a detail as `""` if you don't know it.
The AI will say the agent will confirm it.

## The web demo page

The server also still serves a browser version of the chat at `/` (same AI,
no WhatsApp needed). You can ignore it or use it as a backup when showing
agencies.

## Run locally and test

```bash
cd receptionist
npm test
LLM_API_KEY=your-key ADMIN_PASSWORD=choose-one npm start
```
