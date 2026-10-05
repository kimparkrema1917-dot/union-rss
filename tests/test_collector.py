import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
import xml.etree.ElementTree as ET

import collector as c

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = json.loads((c.ROOT / "sources.json").read_text())["sources"]
NOW = "2026-10-06T03:00:00+00:00"


def fixture(source):
    return (FIXTURES / (source["id"] + ".html")).read_text(encoding="utf-8")


class ParsersTest(unittest.TestCase):
    def test_all_actual_layouts(self):
        expected = [10, 13, 15, 30]
        for source, count in zip(SOURCES, expected):
            with self.subTest(source=source["id"]):
                items = c.parse_source(source, fixture(source))
                self.assertEqual(len(items), count)
                self.assertEqual(len({x["id"] for x in items}), count)
                for item in items:
                    self.assertTrue(item["url"].startswith("https://"))
                    self.assertTrue(c.from_iso(item["published"]).tzinfo)

    def test_kptu_exact_board_and_clean_title(self):
        item = c.parse_source(SOURCES[0], fixture(SOURCES[0]))[0]
        self.assertEqual(item["id"], "56305")
        self.assertNotIn("380", item["title"])
        self.assertEqual(item["published"], "2026-10-02T00:00:00+09:00")

    def test_metal_full_title_and_pinned_exclusion(self):
        items = c.parse_source(SOURCES[1], fixture(SOURCES[1]))
        self.assertNotIn("219977", {item["id"] for item in items})
        self.assertIn("사민사회단체 기자회견", items[0]["title"])
        enabled = dict(SOURCES[1], include_pinned=True)
        self.assertEqual(len(c.parse_source(enabled, fixture(enabled))), 15)

    def test_mobile_truncated_title_is_a_failure(self):
        text = fixture(SOURCES[1]).replace("사민사회단체 기자회견", "사민…")
        with self.assertRaises(c.CollectionError):
            c.parse_source(SOURCES[1], text)

    def test_leftall_uses_post_date_not_date_in_title(self):
        items = c.parse_source(SOURCES[2], fixture(SOURCES[2]))
        item = next(item for item in items if "미국의 민주사회주의" in item["title"])
        self.assertIn("2026-08-06", item["title"])
        self.assertTrue(item["published"].startswith("2026-08-07"))

    def test_climate_three_sections_and_creation_date(self):
        items = c.parse_source(SOURCES[3], fixture(SOURCES[3]))
        self.assertEqual({x["category"] for x in items}, {"알립니다", "성명 및 자료", "활동 소식"})
        self.assertTrue(all(x["date_basis"] == "page_created" for x in items))

    def test_empty_or_changed_site_does_not_look_successful(self):
        for source in SOURCES:
            with self.subTest(source=source["id"]):
                with self.assertRaises(c.CollectionError):
                    c.parse_source(source, "<html><h1>점검 중입니다</h1></html>")

    def test_same_id_with_tracking_parameters_is_deduplicated(self):
        text = fixture(SOURCES[0])
        soup = c.BeautifulSoup(text, "html.parser")
        row = copy.copy(soup.select_one(".news_list li"))
        row.a["href"] += "&page=3&tracking=abc"
        soup.select_one(".news_list").append(row)
        self.assertEqual(len(c.parse_source(SOURCES[0], str(soup))), 10)


class StateAndFeedTest(unittest.TestCase):
    def test_merge_keeps_history_updates_title_and_preserves_first_seen(self):
        items = c.parse_source(SOURCES[2], fixture(SOURCES[2]))
        old, count = c.merge_items([], items, NOW, 200)
        changed = dict(items[0], title="수정한 제목")
        merged, count = c.merge_items(old, [changed], "2026-10-07T00:00:00+00:00", 200)
        self.assertEqual(len(merged), len(items))
        self.assertEqual(count, 0)
        self.assertEqual(merged[0]["title"], "수정한 제목")
        self.assertEqual(merged[0]["first_seen"], NOW)
        self.assertNotEqual(old[0]["title"], merged[0]["title"])
        self.assertEqual(len(c.merge_items(old, [], NOW, 3)[0]), 3)

    def test_failure_isolation_and_old_data_preserved(self):
        state = {"sources": {}}
        old = c.parse_source(SOURCES[1], fixture(SOURCES[1]))
        state["sources"]["kmwu"] = {"items": old, "last_success": "2026-10-05T00:00:00+00:00"}
        class FakeFetcher:
            def get(self, url):
                if "kptu.net" in url:
                    raise c.RobotsBlocked("blocked")
                if "kmwu.kr" in url:
                    raise URLError("temporary error")
                source = next(s for s in SOURCES if s["url"] == url)
                return fixture(source)
        self.assertEqual(c.collect(SOURCES, state, FakeFetcher(), NOW, 200), 1)
        self.assertEqual(state["sources"]["kmwu"]["items"], old)
        self.assertEqual(state["sources"]["kmwu"]["last_success"], "2026-10-05T00:00:00+00:00")
        self.assertEqual(state["sources"]["leftall"]["status"], "ok")
        self.assertEqual(state["sources"]["climatejusticealliance"]["status"], "ok")
        self.assertEqual(state["sources"]["kptu"]["status"], "blocked")

    def test_valid_rss_escaping_stable_guid_and_self_url(self):
        item = c.parse_source(SOURCES[0], fixture(SOURCES[0]))[0]
        item.update(title='한글 & <제목> "인용"\x00', summary='<script>bad()</script> & 내용')
        record = {"items": [item], "status": "ok", "last_success": NOW}
        root = ET.fromstring(c.rss_document(SOURCES[0], record, "https://example.github.io/my-rss"))
        self.assertEqual(root.findtext("channel/item/title"), '한글 & <제목> "인용"')
        self.assertEqual(root.findtext("channel/item/guid"), "urn:union-rss:kptu:56305")
        desc = root.findtext("channel/item/description")
        self.assertNotIn("<script>", desc)
        self.assertIn("&lt;script&gt;", desc)
        self.assertEqual(root.find("channel/{" + c.ATOM + "}link").get("href"), "https://example.github.io/my-rss/feeds/kptu.xml")

    def test_all_files_exist_with_blocked_source(self):
        state = {"sources": {"kptu": {"items": [], "status": "blocked", "message": "robots.txt 차단"}}}
        with tempfile.TemporaryDirectory() as path:
            out = Path(path)
            c.render_site(SOURCES, state, out, "https://test.example/rss", NOW)
            for source in SOURCES:
                ET.parse(out / "feeds" / (source["id"] + ".xml"))
            outlines = ET.parse(out / "feeds.opml").findall("body/outline")
            self.assertEqual(len(outlines), 4)
            self.assertTrue(all(x.get("xmlUrl").startswith("https://test.example/rss/feeds/") for x in outlines))
            status = json.loads((out / "status.json").read_text())
            self.assertEqual(status["sources"]["kptu"]["item_count"], 0)
            self.assertIn("수집 보류", (out / "index.html").read_text())


class RobotsTest(unittest.TestCase):
    def test_kptu_yeti_exception_does_not_allow_our_bot(self):
        cache = {"https://www.kptu.net": {"checked_at": 100, "text": "User-agent: *\nDisallow: /\nUser-agent: Yeti\nDisallow: /adm\nDisallow: /member"}}
        fetcher = c.Fetcher(cache, clock=lambda: 101)
        with patch.object(fetcher, "request") as request:
            with self.assertRaises(c.RobotsBlocked):
                fetcher.get(SOURCES[0]["url"])
            request.assert_not_called()

    def test_metal_delay_is_honored_before_content_request(self):
        cache = {"https://kmwu.kr": {"checked_at": 100, "text": "User-agent: *\nAllow:/\nDisallow: /adm/\nCrawl-delay:180"}}
        waits = []
        fetcher = c.Fetcher(cache, sleep=waits.append, clock=lambda: 120)
        fetcher.last_request["https://kmwu.kr"] = 100
        fetcher.policy(SOURCES[1]["url"])
        class Response:
            url = SOURCES[1]["url"]
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return b"ok"
            @property
            def headers(self):
                from email.message import Message
                return Message()
        with patch.object(c, "urlopen", return_value=Response()):
            self.assertEqual(fetcher.request(SOURCES[1]["url"]), "ok")
        self.assertEqual(waits, [160])

    def test_robots_network_error_does_not_allow_crawl(self):
        fetcher = c.Fetcher({})
        with patch.object(fetcher, "request", side_effect=URLError("offline")) as request:
            with self.assertRaises(URLError):
                fetcher.get(SOURCES[2]["url"])
            self.assertEqual(request.call_count, 1)

    def test_request_time_survives_between_runs(self):
        cache = {"https://kmwu.kr": {"checked_at": 100, "last_request": 115,
                                    "text": "User-agent: *\nAllow: /\nCrawl-delay: 180"}}
        fetcher = c.Fetcher(cache, clock=lambda: 120)
        fetcher.policy(SOURCES[1]["url"])
        self.assertEqual(fetcher.last_request["https://kmwu.kr"], 115)
        self.assertEqual(fetcher.delays["https://kmwu.kr"], 180)


if __name__ == "__main__":
    unittest.main()
