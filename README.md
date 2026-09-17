# News Feed Embed — X (Twitter) + Reddit RSS → Discord Monitor (Multi-Webhook Edition)

A lightweight, **100% serverless** bot that monitors public **X (Twitter)** accounts and **subreddits**
via RSS mirrors, then posts new items to **different Discord channels** (one webhook per account/subreddit)
with rich media embeds, clickable link-style buttons, and automatic **English translation** for
non-English tweets.

No bot token. No gateway. No server. Just **GitHub Actions + Discord Webhooks**.

---

## 🌟 Credits & Acknowledgments

This project stands on the shoulders of these amazing open-source projects and free services —
please support them:

| Project / Service | What it's used for | Links |
|---|---|---|
| **News-Flash-Bot** by [@cold-logic5](https://github.com/cold-logic5) | The original repository this project is based on (RSS → Discord webhook architecture) | [GitHub repo](https://github.com/cold-logic5/News-Flash-Bot) · [Author](https://github.com/cold-logic5) |
| **Nitter** by [@zedeus](https://github.com/zedeus) | Free & open-source, privacy-focused X/Twitter front-end providing the RSS feeds | [GitHub](https://github.com/zedeus/nitter) · [nitter.net](https://nitter.net/) · [nitter.perennialte.ch](https://nitter.perennialte.ch/) · [xcancel.com](https://xcancel.com/) · 💖 [Donations](https://github.com/zedeus/nitter#donations) |
| **FxTwitter / FxEmbed** by [@dangered wolf](https://github.com/dangeredwolf) | Rich X/Twitter embeds (auto-unfurl) + the free API — **primary tweet-data source** (round 11; its same-engine sister client **fixupx.com** is the stand-by host) used for media, stats, translation, GIF re-rendering and the video proxy | [fxtwitter.com](https://fxtwitter.com) · [docs.fxembed.com](https://docs.fxembed.com/) · [FxEmbed GitHub](https://github.com/FxEmbed/FxEmbed) · [GitHub](https://github.com/dangeredwolf) · 💖 [Sponsor dangered wolf](https://github.com/sponsors/dangeredwolf) |
| **vxtwitter (BetterTwitFix / fixvx)** | **Backup tweet-data API** (round 11, 3rd in the fallback chain — multi-photo tweets arrive as separate photos via its API) + its **gifconvert** GIF converter (round 11) | [vxtwitter.com](https://vxtwitter.com) · [API docs](https://vxtwitter.com/api.md) |
| **EmbedEZ** | Rich Reddit embeds (redditez.com mirror) + the provider API used by Reddit V2 + **last-resort tweet-data source** behind twitterez.com (round 11) | [embedez.com](https://embedez.com/) · [redditez.com](https://embedez.com/reddit) · [twitterez.com](https://twitterez.com) · [API docs](https://embedez.com/docs) |
| **Embeddit** by [@DeltAndy123](https://github.com/DeltAndy123) | Alternative Reddit embed mirror (credited — its button was removed in the 2026-09-11 trim) | [GitHub](https://github.com/DeltAndy123/Embeddit) |
| **vxReddit** by [@dylanpdx](https://github.com/dylanpdx) | Alternative Reddit embed mirror (credited — its button was removed in the 2026-09-11 trim) | [GitHub](https://github.com/dylanpdx/vxReddit) · [vxreddit.com](https://vxreddit.com) |
| **Redlib** (community instances) | Reddit front-end mirrors used as RSS fallback sources — official instance list, refreshed 2026-09-12 | [redlib-instances](https://github.com/redlib-org/redlib-instances) · [redlib](https://github.com/redlib-org/redlib) |
| **Arctic Shift** by [@ArthurHeitmann](https://github.com/ArthurHeitmann) | Optional Reddit archive JSON for V3 crosspost originals, ordered galleries including GIFs, text/media fallbacks, and (round 17) the **per-subreddit search backup feed** when RSS yields no new posts. Archive availability and freshness vary; fallback counts are labelled as archived. | [GitHub](https://github.com/ArthurHeitmann/arctic_shift) · [Website](https://arctic-shift.photon-reddit.com/) · [Download tool](https://arctic-shift.photon-reddit.com/download-tool) |
| **cron-job.org** | Free external scheduler that triggers the workflows reliably every 10 minutes | [cron-job.org](https://cron-job.org) |
| **GitHub Actions** | Runs everything on a schedule, for free | — |
| **Discord Webhooks** | Delivers messages to channels statelessly | — |

Huge respect and gratitude to [@cold-logic5](https://github.com/cold-logic5) for the original
architecture, to the Nitter project — if you can, [support zedeus here](https://github.com/zedeus/nitter#donations) —
and to [@dangered wolf](https://github.com/dangeredwolf), creator and lead developer of FxTwitter/FxEmbed — donations welcome at
[github.com/sponsors/dangeredwolf](https://github.com/sponsors/dangeredwolf).

---

## ✨ Features

- 🐦 **X/Twitter monitor** with **three interchangeable render engines**:
  - **V1** — classic text + fxtwitter auto-embed, buttons below.
  - **V2** — Discord *Components V2* card (container, gallery, stats), buttons **outside** the card.
  - **V3** — same rich card, but buttons **nested inside** the container.
- 🌐 **Automatic English translation** — non-English tweets show a *"Translated from X"* block with the
  original text preserved, via FxTwitter's `/en` translation endpoint (works on V1/V2/V3).
- 📄 **Full X Articles (V2/V3, round 10)** — article tweets post their **cover image, title, full body
  text, and every in-article image/GIF** (GIFs animated via the same converter chain) straight into the
  card, from FxTwitter's article JSON — no scraping. One caveat: FxTwitter doesn't translate article
  bodies, so non-English articles post in their original language.
- 🎯 **Multi-webhook routing** — each tracked X account posts to its own Discord channel
  (`WEBHOOK_<ACCOUNT>` secrets), with an optional catch-all fallback webhook.
- 📰 **Reddit monitor** with two engines:
  - **V1** — free, no API key: posts the `redditez.com` link and lets Discord auto-embed it.
    If the thread links to YouTube, the bare YouTube URL is appended on its own line too, so a
    **playable YouTube player** appears next to the reddit embed.
  - **V2** — rich *Components V2* card built from the **EmbedEZ API** (title, media gallery, stats,
    🕐 Discord timestamp).
- 🧵 **Round 9 (2026-09-13): one combined RSS request** — all tracked subreddits are fetched in a
  single `/r/sub1+sub2+.../new.rss` feed, which fits inside Reddit's ~1 request/minute datacenter
  rate limit; automatic per-subreddit fallback if the combined feed ever fails. Optional personal
  **`REDDIT_FEED_TOKEN`** makes it bulletproof. (See the round-9 section under the Reddit monitor.)
- 🔘 **Link-style buttons** with emoji support (Unicode **or** custom server emoji IDs). Reddit
  buttons: **Read Post → the original `reddit.com` thread**, **▶️ YouTube** (only when a link is
  detected), **Citlali News**, **Support**.
- 🔗 **Clickable hashtags & mentions (X V2/V3)** — `#tag` → `x.com/hashtag/tag` and `@user` →
  `x.com/user` as masked links, exactly like fxtwitter auto-embeds.
- 🎬 **Smart video handling (X V2/V3)** — Discord's media gallery can't play large video files, so
  every video's **real file size is probed** (HTTP HEAD) before posting. Oversized videos are
  swapped for the biggest **smaller mp4 variant** from FxTwitter's `formats[]` that still fits
  (stays playable!), with a thumbnail + "Watch on X" link as last resort. Resolution is irrelevant —
  it's all about file size (see the live test tables below).
- 🕐 **Exact timestamps (V2/V3, X & Reddit)** — every card's stats line ends with a Discord-native
  `<t:…:f>` timestamp; hover/tap for the post's exact date & time.
- 🛡 **Mod-queue safe (Reddit)** — a 48-hour freshness window keyed on the RSS *updated* stamp means
  posts approved from a subreddit's moderator queue hours (or a day) later still get posted —
  they're never left out.
- 📊 **Stats line** — replies/retweets/likes/views (X) or comments/shares/likes/views (Reddit V2).
- 🕙 **Reliable 10-minute automation** via an external cron trigger (GitHub's built-in `schedule` is
  kept only as a backup — it's documented as best-effort and can lag or be skipped).
- 💾 **Self-maintaining memory** — posted IDs are cached in JSON files committed back to the repo by
  `github-actions[bot]`, so nothing is ever posted twice.

---

## 🗂 Repository Contents

```
├── .github/
│   ├── dependabot.yml             # Dependabot: weekly pip + actions update PRs (optional)
│   └── workflows/
│       ├── twitter_monitor.yml    # X/Twitter — runs testing area/twitter_v3.py (V3)
│       ├── reddit_monitor.yml     # ⚠️ OLD Reddit V1/V2 workflow — ARCHIVE it (Actions tab),
│       │                          #    see "Testing & verification" — superseded by V3
│       ├── reddit_monitor_v3.yml  # Reddit V3 (ACTIVE) — runs testing area/reddit_main_v3test.py
│       ├── ci.yml                 # PR gate: install + compile + offline smoke test
│       └── dependabot_auto_merge.yml  # opt-in auto-merge for Dependabot PRs (repo Variable)
├── docs/
│   ├── DEPENDABOT.md              # full plain-English Dependabot explanation
│   ├── DISCOHOOK.md               # Discohook: what it's for, fully optional, safe to disable
│   └── CI_SMOKE.md                # ci.yml + test_smoke.py: the required offline safety gate
├── twitter_v1.py                  # X/Twitter — V1 (production copy)
├── testing area/                  # tested copies of every engine (see Testing area guide)
│   ├── twitter_v2_button_outside.py     # X V2 (buttons outside)
│   ├── twitter_v3.py              # X V3 (buttons inside — ACTIVE)
│   ├── twitter_proxy.py           # X V3 tweet-data fallback chain (round 11: fxtwitter/fixupx/vxtwitter/twitterez)
│   ├── reddit_main.py             # Reddit V1 (free, mirror auto-embed)
│   ├── reddit_main_v2_embedez.py  # Reddit V2 (Components V2 via EmbedEZ API)
│   ├── reddit_main_v3.py          # Reddit V3 (proxy media + native fallback — ACTIVE)
│   ├── reddit_proxy.py            # Reddit V3 proxy services (round 13: redditez/vxreddit/embeddit)
│   └── video_diag.py              # X video tile diagnostic (round 10)
├── tests/
│   └── test_smoke.py              # offline smoke test (run by ci.yml on every PR)
├── posted_tweets.json             # X cache (auto-committed) — start with: []
├── posted_reddit.json             # Reddit cache (auto-committed) — start with: []
├── proxy_health.json              # proxy warm-up results (auto-committed, round 13)
├── PRIVACY_POLICY.md              # privacy policy (the bot collects no personal data)
├── TERMS_OF_SERVICE.md            # terms of service / acceptable use
├── requirements.txt               # feedparser, aiohttp, python-dotenv
├── .env.example                   # local testing template
└── .gitignore                     # (keep the posted_*.json force-add exception in workflow)
```

> **Promotion note:** the production root copies of the X V2/V3 and Reddit V1/V2/V3
> engines do not exist yet — by design, everything runs from `testing area/` first.
> When a test copy passes, copy it to the root (`main_v2.py`, `main_v3.py`,
> `reddit_main.py`, `reddit_main_v2.py`, `reddit_main_v3.py`) and point the
> workflow's `run:` line at the copy (the V3 promotion steps are in the testing
> guide below).

---

## 🧪 Testing area — how updates are tested before going live

Every new or changed script is proven **before** it touches production. The process:

1. **The updated script lives in the `testing area/` folder first** (e.g. `testing area/reddit_maintest.py`,
   `testing area/main_v3testproround10.py`, `testing area/reddit_main_v3test.py`). Never run an unproven script from the repo root.
2. **Point the workflow's `run:` line at the test copy.** The **double quotes are required** because
   the folder name contains a space:
   ```yaml
   run: python "testing area/reddit_maintest.py"
   ```
3. **Check two things:**
   - the actual post(s) in Discord (layout, buttons, media), **and**
   - the workflow log (Actions tab) — every skipped source/instance is logged there.
4. **Once both look right, copy the test file over the production file**
   (`reddit_main.py`, `reddit_main_v2.py`, `main.py`, `main_v2.py`, `main_v3.py`) and point the
   `run:` line back at it:
   ```yaml
   run: python reddit_main.py
   ```
5. Commit. Production is updated; the test file can stay or be deleted.

> The same guidance is written as a comment block inside both workflow yml files, right above the
> `run:` line, so future readers find it there too.

---

# 🐦 X (Twitter) Monitor

## Choosing a version (V1 vs V2 vs V3)

All three do the same job with the same multi-webhook routing and translation — they only differ in
**how the Discord message looks**:

| | `main.py` (V1) | `main_v2.py` (V2) | `main_v3.py` (V3) |
|---|---|---|---|
| Message style | Plain text + fxtwitter link → Discord **auto-unfurls** the embed | Fully custom **Components V2** bordered card (type 17 container + text + media gallery + stats) | Same custom card as V2 |
| Buttons | Action row below the embed | Action row **outside/below** the container | Action row **nested inside** the container |
| Data source | RSS + FxTwitter API (light, lang check only) | RSS + FxTwitter API (full tweet JSON) | RSS + FxTwitter API (full tweet JSON) |
| Custom accent color | n/a | ✅ (per-tweet `color`) | ✅ (per-tweet `color`) |
| Switch to it | `run: python main.py` | `run: python main_v2.py` | `run: python main_v3.py` |

**To switch versions:** open `.github/workflows/twitter_monitor.yml` and change the run line:

```yaml
run: python main.py        # V1
# run: python main_v2.py   # V2
# run: python main_v3.py   # V3
```

Commit — done. All three were verified working end-to-end (feeds, translation, per-channel routing,
buttons, and cache commits).

## 🆕 X V2/V3 card behaviors (2026-09-11 update)

* **Clickable hashtags & mentions** — `#tag` → `[#tag](https://x.com/hashtag/tag)`, `@user` →
  `[@user](https://x.com/user)`; bare http(s) links are auto-linked by Discord as before.
  Regex lookbehinds protect URLs like `example.com/path#anchor` and emails like `a@b.com` from being
  linkified by accident.
* **Smart video handling (revised after live testing).** Your tests proved the breakage is about
  **file size, not resolution**:

  | Video | Real size (probed) | Components V2 gallery |
  |---|---|---|
  | 3840×2160 · 24 min | 905 MB | ❌ "image failed to load" |
  | 1920×1080 · 56 min | 578 MB | ⚠️ loads, won't play |
  | 2560×1440 · 5:12 | 405 MB | ❌ "image failed to load" |
  | 2560×1440 · 1:28 | 120 MB | ✅ plays |
  | 3440×1440 · 0:24 | 22 MB | ✅ plays |
  | 2340×1080 · 4:29 | 191 MB | ✅ plays |

  So the scripts now **probe every video's real file size** with an HTTP HEAD request
  (`Content-Length`, with a Range-GET backup) and apply these rules — nothing is forced when the
  size can't be determined:
  * **≤ 256 MB** (`VIDEO_SIZE_LIMIT`, tunable) → video goes in the gallery as-is (confirmed safe zone:
    191 MB works, 405 MB fails).
  * **Over the limit** → the script tries FxTwitter's `formats[]` list (smaller mp4 renditions,
    highest quality first) and probes each; the first that fits is embedded instead, with a
    `🔽 Original video is ~X MB — showing a smaller version (~Y MB)… ▶️ Watch full quality on X`
    note. Example live result: the 905 MB 4K Wuthering video → 1280×720 variant (~135 MB) that
    **plays in Discord**.
  * **Over the limit + no fitting variant** → the video's **thumbnail** appears in the gallery plus
    a `⚠️ Video is ~X MB — ▶️ Watch it on X` note (covers the 56-minute Genshin case).
  * **Size undetectable** → the video is left untouched (never forced) **unless** it's clearly
    risky (> 5 minutes *and* ≥ 1080p — matches every verified failure), in which case it's
    thumbnailed with a watch link. A 2K clip of 1:28 stays in the gallery.
* **Discord timestamp** — the stats line ends with `🕐 <t:epoch:f>` (taken from FxTwitter's
  `created_timestamp`, falling back to `created_at`, then the RSS publish date).
* **Null-safe accent color** — FxTwitter sometimes returns `"color": null`; the card now falls back
  to Twitter blue instead of crashing.

## 🆕 X V2/V3 card behaviors — round 4 (2026-09-11)

Fixes and formats added after real feed runs:

* **Discord `400 {"components": ["0"]}` errors — FIXED.** Root cause: tweets with an **empty body**
  (a repost of a media-only quote post; an X Article) produced a zero-length text component, which
  Discord rejects. Text is now chunked (≤ 1900 chars per component, up to 4 components) and empty
  components are never emitted — so **very long tweets also render now** instead of failing.
* **Quoted posts are rendered.** Tweets quoting another post show:
  `>>> [Quote](url) from **Name** (@user)` + the quoted text + the quoted tweet's own media gallery
  (videos in quotes get the same size/GIF/portrait treatment).
* **X Articles & link cards get their image.** When a tweet has no media, the script fetches the
  tweet's own `x.com` page and reads its OpenGraph image — for X Articles that's the **article
  banner**, for link posts (e.g. `hoyo.link`) it's the **card image**. Fallback: the first external
  link's `og:image` (works for hoyoverse/kurogames pages). Profile pictures are never used, and the
  extra fetch is skipped for normal tweets. (Round 10 supersedes this for articles — see below: the
  full article now renders, not just its banner.)
* **GIF support.** X "GIFs" are internally tiny looping mp4s (`tweet_video/*.mp4`). When detected,
  the script swaps in a real **animated image** so it plays inline instead of sitting in a video
  player. Two community converters are probed in order — **never forced**:
  1. FxTwitter's official animated WebP (`gif.fxtwitter.com/tweet_video/*.webp`) — the same asset
     V1 embeds use. Its CDN is **intermittently down** (Cloudflare 530/1033, confirmed live).
  2. **fastgif** (`fastgif-production.up.railway.app/tweet_video/*.gif`) — an independent
     third-party converter that outputs true GIFs (round 6). Only its `.gif` route works (its
     `.webp` route errors), and unknown ids return 500, which makes it safely probeable.

  Each source is HEAD-probed before use; if the first is down the second takes over automatically,
  and if neither answers, the mp4 is kept, which still plays as a video. The chain is self-healing
  in both directions — the moment `gif.fxtwitter.com` recovers it becomes the primary again.
* **Portrait videos that "load but won't play" — root-caused in round 5.** Vertical videos
  (`h > w`, e.g. the 58s Jingran showcase) intermittently failed to play right after posting —
  but follow-up tests showed the **same direct URLs playing fine** in Components V2 shortly after
  (even media that had failed earlier). It was a transient Discord proxy warm-up issue, not a
  portrait incompatibility, so direct URLs are now used for all videos (same as every other embed
  service). A documented one-line toggle (`PORTRAIT_PROXY = True`) can re-route vertical videos
  through FxTwitter's embed proxy (`/2/go?url=…`) if genuine breakage is ever proven again.
* **`/status/:id` API path.** The screen-name API path (`/<user>/status/:id`) returns **404** for
  reposts of other authors, X Articles, and some newer tweets (verified live); the plain-ID path
  resolves everything. Read Post links now use the **true author** from the payload, so reposts link
  to the original post correctly. Same for the `/en` translation fetch.
* **"↩️ Replying to @user"** small line appears on replies (links to the parent post when known).
* **New animated button emoji** on X *and* Reddit (per your spec): Read Post
  `<a:starwardhmm:1472388018689282261>`, Citlali News `<a:starward11:1439878792653832253>`, Support
  `<a:starwardfans:1509026327548657914>`.
* **Interactive campaign tweets** (multi-photo, e.g. the "mysterious manuscript" Wuthering post) —
  all 4 photos render in the gallery; verified against the live API.

## 🆕 X V2/V3 card behaviors — round 10 (2026-09-13)

* **Full X Article support (verified live).** FxTwitter's API returns each article as clean JSON
  (`tweet.article`: title, cover image, draft.js text blocks, in-article media) — no x.com scraping,
  no login. Article tweets now post as: **cover image** (right under the header) → **title** + full
  body text (chunked exactly like tweets) → **in-article media gallery** (images as-is; in-article
  GIFs go through the same animated `gif.fxtwitter` → `fastgif` chain; in-article videos get the
  same size probe / downgrade handling) → stats → buttons. The round-4 "banner only" OpenGraph
  behavior no longer applies to articles — they render fully.
  * Note: FxTwitter does **not** translate article bodies (there is no `/en` for them), so
    non-English articles post in their original language. Normal tweets still get `/en`.
  * Verified live 2026-09-13: HonkaiNA "DevTalk | Evolution Test Wrap-Up" posted as cover + title +
    text + 4-item gallery (3 images + 1 animated GIF); log line
    `V3 Posted: HonkaiNA_2081590638282432606 (lang=en | article)`.
* **Video gallery limit — live re-verified with a full diagnostic.** A one-off diagnostic card
  (`testing area/video_diag.py`) posted labeled test tiles at every size and URL style to a channel;
  results 2026-09-13:

  | Tile | Result |
  |---|---|
  | 19.3 MB / 10.6 MB (270p) | ✅ plays — all URL styles |
  | **170.8 MB (720p)** — what the bot embeds | ✅ plays — all URL styles |
  | **233.8 MB (1080p)** — what the bot embeds | ✅ plays — all URL styles |
  | 521.7 MB (1080p) | ❌ "image not found" — every style |
  | 824 MB / 1782 MB (4K) | ❌ "image not found" — every style |

  So the 256 MB `VIDEO_SIZE_LIMIT` sits in a **proven-safe gap** (≤ 234 MB plays; ≥ 521 MB never
  gets sent because the downgrade rule swaps first) — no default changed. The test also proved the
  `?tag=` query parameter and the fxtwitter proxy origin are **irrelevant** to playability — the
  plain direct URLs are what play.
* **`GALLERY_VIDEO_LIMIT` (new constant, default `0` = off, behaviour unchanged).** An optional
  extra safety cap for the gallery: if Discord's proxy ever breaks a ≤ 256 MB tile again, set it to
  the largest size that proved playable (e.g. `GALLERY_VIDEO_LIMIT = 100 * 1024 * 1024`) — videos
  above it then auto-downgrade to the largest variant at/below it (checking **all** variants, not
  just the top 3), or post a "watch on X" note, so the gallery can never carry a tile Discord's
  proxy can't play.
* **"image not found" on an already-posted video — what to do.** Discord's media proxy fetches each
  tile's URL **once**, when the message is created. If that single fetch hiccups (transient proxy
  warm-up / CDN edge — the same class of event as the round-5 portrait case), the tile shows
  "image not found" **for that message forever**: reloading Discord doesn't fix it, but
  **re-posting the same URL works** (verified twice, 2026-09-13). The bot can't detect the failure
  itself (the webhook answers "OK" before the proxy fetch even starts — no API exposes tile
  status), so the recovery stays a 30-second manual fix:
  1. Delete the broken message in Discord.
  2. Remove that tweet's line (e.g. `"Ananta_EN_1970307131074355593"`) from `posted_tweets.json`.
  3. Re-run the workflow (or just wait for the next 10-minute run).

  As of 2026-09-13 this had happened exactly once (2 tiles out of hundreds of posts).

## 🆕 X V2/V3 card behaviors — round 11 (2026-09-17): tweet-data fallback chain + GIF restructure

* **Tweet data now has a 4-step fallback chain** (new module `testing
  area/twitter_proxy.py` — the same "mix of services" idea as the Reddit
  proxies, all keyless). The **main source is FxEmbed's FxTwitter API**
  (`api.fxtwitter.com`, docs.fxembed.com); if it can't answer, the chain
  continues seamlessly:
  1. **fxtwitter** — primary (full features: media, quotes, X Articles,
     `/en` translation, views).
  2. **fixupx** (`api.fixupx.com`) — FxEmbed's sister client: **same engine,
     same creator, same domain family** as fxtwitter.com — a hot stand-by on
     a different host. Not listed in the public FxEmbed API docs, so if that
     host doesn't resolve the step fails in ~0 ms and the chain continues —
     safe either way.
  3. **vxtwitter** (`api.vxtwitter.com` — BetterTwitFix, the site behind
     vxtwitter.com/fixvx): text, media, quoted tweets, lang, epoch date,
     stats. **Multi-photo tweets arrive as one entry per photo** (verified
     live 2026-09-17 — its combined-grid image is a website-only
     presentation field and is ignored). No view counts, no X Article
     bodies.
  4. **twitterez** (the EmbedEZ backend behind twitterez.com — the same
     engine redditez.com uses for Reddit): keyless search API → stable key →
     bot embed page og: tags. Media arrives as embedez redirect URLs (GIFs
     as animated `.webp` that Discord loops natively), text + stats line
     (`💬/🔁/💜/👀`, compact numbers incl. `1.5M`). Its occasional promo line
     ("Add the EmbedEZ bot… (ad)") is stripped, and a video tweet's poster
     frame is not duplicated as a photo.
  **Seamless by design:** every service's result is normalized to the exact
  FxTwitter `tweet` shape *before* the card pipeline runs, so layout, media,
  stats, quotes, GIF handling and buttons are identical no matter who
  answered. The winner is logged per tweet —
  `V3 Posted: … (… | source=vxtwitter)` — and a fallback also logs
  `tweet data via vxtwitter (fallback).` If the module file is ever
  missing, the script logs a warning and runs the legacy direct FxTwitter
  call — nothing breaks. `/en` translation is attempted only when the data
  came from FxTwitter itself.
* **GIF converter chain restructured** (fastgif went offline 2026-09-17).
  Probed in order, never forced:
  1. `gif.fxtwitter.com/tweet_video/*.webp` — FxTwitter's official animated
     WebP (intermittent Cloudflare 530s, so probe-gated).
  2. `gifconvert.vxtwitter.com/convert.webp?url=<mp4>` — BetterTwitFix's
     converter (the exact URL shape vxtwitter's own embeds use — verified
     live; they use `.avif`, which Discord's gallery can't render, so we
     probe `.webp` first). Header-gated: probed with a browser Referer.
  3. `gifconvert.vxtwitter.com/convert.gif?url=<mp4>`
  4. `fastgif-production.up.railway.app/tweet_video/*.gif` — **offline since
     2026-09-17** (404 on every route); kept as the *last* probe so it is
     used automatically again if it ever comes back.
  If nothing answers, the mp4 is kept (plays as a video) — unchanged.
* **Reddit V3 got its matching backup the same round** — see the round-17
  section under the Reddit monitor.

## 🌐 How translation works (all versions)

1. The script fetches the tweet from the FxTwitter API and reads its `lang` field.
   (Round 11: the tweet data may instead come from a backup service in the
   fallback chain — see the round-11 section; the `/en` re-fetch below is
   attempted only when the data came from FxTwitter itself.)
2. If it's not English, it re-fetches `https://api.fxtwitter.com/<account>/status/<id>/en`, which
   returns FxTwitter's translated text.
3. The message shows **🌐 Translated from {Language}** then the translation, then an
   **Original text** block with the untranslated tweet. The *Read Post* button points to the `/en`
   fxtwitter page too.
4. If FxTwitter can't translate a specific post, the script gracefully posts the original text instead.
5. `LANGUAGE_NAMES` at the top of each file maps ISO codes (ja, ko, zh, fr, …) to readable names —
   extend it if you track accounts in other languages.

## 🎯 Multi-webhook routing

Every account in `ACCOUNTS` is routed to its own webhook secret:

| Setting | Example |
|---|---|
| `ACCOUNTS` secret | `TYPEII_EN,PomPom_HonkaiSR,Wuthering_Waves,HonkaiNA,Ananta_EN` |
| Per-account secret name | `WEBHOOK_` + account name **UPPERCASED**, non-alphanumerics → `_` |
| `TYPEII_EN` → | `WEBHOOK_TYPEII_EN` (e.g. `#zzz-news`) |
| `PomPom_HonkaiSR` → | `WEBHOOK_POMPOM_HONKAISR` (e.g. `#hsr-news`) |
| `Wuthering_Waves` → | `WEBHOOK_WUTHERING_WAVES` (e.g. `#wuwa-news`) |
| `HonkaiNA` → | `WEBHOOK_HONKAINA` |
| `Ananta_EN` → | `WEBHOOK_ANANTA_EN` (e.g. `#ananta-news`) |
| fallback (optional) | `DISCORD_WEBHOOK_URL` — used for any account without its own secret |

### The workflow (`.github/workflows/twitter_monitor.yml`)

```yaml
name: Twitter Feed Monitor

on:
  schedule:
    - cron: '*/10 * * * *'   # backup only — GitHub cron is best-effort
  workflow_dispatch:          # allows manual + external-cron triggering

permissions:
  contents: write

jobs:
  check-rss:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run Twitter Feed Monitor
        env:
          ACCOUNTS: ${{ secrets.ACCOUNTS }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
          WEBHOOK_TYPEII_EN: ${{ secrets.WEBHOOK_TYPEII_EN }}
          WEBHOOK_POMPOM_HONKAISR: ${{ secrets.WEBHOOK_POMPOM_HONKAISR }}
          WEBHOOK_WUTHERING_WAVES: ${{ secrets.WEBHOOK_WUTHERING_WAVES }}
          WEBHOOK_HONKAINA: ${{ secrets.WEBHOOK_HONKAINA }}
          WEBHOOK_ANANTA_EN: ${{ secrets.WEBHOOK_ANANTA_EN }}
        # While testing a new version, point this line at the test copy instead
        # (QUOTES REQUIRED — the folder name has a space):
        #   run: python "testing area/main_v3test.py"
        run: python main_v3.py   # ← switch to main.py / main_v2.py here

      - name: Commit and push updated posted_tweets.json cache
        run: |
          git config --local user.email "github-actions[bot]@users.noreply.github.com"
          git config --local user.name "github-actions[bot]"
          git add -f posted_tweets.json
          git diff --quiet && git diff --staged --quiet || (git commit -m "auto: update posted_tweets.json cache" && git push)
```

> Every webhook secret you add must get a matching `WEBHOOK_...` line in the `env:` block —
> that's the one manual step when adding a new account.

## 🔘 Customizing the buttons (all files)

Near the top of each script:

```python
READ_POST_LABEL = "Read Post"
READ_POST_EMOJI = {"name": "📖"}        # Unicode emoji — or None
STATIC_BUTTONS = [
    {"label": "Citlali News", "url": "https://discord.gg/HyrVP9wRXu", "emoji": {"name": "✨"}},
    {"label": "Support",     "url": "https://ko-fi.com/jieunlatte",   "emoji": {"name": "☕"}},
]
```

* Max **5 buttons per row** (Discord limit).
* **Custom server emoji:** type `\:emojiname:` in Discord to get its ID, then use:
  `"emoji": {"id": "123456789012345678", "name": "emojiname", "animated": False}`
  (`animated: True` for GIF emoji). Full custom *pictures* on buttons are not possible — Discord only
  supports label + one emoji.

---

# 📰 Reddit Monitor

Monitors subreddits through RSS (sorted by *new*) and posts each new thread to that subreddit's own
Discord channel.

## Choosing a version (V1 vs V2 vs V3)

| | `reddit_main.py` (V1) | `reddit_main_v2.py` (V2) | `reddit_main_v3.py` (V3 — **current**) |
|---|---|---|---|
| Cost | **Free — no API key at all** | Requires an **EmbedEZ API key** (paid credits — see concerns below) | **Free — no API key at all** (Reddit's own media URLs) |
| Look | Plain message + `redditez.com` link → Discord auto-embeds it (same idea as fxtwitter), plus a bare YouTube link with its own playable embed when detected | Rich **Components V2** card built from EmbedEZ data | Same rich **Components V2** card, built from **Reddit's own URLs** |
| Media | Whatever the mirror unfurls | Up to 10 media items via EmbedEZ | **Every photo** (up to 20 → 2 containers), best rendition per photo (full-res `i.redd.it` for jpgs); video posts show the **video only**; never a silent video |
| YouTube | Bare link (auto-embeds) + conditional button | Clickable line + button | **Thumbnail + animated `starwardspark3` button** (deterministic); optional real playback via `YOUTUBE_MEDIA_EMBED=1` |
| Extra | — | — | 💬/👍 stats + **💬 OP comment** (FULL MODE), true crosspost embeds (fetches the original post), native `v.redd.it` video chain, **Discohook preview link** logged per card |
| Switch to it | `run: python reddit_main.py` | `run: python reddit_main_v2.py` | `run: python reddit_main_v3.py` (production copy; the tested copy lives in `testing area/`) |

### 🆕 Reddit V3 — what's different (round 12, 2026-09-15)

* **All photos, always.** Multi-image posts post every photo.
  Single-image posts: the RSS content is scanned for every `redd.it` media
  URL in post order (instead of only the feed's single 140px thumbnail).
  Multi-image GALLERY posts (whose RSS content carries **no** image links —
  verified in the 2026-09-15 workflow log) get a best-effort post-page
  harvest from the redlib fallback instances, probed in parallel (~10s worst
  case; if every instance fails, the single-thumbnail card is kept —
  FULL MODE with an OAuth app is the definitive gallery source). Renditions:
  `i.redd.it` full-res swap for jpg/jpeg, largest signed preview URL for
  PNGs — the 140px feed thumb is no longer used.
* **Clean body text.** Stray `redd.it` image URLs that used to linger in the
  body are stripped (they belong in the media gallery).
* **Video = video only.** Posts with a reddit video (or a YouTube link) show
  the video tile only — the duplicate first-frame / `external-preview.redd.it`
  screenshot is dropped.
* **Native video chain (no key, no proxy first).** `fallback_url` (FULL MODE)
  → `v.redd.it/<id>/DASH_<q>.mp4` (self-contained mp4 **with audio**, straight
  from Reddit, no signature, no expiry — tried 720→1080→480→360) → the
  embedez/vxreddit CMAF muxing proxies as last resort. The signed
  `packaged-media.redd.it` DASH master links are **not** used (they expire in
  hours — the `e=…` param).
* **YouTube (default: thumb + button).** The `YOUTUBE_MEDIA_EMBED` playback
  attempt (seaof.glass) is **off by default** — it adds up to ~3 min of
  per-post probe time and third-party flakiness. Default behavior: best
  available `i.ytimg.com` thumbnail in the gallery + the animated
  `starwardspark3` **YouTube** button. Set `YOUTUBE_MEDIA_EMBED=1` to re-enable
  playback attempts (still degrades to thumb+button automatically).
* **💬 OP comment (FULL MODE).** The stickied/top top-level comment by the
  post author is fetched with the post JSON and shown as a capped (500 char)
  line with a *full comment* link. `REDDIT_OP_COMMENT=0` disables.
* **4000-char budget.** Header + body + OP line + stats are budgeted so the
  card never exceeds Discord's total text limit (body is auto-trimmed last).
* **Discohook preview.** After each successful post, a keyless public share
  link rendering the exact card is created and logged (see
  [Discohook](#-discohook-integration-round-12) below). `DISCOHOOK_PREVIEW=0`
  disables.
* **Test tools (verify before promoting).** In the V3 workflow
  (`workflow_dispatch`):
  * **`test_post`** input = `<subreddit>/<post_id>` (e.g. `AnantaLeaks/1wgvcz7`)
    rebuilds exactly that post (bypasses feed + dedup). Data source: the post
    JSON when reachable (FULL MODE); otherwise the post's RSS feed entry
    (100-entry window) or a redlib post page (round 12c — works in native
    mode too).
  * **`dry_run: yes`** builds + logs the full payloads **without** posting to
    Discord or saving the cache. Use both together to re-test the exact posts
    that were wrong without spammng the channel.
* **Environment switches** (all optional — sane defaults without them):
  `YOUTUBE_MEDIA_EMBED` (default off), `REDDIT_OP_COMMENT` (default on),
  `DISCOHOOK_PREVIEW` (default on), `FEEDTOKEN_JSON_STAGGER` (default 65 s).

### 🆕 Reddit V3 — round 13 (2026-09-16): proxy media services

Native-mode card media now comes from the **public proxy services** before
falling back to RSS — same services you tested by hand (all keyless, no
credits, no API key):

| Priority | Service | What the bot reads from it | Video audio |
|---|---|---|---|
| 1 | **redditez.com** (EmbedEZ) | keyless `search` API → stable key → bot embed page og: tags (photos as embedez media URLs, title/body/stats) | ✅ (playable mp4) |
| 2 | **vxreddit.com** | bot embed page og: tags — every gallery photo as **full-res `i.redd.it`**, stats in `og:site_name` | ✅ (muxed `redditvideo.mp4`) |
| 3 | **embeddit.deltandy.me** | Mastodon-style JSON API — **ALL gallery photos (20)**, body, stats, author | ✅ under ~50 MB (merged mp4) |

* **Fallback chain (your spec):** redditez first; if it's down, or if its
  page shows *"Failed to Get Post | EmbedEZ — Reddit returned a non-JSON
  response"* (that message means the EmbedEZ backend behind redditez —
  which fetches the post from Reddit for us — is down or unavailable at
  that moment; a service-side failure, not a problem with the post), the
  post falls through to **vxreddit**, then **embeddit** — the two most
  uptime-reliable. Detected per post, not just at warm-up. Their own
  URLs are mixed into the components-v2 card verbatim (Discord fetches each
  media URL itself).
* **Warm-up link test (your spec):** every run first probes all three with
  one known post (default `HonkaiStarRail_leaks/1whbjbh`, override
  `PROXY_WARMUP_POST`) and writes **`proxy_health.json`** (auto-committed).
  Dead services are skipped for the run; if ALL three are dead, every
  service is retried per post. Log lines: `[proxy warm-up] <service>: OK/DOWN`.
* **Then the old native path:** if no service can serve a post, the round-12
  RSS media path runs unchanged (RSS media → redlib harvest → thumbnail).
  `PROXY_MEDIA=0` disables the proxy path entirely. **FULL MODE** (OAuth
  app) and test posts are unaffected — proxies also make any-age test posts
  work when the post JSON 403s.
* **Videos are range-checked** before use (muxed mp4 with audio); if the
  proxy video URL dies, the native `v.redd.it` DASH chain (with audio) runs
  instead. Video posts still show **video only** (no duplicate poster).
* **20-photo galleries = 2 containers** (10 media items each) — unchanged;
  **crossposts** keep working (the proxy returns the crosspost's own
  content; FULL MODE still fetches the original post).
* **YouTube second message (your spec):** after the card lands, the bot
  posts a **second plain message containing only the YouTube link** (Discord
  shows the official preview — no buttons, nothing else). The card's own
  YouTube thumbnail + animated `starwardspark3` button stay.
  `YOUTUBE_LINK_MESSAGE=0` disables the second message.
* **New switches** (repo Variables, all optional): `PROXY_MEDIA` (on),
  `PROXY_WARMUP_POST` (`HonkaiStarRail_leaks/1whbjbh`),
  `YOUTUBE_LINK_MESSAGE` (on), `EMBEDDIT_INSTANCE` (self-hosted override).
* **`EMBEDEZ_API_KEY` is no longer used by V3** (the keyless public
  endpoints replaced the paid API) — the repo secret can be deleted; only
  the old V2 script needs it.
* **Docs added:** [`docs/DISCOHOOK.md`](docs/DISCOHOOK.md) (Discohook =
  preview-only here, **fully optional**, safe to disable — and why it isn't
  relied on for posting) and [`docs/CI_SMOKE.md`](docs/CI_SMOKE.md)
  (ci.yml + test_smoke.py = the **required** offline safety gate).

### 🆕 Reddit V3 — round 14 (2026-09-16): card polishing (after the first production runs)

* **Complete galleries incl. GIFs:** the redlib post-page harvest now runs
  **in parallel with the proxy fetch**, and for image posts the complete
  ordered redlib list **wins over the proxy's og: list** — the redditez og:
  tags omit GIFs (a 3-photo + 3-GIF post showed only the 3 photos before).
  Video posts skip the harvest (their DASH chain handles them); when every
  proxy is down the redlib list is still used. No extra time in normal runs
  (the fetches run at the same time).
* **No duplicate gallery items:** the redditez/vxreddit embed pages append
  extra `og:image` tags (the post's "main image", a 140px feed crop, or the
  same photo under a second CDN name). `dedupe_proxy_media` (in
  `testing area/reddit_proxy.py`) drops: the same redd.it **file id**
  (slug/`vN-` variants count as the same file), `width=140`/`crop=1:1`
  crops, and the ONE trailing tag when a page emits N real media + 1 extra.
* **Body text like the redditez card:** every link in the body is now a
  clickable markdown link `[text](url)`, `**bold**` and paragraph breaks are
  kept, and **bare redd.it media URLs are removed from the text** (the media
  already sits in the gallery — fixes the glued
  `…&s=…dc0Seems like the…` text). The og: content values are unescaped
  until stable (fixes `&amp;amp;` in URLs).
* **Crossposts keep working:** the crosspost notice in the RSS content
  ("u/x crossposted this from r/Y — original post") is detected, and the
  media + stats are fetched **from the ORIGINAL post** (a crosspost's own
  pages carry no media — the run-2 crosspost degraded to a plain image
  because vxreddit doesn't resolve crossposts). The card keeps the
  crosspost URL and the "🔁 Crosspost of" line, as before.
* **Missing stats on redditez cards:** the redditez og: page often has no
  stats line (the stats live in the oembed, not the og: tags) — when the
  winning proxy has no stats the bot backfills 💬/👍 from the **Embeddit
  JSON** (one extra request, ~1 s, no bot gate).
* **Embeddit plain-text shape handled:** posts without selftext arrive
  unmarked-up ("Title⬆️ 1.1K • 💬 108" glued on one line, no `<a><b>`
  title) — the parser now handles both shapes and compact numbers
  (`1.1K` → 1100).

### 🆕 Reddit V3 — round 17 (2026-09-17): Arctic Shift search backup

* **Subreddits with NO new RSS posts are re-checked against the Arctic
  Shift archive search API** (`/api/posts/search?subreddit=<sub>&sort=desc
  &md2html=true`, limited to the 48-hour window) — the same post JSON shape
  the crosspost-original lookup already uses. This covers what RSS can't:
  a sub missing from the combined 100-entry feed, per-sub feeds dead or
  bot-walled, or a quiet sub that simply didn't surface.
* **Same pipeline, same guarantees:** archive posts are wrapped as
  feedparser-style entries and run through the SAME `collect()` — the
  dedup cache and the 48h freshness window still apply, so nothing can be
  double-posted. Crossposts found in the archive still get the original
  post's media/stats via the existing crosspost path.
* **Never blocks posting:** the search runs only for subs RSS left empty,
  returns `[]` on any failure (429/timeout/bad shape), and shares the
  existing 3-strike circuit breaker with the crosspost archive lookup.
  First run posts at most one archive post per sub (same anti-flood rule as
  RSS). Log line: `[arctic <sub>] RSS had no new posts — trying N post(s)
  from the archive.`
* Note: Arctic's score/comment counts are stale for ~36 h after a post —
  archive-sourced cards don't present those as live stats (same rule as the
  existing crosspost-original path).
* **Round 18 follow-up (same day, from the live run):** the archive also
  carries posts the moderators soft-removed or the author deleted (a
  removal-notice body instead of content). Those are now detected and
  skipped — not posted and not cached — so they post normally once
  approved.
* **Round 19 follow-up (same day, from the live run — post 1whe2tr):**
  the feed's auto-linker mangled "label line + bare URL" bodies
  (`Firefly video` / `https://b23.tv/…` pairs) into nested `[[U](U)…](U](U)…`
  garbage. A new pre-pass in BOTH body cleaners (RSS + proxy) repairs the
  family to one label line + one clickable URL line per pair (the X-card
  look); nothing else in the body pipeline changed.

### 🧪 Reddit V3 — final testing & verification procedure (round 12)

**Step 0 — one-time: archive the OLD Reddit V1/V2 workflow.**
In the **Actions** tab, open the workflow named **"Reddit Feed Monitor"**
(the old V1 one, `reddit_monitor.yml`) → its three-dot menu →
**Archive workflow**. It targets the same test channels and the same
`posted_reddit.json` dedup cache as V3, so every time GitHub's native cron
fires it, it would post the same new post in the OLD plain style and
"steal" it from V3. (Your external cron-job.org trigger should point at
**"Reddit Feed V3 Monitor"** — the V3 one — not this one.)

Everything is triggered from the repo's **Actions** tab → workflow
**"Reddit Feed V3 Monitor"** → the **Run workflow** button (branch `main`).

**Step 1 — Dry run (safety check; nothing is posted)**

1. Set `dry_run` = **yes**, leave `test_post` **empty** → **Run workflow**.
2. Wait 1–3 minutes and open the run log. It lists every post it *would*
   post, each with its complete card payload. **Discord is NOT touched and
   the cache is NOT saved — that is the whole point of the dry run**
   (a "DRY RUN finished" run intentionally sends nothing).
3. Key lines to see: `Combined feed OK: …`, per post `post JSON …`
   (full or native mode), `video url OK via …` / `gallery via redlib (…)`,
   and `DRY RUN (Discord NOT touched): …` per post.
4. The post the dry run listed will be posted by the **next normal cron run**
   (the dry run doesn't mark it as posted).

**Step 2 — Test posts (re-post specific old posts into the test channel)**

Run the workflow with `dry_run` = **no** and `test_post` =
`<Subreddit>/<post_id>` (one at a time), e.g.:

| `test_post` value | Post type | What to expect in the channel |
|---|---|---|
| `AnantaLeaks/1wguffh` | 3-photo gallery | **all 3 photos**, full-res, never one 140px thumb |
| `AnantaLeaks/1wgq3cy` | YouTube link post | **video only** + the animated YouTube button — no screenshot |
| `HonkaiStarRail_leaks/1wguwvw` | Reddit video | **video tile only** — no duplicate first-frame image |

The log tells you the data source: `post JSON OK via …` (FULL MODE) or
`test post found in the RSS feed` / `test post base via redlib (…)`.

**Step 3 — Normal runs (the real verification)**

Do nothing — the scheduled runs post new posts with the new card. In the test
channel check:

* multi-photo posts → **all** photos (never a single 140px thumbnail)
* video posts → **video tile only** (no duplicate screenshot)
* no raw `redd.it` URLs lingering in the body text
* log: **no** `seaof.glass` lines at all (off by default); if you ever see
  `video url OK via native v.redd.it DASH_720 (…)`, play that video and
  confirm it has **audio** (if it plays silent, report it — the ladder is
  dropped with a one-line change)

**Step 4 — Promotion (only after the test channel looks right)**

1. Copy `testing area/reddit_main_v3test.py` to the repo root as
   `reddit_main_v3.py`.
2. In `.github/workflows/reddit_monitor_v3.yml`, change the run line to
   `python "reddit_main_v3.py"`.
3. Commit. V1/V2 files stay untouched (the promotion path is documented in
   the yml comments).

### Secrets

| Secret | Value |
|---|---|
| `SUBREDDITS` | Comma-separated subreddit names, e.g. `Zenlesszonezeroleaks_,Genshin_Impact_Leaks,HonkaiStarRail_leaks,WutheringWavesLeaks,HonkaiNexusAnimaLeaks,AnantaLeaks` |
| `WEBHOOK_REDDIT_<SUB>` | One per subreddit's channel (rule: `WEBHOOK_REDDIT_` + UPPERCASE name, non-alphanumerics → `_`). For the default six: `WEBHOOK_REDDIT_ZENLESSZONEZEROLEAKS_`, `WEBHOOK_REDDIT_GENSHIN_IMPACT_LEAKS`, `WEBHOOK_REDDIT_HONKAISTARRAIL_LEAKS`, `WEBHOOK_REDDIT_WUTHERINGWAVESLEAKS`, `WEBHOOK_REDDIT_HONKAINEXUSANIMALEAKS`, `WEBHOOK_REDDIT_ANANTALEAKS` |
| `REDDIT_FEED_TOKEN` *(optional — **recommended**)* | Your personal Reddit **feed token** (round 9): old.reddit.com → your username → **Preferences** (or `old.reddit.com/prefs/feeds`) → any feed link ends with `?feed=<token>` — copy just the token. Moves RSS requests to the logged-in rate tier, making multi-sub monitoring bulletproof. See the round-9 section below. |
| `REDDIT_MIRROR` *(optional — set as a repo **Variable**, not a Secret)* | **V1 only.** Embed mirror host: `redditez.com` (default), `embeddit.deltandy.me`, or `vxreddit.com` |
| `EMBEDEZ_API_KEY` | **V2 only** — from your embedez.com dashboard |
| `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` *(optional — V3)* | Reddit **script app** (reddit.com/prefs/apps → type "script" → redirect `http://localhost`). Enables V3 **FULL MODE** reliably (all photos, stats, OP comment, true crosspost embeds) via OAuth. 2026 note: new API access may require Reddit's approval form — V3 works without it (feed-token `.json` attempt, then native mode). |
| `DISCORD_WEBHOOK_URL` *(optional)* | Catch-all fallback |

**Optional V3 switches** (repo **Variables**, not Secrets — behavior is fine
with none of them set):

| Variable | Default | Meaning |
|---|---|---|
| `YOUTUBE_MEDIA_EMBED` | off | `1` = also try to *play* YouTube links (seaof.glass, +up to ~3 min probes/post); off = thumbnail + `starwardspark3` button |
| `REDDIT_OP_COMMENT` | on | `0` = hide the 💬 OP comment line (FULL MODE) |
| `DISCOHOOK_PREVIEW` | on | `0` = don't create/log the per-card Discohook share-link preview |
| `FEEDTOKEN_JSON_STAGGER` | `65` | seconds between feed-token `.json` attempts (lower only if your token reliably works there) |

### The workflow (`.github/workflows/reddit_monitor.yml`)

```yaml
name: Reddit Feed Monitor

on:
  schedule:
    - cron: '*/10 * * * *'
  workflow_dispatch:

permissions:
  contents: write

jobs:
  check-reddit:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run Reddit Feed Monitor
        env:
          SUBREDDITS: ${{ secrets.SUBREDDITS }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
          EMBEDEZ_API_KEY: ${{ secrets.EMBEDEZ_API_KEY }}
          REDDIT_FEED_TOKEN: ${{ secrets.REDDIT_FEED_TOKEN }}   # optional (recommended) — your feed token
          WEBHOOK_REDDIT_ZENLESSZONEZEROLEAKS_: ${{ secrets.WEBHOOK_REDDIT_ZENLESSZONEZEROLEAKS_ }}
          WEBHOOK_REDDIT_GENSHIN_IMPACT_LEAKS: ${{ secrets.WEBHOOK_REDDIT_GENSHIN_IMPACT_LEAKS }}
          WEBHOOK_REDDIT_HONKAISTARRAIL_LEAKS: ${{ secrets.WEBHOOK_REDDIT_HONKAISTARRAIL_LEAKS }}
          WEBHOOK_REDDIT_WUTHERINGWAVESLEAKS: ${{ secrets.WEBHOOK_REDDIT_WUTHERINGWAVESLEAKS }}
          WEBHOOK_REDDIT_HONKAINEXUSANIMALEAKS: ${{ secrets.WEBHOOK_REDDIT_HONKAINEXUSANIMALEAKS }}
          WEBHOOK_REDDIT_ANANTALEAKS: ${{ secrets.WEBHOOK_REDDIT_ANANTALEAKS }}
          REDDIT_MIRROR: ${{ vars.REDDIT_MIRROR }}   # optional (V1): blank/omitted = redditez.com
        # While testing a new version, point this line at the test copy instead
        # (QUOTES REQUIRED — the folder name has a space):
        #   run: python "testing area/reddit_maintest.py"
        run: python reddit_main.py   # ← switch to reddit_main_v2.py for the rich card

      - name: Commit and push updated posted_reddit.json cache
        run: |
          git config --local user.email "github-actions[bot]@users.noreply.github.com"
          git config --local user.name "github-actions[bot]"
          git add -f posted_reddit.json
          git diff --quiet && git diff --staged --quiet || (git commit -m "auto: update posted_reddit.json cache" && git push)
```

Create `posted_reddit.json` with `[]` as its initial content (first run posts only the newest item,
by design).

## 🆕 Reddit behaviors (2026-09-11 update)

* **Buttons were trimmed.** The Embeddit and vxReddit mirror buttons are **gone** (see concerns §6),
  and *Read Post* now points to the **original `https://www.reddit.com/...` permalink** — not the
  redditez mirror. Mirrors stay credited at the top of this README.
* **Switching the V1 embed mirror (redditez ⇄ Embeddit  vxReddit).** By default V1 posts the
  redditez link (plain reddit links don't unfurl richly via plain webhooks). All three mirrors
  accept the **same** `/r/<sub>/comments/…` path format and were verified live (2026-09-12) to
  serve embed meta to Discordbot, so switching is pure configuration — no code edit:
  1. Repo → **Settings → Secrets and variables → Actions → *Variables* tab** → new variable
     **`REDDIT_MIRROR`** = `embeddit.deltandy.me` or `vxreddit.com` (full `https://…/` URLs are
     tolerated; they're normalized down to the host).
  2. In `reddit_monitor.yml` make sure the env block contains
     `REDDIT_MIRROR: ${{ vars.REDDIT_MIRROR }}` (it already does in the sample above).
  3. Next run uses the new mirror. Switch back anytime by setting the variable to `redditez.com`
     (or deleting it).
  **Reddit V2 needs nothing** — it fetches post data from the EmbedEZ API and builds its own
  Components V2 card, so no mirror is involved at all.
* **YouTube posts get a playable embed (V1).** If the thread body links to YouTube (`watch?`,
  `shorts/` or `youtu.be`), the bare YouTube URL is appended on its own line after the redditez
  link — verified to auto-embed a working YouTube player alongside the reddit embed. A conditional
  **▶️ YouTube button** is also added. On V2 the URL appears as a clickable line plus the same
  button (Components V2 messages cannot auto-unfurl links — Discord limitation).
* **Pending-approval / mod-queue posts are never left out.** Subreddits with a moderator queue only
  publish posts to the `new` RSS listing **when approved** — sometimes hours or a day later. Two
  safeguards cover this: the freshness window was widened from 3h to **48h** (`MAX_AGE_SECONDS`), and
  the age check uses the RSS *updated* timestamp whenever it's newer than *published* (an approval
  bumps `updated`). A thread approved "tomorrow" still arrives. If your subs regularly take longer
  than 48h to approve, raise `MAX_AGE_SECONDS` near the top of the script.
* **Reddit V2 fixes** — all EmbedEZ text fields are now HTML-sanitized (their authorized
  `content.title` itself contains raw `<a>`/`<br>`
  tags, which previously rendered literally), and
  the stats line ends with a 🕐 `<t:…:f>` timestamp (from EmbedEZ `postedDate`, falling back to the
  RSS date).

## ⚠️ Reddit V2 (Components V2) — concerns you should know

The V2 script was rebuilt against the **currently documented** EmbedEZ API, but please read these
points before relying on it:

1. **The API key is not fully free.** The embedez dashboard shows a *credits* balance (fresh accounts
   start around 100 credits; more requires payment, and payments "may take up to 5 minutes to
   process"). **Every new post costs 2 API calls** (one `search` + one `preview`). If you don't want
   to spend credits, just use **Reddit V1** — it needs no key at all.
2. **Documented two-step flow.** V2 uses only the endpoints in the current OpenAPI docs:
   `GET /api/v1/providers/search?url=…` → returns a `key`, then
   `GET /api/v1/providers/preview?search_key=…` with header `Authorization: Bearer <ez_key>`.
   The older unofficial `/providers/combined?q=` endpoint from early docs is **no longer documented**
   and is not used.
3. **Graceful no-key fallback.** Without a valid key, the preview endpoint still returns *public* data
   (author, title, one thumbnail). V2 detects that and posts a **limited card** with a small
   `ℹ️ Limited preview` note instead of skipping the post.
4. **Defensive field parsing.** Media URLs are read from `media[].url` **or** the legacy
   `media[].source.url` shape; HTML in preview titles is stripped automatically. Even so —
5. **EmbedEZ warns the API may break.** Their docs explicitly say *"large changes will be made to the
   API in the future, and these might break the current API."* If posts suddenly fail, read the Actions
   log — it prints the exact API response — and check their release notes/docs for field renames.
6. **The Embeddit / vxReddit buttons were removed (2026-09-11).** A true
   "click to switch embed mirror" rotation is impossible via webhooks — interactive buttons need a
   24/7 bot process answering Discord interactions, incompatible with this stateless design — and the
   always-visible duplicate mirror buttons added clutter without value. The mirrors remain fully
   credited at the top of this README.
7. **HTML is stripped from every text field.** With a valid API key, EmbedEZ's `content.title` itself
   contains HTML (`Posted in <a …>r/sub</a>
…`) — earlier builds rendered those tags literally in
   the Discord card. All title/description/text fields (authorized *and* public-preview) are
   sanitized now.
8. **Components V2 can't auto-unfurl a bare YouTube link** inside a card (the auto-embed player is a
   V1 behavior Discord only applies to regular message content). V2 therefore shows the YouTube URL
   as a clickable line plus a ▶️ YouTube button; if you want the playable inline player, use
   **Reddit V1**.

## 🔧 Reddit V1 fix (2026-09-11) — why the first run failed

Your first V1 test logged `Could not fetch valid RSS feed for r/*** from any instance.` The cause was
verified live:

| Source (in code order) | Result |
|---|---|
| `redlib.perennialte.ch` | **HTTP 403** — Cloudflare "Just a moment…" challenge |
| `old.reddit.com` | HTTP 200 but an **HTML "Welcome to Reddit" interstitial**, zero RSS entries |
| `www.reddit.com` | ✅ **real Atom feed, 25 entries** — but it wasn't in the source list! |

`reddit_main.py` (and V2) now:
* try **`https://www.reddit.com/r/<sub>/new/.rss` first**, with `old.reddit.com` and redlib as fallbacks;
* **validate** the response actually contains `/comments/` permalinks before accepting it (old.reddit's
  HTML page is now properly rejected);
* **log exactly why each source was skipped**, so future breakage is diagnosable from the Actions log.

If `www.reddit.com` ever starts blocking GitHub's datacenter IPs for you, open the Actions log —
you'll see the per-source reasons — and just reorder/replace entries in `REDDIT_RSS_INSTANCES`.

### 🆕 2026-09-12 — dead Redlib instance + HTTP 429 fixes (all subreddits at once)

With all six subreddits monitored simultaneously, two live issues surfaced:

| Problem | What the Actions log showed |
|---|---|
| `redlib.perennialte.ch` **shut down** (31 Aug 2026 — "long-term unreliability") | `[https://redlib.perennialte.ch] HTTP 410 for r/… — trying next source.` |
| `www.reddit.com` **rate-limits parallel fetches** (six subs hit in the same second) | `[https://www.reddit.com] HTTP 429 for r/… — trying next source.` for most subs; only one or two got through |

Both Reddit scripts now:
* **retry once on HTTP 429** after `RATE_LIMIT_RETRY_DELAY` (6s) before falling through to the
  next source;
* **stagger the fetch starts** by `FEED_FETCH_STAGGER` (1.2s between subreddits) so the six feeds
  no longer fire simultaneously;
* use a **fresh Redlib fallback chain** from the official instance list (checked 2026-09-12):
  `safereddit.com` → `red.artemislena.eu` → `redlib.privacyredirect.com` → `redlib.privadency.com`
  → `redlib.nadeko.net` → `redlib.ducks.party` → `redlib.catsarch.com` → `snoo.habedieeh.re`
  (note: `safereddit.com` filters NSFW — harmless as a fallback for these subs).

A missed run loses nothing: the 48-hour window still catches any post on a later run. If Reddit
ever blocks GitHub's datacenter IPs more aggressively, or a Redlib instance dies, the Actions log
shows exactly which source answered what — just reorder/replace entries in `REDDIT_RSS_INSTANCES`
(identical list in both Reddit scripts).

### 🆕 2026-09-13 — round 9: one combined RSS request + feed token + verified mirrors

Live testing on 2026-09-13 confirmed how strict Reddit's datacenter rate limiting has become
(anonymous RSS ≈ **1 request/minute per IP** since June 2026 — a burst of 7 requests 429'd
entirely; one request 65s later succeeded), and that **every public Redlib/Eddrit mirror is now
bot-walled** (every official registry instance was probed: Anubis "Verifying your browser…"
challenges, 418 bot-checks, Cloudflare 403s, 404s, dead SSL). So round 9 does three things:

1. **ONE combined feed request per run (the big fix).** Reddit joins subreddits with `+` in one
   URL, and it's verified live that this works with the `?limit=100` parameter (default 25, max 100):
   ```
   https://www.reddit.com/r/Zenlesszonezeroleaks_+Genshin_Impact_Leaks+HonkaiStarRail_leaks+WutheringWavesLeaks+HonkaiNexusAnimaLeaks+AnantaLeaks/new.rss?limit=100
   ```
   → **200, real Atom, ~190 KB, posts from all active subs in a SINGLE request.** One request per
   run fits inside the ~1/min anonymous limit by itself. Each entry's permalink still names its
   subreddit, so **per-channel webhook routing is unchanged** (and the existing
   `posted_reddit.json` dedup keys still match). If the combined feed ever fails, the script
   **automatically falls back** to the old per-subreddit fetches (instance rotation + retries).
2. **`REDDIT_FEED_TOKEN` (repo secret — recommended, optional).** Your personal feed token:
   1. Log in at **old.reddit.com** → click your username → **Preferences** (or open
      `https://old.reddit.com/prefs/feeds`).
   2. Any feed link on that page ends with `?feed=<token>` — copy just the token value.
   3. Add it as the secret **`REDDIT_FEED_TOKEN`** (Settings → Secrets and variables → Actions).
      The script appends `&feed=<token>` to native reddit.com requests, moving them to the
      logged-in rate tier — 429s should then essentially stop. (Don't paste the token in chat;
      treat it like a password.)
3. **Fallback mode hardened.** Per-subreddit fallback now retries 429s **twice** (after 6s *and*
   after 45s — the 45s wait rides out the ~1-minute anonymous window refill), and the fallback
   instance list was trimmed to the 5 sources that at least respond
   (`www.reddit.com`, `old.reddit.com`, `safereddit.com`, `red.artemislena.eu`,
   `redlib.privacyredirect.com`). The dead/404/418 instances were dropped; all remaining Redlib
   entries are verified-behind-bot-check "lottery tickets" only. Refresh candidates anytime at
   [redlib-instances](https://github.com/redlib-org/redlib-instances).

**Expected Actions log (round 9, with token):** `Fetching combined feed for 6 subreddits in 1
request...` → `Combined feed OK: NN entries covering N subreddit(s).` → posts per channel.

**X side: no changes.** The `RSS_INSTANCES` Nitter list in all `main*.py` files was retested
2026-09-13 and intentionally left exactly as the original repo's (`nitter.perennialte.ch` has the
best GitHub-runner track record; the rest are fallbacks).

---

## 🔗 Discohook integration (round 12)

[Discohook](https://discohook.app) is a free, public Components-V2 message
designer/previewer. V3 uses its **keyless public API** (`POST
https://discohook.app/api/v1/share`): after each successful Discord post it
creates a **share link that renders the exact card** and logs the URL in the
workflow run (`Discohook preview for <key>: https://discohook.app/?share=…`).
That's a fast way to verify a card in the browser while reviewing the log
before promoting a version.

* **No key, no account, no webhook execution** — Discohook's public API has no
  authenticated "send" endpoint (they plan one), so the monitor still posts
  straight to your Discord webhooks; Discohook is preview-only here.
* **Privacy:** the share payload contains only the public card content.
  **No `targets` are sent, so your webhook URL never leaves the repo.** Links
  are public while alive (7-day TTL; share IDs are reused after expiry), so
  don't pin them permanently.
* Disable with `DISCOHOOK_PREVIEW=0`; the share call is best-effort — if
  Discohook is down, the post still goes out and only the preview is skipped.
* Also available (not wired into the monitor): the `/unfurl?url=…` endpoint
  (a re-implementation of Discord's link scraper — handy for debugging how a
  bare URL would embed) and the `discohook.app` website itself for designing
  cards by hand.

## 🤖 Dependabot — automatic dependency updates (optional, free)

This repo ships a ready-made, safe Dependabot setup:

| File | Role |
|---|---|
| `.github/dependabot.yml` | The switch: weekly **pull requests** for `requirements.txt` (pip) + `.github/workflows` (GitHub Actions). **Delete this file to disable — the monitor is unaffected.** |
| `.github/workflows/ci.yml` | The safety gate: every PR (including Dependabot's) must pass `pip install` + `compileall` + `tests/test_smoke.py` before it can be merged. |
| `.github/workflows/dependabot_auto_merge.yml` | **Opt-in** auto-merge of Dependabot PRs once all checks are green. Disabled until you set the repo variable `AUTO_MERGE_DEPENDABOT=yes`. |
| `docs/DEPENDABOT.md` | The **full explanation**: what it is, what it does, what it never does, whether it's optional (yes, 100%), costs/limits, and both ways to enable auto-merge. |

**Short version:** Dependabot is free, built into GitHub, needs no token, and
**only opens PRs — it never touches `main` until you merge** (or explicitly
enable the gated auto-merge). Your monitor keeps running exactly as before in
the meantime.

---

# 🛠 Full Setup Guide

## Step 0 — Make the repo your own (**do NOT fork**)

Forked repos get Actions/schedules disabled and auto-disabled again after ~60 days of inactivity —
your bot would silently stop. Instead:

1. On the source repo: **Code → Download ZIP**, then unzip locally.
2. Create a **brand-new empty repository** on your GitHub account.
3. Click *"uploading an existing file"* and drag in **all** files — including the hidden `.github`
   folder (enable *show hidden files* in your file explorer first!).
4. Commit. Since it's a fresh, non-fork repo, workflow **read/write** permissions work out of the box
   (verify at *Settings → Actions → General → Workflow permissions → Read and write*).

## Step 1 — Create Discord webhooks (one per channel)

For each target channel: *Channel Settings → Integrations → Webhooks → New Webhook → Copy URL.*

## Step 2 — Add repository secrets

*Repo → Settings → Secrets and variables → Actions → New repository secret*, then add the ones you
need from the X and Reddit tables above (`ACCOUNTS`, `WEBHOOK_<ACCOUNT>` per account, `SUBREDDITS`,
`WEBHOOK_REDDIT_<SUB>` per subreddit, `EMBEDEZ_API_KEY` only if using Reddit V2, optional
`DISCORD_WEBHOOK_URL` fallback, and **recommended** `REDDIT_FEED_TOKEN` — see the round-9 section
for the 2-minute how-to).

Then, if you use the V1 embed mirror switch, create the repo **Variable** `REDDIT_MIRROR`
(Variables tab, not Secrets).

## Step 3 — Reset the caches for a fresh start

Edit `posted_tweets.json` and `posted_reddit.json` to contain just:

```json
[]
```

On the first run the bots post only the **single newest item** per account/subreddit (by design — no
channel flooding).

## Step 4 — Reliable 10-minute automation (external trigger)

GitHub's built-in `schedule:` can lag 15–60 min or skip runs under load, so we replicate the original
author's "Manually run by …" pattern with a free external cron:

1. **Create a PAT:** GitHub → *Settings → Developer settings → Personal access tokens (classic) →
   Generate new token* → check **`workflow`** (and `repo` if private) → copy it.
2. Sign up at [cron-job.org](https://cron-job.org) (free) and create a job **per workflow**:
   * **URL:**
     `https://api.github.com/repos/<YOU>/<REPO>/actions/workflows/twitter_monitor.yml/dispatches`
     (and a second job for `reddit_monitor.yml`)
   * **Method:** `POST` · **Crontab:** `*/10 * * * *`
   * **Headers:**
     | Key | Value |
     |---|---|
     | `Authorization` | `token <YOUR_PAT>` |
     | `Accept` | `application/vnd.github+json` |
     | `Content-Type` | `application/json` |
     | `X-GitHub-Api-Version` | `2026-03-10` *(optional, future-proof)* |
   * **Body:** `{"ref":"main"}` (match your default branch name)
3. **Perform test run** → expect `204 No Content` (or `200 OK`), then check the Actions tab for a run
   labeled *Manually run by you*. `401` = bad token/scope; `404` = wrong repo/workflow/branch name.

Keep the in-file `schedule:` cron as a harmless backup — occasional extra *Scheduled* runs are fine.

## Step 5 — Test end-to-end

*Actions → select the workflow → Run workflow*, then check: the right Discord channels got the right
posts, buttons render, and the cache file shows a new `github-actions[bot]` commit.

For any **new or updated script**, test it from the `testing area/` folder first — see the
[Testing area guide](#-testing-area--how-updates-are-tested-before-going-live) above.

## (Optional) Render Cron instead of GitHub Actions

Create a **Cron Job** on Render: build `pip install -r requirements.txt`, command
`python main.py` (or any other engine file), schedule `*/10 * * * *`, and add the same env vars there.

---

## 💻 Local Testing

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your values
```

`.env` example:

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
ACCOUNTS=TYPEII_EN,PomPom_HonkaiSR,Wuthering_Waves,HonkaiNA,Ananta_EN
WEBHOOK_TYPEII_EN=https://discord.com/api/webhooks/...
WEBHOOK_POMPOM_HONKAISR=https://discord.com/api/webhooks/...
WEBHOOK_WUTHERING_WAVES=https://discord.com/api/webhooks/...
WEBHOOK_HONKAINA=https://discord.com/api/webhooks/...
WEBHOOK_ANANTA_EN=https://discord.com/api/webhooks/...
SUBREDDITS=Zenlesszonezeroleaks_,Genshin_Impact_Leaks,HonkaiStarRail_leaks,WutheringWavesLeaks,HonkaiNexusAnimaLeaks,AnantaLeaks
WEBHOOK_REDDIT_ZENLESSZONEZEROLEAKS_=https://discord.com/api/webhooks/...
WEBHOOK_REDDIT_GENSHIN_IMPACT_LEAKS=https://discord.com/api/webhooks/...
WEBHOOK_REDDIT_HONKAISTARRAIL_LEAKS=https://discord.com/api/webhooks/...
WEBHOOK_REDDIT_WUTHERINGWAVESLEAKS=https://discord.com/api/webhooks/...
WEBHOOK_REDDIT_HONKAINEXUSANIMALEAKS=https://discord.com/api/webhooks/...
WEBHOOK_REDDIT_ANANTALEAKS=https://discord.com/api/webhooks/...
REDDIT_MIRROR=redditez.com   # optional, V1 only: embeddit.deltandy.me | vxreddit.com
EMBEDEZ_API_KEY=ez_...       # Reddit V2 only
REDDIT_FEED_TOKEN=           # optional (recommended) — old.reddit.com/prefs/feeds, the ?feed= value
```

Then run any engine: `python main.py` / `python main_v2.py` / `python main_v3.py` /
`python reddit_main.py` / `python reddit_main_v2.py`.

> When a script sits in `testing area/`, quote the path (the space):
> `python "testing area/reddit_maintest.py"`.

---

## 🚨 Troubleshooting

* **Buttons don't render.** Every webhook POST must use the query param `?with_components=true` —
  Discord *silently drops* components without it (already handled in all scripts; don't remove it).
  Rich-card versions also set the `IS_COMPONENTS_V2` flag (`1 << 15`).
* **`Could not fetch valid RSS feed for @…` / `r/…`** — public mirrors rotate/die. For X, swap
  `RSS_INSTANCES` with currently-live Nitter mirrors; for Reddit, see the *Reddit V1 fix* section and
  read the new per-source log lines.
* **`HTTP 429 for r/…` lines in a Reddit run** — Reddit's anonymous datacenter rate limit
  (~1 request/minute per IP since June 2026). Round 9 makes the primary fetch a **single combined
  request** for all subreddits, which normally fits the limit; in fallback mode the script retries
  twice (6s, then 45s) before moving on. A subreddit that still ends up "from any instance" loses
  nothing — the 48h window catches it on a later run. **The permanent fix is the
  `REDDIT_FEED_TOKEN` secret** (round-9 section above) — with it, 429s should essentially stop.
* **`ValueError: invalid literal for int() with base 16: 'None'`** — old V3 bug when FxTwitter returns
  `"color": null`; fixed via the `accent_from_color()` helper with a safe Twitter-blue default.
* **`Deprecation` / `Node.js 20 is deprecated` warnings in Actions logs** —
  these appeared while the workflow still pinned old action versions
  (`actions/checkout@v4`, `actions/setup-python@v5`, which run on the
  deprecated Node 20 runtime). Dependabot's github-actions bump to **v7**
  (Node 24 runtime) removed them — see the Node 20→24 FAQ in
  [`docs/DEPENDABOT.md`](docs/DEPENDABOT.md). Cosmetic either way; your
  Python scripts are unaffected.
* **No run at 10-minute marks** — GitHub's native cron is best-effort; that's why the external
  cron-job.org trigger exists. Also note GitHub auto-disables `schedule:` after 60 days of repo
  inactivity — the cache auto-commits usually count as activity, and the external trigger is immune.
* **Reddit V2 posts "Limited preview" cards** — your `EMBEDEZ_API_KEY` is missing/invalid or out of
  credits; add a valid key (and watch the credit balance), or switch to free V1.
* **First run posts only one item per account** — intentional anti-flood behavior; normal backfill
  starts on subsequent runs.
* **A big video shows as a thumbnail / "smaller version" note (X V2/V3)** — intended behavior:
  the file exceeded the verified ~256 MB Discord gallery limit (e.g. 4K or very long videos). The
  card still plays a smaller rendition, or links out to X when even that is too big. Tune
  `VIDEO_SIZE_LIMIT` at the top of the script if Discord's behavior ever changes.
* **A video tile says "image not found" (X V2/V3)** — rare, transient Discord proxy hiccup at fetch
  time (not a URL or size problem — the same URL plays fine when re-posted, verified 2026-09-13).
  The old message can't be repaired, so: delete it → remove that tweet's line from
  `posted_tweets.json` → re-run the workflow (or wait for the next run). Full details in the
  round-10 section. If it ever becomes frequent, set `GALLERY_VIDEO_LIMIT` to a smaller proven size.
* **`Discord error 400 ... {"components": ["0"]}`** — old round-3 bug: a tweet with empty body (or
  over-length text) emitted an invalid empty text component. Fixed in round 4 — text is chunked and
  empty components are never sent. If it ever recurs, the Actions log prints the full Discord
  response next to the tweet ID.
* **A GIF shows as a video player instead of an animated image** — every GIF converter was
  unreachable at post time (the log shows `No GIF converter answered ... keeping mp4 player`), so
  the mp4 was kept as the safe fallback. Round-11 chain: `gif.fxtwitter.com` `.webp` →
  `gifconvert.vxtwitter.com` `.webp` → `gifconvert.vxtwitter.com` `.gif` → **fastgif**
  (offline since 2026-09-17, last probe only); the log names the winner
  (`gif.fxtwitter.com down; using gifconvert for ...`). They recover on their own; nothing to do.
* **A portrait/vertical video loads but won't play right after posting** — this was a transient
  Discord proxy warm-up behavior (the same URLs play fine shortly after, confirmed across services).
  Direct URLs are the default again since round 5. If you ever confirm a *persistent* portrait
  breakage, set `PORTRAIT_PROXY = True` near the top of `main_v2.py`/`main_v3.py` to route vertical
  videos through FxTwitter's embed proxy instead.
* **EmbedEZ suddenly errors after an update** — expected risk (their docs warn of breaking changes);
  the Actions log prints the raw API response to help adjust field names.
* **Combined feed returns "no RSS entries" / `429`** — Reddit's "loading takes a moment" HTML page or
  rate limit. The script rejects non-feed HTML automatically and falls back to per-subreddit fetches;
  adding `REDDIT_FEED_TOKEN` removes the rate-limit cause entirely.

---

## 📄 Final notes

* All engines are independent — mix and match freely (e.g. X on V3, Reddit on V1).
* Legal docs are included: [Privacy Policy](PRIVACY_POLICY.md) · [Terms of Service](TERMS_OF_SERVICE.md)
  (summary: webhook-only and stateless — the bot collects **no** personal data).
* Be nice to the free services this project uses: don't shorten the polling interval below 10 minutes,
  cache stays committed so nothing is fetched/posted twice, and consider donating to Nitter's author.
* All trademarks belong to their respective owners; this project is an unofficial, non-affiliated
  automation tool for personal servers.

---

## 🗒 Changelog

* **2026-09-17 — round 19 (Reddit V3): 'label line + bare URL' link mangle
  repair** (follow-up to the round-18 live run — post 1whe2tr):
  * The feed's auto-linker mangled bodies made of "label line + bare URL
    line" pairs (e.g. `Firefly video` / `https://b23.tv/…` / `Feixiao
    video` / …): it doubled/tripled the opening `[` of the URL-labelled
    link, glued `](U](U))` tail fragments on, and duplicated the next
    label's first word as a dangling `Word](U](U)` line — the card showed
    nested `[[U](U)…](U](U)…` garbage instead of clickable links.
  * A new pre-pass in **both** body cleaners (RSS path and proxy path)
    repairs the family to **one label line + one clickable URL line per
    pair** — the look of the X cards. Every other line shape is
    byte-identical to before; the round-15/16 mangle repairs are
    unchanged.
  * The round-16 smoke check's expected output was updated to this same
    label+URL-line format (it is the same mangle family, now rendered in
    the target layout).
  * Smoke test: 6 new checks (`tests/test_smoke.py` — 214 total).
  * Nothing else changed: the round-18 removal filter, cache, proxies,
    media, FULL MODE, YouTube and crossposts all run exactly as before.

* **2026-09-17 — round 18 (Reddit V3): soft-removed / deleted post filter**
  (follow-up to the round-17 live run):
  * The archive (and occasionally RSS) still carries posts the moderators
    soft-removed or the author deleted, with a removal-notice body —
    `"[deleted]"`, `"[removed]"`, `"**[ Removed by moderator ]**"`,
    `"Sorry, this post has been removed by the moderators of r/…"`,
    `"Sorry, this post was deleted by the person who originally posted
    it"`. These are now detected and **skipped** (round 17's first live
    run posted a few such cards, which had to be deleted from the channels
    manually).
  * Skipped posts are **not added to the dedup cache** — if a post is
    approved later it surfaces again (RSS or archive) and posts normally.
  * Explicit `TEST_POST_ID` rebuilds are unaffected; every skip is logged:
    `[<sub>_<id>] post appears removed/deleted (<reason>) — skipping, not
    cached (will post once approved).`
  * Smoke test: 9 new detection checks (`tests/test_smoke.py` — 208 total).
  * Nothing else changed: RSS, proxies, FULL MODE, YouTube, crossposts and
    the round-17 archive backup all run exactly as before.

* **2026-09-17 — round 11 (X V3) + round 17 (Reddit V3): tweet-data
  fallback chain, GIF chain restructure, Arctic Shift search backup:**
  * **X V3 tweet-data fallback chain** (new `testing area/twitter_proxy.py`):
    **FxEmbed/FxTwitter** (primary) → **fixupx** (same engine, stand-by
    host) → **vxtwitter** (BetterTwitFix API — multi-photo tweets as
    separate photos) → **twitterez** (EmbedEZ bot page — ad lines
    stripped, video posters not duplicated). Every result is normalized to
    the FxTwitter shape, so cards are identical no matter which service
    answered; the winner is logged per tweet. `/en` translation only when
    the data came from FxTwitter.
  * **X V3 GIF chain restructured:** `gif.fxtwitter.com` `.webp` →
    `gifconvert.vxtwitter.com` `.webp` → `.gif` (browser-Referer probe) →
    fastgif (offline 2026-09-17 — last probe, auto-revives if it returns).
    `.avif` intentionally not used (Discord's gallery can't render it).
  * **Reddit V3 Arctic Shift search backup:** subreddits with no new RSS
    posts are re-checked via the archive's `/api/posts/search` (same post
    shape as the crosspost lookup); archive posts run through the same
    `collect()` (dedup + 48h window unchanged); soft-fail + shared circuit
    breaker.
  * **Smoke test:** first functional checks for the X V3 data path — GIF
    chain order/probes, vxtwitter normalization (GIF, multi-photo, quotes),
    twitterez og-page parsing (stats incl. `1.5M`, ad lines, posters),
    fallback-chain order, Arctic search params/failures + entry shim
    (40 new functional checks + the import gate — 199 total).
  * **Docs updated:** this entry, the round-11/round-17 sections, credits,
    troubleshooting, `docs/CI_SMOKE.md`, `PRIVACY_POLICY.md`,
    `TERMS_OF_SERVICE.md`. **Untouched:** `twitter_v1.py`,
    `twitter_v2_button_outside.py`, both workflow yml files,
    `.env.example`, `.gitignore`, `requirements.txt` (no new secrets,
    dependencies, or files at runtime).

* **2026-09-16 — round 14 (Reddit V3 card polishing, after the first
  production runs):**
  * **Complete galleries incl. GIFs** — the redlib post-page harvest now
    runs in parallel with the proxy fetch and its complete ordered list
    wins for image posts (redditez og: tags omit GIFs; a 6-item post showed
    3 before). Video posts skip the harvest; all-proxies-down still gets
    the redlib list.
  * **Gallery dedupe** — the proxy embed pages' extra `og:image` tags (the
    "main image", 140px crops, same-photo second rendition) are dropped by
    the new `dedupe_proxy_media` in `reddit_proxy.py`.
  * **Body formatting like the redditez card** — clickable markdown links
    for all links, `**bold**` + paragraph breaks kept, bare redd.it media
    URLs removed from the text (fixes the glued-URL bug), og: values
    unescaped until stable (fixes `&amp;amp;`).
  * **Crossposts keep working** — the crosspost notice in the RSS content
    is detected; media/stats are fetched from the ORIGINAL post; the card
    keeps the crosspost URL + "🔁 Crosspost of" line.
  * **Stats backfill** — when the winning proxy has no stats (common with
    redditez), the 💬/👍 row is backfilled from the Embeddit JSON (~1 s).
  * **Embeddit plain-text shape** — unmarked-up content ("Title⬆️ 1.1K
    • 💬 108") and compact numbers are parsed.
* **2026-09-16 — round 13 (Reddit V3 proxy media services + docs):**
  * **Proxy media path (native mode):** card media now comes FIRST from the
    public proxy services — **redditez.com (EmbedEZ) → vxreddit.com →
    embeddit.deltandy.me** in that priority order (new module
    `testing area/reddit_proxy.py`, keyless public APIs — no credits, no
    API key). The winning service's own URLs are used verbatim in the
    components-v2 card: **full-res photos, EVERY gallery photo (up to 20 =
    2 containers), videos WITH audio, GIFs, plus 💬/ stats**. This fixes
    the native-mode gaps from round 12: multi-photo galleries now post all
    photos (the RSS content only inlines one), videos use each service's
    muxed mp4 (with audio) and are range-checked before use, and any-age
    test posts resolve from any service (post JSON 403 / outside the
    100-entry feed window no longer matter).
  * **Warm-up link test:** every run probes all three services in parallel
    with one known post (default `HonkaiStarRail_leaks/1whbjbh`, override
    `PROXY_WARMUP_POST`) and writes **`proxy_health.json`** (auto-committed
    with the cache). Services proven dead are skipped for the run — unless
    all three are dead, in which case every service is retried per post.
    When a redditez page shows *"Failed to Get Post | EmbedEZ — Reddit
    returned a non-JSON response"* it means the EmbedEZ backend (redditez's
    engine, which fetches the post from Reddit for us) is down or
    unavailable at that moment — a service-side failure detected **per
    post** — and the post falls through to vxreddit/embeddit (the two most
    uptime-reliable).
  * **Native path kept as final fallback:** if every proxy fails for a
    post, the round-12 native RSS path (RSS media → redlib harvest →
    thumbnail) runs unchanged. `PROXY_MEDIA=0` disables the proxy path
    entirely. FULL MODE (OAuth app) is untouched.
  * **YouTube second message:** posts containing a YouTube link now also
    send a **second, plain message with only the YouTube link** after the
    card lands (Discord shows the official preview; no buttons). The card's
    own YouTube thumb + animated `starwardspark3` button stay.
    `YOUTUBE_LINK_MESSAGE=0` disables the second message.
  * **Crossposts + 20-photo galleries:** unchanged — proxies return the
    crosspost's own content (RSS/native paths still follow the original),
    and 11–20 media items still render as **2 containers** (10 items each).
  * **Docs:** new `docs/DISCOHOOK.md` (what Discohook is/does here —
    **preview-only, fully optional, safe to disable**, and why it isn't
    relied on for posting) and `docs/CI_SMOKE.md` (ci.yml + test_smoke.py
    are the **required** offline safety gate — what they catch and why
    auto-merge waits on them); `docs/DEPENDABOT.md` gains the
    **Node 20 → 24** explanation (the deprecation warning vanished because
    Dependabot auto-bumped `actions/checkout`/`setup-python` to v7).
  * **Workflow:** `actions/checkout@v7` + `actions/setup-python@v7`
    (Node 24 runtime, matches the verified 2026-09-15 run log); auto-commit
    now also commits `proxy_health.json`; `EMBEDEZ_API_KEY` no longer
    needed by V3 (the keyless proxy endpoints replaced the paid API — the
    secret can be deleted; only old V2 uses it).

* **2026-09-15 — round 12 (Reddit V3 polish, from live test-channel review):**
  * **All photos now post (native mode):** the RSS content is scanned for
    every `redd.it` media URL in post order; single-image posts no longer
    show only the 140px thumbnail. (FULL MODE already had all photos.)
  * **Gallery posts (native mode):** multi-image posts carry no image links
    in the RSS content (verified in the live 2026-09-15 workflow log), so
    the post page is now harvested from the redlib fallback instances in
    parallel — same lottery as the feed, ~10s worst case, thumbnail kept on
    failure.
  * **Best rendition per photo:** `i.redd.it` full-res swap for jpg/jpeg
    (slug-prefixed preview names reduced to the bare file id) or the largest
    signed preview URL — the 140px feed thumbnail is no longer used.
  * **Body cleanup:** stray `redd.it` image URLs stripped from card text.
  * **Video posts = video only:** duplicate first-frame /
    `external-preview.redd.it` screenshots dropped whenever a video resolves
    (also fixes YouTube posts that showed a screenshot tile + video).
  * **Native video chain:** `v.redd.it/<id>/DASH_<q>.mp4` (self-contained mp4
    **with audio**, no proxy/sig/expiry) now tried before the embedez/vxreddit
    CMAF muxing proxies; signed `packaged-media.redd.it` masters deliberately
    avoided (they expire in hours).
  * **YouTube default = thumbnail + animated `starwardspark3` button**
    (the old `▶️` emoji is gone from V1/V2 buttons too); playback attempt
    (seaof.glass) moved behind `YOUTUBE_MEDIA_EMBED=1`; thumb chain
    maxres→hq→mq.
  * **💬 OP comment (FULL MODE):** stickied/top OP comment fetched with the
    post JSON (`limit=25`) and shown capped (500 chars) with a full-comment
    link; `REDDIT_OP_COMMENT=0` disables. Total text is now budgeted under
    Discord's 4000-char limit.
  * **Discohook preview (keyless):** per-card share link rendered from the
    exact payload, logged to the workflow run; webhook URL never sent to it;
    `DISCOHOOK_PREVIEW=0` disables.
  * **Test tools:** workflow `test_post` input (`<sub>/<post_id>`) + `dry_run`
    (payloads logged, Discord/cache untouched) for verifying before
    promoting; `FEEDTOKEN_JSON_STAGGER` made configurable.
  * **Dependabot + CI safety chain (all optional but shipped):**
    `.github/dependabot.yml` (weekly PRs, delete to disable), `ci.yml`
    (install + compile + offline smoke test gate on every PR),
    `dependabot_auto_merge.yml` (opt-in auto-merge, green checks required,
    enabled only via the `AUTO_MERGE_DEPENDABOT=yes` variable),
    `tests/test_smoke.py`, and full user-facing docs in `docs/DEPENDABOT.md`.
  * **Docs:** README V1/V2/**V3** comparison + V3 behavior, optional-variable
    table, Discohook + Dependabot sections; `.env.example`, privacy policy
    and ToS updated for the new third parties.
* **2026-09-13 — round 10:**
  * **Full X Article support (V2/V3)** — article tweets now post cover image + **title** + full
    body text + in-article images/GIFs (GIFs animated via the existing gif.fxtwitter → fastgif
    chain; in-article videos get the same size handling), all from FxTwitter's `tweet.article`
    JSON — no scraping, no login. Verified live (HonkaiNA DevTalk article; log shows
    `| article`). FxTwitter doesn't translate article bodies, so non-English articles post in
    their original language (normal tweets still get `/en`).
  * **Video gallery limit live re-verified** with a one-off diagnostic card
    (`testing area/video_diag.py`, safe to delete): 171 MB & 234 MB tiles **play** in every URL
    style; 521 MB+ **fail** ("image not found") in every style → the 256 MB default confirmed in a
    proven-safe gap; `?tag` param and proxy origin proven irrelevant to playability.
  * **New `GALLERY_VIDEO_LIMIT` safety cap** (default `0` = off, behavior unchanged): optional
    extra gallery ceiling that auto-downgrades to the largest fitting variant (**all** variants
    checked) or posts a "watch on X" note — the gallery can never embed an unplayable tile when
    enabled.
  * **Docs:** "image not found" recovery steps (transient Discord proxy failure on old messages —
    delete message + remove its cache line + re-run; re-posting always works).
  * **X V1 (`main.py`)** — default `ACCOUNTS` list now includes `Ananta_EN` (matches V2/V3);
    header comment tidy-up only. No behavior changes.
* **2026-09-13 — round 9:**
  * **Reddit reliability (live-verified):** primary fetch is now **ONE combined feed request**
    (`/r/sub1+sub2+.../new.rss?limit=100`) covering all subreddits — fits Reddit's
    ~1 req/min anonymous datacenter limit; automatic per-subreddit fallback kept. `?limit=100`
    verified (default 25, max 100).
  * **New `REDDIT_FEED_TOKEN` secret** (optional, recommended): personal feed token
    (old.reddit.com → Preferences → Feeds) appended as `?feed=…` → logged-in rate tier.
  * **Fallback mode:** two 429 retries (6s + 45s) instead of one; instance list trimmed to 5
    responding sources after live-probing **every** official Redlib registry instance + eddrit —
    all behind Anubis/Cloudflare/gammaspectra bot challenges or dead (fallback lottery only).
  * **Docs:** new Testing Area guide (quotes required for `testing area/` paths) + guidance comments
    inside both workflow ymls; X `RSS_INSTANCES` retested and intentionally unchanged.
* **2026-09-12 — round 8:**
  * **Reddit RSS sources fixed for multi-sub monitoring.** `redlib.perennialte.ch` removed (shut
    down 2026-08-31, now answers HTTP 410); fresh Redlib fallback chain from the official
    [redlib-instances](https://github.com/redlib-org/redlib-instances) list (safereddit.com,
    red.artemislena.eu, redlib.privacyredirect.com, redlib.privadency.com, redlib.nadeko.net,
    redlib.ducks.party, redlib.catsarch.com, snoo.habedieeh.re). **429 retry with 6s backoff** +
    **staggered fetch starts (1.2s)** so six subreddits no longer hit www.reddit.com in the same
    second — fixes the "only one subreddit posts per run" symptom.
* **2026-09-12 — round 7:**
  * **Five new default subreddits** added to both Reddit engines:
    `Genshin_Impact_Leaks`, `HonkaiStarRail_leaks`, `WutheringWavesLeaks`, `HonkaiNexusAnimaLeaks`,
    `AnantaLeaks` (all verified live/active). Matching per-sub secrets
    (`WEBHOOK_REDDIT_GENSHIN_IMPACT_LEAKS` … `WEBHOOK_REDDIT_ANANTALEAKS`) documented, and the
    sample `reddit_monitor.yml`/`.env` updated.
  * **Switchable V1 embed mirror:** new optional **`REDDIT_MIRROR`** repo Variable — `redditez.com`
    (default), `embeddit.deltandy.me`, or `vxreddit.com`. All three were verified live to accept
    the same post path and serve embed meta to Discordbot. Host normalization tolerates full URLs.
    Reddit V2 is unaffected (EmbedEZ API builds the card itself).
* **2026-09-12 — round 6:**
  * **GIF resilience — fastgif fallback added.** With `gif.fxtwitter.com`'s CDN still down
    (530/1033), GIF posts were falling back to mp4 players. GIFs now resolve through a two-source
    probe chain: the official `gif.fxtwitter.com` WebP first, then
    **fastgif** (`fastgif-production.up.railway.app/tweet_video/<id>.gif`) — an independent
    third-party converter serving REAL animated GIFs that show *and* play in Components V2
    (confirmed live against the exact tweet ids that were broken). Only its `.gif` route is used —
    its `.webp` route errors, and unknown ids return 500, so the probe is safe and never forced.
    If neither converter answers, the original mp4 is kept (still plays as a video). The chain
    self-heals in both directions. Verified live on single-GIF and 4-GIF tweets.
* **2026-09-11 — round 5:**
  * **Portrait-video handling revised** after further evidence: the "loads but won't play" symptom
    is a transient Discord proxy warm-up (the same direct URLs soon play fine in Components V2), so
    the round-4 proxy wrap is retracted to an opt-in `PORTRAIT_PROXY` toggle (default **off**) —
    direct URLs for all videos, zero extra load on FxTwitter.
  * **Ananta_EN added** to tracked accounts (default list, README routing table, workflow env,
    .env example). Remember: a new account needs its `WEBHOOK_ANANTA_EN` secret *and* the matching
    `env:` line in the workflow, plus `Ananta_EN` appended to the `ACCOUNTS` secret.
* **2026-09-11 — round 4 (quotes, GIFs, articles, portrait fix):**
  * **Fixed both live `400 {"components": ["0"]}` failures** (empty-text quote post + X Article) —
    text chunking (×4 @ ≤1900) + never emitting empty components; very long tweets now render.
  * **Quoted-post rendering** (`>>> [Quote](url) from **Name** (@user)` + quoted text + quoted
    media, with full video handling on quote media too).
  * **X Article / link-card images** via OpenGraph fetch of the post's `x.com` page (article banner
    / `card_img`), falling back to the shared link's OG image (hoyo.link & co. verified working).
  * **GIF support**: `tweet_video` GIFs render as animated WebP via `gif.fxtwitter.com` when that
    CDN is up; graceful mp4 fallback when it 530s (maintainer-side).
  * **Portrait-video playback fix** via the `api.fxtwitter.com/2/go?url=…` proxy wrapper.
  * **Robust `/status/:id` API path** (the screen-name path 404s on reposts/articles/newer tweets);
    Read Post links use the true author; `/en` translation uses the same path.
  * **"↩️ Replying to"** line on replies; **animated custom emoji** on all buttons (X + Reddit).
* **2026-09-11 — round 3 (smart videos):** X V2/V3 video handling rebuilt after live Discord tests
  proved **file size** (not resolution) decides playability. Each video's real size is now probed by
  HTTP HEAD; oversized (> 256 MB) videos are swapped for a smaller playable FxTwitter `formats[]`
  rendition (905 MB 4K → 135 MB 720p that plays), or thumbnailed with a watch link when nothing
  fits. Unknown sizes are left untouched unless clearly risky (> 5 min **and** ≥ 1080p). Replaces
  the earlier pixel-count rule, which would have wrongly thumbnailed playable 2K clips.
* **2026-09-11 — round 2:**
  * **Reddit (V1 + V2):** Embeddit/vxReddit buttons removed; *Read Post* → original `reddit.com`
    permalink; YouTube link detection (bare playable link on V1, clickable line + ▶️ button on V2);
    **48-hour mod-queue-safe window** keyed on the RSS *updated* stamp so late-approved posts are
    never missed; V2 now strips HTML from **all** EmbedEZ text fields and adds a 🕐 `<t:…:f>`
    Discord timestamp to cards.
  * **X (V2 + V3):** clickable `#hashtags` / `@mentions` (masked x.com links); 🕐 Discord timestamp
    on the stats line; null-safe accent color (`accent_from_color`).
  * **Docs:** added `PRIVACY_POLICY.md` and `TERMS_OF_SERVICE.md`.
* **2026-09-11 — round 1:** Reddit V1 source-order fix (`www.reddit.com` first + feed validation +
  per-source logging); Reddit V2 rebuilt on the documented two-step EmbedEZ flow
  (`search` → `preview`) with graceful public-preview fallback.
* **Earlier:** X V1/V2/V3 engines, multi-webhook routing, `/en` auto-translation, external
  cron-job.org scheduling guide.

---
