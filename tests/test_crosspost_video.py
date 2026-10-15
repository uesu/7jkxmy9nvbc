"""General crosspost-video discovery — no hard-coded incident IDs required."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

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

import importlib.util


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


v3 = load("crosspost_v3", "testing area/reddit_main_v3.py")
proxy = load("crosspost_proxy", "testing area/reddit_proxy.py")


class OriginalDiscoveryTests(unittest.TestCase):
    def test_labeled_original_without_keyword(self):
        path = v3.find_crosspost_original_path(
            "See the [Original Post](/r/Alpha/comments/parent01/title/)",
            "/r/Beta/comments/child001/",
        )
        self.assertEqual(path, "/r/Alpha/comments/parent01/")

    def test_html_anchor_original_post(self):
        path = v3.find_crosspost_original_path(
            '<a href="https://www.reddit.com/r/Alpha/comments/parent02/x/">Original Post</a>',
            "/r/Beta/comments/child002/",
        )
        self.assertEqual(path, "/r/Alpha/comments/parent02/")

    def test_profile_original_still_resolves(self):
        path = v3.find_crosspost_original_path(
            'crossposted this from <a href="/user/someuser/comments/parent03/clip/">u/someuser</a>',
            "/r/Beta/comments/child003/",
        )
        self.assertEqual(path, "/user/someuser/comments/parent03/")

    def test_own_slugged_link_is_skipped(self):
        html = (
            'crosspost <a href="/r/Beta/comments/child004/child_slug/">self</a> '
            '<a href="/r/Alpha/comments/parent04/orig_slug/">orig</a>'
        )
        path = v3.find_crosspost_original_path(html, "/r/Beta/comments/child004/child_slug/")
        self.assertEqual(path, "/r/Alpha/comments/parent04/")

    def test_body_link_without_crosspost_context_is_not_a_parent(self):
        self.assertIsNone(v3.find_crosspost_original_path(
            "related reading /r/Alpha/comments/parent05/title/",
            "/r/Beta/comments/child005/",
        ))

    def test_foreign_host_rejected(self):
        self.assertIsNone(v3.find_crosspost_original_path(
            "crosspost https://not-reddit.example/r/Alpha/comments/parent06/",
            "/r/Beta/comments/child006/",
        ))

    def test_self_parent_id_is_dropped(self):
        source = v3.resolve_crosspost_source(
            own_path="/r/Beta/comments/child007/",
            base={},
            post_json={"crosspost_parent": "t3_child007"},
        )
        self.assertEqual(source, {})

    def test_structured_parent_one_hop(self):
        source = v3.resolve_crosspost_source(
            own_path="/r/Beta/comments/child008/",
            base={},
            post_json={
                "crosspost_parent_list": [{
                    "id": "parent08",
                    "permalink": "/r/Alpha/comments/parent08/orig/",
                    "media": {"reddit_video": {
                        "fallback_url": "https://v.redd.it/videoid08/DASH_720.mp4",
                    }},
                }],
            },
        )
        self.assertEqual(source.get("id"), "parent08")
        self.assertEqual(source.get("vred_id"), "videoid08")
        self.assertFalse(v3.is_same_reddit_post(source.get("path"), "/r/Beta/comments/child008/"))


class VideoEligibilityTests(unittest.TestCase):
    def test_audio_cover_filtered(self):
        cover = "https://proxy.embedez.com/render/audio?cover=https://i.redd.it/x.jpg"
        self.assertTrue(proxy.is_audio_cover_url(cover))
        self.assertFalse(proxy.is_motion_video_item({"kind": "video", "url": cover}))
        media = proxy.filter_proxy_media([
            {"kind": "video", "url": cover},
            {"kind": "image", "url": "https://i.redd.it/x.jpg"},
        ])
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]["kind"], "image")

    def test_proxy_og_skips_audio_cover(self):
        media = proxy._media_from_og({
            "og:video": "https://proxy.embedez.com/render/audio?cover=x",
            "og:image": ["https://i.redd.it/still.jpg"],
        })
        self.assertTrue(all(item["kind"] != "video" for item in media))

    def test_encoded_video_id_and_preview_negative(self):
        encoded = "https://x.test/?videoUrl=https%3A%2F%2Fv.redd.it%2Fvideoid09%2FDASH_1080.mp4"
        self.assertEqual(v3.extract_vreddit_id_from_media_url(encoded), "videoid09")
        self.assertIsNone(v3.extract_vreddit_id_from_media_url(
            "https://external-preview.redd.it/videoid09.jpg"))

    def test_images_are_not_usable_when_video_was_requested(self):
        result = {"media": [{"kind": "image", "url": "https://i.redd.it/x.jpg"}]}
        self.assertFalse(v3._proxy_result_usable(result, True))
        self.assertTrue(v3._proxy_result_usable(result, False))

    def test_path_aliases_only_for_profile_posts(self):
        aliases = v3._path_aliases("/user/sampleuser/comments/parent10/")
        self.assertEqual(aliases[0], "/user/sampleuser/comments/parent10/")
        self.assertIn("/r/u_sampleuser/comments/parent10/", aliases)
        self.assertEqual(v3._path_aliases("/r/Beta/comments/child010/"),
                         ["/r/Beta/comments/child010/"])


class ChildIdentityTests(unittest.TestCase):
    def test_card_path_helpers_keep_child_id(self):
        child = "/r/Beta/comments/child011/slug/"
        parent = "/r/Alpha/comments/parent11/"
        self.assertEqual(v3.extract_post_id(child), "child011")
        self.assertNotEqual(v3.extract_post_id(child), v3.extract_post_id(parent))
        self.assertTrue(v3.is_same_reddit_post(child, "/r/Beta/comments/child011/"))


if __name__ == "__main__":
    unittest.main()
