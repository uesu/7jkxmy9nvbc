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

import importlib.util  # noqa: E402


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
        # A verb-governed link that points back at the child is not its parent,
        # even though the slug differs from the bare id form.
        html = 'crossposted this from <a href="/r/Beta/comments/child004/child_slug/">self</a>'
        path = v3.find_crosspost_original_path(html, "/r/Beta/comments/child004/child_slug/")
        self.assertIsNone(path)

    def test_bare_keyword_near_an_unrelated_link_is_not_a_parent(self):
        # Regression: the body used to be scanned for any permalink once the word
        # "crosspost" appeared anywhere in it, so an unrelated link in the same
        # post was promoted to the parent.
        body = (
            "This is a crosspost. Unrelated discussion: "
            "/r/example/comments/abc123/topic/"
        )
        self.assertIsNone(v3.find_crosspost_original_path(body, "/r/example/comments/child99/"))

    def test_verb_region_does_not_leak_across_a_sentence_or_line(self):
        # The governing region is bounded: a link in a later sentence or on a
        # later line is not what the post was crossposted from.
        for label, body in (
            ("later sentence", "u/x crossposted this. See also /r/Other/comments/zzz1/x for more."),
            ("later line", "u/x crossposted this from r/Y\nUnrelated: /r/Other/comments/zzz2/x"),
        ):
            with self.subTest(case=label):
                self.assertIsNone(
                    v3.find_crosspost_original_path(body, "/r/Beta/comments/c1/")
                )

    def test_verb_with_attribution_then_plain_permalink(self):
        # Real-world shape: an attribution sits between the verb and the link.
        self.assertEqual(
            v3.find_crosspost_original_path(
                "u/x crossposted this from r/Y — /r/AnantaLeaks/comments/1wgjk4a/x", None
            ),
            "/r/AnantaLeaks/comments/1wgjk4a/",
        )

    def test_self_link_inside_the_region_is_skipped_not_returned(self):
        body = (
            'u/x crossposted this from r/S — '
            '<a href="/r/C/comments/zc1/slug/">own</a> '
            '<a href="/r/S/comments/zp1/slug/">orig</a>'
        )
        self.assertEqual(
            v3.find_crosspost_original_path(body, "/r/C/comments/zc1/slug/"),
            "/r/S/comments/zp1/",
        )

    def test_foreign_host_behind_the_verb_is_rejected(self):
        # Regression: the sliced region was passed to the host check together
        # with an offset taken from the full text, so the backwards scan inspected
        # the wrong substring and never saw the foreign domain.
        body = ("Someone crossposted this from "
                "https://evil.example/r/example/comments/abc123/topic/")
        self.assertIsNone(
            v3.find_crosspost_original_path(body, "/r/example/comments/child99/")
        )

    def test_scheme_relative_foreign_host_is_rejected(self):
        self.assertIsNone(v3.find_crosspost_original_path(
            "crossposted this from //evil.example/r/X/comments/abc/t/",
            "/r/Y/comments/c1/",
        ))

    def test_absolute_reddit_url_behind_the_verb_still_resolves(self):
        self.assertEqual(
            v3.find_crosspost_original_path(
                "crossposted this from https://www.reddit.com/r/Alpha/comments/parent01/t/",
                "/r/Beta/comments/c1/",
            ),
            "/r/Alpha/comments/parent01/",
        )

    def test_markdown_link_to_a_reddit_mirror_resolves(self):
        self.assertEqual(
            v3.find_crosspost_original_path(
                "crossposted this from [orig](https://old.reddit.com/r/A/comments/p2/t/)",
                "/r/Y/comments/c1/",
            ),
            "/r/A/comments/p2/",
        )

    def test_crosspost_verb_still_binds_its_own_link(self):
        # The tightened rule must not lose genuine markup: the link has to be the
        # object of the verb, which is what makes it a relationship.
        for label, body, expected in (
            ("anchor", 'crossposted this from <a href="/user/u/comments/parent09/x/">u/u</a>',
             "/user/u/comments/parent09/"),
            ("bare url", "crosspost of https://www.reddit.com/r/Alpha/comments/parent10/t/",
             "/r/Alpha/comments/parent10/"),
            ("crossposted of", "This was crossposted of /r/Alpha/comments/parent11/t/",
             "/r/Alpha/comments/parent11/"),
        ):
            with self.subTest(case=label):
                self.assertEqual(
                    v3.find_crosspost_original_path(body, "/r/Beta/comments/child012/"),
                    expected,
                )

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
