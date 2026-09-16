# 🪝 Discohook — full explanation (what it does here, and whether it's optional)

> **TL;DR:** In this repo Discohook is a **preview-only** tool. The bot
> **posts straight to your Discord webhooks** — Discohook is never in the
> posting path. After each successful post it creates a **keyless share
> link that renders the exact card** and logs it in the workflow run, so
> you can verify a card in the browser while reviewing the log. It is
> **100% optional**: set `DISCOHOOK_PREVIEW=0` (or delete the three
> `DISCOHOOK_*` lines) and everything else works exactly the same.

---

## 1. What is Discohook?

[Discohook](https://discohook.app) is a free, public **Components-V2 message
designer/previewer** for Discord. You can design cards by hand in their
website, and their **public API** (no key, no account) can:

| Endpoint | What it does | Used by this repo? |
|---|---|---|
| `POST https://discohook.app/api/v1/share` | Creates a public share link that renders any Components-V2 message payload (TTL up to 28 days) | ✅ **Yes** — once per posted card |
| `GET https://discohook.app/unfurl?url=…` | Re-implements Discord's link scraper (shows how a bare URL would embed) | ❌ No — handy for manual debugging only |
| authenticated "send" endpoint | Would let a keyless payload be *posted* to webhooks by their servers | ❌ No — **it does not exist publicly yet** (they plan one) |

## 2. Exactly what the monitor uses it for (round 12+)

After each **successful** Discord post, the Reddit V3 script (and the
Twitter V2/V3 scripts' preview equivalent) does one best-effort call:

```
POST https://discohook.app/api/v1/share
     json = {"data": {"version": "d2", "messages": [{"data": <the exact card payload>}]},
             "ttl": 604800}
```

and logs the returned URL in the workflow run:

```
Discohook preview for AnantaLeaks_1wgvcz7: https://discohook.app/?share=…
```

That's the entire usage. Nothing else in any script depends on Discohook.

## 3. Is it optional or required? — **Optional. Fully.**

| Question | Answer |
|---|---|
| Does the monitor need Discohook to post? | **No.** Posts go directly to your Discord webhooks (`?with_components=true`). Discohook is not in that path at all. |
| Does it affect posting speed/reliability? | **No.** The share call happens **after** the post already succeeded, is best-effort with a 20 s timeout, and any failure (DNC, timeout, 5xx) only logs a warning. The card is already in Discord. |
| Can I disable it? | **Yes** — repo Variable `DISCOHOOK_PREVIEW=0`, or delete the three `DISCOHOOK_*` lines + the `create_discohook_share` call. Nothing else changes. |
| Do I pay for it? | **No** — the public share API is keyless and free. |
| What do I lose if I disable it? | Only the per-card browser preview link in the workflow log. You can always design/preview cards by hand at discohook.app if you want. |

## 4. Why not rely on it more (e.g. for "blazing-fast action flow")?

Good instinct to ask. Two reasons keep Discohook preview-only here:

1. **There is no public keyless send endpoint.** Discohook's public API can
   render/share, but it cannot *post to your webhook on your behalf* without
   an authenticated send API (planned, not public). So "route the monitor's
   posts through Discohook" is simply not possible today — and the direct
   webhook POST is already the fastest possible path (one HTTP request from
   the GitHub runner to Discord, no middleman hop).
2. **Third-party dependency.** discohook.app is a free public service; its
   uptime/limits are outside your control. The monitoring loop (fetch feed →
   build card → post webhook → commit cache) must never depend on an
   optional extra — which is exactly how it's built: the share call is
   fire-and-forget after the fact.

If/when they ship a stable public send API and you want it, that's a
separate, explicit change — not something this repo quietly depends on.

## 5. Privacy (what goes to Discohook)

* The share payload contains **only the public card payload** (title, body,
  media URLs, buttons) — the same thing your Discord channel sees.
* **No `targets` are sent**, so your **webhook URL never leaves the repo**.
* Share links are **public while alive** (7-day TTL; share IDs are reused
  after expiry) — treat them as temporary, don't pin them permanently.
* No account, no login, no tracking data from you.

## 6. Turning it off / on

* **Off:** repo → Settings → Secrets and variables → Actions → Variables →
  new variable `DISCOHOOK_PREVIEW` = `0`. (Or remove the env line from the
  workflow — the script's default is on, so the Variable is the clean switch.)
* **On again:** set it to `1` (or delete the Variable).
* No workflow re-run is needed for either — it's read at script start.

---

*Files involved: `create_discohook_share()` in the Reddit V3 / X V2/V3
scripts, `DISCOHOOK_PREVIEW` switch, `DISCOHOOK_SHARE_*` constants.*
