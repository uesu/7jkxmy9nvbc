"""Offline smoke test — no network, no secrets.

Run:  python tests/test_smoke.py
Purpose (also used by CI as the safety gate for Dependabot PRs):
  1. every monitor script imports cleanly (catches import-time breakage
     from dependency bumps),
  2. the Reddit V3 card pipeline still behaves (body cleaning, media
     extraction/dedup, OP comment, components-v2 layout, button set).
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

asyncio.run(round15_flows())
asyncio.run(round15_fetch())


print()
if failures:
    print(f"SMOKE TEST FAILURES ({len(failures)}): {failures}")
    sys.exit(1)
print("SMOKE TEST: ALL PASS")
