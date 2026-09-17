"""Offline smoke test — no network, no secrets.

Run:  python tests/test_smoke.py
Purpose (also used by CI as the safety gate for Dependabot PRs):
  1. every monitor script imports cleanly (catches import-time breakage
     from dependency bumps),
  2. the Reddit V3 card pipeline still behaves (body cleaning, media
     extraction/dedup, OP comment, components-v2 layout, button set,
     Arctic Shift search backup — round 17),
  3. the X V3 tweet-data path still behaves (GIF converter chain,
     vxtwitter normalization, twitterez og-page parsing, fallback-chain
     order — round 11).
"""
import os
import sys
import json
import types
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# In offline environments (no aiohttp/feedparser/dotenv installed) use stubs —
# this test never opens a connection, so stubs are safe.
try:
    import aiohttp  # noqa: F401
    import feedparser  # noqa: F401
    import dotenv  # noqa: F401
except ImportError:
    for name in ("aiohttp", "feedparser", "dotenv"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["aiohttp"].ClientSession = object
    sys.modules["aiohttp"].ClientTimeout = lambda total=None: None
    sys.modules["feedparser"].parse = lambda *a, **k: None
    sys.modules["dotenv"].load_dotenv = lambda *a, **k: None

failures = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        failures.append(label)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- 1. every monitor script must import --------------------------------
SCRIPTS = [
    "twitter_v1.py",
    "testing area/reddit_main.py",
    "testing area/reddit_main_v2_embedez.py",
    "testing area/reddit_main_v3.py",
    "testing area/twitter_v2_button_outside.py",
    "testing area/twitter_v3.py",
    "testing area/twitter_proxy.py",
    "testing area/video_diag.py",
]
v3 = None
for rel in SCRIPTS:
    try:
        m = load_module("smoke_" + rel.replace(os.sep, "_").replace(" ", "_"), rel)
        check(f"import {rel}", True)
        if rel.endswith("reddit_main_v3.py"):
            v3 = m
    except Exception as e:
        check(f"import {rel}", False, repr(e))

if v3 is None:
    print("FATAL: reddit_main_v3.py could not be imported.")
    sys.exit(1)

# ---- 2. body cleaning -----------------------------------------------------
html = ('<table><tr><td><p><a href="https://preview.redd.it/abc123.png?width=1280&s=x">'
        'https://preview.redd.it/abc123.png?width=1280&s=x</a></p>'
        '<p>Keep me</p></td></tr></table>\nsubmitted by /u/x to r/y')
body = v3.clean_rss_body(html)
check("body: redd.it URL line stripped", "preview.redd.it" not in body, body)
check("body: text kept", "Keep me" in body, body)

# ---- 3. native media extraction (order + dedup + best rendition) ----------
content = (
    '<a href="https://preview.redd.it/post-slug-v0-aaaa1111bbbb.jpg?width=140&crop=1:1,smart&auto=webp&s=1"><img></a> '
    '<a href="https://i.redd.it/aaaa1111bbbb.jpg"><img></a> '
    '<a href="https://preview.redd.it/post-slug-v0-cccc2222dddd.jpg?width=1080&crop=smart&auto=webp&s=2"><img></a> '
    '<a href="https://i.redd.it/eeee3333ffff.gif"><img></a> '
    '<a href="https://external-preview.redd.it/ext.png?width=640&s=3"><img></a>'
)
items = v3.extract_native_media(content)
check("media: 4 distinct items (deduped)", len(items) == 4, str(items))
check("media: photo1 full-res swap", items[0] == {"kind": "image", "url": "https://i.redd.it/aaaa1111bbbb.jpg"}, str(items[0]))
check("media: photo2 (signed jpg only) swapped to i.redd.it",
      items[1] == {"kind": "image", "url": "https://i.redd.it/cccc2222dddd.jpg"}, str(items[1]))
check("media: gif kind", items[2] == {"kind": "gif", "url": "https://i.redd.it/eeee3333ffff.gif"}, str(items[2]))
check("media: external-preview kept for caller", "external-preview" in items[3]["url"], str(items[3]))

# ---- 4. i_reddit_swap reduces slug-prefixed names to the bare file id ------
check("swap: bare id", v3.i_reddit_swap("https://preview.redd.it/yjexawtg9nph1.jpg?width=1280&s=x")
      == "https://i.redd.it/yjexawtg9nph1.jpg")
check("swap: slug -> bare id", v3.i_reddit_swap(
    "https://preview.redd.it/heist-mode-v0-8la7js0h9nph1.jpg?width=1080&s=x")
    == "https://i.redd.it/8la7js0h9nph1.jpg")
check("swap: png not swapped", v3.i_reddit_swap("https://preview.redd.it/xyz.png?width=1280&s=x") is None)

# ---- 4b. redlib gallery scoping ---------------------------------------------
redlib_page = """
<html><head><style>.post_title{font-size:20px}</style></head><body>
<header><img src="https://i.redd.it/subicon.jpg"></header>
<h1 class="post_title"><a href="/r/X/comments/abc/t/">Title</a></h1>
<div class="post_content">
  <img src="https://preview.redd.it/photo-a-v0-111aaa1.jpg?width=140&crop=1:1,smart&auto=webp&s=x">
  <img src="https://i.redd.it/222bbb2.jpg">
  <img src="https://preview.redd.it/photo-b-v0-333ccc3.jpg?width=1080&crop=smart&auto=webp&s=y">
  <img src="https://i.redd.it/444ddd4.gif">
</div>
<div id="comment-9"><img src="https://i.redd.it/commentside.jpg"></div>
<div class="sidebar"><img src="https://i.redd.it/sidebar.jpg"></div>
</body></html>
"""
g = v3.extract_redlib_gallery(redlib_page)
check("redlib: 4 items (sub icon + comment/sidebar imgs excluded)", len(g) == 4, str(g))
check("redlib: photo-a deduped to full-res", g[0] == {"kind": "image", "url": "https://i.redd.it/111aaa1.jpg"}, str(g[0]))
check("redlib: order kept (signed jpg/jpeg swapped to i.redd.it)",
      [x["url"] for x in g][:3]
      == ["https://i.redd.it/111aaa1.jpg", "https://i.redd.it/222bbb2.jpg",
          "https://i.redd.it/333ccc3.jpg"], str(g))
check("redlib: gif kind", g[3] == {"kind": "gif", "url": "https://i.redd.it/444ddd4.gif"}, str(g[3]))
check("redlib: empty page -> []", v3.extract_redlib_gallery("") == [])
check("redlib: bot-challenge page -> []", v3.extract_redlib_gallery("<html><h1>Please verify</h1></html>") == [])

# ---- 4d. test-post post-RSS source (round 12e) ----------------------------
import asyncio


class _FakeEntry:
    def __init__(self, link, title, author, content_value):
        self.link = link
        self.title = title
        self.author = author
        self._d = {"content": [{"value": content_value}], "summary": "",
                   "media_thumbnail": []}

    def get(self, k, d=None):
        return self._d.get(k, d)


def _post_rss_feed():
    post = _FakeEntry("/r/AnantaLeaks/comments/1wguffh/heist_mode/", "Heist mode",
                      "hugosince1999", "<p>1 hour long, 2-4 players</p>")
    comment = _FakeEntry("/r/AnantaLeaks/comments/1wguffh/heist_mode/comment/zzz/",
                         "a comment", "somebody", "<p>comment body</p>")
    return types.SimpleNamespace(entries=[post, comment])


orig_combined = v3.fetch_combined_feed
orig_post_rss = v3._fetch_post_rss
orig_fetch_feed = v3._fetch_feed

# 4d.1 URL construction (real _fetch_post_rss, fake _fetch_feed)
captured = []


async def _fetch_feed_fake(session, url, label):
    captured.append(url)
    return None


v3._fetch_feed = _fetch_feed_fake
asyncio.run(v3._fetch_post_rss(None, "/r/AnantaLeaks/comments/1wgq3cy/"))
v3._fetch_feed = orig_fetch_feed
check("post-rss: url = instance + permalink + .rss",
      bool(captured) and captured[0].startswith(
          "https://www.reddit.com/r/AnantaLeaks/comments/1wgq3cy/.rss"), str(captured[:1]))
check("post-rss: falls through every instance when all fail",
      len(captured) == len(v3.REDDIT_RSS_INSTANCES), str(len(captured)))

# 4d.2 end-to-end base from the post entry (fake feeds, no network)
async def _combined_none(session):
    return None


async def _post_rss_fake(session, path):
    return _post_rss_feed()


v3.fetch_combined_feed = _combined_none
v3._fetch_post_rss = _post_rss_fake
b2 = asyncio.run(v3.fetch_test_post_base(None, "/r/AnantaLeaks/comments/1wguffh/", "tp"))
check("tp-12e: base built from the post entry (not the comment)",
      b2 and b2["title"] == "Heist mode" and b2["author"] == "hugosince1999", str(b2))
check("tp-12e: body cleaned from post content",
      b2 and b2["body"] == "1 hour long, 2-4 players", str(b2 and b2.get("body")))
v3.fetch_combined_feed = orig_combined
v3._fetch_post_rss = orig_post_rss

# ---- 5. OP comment selection + card line ----------------------------------
pj = {"author": "OP", "permalink": "/r/Sub/comments/abc/title/"}
pj["_top_comments"] = [
    {"data": {"author": "other", "body": "nope"}},
    {"data": {"author": "OP", "body": "first"}},
    {"data": {"author": "OP", "body": "stickied!", "stickied": True, "id": "p9"}},
]
oc = v3.extract_op_comment(pj)
check("op: stickied wins", oc and oc["stickied"] and oc["text"] == "stickied!", str(oc))
check("op: permalink", oc and oc["permalink"] == "https://www.reddit.com/r/Sub/comments/abc/title/comment/p9/", str(oc))
check("op: none when absent", v3.extract_op_comment({"author": "A", "permalink": "/r/S/comments/x/",
                                                     "_top_comments": []}) is None)

# ---- 6. card layout ---------------------------------------------------------
data = {"title": "T", "author": "A", "body": "b" * 50,
        "media": [{"kind": "image", "url": f"https://i.redd.it/{i}.jpg"} for i in range(12)],
        "stats": {"comments": 3, "ups": 9}, "crosspost": None,
        "op_comment": {"text": "op note", "permalink": "https://pc", "stickied": True},
        "youtube_url": "https://youtube.com/shorts/ABCDEFGHI12", "full_mode": True}
p = v3.build_v3_payload("AnantaLeaks", data, "https://www.reddit.com/r/AnantaLeaks/comments/x/", 1)
check("layout: 2 containers for 12 media", len(p["components"]) == 2)
check("layout: flags", p["flags"] == 32768)
c2 = p["components"][1]
g2 = [c for c in c2["components"] if c.get("type") == 12]
check("layout: 2nd gallery has 2 items", len(g2) == 1 and len(g2[0]["items"]) == 2, str(len(g2)))
row = [c for c in c2["components"] if c.get("type") == 1][0]
labels = [b["label"] for b in row["components"]]
check("buttons: Read Post, YouTube, statics", labels == ["Read Post", "YouTube", "Citlali News", "Support"], str(labels))
yt = row["components"][1]
check("buttons: youtube uses starwardspark3",
      yt["emoji"] == {"id": "1483083423290490891", "name": "starwardspark3", "animated": True}, str(yt))
texts = [c["content"] for ct in p["components"] for c in ct["components"] if c.get("type") == 10]
check("op line in card", any("OP comment" in t for t in texts), str(texts))
total = sum(len(t) for t in texts)
check("char budget under 4000", total < 4000, str(total))

# ---- 7. proxy media services (round 13, offline fixtures) ------------------
proxy = load_module("smoke_reddit_proxy", "testing area/reddit_proxy.py")

# 7.1 embeddit status-id codec (port of src/util/encode.ts — base-36:
# 36-char alphabet "1234567890" + "a-z"; '{' (123) -> 123//36=3 -> '4',
# 123%36=15 -> 'f')
enc = proxy.status_id_encode({"type": "post", "id": "abc123", "merge": True})
check("proxy: embeddit id encodes '{' as '4f'", enc.startswith("4f"), enc)
check("proxy: embeddit id round-trips",
      proxy.status_id_decode(enc) == json.dumps(
          {"type": "post", "id": "abc123", "merge": True}, separators=(",", ":")), enc)

# 7.2 og: meta parsing (multiple og:image = gallery, unescape, video tag)
og_page = (
    '<html><head>'
    '<meta property="og:site_name" content="u/leaker on r/AnantaLeaks - ⬆️ 1234 | 💬 56"/>'
    '<meta property="og:title" content="Heist mode &amp; more"/>'
    '<meta property="og:description" content="line one\nline two"/>'
    '<meta property="og:image" content="https://i.redd.it/aaa111.jpg"/>'
    '<meta property="og:image" content="https://i.redd.it/bbb222.gif"/>'
    '<meta property="og:video:secure_url" content="https://vxreddit.com/redditvideo.mp4?video_url=x"/>'
    '</head><body></body></html>'
)
meta = proxy._og_meta(og_page)
check("proxy: og:image collects all in order",
      meta.get("og:image") == ["https://i.redd.it/aaa111.jpg", "https://i.redd.it/bbb222.gif"],
      str(meta.get("og:image")))
check("proxy: og values unescaped", meta.get("og:title") == "Heist mode & more", str(meta.get("og:title")))
check("proxy: og:video captured",
      str(meta.get("og:video:secure_url", "")).startswith("https://vxreddit.com/redditvideo.mp4"),
      str(meta.get("og:video:secure_url")))

# 7.3 stats-line parsing (both service formats)
st = proxy.parse_icon_stats("💬 152  🔁 0  💜 573  👀 0")
check("proxy: redditez icon stats", st == {"comments": 152, "ups": 573}, str(st))
sm = proxy.VXREDDIT_STATS_RE.search("u/IdiotGaming on r/196 - ⬆️ 699 | 💬 29")
check("proxy: vxreddit stats line",
      bool(sm) and sm.group(1) == "IdiotGaming" and sm.group(3) == "699" and sm.group(4) == "29",
      str(sm.groups() if sm else None))

# 7.4 redditez search key extraction
check("proxy: redditez search key",
      proxy.parse_redditez_search({"success": True, "data": {"key": "search_abc", "site": "reddit"}})
      == "search_abc")
check("proxy: redditez search failure -> None",
      proxy.parse_redditez_search({"success": False}) is None)

# 7.5 embeddit JSON parsing (20-photo shape: title + body + stats + media)
edd_fixture = {
    "account": {"display_name": "u/Aikz21 (@ r/AnimeFigures)"},
    "content": ('<a href="https://reddit.com/r/AnimeFigures/comments/1sqass3/x/">'
                '<b>First time posting collection</b></a>'
                '<br/><br/><div>So, I generally never post online.</div>'
                '<br/><br/><div><b>⬆️ 305 • 💬 21</b></div>'),
    "media_attachments": [
        {"type": "image", "url": "https://preview.redd.it/aaa.jpg?width=4059&s=1"},
        {"type": "image", "url": "https://preview.redd.it/bbb.gif?width=4074&s=2"},
        {"type": "video", "url": "https://embeddit.deltandy.me/video/vid1/name.mp4"},
    ],
}
res = proxy.parse_embeddit_post(edd_fixture)
check("proxy: embeddit title", res and res["title"] == "First time posting collection",
      str(res and res.get("title")))
check("proxy: embeddit author + subreddit",
      res and res["author"] == "Aikz21" and res["subreddit"] == "AnimeFigures",
      str(res and (res.get("author"), res.get("subreddit"))))
check("proxy: embeddit stats", res and res["stats"] == {"ups": 305, "comments": 21},
      str(res and res.get("stats")))
check("proxy: embeddit body keeps middle lines only",
      res and res["body"] == "So, I generally never post online.", str(res and res.get("body")))
check("proxy: embeddit media kinds (image, gif, video)",
      res and [m["kind"] for m in res["media"]] == ["image", "gif", "video"],
      str(res and res["media"]))
check("proxy: embeddit bad data -> None", proxy.parse_embeddit_post({"nope": 1}) is None)

# 7.6 fallback chain + warm-up health skipping (fakes, no network)
async def _fake_rr(session, path, label=""):
    return None

async def _fake_vx(session, path, label=""):
    return {"service": "vxreddit", "title": "T", "author": "a", "subreddit": None,
            "body": "b", "stats": {"ups": 1, "comments": 2},
            "media": [{"kind": "image", "url": "https://i.redd.it/x.jpg"}]}

async def _fake_ed(session, path, label=""):
    return {"service": "embeddit", "title": "T", "author": "a", "subreddit": None,
            "body": "b", "stats": None,
            "media": [{"kind": "image", "url": "https://preview.redd.it/y.jpg?s=1"}]}

orig_rr, orig_vx, orig_ed = proxy._fetch_redditez, proxy._fetch_vxreddit, proxy._fetch_embeddit
proxy._fetch_redditez, proxy._fetch_vxreddit, proxy._fetch_embeddit = _fake_rr, _fake_vx, _fake_ed
r1 = asyncio.run(proxy.fetch_proxy_post(None, "/r/X/comments/abc/", label="t", health={}))
check("proxy: falls through to vxreddit when redditez has no data",
      r1 and r1["service"] == "vxreddit", str(r1))
r2 = asyncio.run(proxy.fetch_proxy_post(None, "/r/X/comments/abc/", label="t",
                                        health={"vxreddit": {"ok": False}}))
check("proxy: warm-up-dead service is skipped (embeddit wins)",
      r2 and r2["service"] == "embeddit", str(r2))
r3 = asyncio.run(proxy.fetch_proxy_post(None, "/r/X/comments/abc/", label="t",
                                        health={s: {"ok": False} for s in proxy.PROXY_SERVICES}))
check("proxy: ALL-dead health still retries every service",
      r3 and r3["service"] == "vxreddit", str(r3))
proxy._fetch_redditez, proxy._fetch_vxreddit, proxy._fetch_embeddit = orig_rr, orig_vx, orig_ed

# 7.7 health file round-trip
import tempfile
orig_health_file = proxy.PROXY_HEALTH_FILE
with tempfile.TemporaryDirectory() as _td:
    proxy.PROXY_HEALTH_FILE = os.path.join(_td, "health.json")
    proxy.save_proxy_health({"post": "X/y",
                             "services": {"redditez": {"ok": True, "detail": "1 media item(s)"}}})
    loaded = proxy.load_proxy_health()
    check("proxy: health file round-trip",
          loaded.get("redditez", {}).get("ok") is True, str(loaded))
    proxy.PROXY_HEALTH_FILE = os.path.join(_td, "missing.json")
    check("proxy: missing health file -> {}", proxy.load_proxy_health() == {})
proxy.PROXY_HEALTH_FILE = orig_health_file

# ---- 8. round 14: body formatting, og dedupe, crosspost -------------------
# 8.1 clean_proxy_body: markdown links + bold + paragraph breaks + URL strip
html_body = ('<a href="https://en.wikipedia.org/wiki/Heist">BGM: Heist</a> more text<br/>'
             '<b>bold line</b><p><a href="https://i.redd.it/abc123.png?s=1">img</a></p>'
             'plain https://preview.redd.it/xyz-v0-def456.jpg?width=140&s=2 end')
cb = proxy.clean_proxy_body(html_body)
check("r14 body: markdown link kept",
      "[BGM: Heist](https://en.wikipedia.org/wiki/Heist)" in cb, cb)
check("r14 body: bold kept as **bold**", "**bold line**" in cb, cb)
check("r14 body: paragraph breaks kept", "\n" in cb, cb)
check("r14 body: redd.it media links+URLs removed", "redd.it" not in cb, cb)
check("r14 body: surrounding text kept", "more text" in cb and "end" in cb, cb)

# 8.2 _og_meta: double-escaped values unescape to stable
meta2 = proxy._og_meta('<html><head><meta property="og:title" content="A &amp;amp; B"/></head></html>')
check("r14 og: double-escape unescaped", meta2.get("og:title") == "A & B", str(meta2.get("og:title")))

# 8.3 dedupe_proxy_media (the 4 duplicate shapes from the 2026-09-16 run)
dm = proxy.dedupe_proxy_media
check("r14 dedupe: single item untouched",
      dm([{"kind": "image", "url": "https://i.redd.it/solo.jpg"}])
      == [{"kind": "image", "url": "https://i.redd.it/solo.jpg"}])
check("r14 dedupe: same file id collapsed",
      dm([{"kind": "image", "url": "https://i.redd.it/aaaa.jpg"},
          {"kind": "image", "url": "https://i.redd.it/aaaa.jpg"}])
      == [{"kind": "image", "url": "https://i.redd.it/aaaa.jpg"}])
check("r14 dedupe: 140px crop dropped",
      dm([{"kind": "image", "url": "https://i.redd.it/aaaa.jpg"},
          {"kind": "image", "url": "https://preview.redd.it/s-v0-bbbb.jpg?width=140&crop=1:1,smart&s=1"}])
      == [{"kind": "image", "url": "https://i.redd.it/aaaa.jpg"}])
check("r14 dedupe: trailing main-image tag dropped (1wguffh shape)",
      dm([{"kind": "image", "url": "https://embedez.com/api/v2/redirect/6633670e/1"},
          {"kind": "image", "url": "https://embedez.com/api/v2/redirect/6633670e/2"},
          {"kind": "image", "url": "https://embedez.com/api/v2/redirect/6633670e/3"},
          {"kind": "image", "url": "https://i.redd.it/heist-mode-v0-qw19p2v3g8uh1.jpg"}])
      == [{"kind": "image", "url": "https://embedez.com/api/v2/redirect/6633670e/1"},
          {"kind": "image", "url": "https://embedez.com/api/v2/redirect/6633670e/2"},
          {"kind": "image", "url": "https://embedez.com/api/v2/redirect/6633670e/3"}])
check("r14 dedupe: vN- slug variants of same id collapsed",
      dm([{"kind": "image", "url": "https://i.redd.it/heist-mode-v0-qw19p2v3g8uh1.jpg"},
          {"kind": "image", "url": "https://preview.redd.it/qw19p2v3g8uh1.jpg?width=1080&s=1"}])
      == [{"kind": "image", "url": "https://i.redd.it/heist-mode-v0-qw19p2v3g8uh1.jpg"}])

# 8.4 clean_rss_body: clickable links kept, redd.it URLs gone, nav gone
rss_html = ('<table><tr><td><p>Check <a href="https://example.com/x">this link</a> out</p>'
            '<p>pic: https://i.redd.it/abcd1234efgh.jpg and '
            '<a href="https://i.redd.it/abcd1234efgh.jpg">it</a></p>'
            '<span>submitted by /u/x to r/y <a href="https://www.reddit.com/r/y/comments/1z/">link</a> '
            '<a href="https://www.reddit.com/r/y/comments/1z/">comments</a></span>'
            '</td></tr></table>')
rb = v3.clean_rss_body(rss_html)
check("r14 rss: non-redd.it link clickable", "[this link](https://example.com/x)" in rb, rb)
check("r14 rss: redd.it URLs gone", "redd.it" not in rb, rb)
check("r14 rss: [link]/[comments] nav gone",
      "www.reddit.com" not in rb and "comments" not in rb, rb)

# 8.5 crosspost detection
cp = v3.find_crosspost_original_path
check("r14 crosspost: detected in RSS content",
      cp('<p>u/leak crossposted this from r/AnantaLeaks — '
         '<a href="https://www.reddit.com/r/AnantaLeaks/comments/1wgjk4a/orig/">original post</a></p>',
         "/r/Other/comments/1wabcdx/") == "/r/AnantaLeaks/comments/1wgjk4a/", "")
check("r14 crosspost: no 'crosspost' marker -> None",
      cp('<p>see <a href="https://www.reddit.com/r/X/comments/abc/">that post</a></p>') is None)
check("r14 crosspost: own permalink excluded",
      cp("crosspost /r/X/comments/abc/", "/r/X/comments/abc/") is None)
check("r14 crosspost: plain-text permalink found",
      cp("u/x crossposted this from r/Y — /r/AnantaLeaks/comments/1wgjk4a/x", None)
      == "/r/AnantaLeaks/comments/1wgjk4a/", "")

# 8.6 entry_to_base_data carries the crosspost field
ce = _FakeEntry("/r/Other/comments/1wabcdx/slug/", "Crosspost title", "leak",
                '<p>u/leak crossposted this from r/AnantaLeaks — '
                '<a href="https://www.reddit.com/r/AnantaLeaks/comments/1wgjk4a/orig/">original post</a></p>')
b3 = v3.entry_to_base_data(ce)
check("r14 crosspost: base carries original path",
      b3.get("crosspost_orig_path") == "/r/AnantaLeaks/comments/1wgjk4a/",
      str(b3.get("crosspost_orig_path")))

# 8.7 embeddit title from the <a><b>…</b></a> anchor
edd2 = proxy.parse_embeddit_post({
    "account": {"display_name": "u/A (@ r/B)"},
    "content": ('<a href="https://reddit.com/r/B/comments/1abc/x/"><b>My &amp; title</b></a>'
                '<br/><div>body line</div><br/><div><b>⬆️ 10 • 💬 2</b></div>'),
    "media_attachments": [],
})
check("r14 embeddit: anchor title (plain, unescaped)",
      edd2 and edd2["title"] == "My & title", str(edd2 and edd2.get("title")))
check("r14 embeddit: body excludes title link + stats footer",
      edd2 and edd2["body"] == "body line", str(edd2 and edd2.get("body")))

# ---- Round 15: regression coverage (offline; synthetic archive fixtures) ----
for module in (v3, proxy):
    cleaner = module.clean_rss_body if module is v3 else module.clean_proxy_body
    check("r15 valid standalone markdown retained",
          cleaner("[Spotify](https://example.com/music)") == "[Spotify](https://example.com/music)")
    check("r15 URL-labelled markdown retained",
          cleaner("[https://example.com](https://example.com)") == "[https://example.com](https://example.com)")
    check("r15 legitimate submitted-by prose retained",
          cleaner("This was submitted by a musician.") == "This was submitted by a musician.")
    check("r15 punctuation repair", cleaner("Buff](https://example.com)\nBuff): TBD") == "Buff: TBD")
    check("r15 cascade repair", cleaner(
        "Firefly](https://example.com/previous)\nFirefly) video [https://b23.tv/aaa\n"
        "Feixiao](https://b23.tv/aaa)\nFeixiao) video [https://b23.tv/bbb") ==
        "Firefly video [https://b23.tv/aaa](https://b23.tv/aaa)\n"
        "Feixiao video [https://b23.tv/bbb](https://b23.tv/bbb)")
    check("r15 footer repair", cleaner(
        "[ ](https://reddit.com/post)\nsubmitted](https://reddit.com/post)\n"
        "submitted) by [ /u/name_ ](https://reddit.com/u/name_) to [r/sub](https://reddit.com/r/sub)") == "")
    check("r15 merged linked footer dropped", cleaner(
        "[](https://www.reddit.com/r/Sub/comments/1abc/) submitted by "
        "[/u/name_](https://www.reddit.com/user/name_/) to [r/Sub](https://www.reddit.com/r/Sub/)") == "")
    check("r15 paragraph spacing", cleaner("<p>First</p><p>Second</p>") == "First\n\nSecond")
    check("r15 hidden video URL", cleaner("<p>https://v.redd.it/abc</p>") == "")
    check("r15 linked HTML footer", cleaner('<span>submitted by <a href="https://reddit.com/u/name">/u/name</a> to <a href="https://reddit.com/r/sub">r/sub</a></span>') == "")
    # ---- round 16: source HTML formatting (both cleaners) ------------------
    check("r16 bold from strong tag",
          cleaner("<p>Ice DMG <strong>increases by 20%</strong> a lot</p>")
          == "Ice DMG **increases by 20%** a lot")
    check("r16 bold from b tag",
          cleaner("<p><b>Anomaly</b> specialty</p>") == "**Anomaly** specialty")
    check("r16 no bold forced when absent",
          cleaner("<p>Ice DMG increases by 20% a lot</p>")
          == "Ice DMG increases by 20% a lot")
    check("r16 bold nested inside a link",
          cleaner('<strong><a href="https://lunaris.moe/">Lunaris</a></strong> is nice')
          == "**[Lunaris](https://lunaris.moe/)** is nice")
    check("r16 bullet list",
          cleaner("<ul><li>first item</li><li>second item</li></ul>")
          == "- first item\n- second item")
    check("r16 bullet with inline bold",
          cleaner("<ul><li>Agents with the <strong>Anomaly</strong> specialty "
                  "have their ATK increased by <strong>20%</strong>.</li></ul>")
          == "- Agents with the **Anomaly** specialty have their ATK "
             "increased by **20%**.")
    check("r16 blockquote becomes a Discord quote line",
          cleaner("<p>before</p><blockquote>[spoilers] &amp;gt;!hidden!&amp;lt;"
                  "</blockquote><p>after</p>")
          == "before\n> [spoilers] >!hidden!" + "<\nafter")
    check("r16 relative user link becomes absolute",
          cleaner('<a href="/u/empty_Berry-Kun">u/empty_Berry-Kun</a>')
          == "[u/empty_Berry-Kun](https://www.reddit.com/user/empty_Berry-Kun/)")
    check("r16 relative subreddit link becomes absolute",
          cleaner('<a href="/r/Genshin_Impact_Leaks/wiki/posting_guidelines/">'
                  "posting guidelines</a>")
          == "[posting guidelines]"
             "(https://www.reddit.com/r/Genshin_Impact_Leaks/wiki/posting_guidelines/)")
    check("r16 mangled 3-line link shape repairs to 3 URL-labelled lines",
          cleaner("Firefly](https://b23.tv/prev0)\n"
                  "Firefly) video [[https://b23.tv/dkCXgES](https://b23.tv/dkCXgES)\n\n"
                  "Feixiao](https://b23.tv/dkCXgES](https://b23.tv/dkCXgES)\n\n"
                  "Feixiao) video [[https://b23.tv/XojBeMr](https://b23.tv/XojBeMr)\n\n"
                  "Therta](https://b23.tv/XojBeMr](https://b23.tv/XojBeMr)\n\n"
                  "Therta) video [[https://b23.tv/PNtXo0u](https://b23.tv/PNtXo0u)]"
                  "(https://b23.tv/PNtXo0u](https://b23.tv/PNtXo0u))")
          == "Firefly video [https://b23.tv/dkCXgES](https://b23.tv/dkCXgES)\n\n"
             "Feixiao video [https://b23.tv/XojBeMr](https://b23.tv/XojBeMr)\n\n"
             "Therta video [https://b23.tv/PNtXo0u](https://b23.tv/PNtXo0u)")

check("r15 author underscore", v3._clean_author_name(
    "](https://reddit.com/post)\n*by) Knight_Steve_") == "Knight_Steve_")
check("r15 author hyphen", v3._clean_author_name("/u/valid-name") == "valid-name")
check("r15 garbage author", v3._clean_author_name("](https://reddit.com/post)") == "unknown")
check("r15 clean title punctuation", v3._clean_post_title("[Preview] *New* weapon") == "[Preview] *New* weapon")
check("r15 title artifact", v3._clean_post_title("Overview](https://reddit.com/post)\n*by") == "Overview")
youtube = "https://www.youtube.com/watch?v=abcdefghijk"
check("r15 cleaned YouTube URL dropped", v3._drop_youtube_line(
    v3.clean_rss_body(f"<p>{youtube}</p><p>First</p><p>Second</p>"), youtube) == "First\n\nSecond")
check("r15 other YouTube URL kept", v3._drop_youtube_line(
    "https://youtu.be/12345678901", youtube) == "https://youtu.be/12345678901")

archive_gallery = {"id": "gallery1", "gallery_data": {"items": [
    {"media_id": str(i)} for i in range(6)]}, "media_metadata": {
    str(i): {"status": "valid", "e": "AnimatedImage" if i in (2, 3, 4) else "Image",
             "s": {"gif" if i in (2, 3, 4) else "u":
                   f"https://i.redd.it/{i}.gif" if i in (2, 3, 4) else
                   f"https://preview.redd.it/slug-v0-{i}.jpg?width=700&amp;s=x"}}
    for i in range(6)}}
items = v3.arctic_gallery_items(archive_gallery)
check("r15 six ordered gallery items", [item["kind"] for item in items] ==
      ["image", "image", "gif", "gif", "gif", "image"])
check("r15 full resolution image", items[0]["url"] == "https://i.redd.it/0.jpg")
for malformed in (None, [], {}, {"gallery_data": []},
                  {"gallery_data": {"items": []}, "media_metadata": []},
                  {"gallery_data": {"items": [{"media_id": []}]}, "media_metadata": {}}):
    check("r15 malformed gallery safe", v3.arctic_gallery_items(malformed) == [])

# Fake every I/O boundary to exercise actual orchestration, not just parsers.
import asyncio
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace

async def round15_flows():
    original_path = "/r/Original/comments/orig1/title/"
    original = {"id": "orig1", "permalink": original_path,
                "selftext": "", "ups": 10, "num_comments": 2,
                "media": {"reddit_video": {"fallback_url": "https://v.redd.it/video1/CMAF_1080.mp4"}}}
    base = {"title": "Crosspost", "author": "name_", "body": "", "youtube_url": None,
            "vred_id": None, "redgifs_url": None, "content_html": "", "thumb": None}
    async def get_proxy(session, path, **kwargs):
        check("r15 proxy fetch uses original", path == original_path)
        return {"service": "test", "media": [{"kind": "video", "url": "https://example.com/video.mp4"}],
                "stats": {"ups": 30, "comments": 4}, "body": ""}
    fake_proxy = SimpleNamespace(fetch_proxy_post=AsyncMock(side_effect=get_proxy),
                                 fetch_embeddit_stats=AsyncMock(return_value=None))
    with patch.object(v3, "reddit_proxy", fake_proxy), patch.object(v3, "PROXY_MEDIA", True), \
         patch.object(v3, "fetch_arctic_post", AsyncMock(return_value={"crosspost_parent_list": [original]})), \
         patch.object(v3, "enrich_gallery_redlib", AsyncMock(return_value=[])), \
         patch.object(v3, "media_url_ok", AsyncMock(return_value=(True, 123))), \
         patch.object(v3, "resolve_video_url", AsyncMock(return_value="https://example.com/fallback.mp4")):
        result = await v3.resolve_post_media(None, base, None, "/r/Sub/comments/cross1/title/")
        check("r15 original crosspost link", result["crosspost"]["path"] == original_path)
        check("r15 crosspost video only", result["media"] == [{"kind": "video", "url": "https://example.com/video.mp4"}])
        check("r15 live proxy stats preferred", result["stats"]["ups"] == 30)
        # A proxy screenshot must not prevent the original video's fallback.
        fake_proxy.fetch_proxy_post = AsyncMock(return_value={"service": "test", "media": [
            {"kind": "image", "url": "https://example.com/screenshot.jpg"}], "stats": None, "body": ""})
        result = await v3.resolve_post_media(None, base, None, "/r/Sub/comments/cross1/title/")
        check("r15 screenshot rejected", result["media"] == [{"kind": "video", "url": "https://example.com/fallback.mp4"}])
        check("r15 archived stats labelled", result["stats"].get("archived") is True)
    fake_proxy.fetch_proxy_post = AsyncMock(return_value={"service": "test", "media": items[:2],
                                                         "body": "FirstSecond", "stats": None})
    with patch.object(v3, "reddit_proxy", fake_proxy), patch.object(v3, "PROXY_MEDIA", True), \
         patch.object(v3, "fetch_arctic_post", AsyncMock(return_value=archive_gallery)), \
         patch.object(v3, "enrich_gallery_redlib", AsyncMock(return_value=[])):
        result = await v3.resolve_post_media(None, dict(base, body="First\n\nSecond"), None,
                                             "/r/Sub/comments/gallery1/title/")
        check("r15 archive gallery beats short proxy", result["media"] == items)
        check("r15 RSS body wins", result["body"] == "First\n\nSecond")
    with patch.object(v3, "PROXY_MEDIA", False), \
         patch.object(v3, "fetch_arctic_post", AsyncMock(return_value=archive_gallery)):
        result = await v3.resolve_post_media(None, base, None, "/r/Sub/comments/gallery1/title/")
        check("r15 gallery independent of proxies", result["media"] == items)
    with patch.object(v3, "reddit_proxy", fake_proxy), patch.object(v3, "PROXY_MEDIA", True), \
         patch.object(v3, "fetch_arctic_post", AsyncMock(return_value=None)), \
         patch.object(v3, "enrich_gallery_redlib", AsyncMock(return_value=[])):
        result = await v3.resolve_post_media(None, base, None, "/r/Sub/comments/new1/title/")
        check("r15 archive miss keeps existing proxy path", result["media"] == items[:2])

async def round15_fetch():
    class Response:
        status = 200
        data = {"data": []}
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def json(self, **kwargs): return self.data
    response = Response()
    session = SimpleNamespace(get=lambda *args, **kwargs: response)
    with patch.object(v3, "_arctic_fail_count", 0):
        check("r15 archive empty response", await v3.fetch_arctic_post(session, "abc") is None)
        check("r15 archive misses not outages", v3._arctic_fail_count == 0)
        response.data = {"data": [{"id": "wrong"}, {"id": "abc"}]}
        check("r15 archive verifies post ID", (await v3.fetch_arctic_post(session, "abc"))["id"] == "abc")
        response.data = []
        check("r15 archive malformed safe", await v3.fetch_arctic_post(session, "abc") is None)
        response.status = 429
        for _ in range(2): await v3.fetch_arctic_post(session, "abc")
        check("r15 archive circuit breaker", v3._arctic_fail_count == 3)
        response.status = 200
        check("r15 archive circuit breaker skips", await v3.fetch_arctic_post(session, "abc") is None)

# ---- round 16: crosspost line (subreddit masked to the original post) -----
_cp_data = {"title": "Houses", "author": "Ananta2027", "body": "", "media": [],
            "stats": None,
            "crosspost": {"url": "https://www.reddit.com/r/Ananta2027/comments/1wgjebk/houses/",
                          "path": "/r/Ananta2027/comments/1wgjebk/houses/"},
            "op_comment": None, "youtube_url": None, "full_mode": False}
_cp = v3.build_v3_payload("Ananta2027", _cp_data,
                          "https://www.reddit.com/r/Other/comments/1wgjebl/cross/", 1)
_cp_texts = [c["content"] for ct in _cp["components"] for c in ct["components"]
             if c.get("type") == 10]
check("r16 crosspost line masks the original subreddit",
      "*🔁 Crosspost of [Ananta2027]"
      "(https://www.reddit.com/r/Ananta2027/comments/1wgjebk/houses/) Subreddit*"
      in _cp_texts[0], str(_cp_texts))
_cp_raw = v3.build_v3_payload("Sub", dict(_cp_data, crosspost={"url": "https://x", "path": ""}),
                              "https://www.reddit.com/r/Sub/comments/x/", 1)
_cp_texts = [c["content"] for ct in _cp_raw["components"] for c in ct["components"]
             if c.get("type") == 10]
check("r16 crosspost raw line when subreddit unknown",
      any("*🔁 Crosspost of https://x*" in t for t in _cp_texts), str(_cp_texts))
_cp_none = v3.build_v3_payload("Sub", dict(_cp_data, crosspost=None),
                               "https://www.reddit.com/r/Sub/comments/x/", 1)
_cp_texts = [c["content"] for ct in _cp_none["components"] for c in ct["components"]
             if c.get("type") == 10]
check("r16 no crosspost line when none",
      not any("Crosspost of" in t for t in _cp_texts), str(_cp_texts))

# ---- round 16: need_video fall-through (video posts prefer the muxed video)
async def _nv_rr(session, path, label=""):
    return {"service": "redditez", "title": "T", "author": None, "subreddit": None,
            "body": "b", "stats": {"ups": 1, "comments": 2}, "media": []}

async def _nv_vx(session, path, label=""):
    return {"service": "vxreddit", "title": "T", "author": "a", "subreddit": None,
            "body": "b", "stats": None,
            "media": [{"kind": "video", "url": "https://vxreddit.com/video.mp4"}]}

async def _nv_ed(session, path, label=""):
    return None

orig_nv_rr, orig_nv_vx, orig_nv_ed = proxy._fetch_redditez, proxy._fetch_vxreddit, proxy._fetch_embeddit
proxy._fetch_redditez, proxy._fetch_vxreddit, proxy._fetch_embeddit = _nv_rr, _nv_vx, _nv_ed
_nv1 = asyncio.run(proxy.fetch_proxy_post(None, "/r/X/comments/abc/", label="t",
                                          health={}, need_video=True))
check("r16 need_video: skips media-less service, muxed video wins",
      _nv1 and _nv1["service"] == "vxreddit" and _nv1["media"][0]["kind"] == "video",
      str(_nv1))
_nv2 = asyncio.run(proxy.fetch_proxy_post(None, "/r/X/comments/abc/", label="t", health={}))
check("r16 need_video off (default): first usable service wins",
      _nv2 and _nv2["service"] == "redditez", str(_nv2))
proxy._fetch_vxreddit = _nv_ed
_nv3 = asyncio.run(proxy.fetch_proxy_post(None, "/r/X/comments/abc/", label="t",
                                          health={}, need_video=True))
check("r16 need_video: keeps body/stats fallback when no video anywhere",
      _nv3 and _nv3["service"] == "redditez"
      and _nv3["stats"] == {"ups": 1, "comments": 2}, str(_nv3))
proxy._fetch_vxreddit = _nv_vx
_nv4 = asyncio.run(proxy.fetch_proxy_post(None, "/r/X/comments/abc/", label="t",
                                          health={"redditez": {"ok": False}},
                                          need_video=True))
check("r16 need_video: warm-up-dead service still skipped",
      _nv4 and _nv4["service"] == "vxreddit", str(_nv4))
proxy._fetch_redditez, proxy._fetch_vxreddit, proxy._fetch_embeddit = orig_nv_rr, orig_nv_vx, orig_nv_ed

# ---- round 11: X V3 tweet-data fallback chain (twitter_proxy) -------------
tpx = None
try:
    tpx = load_module("smoke_twitter_proxy", "testing area/twitter_proxy.py")
except Exception as e:
    tpx = None
    check("import testing area/twitter_proxy.py", False, repr(e))

if tpx is not None:
    check("import testing area/twitter_proxy.py", True)

    # --- GIF chain: order, probes, short-circuit (no network) --------------
    async def round11_gif():
        probes = []
        orig_probe = tpx._probe_image_url

        def make_fake(ok_map):
            async def fake_probe(session, url, referer=None):
                probes.append((url, referer))
                return bool(ok_map(url))
            return fake_probe

        mp4 = "https://video.twimg.com/tweet_video/abc123DEF.mp4"

        tpx._probe_image_url = make_fake(lambda u: "gif.fxtwitter.com" in u)
        url, src = await tpx.resolve_gif_image(None, mp4)
        check("r11 gif: fxtwitter .webp is first and wins",
              url == "https://gif.fxtwitter.com/tweet_video/abc123DEF.webp" and src == "gif.fxtwitter",
              f"{url} {src}")
        check("r11 gif: short-circuits after the winner (1 probe)", len(probes) == 1, str(probes))

        probes.clear()
        tpx._probe_image_url = make_fake(lambda u: "gifconvert" in u and "/convert.webp" in u)
        url, src = await tpx.resolve_gif_image(None, mp4)
        check("r11 gif: gifconvert .webp is 2nd (referer-gated)",
              src == "gifconvert" and "convert.webp" in url
              and probes[1][1] == "https://vxtwitter.com", f"{url} {src} {probes[1:]}")
        check("r11 gif: gifconvert URL carries the quoted mp4",
              "?url=" in url and "video.twimg.com" in url.replace("%2F", "/").replace("%3A", ":"),
              url)

        probes.clear()
        tpx._probe_image_url = make_fake(lambda u: "gifconvert" in u and "/convert.gif" in u)
        url, src = await tpx.resolve_gif_image(None, mp4)
        check("r11 gif: gifconvert .gif is 3rd",
              src == "gifconvert" and "convert.gif" in url, f"{url} {src}")

        probes.clear()
        tpx._probe_image_url = make_fake(lambda u: "fastgif" in u)
        url, src = await tpx.resolve_gif_image(None, mp4)
        check("r11 gif: fastgif is last (4 probes, in order)",
              src == "fastgif" and len(probes) == 4
              and "gif.fxtwitter.com" in probes[0][0]
              and "/convert.webp" in probes[1][0]
              and "/convert.gif" in probes[2][0]
              and "fastgif" in probes[3][0], str([p[0] for p in probes]))

        probes.clear()
        tpx._probe_image_url = make_fake(lambda u: False)
        url, src = await tpx.resolve_gif_image(None, mp4)
        check("r11 gif: nothing answers -> (None, '')", url is None and src == "", f"{url} {src}")

        probes.clear()
        tpx._probe_image_url = make_fake(lambda u: True)
        url, src = await tpx.resolve_gif_image(None, "https://video.twimg.com/ext_tw_video/xyz.mp4")
        check("r11 gif: non-tweet_video URLs are untouched",
              url is None and src == "" and not probes, f"{url} {src} {probes}")
        tpx._probe_image_url = orig_probe

    asyncio.run(round11_gif())

    # --- vxtwitter normalization --------------------------------------------
    vx_sample = {
        "tweetID": "2099906088489439483",
        "tweetURL": "https://vxtwitter.com/PomPom_HonkaiSR/status/2099906088489439483",
        "text": "three photos here",
        "lang": "en",
        "user_name": "PomPom", "user_screen_name": "PomPom_HonkaiSR",
        "date": "Tue Sep 16 2026", "date_epoch": 1760640000,
        "replies": 3, "retweets": 677, "likes": 6500,
        "replyingTo": None, "replyingToID": None,
        "qrt": {"tweetID": "111", "tweetURL": "https://vxtwitter.com/x/status/111",
                "text": "quoted", "user_name": "X", "user_screen_name": "x",
                "date_epoch": 1760000000, "replies": 1, "retweets": 2, "likes": 3,
                "media_extended": []},
        "media_extended": [
            {"type": "image", "url": "https://pbs.twimg.com/media/p1.jpg",
             "size": {"width": 640, "height": 1080}},
            {"type": "image", "url": "https://pbs.twimg.com/media/p2.jpg",
             "size": {"width": 640, "height": 1080}},
            {"type": "image", "url": "https://pbs.twimg.com/media/p3.jpg",
             "size": {"width": 640, "height": 1080}},
            {"type": "gif", "url": "https://video.twimg.com/tweet_video/g1.mp4",
             "thumbnail_url": "https://pbs.twimg.com/tweet_video_thumb/g1.jpg",
             "duration_millis": 3000, "size": {"width": 1200, "height": 675}},
        ],
    }
    t1 = tpx.normalize_vxtwitter(vx_sample)
    check("r11 vx: base shape (id/text/author/stats/epoch/views N/A)",
          t1 and t1["id"] == "2099906088489439483"
          and t1["author"] == {"name": "PomPom", "screen_name": "PomPom_HonkaiSR"}
          and (t1["replies"], t1["retweets"], t1["likes"]) == (3, 677, 6500)
          and t1["created_timestamp"] == 1760640000 and t1["views"] == "N/A",
          str(t1)[:200] if t1 else "None")
    check("r11 vx: multi-photo keeps one entry per photo, in order",
          [p["url"] for p in t1["media"]["photos"]]
          == ["https://pbs.twimg.com/media/p1.jpg", "https://pbs.twimg.com/media/p2.jpg",
              "https://pbs.twimg.com/media/p3.jpg"], str(t1["media"]["photos"]))
    v0 = t1["media"]["videos"][0]
    check("r11 vx: gif type + duration (ms -> s) + formats",
          v0["type"] == "gif" and v0["duration"] == 3 and v0["formats"][0]["container"] == "mp4",
          str(v0))
    check("r11 vx: quote normalized recursively",
          t1["quote"] and t1["quote"]["id"] == "111" and t1["quote"]["text"] == "quoted"
          and t1["quote"]["media"] == {"videos": [], "photos": []}, str(t1["quote"]))
    check("r11 vx: malformed payload -> None",
          tpx.normalize_vxtwitter({"nope": 1}) is None and tpx.normalize_vxtwitter(None) is None)
    t2 = tpx.normalize_vxtwitter(dict(vx_sample, media_extended=[
        {"type": "video", "url": "https://video.twimg.com/ext_tw_video/v1.mp4",
         "duration_millis": 120000, "size": {"width": 1920, "height": 1080}}]))
    check("r11 vx: plain video (not gif) + dimensions",
          t2["media"]["videos"][0]["type"] == "video"
          and t2["media"]["videos"][0]["width"] == 1920
          and t2["media"]["videos"][0]["duration"] == 120, str(t2["media"]["videos"]))

    # --- twitterez og: parsing (dict meta) ----------------------------------
    ez_meta = {
        "og:url": "https://x.com/someone/status/2090000000000000001",
        "og:title": "Someone (@someone)",
        "og:description": ("**💬 2  🔁 140  💜 1K  👀 16.7K**\n"
                           "actual tweet text line one\n"
                           "actual tweet text line two"),
        "og:image": "https://embedez.com/api/v2/redirect/k?path=content.media.0.source",
    }
    t3 = tpx.normalize_twitterez(ez_meta, "2090000000000000001")
    check("r11 ez: stats line parsed + stripped (1K/16.7K) + author kept",
          t3 and (t3["replies"], t3["retweets"], t3["likes"], t3["views"]) == (2, 140, 1000, 16700)
          and "actual tweet text line one" in t3["text"]
          and "💬" not in t3["text"]
          and t3["author"]["name"] == "Someone (@someone)",
          str(t3["text"])[:120] if t3 else "None")
    check("r11 ez: photo from og:image",
          t3 and t3["media"]["photos"]
          == [{"url": "https://embedez.com/api/v2/redirect/k?path=content.media.0.source"}],
          str(t3["media"]) if t3 else "None")
    ez_gif = {"og:title": "G", "og:description": "gif text",
              "og:video:secure_url": "https://video.twimg.com/tweet_video/g1.mp4"}
    t4 = tpx.normalize_twitterez(ez_gif, "2")
    check("r11 ez: tweet_video og:video -> gif type",
          t4 and t4["media"]["videos"][0]["type"] == "gif" and t4["media"]["photos"] == [],
          str(t4["media"]) if t4 else "None")
    ez_multi = {
        "og:title": "M", "og:description": "multi",
        "og:image": ["https://embedez.com/api/v2/redirect/m?path=content.media.0.source",
                     "https://embedez.com/api/v2/redirect/m?path=content.media.1.source",
                     "https://embedez.com/api/v2/redirect/m?path=content.media.2.source",
                     "https://embedez.com/api/v2/redirect/m?path=content.media.3.source"],
    }
    t7 = tpx.normalize_twitterez(ez_multi, "3")
    check("r11 ez: 4-photo gallery order (dict meta)",
          t7 and [p["url"].rsplit("=", 1)[-1] for p in t7["media"]["photos"]]
          == ["content.media.0.source", "content.media.1.source",
              "content.media.2.source", "content.media.3.source"],
          str(t7["media"]["photos"]) if t7 else "None")
    check("r11 ez: empty meta -> None",
          tpx.normalize_twitterez({}, "x") is None and tpx.normalize_twitterez(None, None) is None)

    # --- twitterez real bot-page HTML (og: tags end-to-end) -----------------
    ez_page_video = (
        "<html><head>"
        '<meta property="og:title" content="Video Poster Guy (@vp)" />'
        '<meta property="og:url" content="https://x.com/vp/status/9001" />'
        '<meta property="og:description" content="**💬 4  🔁 210  💜 2K  👀 1.5M**\n'
        "a video tweet\n"
        "[Add](https://embedez.com/t/test-bot) the EmbedEZ bot to your server *(ad)*"
        '" />'
        '<meta property="og:video:secure_url" '
        'content="https://proxy.embedez.com/advanced.mp4?url=https%3A%2F%2Fvideo.twimg.com%2Fext_tw_video%2Fv9.mp4" />'
        '<meta property="og:image" '
        'content="https://proxy.embedez.com/thumbnail?url=https%3A%2F%2Fvideo.twimg.com%2Fext_tw_video%2Fv9.mp4" />'
        "</head><body></body></html>"
    )
    m1 = tpx._og_meta(ez_page_video)
    t5 = tpx.normalize_twitterez(m1, "9001")
    check("r11 ez page: video tweet -> video kept, poster skipped",
          t5 and len(t5["media"]["videos"]) == 1 and t5["media"]["photos"] == [],
          str(t5["media"]) if t5 else "None")
    check("r11 ez page: 1.5M views + 2K likes parsed",
          t5 and t5["views"] == 1500000 and t5["likes"] == 2000,
          f"{t5['views']} {t5['likes']}" if t5 else "None")
    check("r11 ez page: ad line stripped from text",
          t5 and "embedez.com" not in t5["text"].lower()
          and "*(ad)*" not in t5["text"] and "a video tweet" in t5["text"],
          repr(t5["text"]) if t5 else "None")
    ez_page_photos = (
        "<html><head>"
        '<meta property="og:title" content="Gallery Gal (@gg)" />'
        '<meta property="og:description" content="**💬 3  🔁 677  💜 6.5K  👀 48.8K**\nfour photos" />'
        '<meta property="og:image" content="https://embedez.com/api/v2/redirect/k1?path=content.media.0.source" />'
        '<meta property="og:image" content="https://embedez.com/api/v2/redirect/k1?path=content.media.1.source" />'
        '<meta property="og:image" content="https://embedez.com/api/v2/redirect/k1?path=content.media.1.source" />'
        '<meta property="og:image" content="https://embedez.com/api/v2/redirect/k1?path=content.media.3.source" />'
        "</head><body></body></html>"
    )
    m2 = tpx._og_meta(ez_page_photos)
    t6 = tpx.normalize_twitterez(m2, "9002")
    check("r11 ez page: 6.5K/48.8K compact stats parsed",
          t6 and t6["likes"] == 6500 and t6["views"] == 48800,
          f"{t6['likes']} {t6['views']}" if t6 else "None")
    check("r11 ez page: 4 photos, in order",
          t6 and len(t6["media"]["photos"]) == 4
          and t6["media"]["photos"][1]["url"].endswith("content.media.1.source"),
          str(t6["media"]["photos"]) if t6 else "None")
    check("r11 ez page: empty page -> None",
          tpx.normalize_twitterez(tpx._og_meta(""), None) is None)

    # --- fallback chain order (monkeypatched fetchers, no network) ----------
    async def round11_chain():
        calls = []
        fake_fx = {"id": "77", "text": "fx",
                   "author": {"name": "F", "screen_name": "f"},
                   "media": {"videos": [], "photos": []}}
        fake_vx = {"id": "77", "text": "vx",
                   "author": {"name": "V", "screen_name": "v"},
                   "media": {"videos": [], "photos": []}}
        fake_ez = {"id": "77", "text": "ez",
                   "author": {"name": "E", "screen_name": "e"},
                   "media": {"videos": [], "photos": []}}

        def make_ok(name, payload):
            async def ok(session, screen, tid, label=""):
                calls.append(name)
                return dict(payload)
            return ok

        def make_no(name):
            async def no(session, screen, tid, label=""):
                calls.append(name)
                return None
            return no

        async def fx_boom(session, screen, tid, label=""):
            calls.append("fxtwitter")
            raise RuntimeError("boom")

        orig = (tpx._fetch_fxtwitter, tpx._fetch_fixupx,
                tpx._fetch_vxtwitter, tpx._fetch_twitterez)
        try:
            tpx._fetch_fxtwitter = make_ok("fxtwitter", fake_fx)
            tpx._fetch_fixupx = make_no("fixupx")
            tpx._fetch_vxtwitter = make_no("vxtwitter")
            tpx._fetch_twitterez = make_no("twitterez")
            calls.clear()
            tweet, src = await tpx.fetch_tweet_details_any(None, "scr", "77", "t")
            check("r11 chain: fxtwitter wins (primary)",
                  src == "fxtwitter" and tweet["id"] == "77", f"{src}")
            check("r11 chain: stops at the winner (1 call)", calls == ["fxtwitter"], str(calls))

            calls.clear()
            tpx._fetch_fxtwitter = make_no("fxtwitter")
            tpx._fetch_vxtwitter = make_ok("vxtwitter", fake_vx)
            tweet, src = await tpx.fetch_tweet_details_any(None, "scr", "77", "t")
            check("r11 chain: vxtwitter fallback (fx+fixupx fail)",
                  src == "vxtwitter" and calls == ["fxtwitter", "fixupx", "vxtwitter"],
                  f"{src} {calls}")

            calls.clear()
            tpx._fetch_vxtwitter = make_no("vxtwitter")
            tpx._fetch_twitterez = make_ok("twitterez", fake_ez)
            tweet, src = await tpx.fetch_tweet_details_any(None, "scr", "77", "t")
            check("r11 chain: twitterez is the last resort (4 calls)",
                  src == "twitterez" and len(calls) == 4, f"{src} {calls}")

            calls.clear()
            tpx._fetch_twitterez = make_no("twitterez")
            tweet, src = await tpx.fetch_tweet_details_any(None, "scr", "77", "t")
            check("r11 chain: all fail -> (None, None)",
                  tweet is None and src is None and len(calls) == 4, str(calls))

            calls.clear()
            tpx._fetch_fxtwitter = fx_boom
            tpx._fetch_vxtwitter = make_ok("vxtwitter", fake_vx)
            tweet, src = await tpx.fetch_tweet_details_any(None, "scr", "77", "t")
            check("r11 chain: a fetcher exception is swallowed (chain continues)",
                  src == "vxtwitter", f"{src} {calls}")
        finally:
            (tpx._fetch_fxtwitter, tpx._fetch_fixupx,
             tpx._fetch_vxtwitter, tpx._fetch_twitterez) = orig

    asyncio.run(round11_chain())

# ---- round 17: Arctic Shift search backup (v3) ----------------------------
class _ArcticResp:
    def __init__(self, status, data):
        self.status = status
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def json(self, **k):
        return self.data

arctic_calls = []

def _arctic_session(status, data):
    def get(url, params=None, **k):
        arctic_calls.append((url, params))
        return _ArcticResp(status, data)
    return SimpleNamespace(get=get)

arc_posts = [
    {"id": "1wgaaa1", "subreddit": "AnantaLeaks", "title": "Archive A",
     "author": "userA", "created_utc": 1760630000, "updated_utc": 1760630010,
     "body": "<p>body A</p>"},
    {"id": "1wgbbb2", "subreddit": "AnantaLeaks", "title": "Archive B",
     "author": "userB", "created_utc": 1760620000, "updated_utc": 1760620005,
     "body": "<p>body B</p>"},
]
orig_arctic_fail = v3._arctic_fail_count
v3._arctic_fail_count = 0
arctic_calls.clear()
got = asyncio.run(v3.fetch_arctic_subreddit_posts(
    _arctic_session(200, {"data": arc_posts}), "AnantaLeaks",
    after_epoch=1760600000, label="t"))
check("r17 arctic: valid response -> post dicts",
      [p["id"] for p in got] == ["1wgaaa1", "1wgbbb2"], str(got))
check("r17 arctic: params (subreddit/limit/sort/md2html/after)",
      arctic_calls and arctic_calls[0][0].endswith("/api/posts/search")
      and arctic_calls[0][1].get("subreddit") == "AnantaLeaks"
      and arctic_calls[0][1].get("sort") == "desc"
      and arctic_calls[0][1].get("md2html") == "true"
      and arctic_calls[0][1].get("after") == "1760600000", str(arctic_calls[:1]))
check("r17 arctic: empty data -> []",
      asyncio.run(v3.fetch_arctic_subreddit_posts(
          _arctic_session(200, {"data": []}), "AnantaLeaks", label="t")) == [])
v3._arctic_fail_count = 0
check("r17 arctic: 429 -> [] (soft fail, counts as outage)",
      asyncio.run(v3.fetch_arctic_subreddit_posts(
          _arctic_session(429, {}), "AnantaLeaks", label="t")) == []
      and v3._arctic_fail_count == 1)
v3._arctic_fail_count = 3
calls_before = len(arctic_calls)
check("r17 arctic: circuit breaker skips when tripped",
      asyncio.run(v3.fetch_arctic_subreddit_posts(
          _arctic_session(200, {"data": arc_posts}), "AnantaLeaks", label="t")) == []
      and len(arctic_calls) == calls_before)
v3._arctic_fail_count = orig_arctic_fail

e = v3._ArcticEntry(arc_posts[0])
check("r17 entry: link/title/author",
      e.link == "https://www.reddit.com/r/AnantaLeaks/comments/1wgaaa1/"
      and e.title == "Archive A" and e.author == "userA", str(e.link))
check("r17 entry: timestamps + body",
      e.get("published_parsed") is not None and e.get("updated_parsed") is not None
      and e.get("content")[0]["value"] == "<p>body A</p>", str(e.get("content")))
cp_entry = v3._ArcticEntry(dict(arc_posts[0], body=(
    "u/x crossposted this from r/Ananta2027 — original post "
    "https://www.reddit.com/r/Ananta2027/comments/1wgjebk/houses/")))
check("r17 entry: crosspost permalink detected (original path)",
      v3.find_crosspost_original_path(cp_entry.get("content")[0]["value"], e.link)
      == "/r/Ananta2027/comments/1wgjebk/",
      str(v3.find_crosspost_original_path(cp_entry.get("content")[0]["value"], e.link)))
check("r17 entry: .get default like feedparser", e.get("nope") is None)

# ---- round 18: soft-removed/deleted post detection (v3) -------------------
check("r18 removed: [deleted] body",
      v3.removed_post_reason("Real title", "[deleted]") == "whole-body marker")
check("r18 removed: [removed] body",
      v3.removed_post_reason("Real title", "[removed]") == "whole-body marker")
check("r18 removed: bolded [ Removed by moderator ]",
      v3.removed_post_reason("Real title", "**[ Removed by moderator ]**") == "whole-body marker")
check("r18 removed: [deleted] title",
      v3.removed_post_reason("[deleted]", "some body") == "title marker")
check("r18 removed: moderators notice (live example)",
      v3.removed_post_reason("T",
                             "Sorry, this post has been removed by the moderators of r/HonkaiStarRail_leaks.")
      == "removal notice")
check("r18 removed: author-deleted notice",
      v3.removed_post_reason("T",
                             "Sorry, this post was deleted by the person who originally posted it.")
      == "removal notice")
check("r18 removed: real title + deleted body (live example)",
      v3.removed_post_reason("Version 7.1 New Weapon Overview",
                             "**Version 7.1 New Weapon Overview** "
                             "Sorry, this post was deleted by the person who originally posted it.")
      == "removal notice")
check("r18 kept: empty body is NOT removed (link posts)",
      v3.removed_post_reason("Link post", "") is None)
check("r18 kept: normal body mentioning a pull",
      v3.removed_post_reason("T", "The previous leak was pulled. Here is the new build list...") is None)

# ---- round 20: simple plain-link mangle fix (post 1whe2tr, final form) ---
_r20_mangled = ("Firefly video [[https://b23.tv/dkCXgES](https://b23.tv/dkCXgES)]"
                "(https://b23.tv/dkCXgES](https://b23.tv/dkCXgES))\n\n"
                "Feixiao video [[https://b23.tv/XojBeMr](https://b23.tv/XojBeMr)]"
                "(https://b23.tv/XojBeMr](https://b23.tv/XojBeMr))\n\n"
                "Therta video [[https://b23.tv/PNtXo0u](https://b23.tv/PNtXo0u)]"
                "(https://b23.tv/PNtXo0u](https://b23.tv/PNtXo0u))")
_r20_expected = ("Firefly video [https://b23.tv/dkCXgES](https://b23.tv/dkCXgES)\n\n"
                 "Feixiao video [https://b23.tv/XojBeMr](https://b23.tv/XojBeMr)\n\n"
                 "Therta video [https://b23.tv/PNtXo0u](https://b23.tv/PNtXo0u)")
check("r20 link: doubled mangle -> one plain link per line (v3)",
      v3.clean_rss_body(_r20_mangled) == _r20_expected,
      v3.clean_rss_body(_r20_mangled))
check("r20 link: same result via the proxy cleaner",
      proxy.clean_proxy_body(_r20_mangled) == _r20_expected,
      proxy.clean_proxy_body(_r20_mangled))
_r20_plain = ("Firefly video [https://b23.tv/dkCXgES](https://b23.tv/dkCXgES](https://b23.tv/dkCXgES))\n\n"
              "Feixiao video [https://b23.tv/XojBeMr](https://b23.tv/XojBeMr](https://b23.tv/XojBeMr))\n\n"
              "Therta video [https://b23.tv/PNtXo0u](https://b23.tv/PNtXo0u](https://b23.tv/PNtXo0u))")
check("r20 link: feed plain face (URL x3) -> one plain link per line",
      v3.clean_rss_body(_r20_plain) == _r20_expected,
      v3.clean_rss_body(_r20_plain))
_r20_deep = ("Firefly video [[[https://b23.tv/dkCXgES](https://b23.tv/dkCXgES](https://b23.tv/dkCXgES)]"
             "(https://b23.tv/dkCXgES](https://b23.tv/dkCXgES](https://b23.tv/dkCXgES)]"
             "(https://b23.tv/dkCXgES](https://b23.tv/dkCXgES](https://b23.tv/dkCXgES))"
             "(https://b23.tv/dkCXgES](https://b23.tv/dkCXgES](https://b23.tv/dkCXgES))))")
check("r20 link: deep nested mangle -> one plain link",
      v3.clean_rss_body(_r20_deep)
      == "Firefly video [https://b23.tv/dkCXgES](https://b23.tv/dkCXgES)",
      v3.clean_rss_body(_r20_deep))
check("r20 kept: a single clean link line is untouched",
      v3.clean_rss_body("Firefly video [https://b23.tv/x](https://b23.tv/x)")
      == "Firefly video [https://b23.tv/x](https://b23.tv/x)",
      v3.clean_rss_body("Firefly video [https://b23.tv/x](https://b23.tv/x)"))
_r20_clean = ("Firefly video\nhttps://b23.tv/dkCXgES\n\n"
              "Feixiao video\nhttps://b23.tv/XojBeMr")
check("r20 kept: clean bare-URL body keeps the same look",
      v3.clean_rss_body(_r20_clean)
      == "Firefly video\n[https://b23.tv/dkCXgES](https://b23.tv/dkCXgES)\n\n"
         "Feixiao video\n[https://b23.tv/XojBeMr](https://b23.tv/XojBeMr)",
      v3.clean_rss_body(_r20_clean))
check("r20 kept: mangled body is NOT treated as removed (1whe2tr)",
      v3.removed_post_reason("4.6 Event Firefly, Feixiao and The Herta gameplay",
                             _r20_mangled) is None)

# ---- round 20: archive post liveness gate (offline, stubbed sources) -----
_r20_proxy_result = {"holder": None}

class _R20FakeProxy:
    async def fetch_proxy_post(self, session, path, label="", health=None, need_video=False):
        return _r20_proxy_result["holder"]

async def _r20_gate():
    orig_proxy, orig_base = v3.reddit_proxy, v3.fetch_test_post_base
    v3.reddit_proxy = _R20FakeProxy()
    try:
        v3.fetch_test_post_base = AsyncMock(return_value=None)
        _r20_proxy_result["holder"] = None
        live, why = await v3.verify_archive_post_live(None, "/r/Sub/comments/x/", label="t")
        check("r20 gate: no live source can see the post -> not live",
              live is False and "pending approval" in why, why)
        _r20_proxy_result["holder"] = {"service": "redditez", "title": "T", "author": None,
                                       "subreddit": None, "body": "", "stats": None, "media": []}
        live, why = await v3.verify_archive_post_live(None, "/r/Sub/comments/x/", label="t")
        check("r20 gate: proxy chain retrieves the post -> live",
              live is True and "redditez" in why, why)
        _r20_proxy_result["holder"] = {"service": "redditez", "title": "T", "author": None,
                                       "subreddit": None, "body": "[ Removed by moderator ]",
                                       "stats": None, "media": []}
        live, why = await v3.verify_archive_post_live(None, "/r/Sub/comments/x/", label="t")
        check("r20 gate: live source still shows a removal notice -> not live",
              live is False and "removal notice" in why, why)
        _r20_proxy_result["holder"] = None
        v3.fetch_test_post_base = AsyncMock(return_value={"title": "T", "body": "b"})
        live, why = await v3.verify_archive_post_live(None, "/r/Sub/comments/x/", label="t")
        check("r20 gate: redlib retrieves the post -> live",
              live is True and "redlib" in why, why)
    finally:
        v3.reddit_proxy, v3.fetch_test_post_base = orig_proxy, orig_base

asyncio.run(_r20_gate())

asyncio.run(round15_flows())
asyncio.run(round15_fetch())


print()
if failures:
    print(f"SMOKE TEST FAILURES ({len(failures)}): {failures}")
    sys.exit(1)
print("SMOKE TEST: ALL PASS")
