# Kortexa follow-up server (option 2)

Automatic WhatsApp follow-ups for the agencies that **replied** to your
outreach. It uses Meta's official WhatsApp Business Cloud API, so there is no
bot logged into your phone and no ban risk from automation tools.

```
Outreach dashboard (option 1)          This server (option 2)
──────────────────────────────         ─────────────────────────────────────────
You send first messages by hand   →    Import "replied" CSV
Mark who replied                       Sends opener template from the API number
Download "replied" CSV                 Agency replies → Claude drafts or sends a reply
                                       Silent 2 days → follow-up 1 (template)
                                       Silent 5 more → follow-up 2 (template), then stops
                                       STOP → opted out forever
                                       Call booked → stops following up
```

## What it does

- **Imports leads** from the dashboard's "Download replied (CSV)" button.
- **Sends follow-ups automatically**, only between 9am and 6pm Ghana time and
  never more than `DAILY_CAP` a day.
- **Stops following up** as soon as an agency writes back, books a call, says
  they're not interested, or asks to stop.
- **Answers replies with Claude**: it either drafts a reply for you to approve
  (`AI_MODE=draft`) or replies by itself (`AI_MODE=auto`). Questions about price,
  contracts or complaints are always handed to you.
- **Admin inbox** at `/admin`: see every conversation, send replies, approve AI
  drafts, change a lead's status, pause a lead.

The AI only states facts written in [`kortexa-facts.md`](kortexa-facts.md).
Edit that file in your own words before going live.

## The 24-hour rule (important)

WhatsApp lets a business send **any message** only within 24 hours of the
agency's last message. Outside that window you can only send **pre-approved
templates**. The server handles this for you. Replies use free text inside the
window, and follow-ups use your templates.

## Setup

### 1. Meta / WhatsApp (about 1–2 weeks the first time)

1. Create a Meta Business account at business.facebook.com and start
   **business verification** (company documents, website).
2. At developers.facebook.com create an app (type **Business**) and add the
   **WhatsApp** product.
3. Add your business phone number. Meta's "coexistence" option can keep the
   number working in the WhatsApp Business app too, so agencies keep chatting
   in the same thread they started with you. Check it's offered for your number.
4. Create a **permanent access token** (System user in Business settings with
   `whatsapp_business_messaging` permission). Note the **Phone number ID**.
5. Submit the three templates below in WhatsApp Manager (category: Marketing,
   language: English). Approval usually takes minutes to a day.
6. Deploy the server (step 2), then in the app's WhatsApp > Configuration set:
   - Callback URL: `https://YOUR-SERVER/webhook`
   - Verify token: the same value as `WHATSAPP_VERIFY_TOKEN`
   - Subscribe to the **messages** field.

### Templates to submit

Each has one variable, `{{1}}` = the agency name. They follow the same copy
structure as the outreach messages: problem first, then outcome and benefit,
then a low-stakes ask.

**`kortexa_continue`** (sent once, when you import someone who replied)
> Hi {{1}}, it's Ahmed-Saleem, following up on our WhatsApp chat about cinematic listing videos made from ordinary photos. This is my main business line. Seats for the Photo-to-Cinema Method workshop are limited to 10. Reply YES and I'll send you the booking link. Reply STOP to opt out.

**`kortexa_followup_1`** (after 2 quiet days)
> Hi {{1}}, quick one from Ahmed-Saleem. If you've tried AI for property videos, you may have seen it change the rooms or make the house look fake. The Photo-to-Cinema Method keeps the house exactly as it is. The GH₵500 early price is only for the first 5 people. Reply YES for the booking link.

**`kortexa_followup_2`** (after 5 more quiet days, then nothing)
> Last message from Ahmed-Saleem, {{1}}. If you ever want your listings to stop looking like every other slideshow, reply YES and I'll send the workshop booking link. Reply STOP and I won't message again.

The templates don't include the date or link because Meta templates are fixed
text. When an agency replies YES, the AI sends `BOOKING_LINK` and the date from
`kortexa-facts.md`.

### 2. Run it

Needs Node.js 20+.

```bash
cd automation
npm install
cp .env.example .env      # fill it in
npm start                 # admin inbox at http://localhost:3000/admin
```

Leave `WHATSAPP_TOKEN` empty and it runs in **dry-run mode**: everything works
but messages are only logged. Good for trying it out first.

**Hosting:** use a host with a persistent disk, because leads are saved in
`data/store.json`. Railway (with a volume), Render (with a disk), Fly.io (with
a volume) or any small VPS works. Serverless hosts like Vercel are not a fit:
they have no disk, and their timers don't run all the time. Put the values from
`.env` into the host's environment settings, never into the repository.

### 3. Daily use

1. Send outreach from the dashboard as usual and mark who replied.
2. Click **Download replied (CSV)** in the dashboard.
3. Open `/admin`, import the CSV. The opener goes out at the next run (within
   15 minutes during sending hours), or click **Send due follow-ups now**.
4. Check **Needs you** in the admin inbox for AI drafts and handed-over questions.

## Costs

- WhatsApp: Meta charges per template message delivered. Marketing messages to
  Ghana cost a few US cents each; check Meta's current rate card. Replies within
  the 24-hour window are free.
- Claude: one request per agency reply, using the model in `CLAUDE_MODEL`.

## Tests

```bash
npm test
```
