# Carousel Studio

Carousel Studio helps you make Instagram carousels (the swipe-through posts with several slides) that look like the ones you already like.

You show it examples. It learns the style. It writes new carousels in that style and shows them to you. You approve the ones you like, and only then does it post them to Instagram.

**Nothing posts without your approval.**

> This repo also contains `index.html`, the Kortexa landing page. It is separate from Carousel Studio and is not used by it.

---

## 1. What it does

1. **Learn the styles you like.** Give it screenshots of carousels you admire, or links to them. It studies colors, fonts, layout and tone.
2. **Create ideas and carousels in that style.** It writes ideas, then full carousels (text for each slide, a caption and hashtags), and draws the slides.
3. **You review and approve.** A web page on your own computer lets you flip through the slides, edit the caption, ask for changes, and approve or reject each one.
4. **It posts to Instagram.** Only approved carousels can be posted, and the program asks you to confirm first.

---

## 2. Install

You need:

- **Python 3.10 or newer.** Check with `python3 --version`.
- A terminal (Terminal on Mac, PowerShell or Command Prompt on Windows).

Then, from the folder that holds this README:

```bash
pip install -e .
playwright install chromium
cp .env.example .env
```

- `pip install -e .` installs the program and the `studio` command.
- `playwright install chromium` downloads a small browser. The program uses it to draw the slides as pictures.
- `cp .env.example .env` makes your private settings file. You will fill it in with your keys in the next section. (On Windows, use `copy .env.example .env`.)

Never share your `.env` file. It holds passwords.

---

## 3. Keys and accounts you need

Keys are long codes that prove to a service that you are you. Put them in the `.env` file, after the `=` sign.

| Setting | What it is | Where to get it | Needed for |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Lets the program use Claude, the AI that writes the text. | Sign in at [console.anthropic.com](https://console.anthropic.com), then create a key. | Everything that writes (required). |
| `APIFY_TOKEN` | Lets the program fetch carousels from post links or @handles. | [apify.com](https://apify.com) → Settings → Integrations → copy the API token. | Only links and @handles. Screenshots work without it. |
| `IG_USER_ID` | Your Instagram account's ID number. | See the Instagram steps below. | Posting. |
| `IG_ACCESS_TOKEN` | Permission for the program to post for your account. | See the Instagram steps below. | Posting. |
| Image hosting (`S3_*` or `PUBLIC_BASE_URL`) | A public place on the internet where the slide pictures are stored. | See "Image hosting" below. | Posting. |

### Instagram: step by step

Instagram only lets programs post through its official system (the "Graph API"). Follow these steps once.

1. **Switch your Instagram account to a Business or Creator account.** In the Instagram app: Settings → Account type and tools.
2. **Link it to a Facebook Page.** Create a Facebook Page if you do not have one. In Instagram, connect the Page under Settings → Account center, or in the Page's settings.
3. **Create an app.** Go to [developers.facebook.com](https://developers.facebook.com), create a new app (type "Business"), and add the **Instagram Graph API** product.
4. **Give the app these permissions:** `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`.
5. **Make a long-lived access token.**
   - Open the **Graph API Explorer** (developers.facebook.com/tools/explorer) and pick your app.
   - Generate a short-lived user token with the permissions above.
   - Exchange it for a long-lived token (the Graph API documentation shows the exact link to use, with your app ID and secret). A long-lived token lasts about 60 days, so you will need to repeat this when it expires.
   - Paste the result into `IG_ACCESS_TOKEN`.
6. **Find your Instagram user ID.**
   - Open `https://graph.facebook.com/v23.0/me/accounts?access_token=YOUR_TOKEN` in a browser. It lists your Pages and their IDs.
   - Open `https://graph.facebook.com/v23.0/PAGE_ID?fields=instagram_business_account&access_token=YOUR_TOKEN`. The number shown next to `instagram_business_account` is your `IG_USER_ID`.

Instagram needs a link to each slide picture, so the pictures must be stored somewhere public.

### Image hosting

**Recommended: Cloudflare R2 (has a free tier).**

1. Create a free Cloudflare account and an R2 bucket (for example, named `carousels`).
2. Turn on public access for the bucket. Cloudflare gives you a public address that looks like `https://pub-xxxx.r2.dev`.
3. Create an R2 API token with read and write access to the bucket. It gives you an Access Key ID and a Secret Access Key.
4. Fill in `.env`:

   | Setting | Value |
   |---|---|
   | `IMAGE_HOST` | `s3` |
   | `S3_BUCKET` | your bucket name |
   | `S3_ENDPOINT_URL` | the R2 address shown on the API token page, like `https://<account-id>.r2.cloudflarestorage.com` |
   | `S3_PUBLIC_BASE_URL` | the public address from step 2 |
   | `AWS_ACCESS_KEY_ID` | the Access Key ID from step 3 |
   | `AWS_SECRET_ACCESS_KEY` | the Secret Access Key from step 3 |

   `S3_*` is the common name for this kind of storage. Amazon S3 works the same way. For Amazon S3, leave `S3_ENDPOINT_URL` empty.

**Alternative: keep the pictures on your computer.** Set `IMAGE_HOST=local`. Instagram then loads the pictures from your own computer through a "tunnel" (a temporary public link). Cloudflare's free `cloudflared` tool does this:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

It prints a public `https://...` address. Put it in `.env` as `PUBLIC_BASE_URL=` (no trailing slash). Keep `studio review` running while you publish, and keep the tunnel open. Free tunnel addresses change each time you restart the tunnel, so update `PUBLIC_BASE_URL` when that happens.

### Check everything

```bash
studio doctor
```

It shows **OK** or **--** next to each item: Claude key, Apify token, Instagram login, image hosting, and whether you have set your niche. If Instagram is set up, it also shows your account name and how many posts you have left in the current 24-hour window.

---

## 4. Tell it about your niche

The program needs to know what your account is about. Run:

```bash
studio brand
```

This shows the file `data/brand.json`. You can edit it in any text editor. Example:

```json
{
  "brand_name": "Kortexa",
  "instagram_handle": "@kortexa",
  "niche": "AI tools for real estate agents",
  "audience": "Busy real estate agents who want to save time",
  "goals": "Grow followers and drive profile visits",
  "call_to_action": "Follow for more",
  "topics_to_avoid": ["politics"],
  "language": "English"
}
```

Replace the two lines that say `CHANGE ME`. `studio doctor` will remind you until you do. `topics_to_avoid` is a list, and `language` is the language the carousels are written in.

---

## 5. Your daily workflow

Use these commands in the terminal, in the project folder. Replace the words in `< >` with your own. Use a short name for each style, such as `bold-dark`.

**Step A: teach it a style (do this once per style).**

```bash
studio learn bold-dark ./screenshots @someaccount https://www.instagram.com/p/XYZ/
```

- `bold-dark` is the name you give this style.
- `./screenshots` is a folder of screenshots. You can mix folders, @handles and post links in one command.
- The program reads the style automatically when it finishes. To skip that, add `--no-analyze`.

**Pinterest references.** You can also use Pinterest pins, boards or profiles as references (uses the same `APIFY_TOKEN`):

```bash
studio learn bold-dark https://www.pinterest.com/pin/123456789/ https://www.pinterest.com/someone/my-board/ --per-board 12
```

- Each pin becomes one single-slide reference. For a board or profile link, the program takes the most-liked pins, up to `--per-board` (default 12).
- `pin.it` short links work too. Pins that are videos are skipped.

**Step B: check the style looks right.**

```bash
studio preview bold-dark
```

This draws a few sample slides in your style. Look at them. If they do not look like the examples, add more references and run `studio analyze bold-dark`.

**Step C: get ideas (optional).**

```bash
studio ideas bold-dark
```

This lists carousel ideas with a hook and a reason for each. It does not save anything. Add `--theme "..."` to focus the ideas, for example `--theme "first-time home buyers"`.

**Step D: make carousels.**

```bash
studio make bold-dark -n 3 --theme "common mistakes when listing a house"
```

This creates 3 drafts and draws their slides. `-n` is how many to make, and `--theme` is optional.

**Step E: review and approve in the web page.**

```bash
studio review
```

Then open **http://127.0.0.1:8000** in your browser. In the page you can:

- Flip through the slides.
- Edit the caption.
- Type feedback (for example, "punchier hook, fewer words on slide 4") and click **revise**. It rewrites the carousel with your notes.
- **Approve** or **reject** each draft.
- Click **publish** on an approved draft. It asks you to confirm before it posts.

Press `Ctrl+C` in the terminal to stop the web page.

**Terminal alternatives** (same jobs, no web page):

```bash
studio list                  # show all drafts, their IDs and status
studio approve <draft-id>    # approve a draft
studio publish <draft-id>    # post it; asks you to confirm (add --yes to skip)
```

Draft IDs look like `c_3f9a1b2c4d`. `studio list` shows them.

---

## 6. Tips

- **Collect 5 to 15 carousels per style.** Fewer gives a weak style. More does not always help.
- **Screenshot folders:** make one subfolder per carousel, and put its slide screenshots in that subfolder in slide order (for example `slide1.png`, `slide2.png`). Loose pictures in a folder count as one carousel.
- **Slide limits:** Instagram carousels need between 2 and 10 slides. The program uses `IG_MAX_SLIDES` (default 10) and refuses to post outside that range.
- **Posting limit:** Instagram limits how many posts can be published through the API in 24 hours. `studio doctor` shows your current quota.
- **Protect the web page:** if other people can reach your computer, set `REVIEW_PASSWORD` in `.env`. The page will then ask for a password. The page is safe on your own computer by default (it only listens on 127.0.0.1).
- **Costs:** each carousel uses several calls to Claude, and Anthropic bills for those calls. To keep costs down or get better quality, change these in `.env`:
  - `STUDIO_MODEL` picks the Claude model (default `claude-opus-5-5`).
  - `STUDIO_EFFORT` sets how hard it thinks (`high` by default). Lower it to spend less.
- **Check before you post.** Read every caption and slide. The program writes the text, and you are responsible for what goes out under your name.

---

## 7. Project layout

- `carousel_studio/` is the program.
  - `cli.py`: the `studio` commands.
  - `config.py`: reads your settings and `data/brand.json`.
  - `llm.py`: talks to Claude.
  - `models.py`: the shape of styles, drafts and slides.
  - `store.py`: saves and loads files on your computer.
  - `ingest/`: reads your screenshots, post links and @handles.
  - `style/`: learns a style from the examples.
  - `generate/`: writes ideas, carousels and revisions.
  - `render/`: draws the slides from templates (`render/templates/`) using the browser.
  - `review/`: the web page for reviewing (`review/templates/`).
  - `publish/`: uploads the pictures (`hosting.py`) and posts to Instagram (`instagram.py`).
- `data/` holds your files. It is created as you use the program.
  - `data/brand.json`: your niche and audience.
  - `data/styles/`: the styles you have taught it, and their examples.
  - `data/drafts/`: drafts, slide pictures and captions.
- `tests/` holds the automatic tests.
- `.env.example` is the list of settings. Your private copy is `.env`.
- `pyproject.toml` lists the required software and the `studio` command.
- `index.html` is the separate Kortexa landing page.

To run the tests:

```bash
pip install -e .
pytest
```
