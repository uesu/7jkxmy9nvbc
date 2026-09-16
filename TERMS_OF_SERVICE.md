# Terms of Service

**Effective date:** September 11, 2026 (updated September 15, 2026 for Reddit V3 round 12)
**Applies to:** the *News Feed Embed* / *Citlali News* X (Twitter) + Reddit → Discord monitor
("the Service"), an open-source, self-hosted automation tool.

---

## 1. Acceptance

By deploying, running, or modifying the Service, you agree to these Terms. If you do not agree, do
not use the Service.

## 2. What the Service Is

A set of open-source Python scripts that fetch **public** X/Twitter and Reddit content via RSS/API
mirrors and repost links, text excerpts, and media into Discord channels **you control**, using
Discord webhooks triggered from your own GitHub repository. There is no hosted bot and no service
operated by the author on your behalf — you run your own instance.

## 3. Acceptable Use

You agree NOT to use the Service to:

* violate Discord's [Terms of Service](https://discord.com/terms) or
  [Community Guidelines](https://discord.com/guidelines), X/Twitter's or Reddit's terms, or any
  applicable law;
* repost private, paywalled, NSFW-into-SFW-channel, or otherwise restricted content;
* harass, defame, doxx, or target any person or community;
* spam channels, or poll source services aggressively (keep the interval at **10 minutes or longer**;
  the free mirrors and APIs this project relies on are shared community resources);
* misrepresent the origin of posts, remove author attribution, or claim the Service as your own
  original work (see §6 License & Credits);
* circumvent rate limits, blocks, or technical protections of any third-party service.

## 4. Third-Party Dependencies

The Service depends on free/community-run third parties — Nitter mirrors, Redlib, FxTwitter/FxEmbed,
the independent "fastgif" GIF converter (fastgif-production.up.railway.app, used only as a
probe-verified fallback when FxTwitter's GIF CDN is down), EmbedEZ, the redditez.com /
Embeddit (embeddit.deltandy.me) / vxReddit (vxreddit.com) Reddit-embed mirrors (V1 switchable),
reddit.com RSS and Reddit's own media CDNs (i.redd.it / preview.redd.it / v.redd.it), the
proxy.embedez.com / vxreddit.com video-muxing fallbacks (Reddit V3, used only when Reddit's own
video files are unavailable), seaof.glass (optional YouTube playback, off by default),
i.ytimg.com (YouTube thumbnails), discohook.app (optional per-card share-link preview, on by
default, keyless public API), GitHub Actions,
cron-job.org, and Discord webhooks. **Availability is not
guaranteed**: mirrors rotate or shut down, APIs change (EmbedEZ explicitly warns of breaking
changes), GitHub's native scheduler is best-effort, and the EmbedEZ API may consume paid credits per
its own pricing. The author of this project has no control over, and accepts no liability for, those
services. Optional extras (Discohook preview, Dependabot dependency-update PRs) may be disabled at
any time without affecting the core monitor — see the README and `docs/DEPENDABOT.md`.

## 5. Content Responsibility

You are solely responsible for what your instance posts into your Discord server, including
compliance with copyright, fair use/fair dealing, and your server's rules. The Service only
re-serves **publicly available** content with source attribution and links back to the original;
rights holders who want a source or account excluded can open an issue and the relevant integration
can be adjusted or documented for removal.

## 6. License & Credits

The Service builds on published open-source work — notably **News-Flash-Bot** by @cold-logic5
(original architecture) and the projects listed in the README's credits. You must retain authorship
notices and credits in any copy, fork, or derivative you distribute or deploy publicly. Platform
names, logos, and trademarks (Discord, X, Reddit, GitHub, game titles mentioned in feeds, etc.)
belong to their respective owners; this project is unofficial and non-affiliated.

## 7. No Warranty

THE SERVICE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
LIMITED TO WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT. IT
MAY STOP WORKING AT ANY TIME WITHOUT NOTICE (e.g. if an upstream mirror or API changes).

## 8. Limitation of Liability

To the maximum extent permitted by law, the author(s) shall not be liable for any indirect,
incidental, special, consequential, or punitive damages — including lost data, lost revenue, Discord
account/server actions, missed or duplicate posts, or third-party charges (such as EmbedEZ credits) —
arising from the use or inability to use the Service.

## 9. Modifications & Termination

You may modify or stop using your instance at any time — it is yours. These Terms may be updated in
this repository with a new effective date; continued use after an update constitutes acceptance.

## 10. Contact

* GitHub: open an issue on this repository
* Discord: https://discord.gg/HyrVP9wRXu
* Support/dev: https://ko-fi.com/jieunlatte
