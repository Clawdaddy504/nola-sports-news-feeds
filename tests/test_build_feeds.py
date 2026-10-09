import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from build_feeds import build, canonical_url, parse_items


NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
SOURCE = {"title": "Example News", "category": "NFL & American Football", "url": "https://example.com/rss", "enabled": True}


class FeedTests(unittest.TestCase):
    def test_rss_removes_tracking_and_old_items(self):
        rss = b"""<rss version="2.0"><channel>
          <item><title>Saints vs Falcons</title><link>https://example.com/story?utm_source=feed&amp;id=4</link><pubDate>Fri, 09 Oct 2026 11:00:00 GMT</pubDate></item>
          <item><title>Old story</title><link>https://example.com/old</link><pubDate>Mon, 01 Oct 2026 11:00:00 GMT</pubDate></item>
        </channel></rss>"""
        items = parse_items(rss, SOURCE, NOW, 96)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.com/story?id=4")

    def test_atom_alternate_link_and_utc_date(self):
        atom = b"""<feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>Pelicans win</title><link rel="alternate" href="https://example.com/pels"/><updated>2026-10-09T08:00:00-04:00</updated></entry>
        </feed>"""
        items = parse_items(atom, SOURCE, NOW, 96)
        self.assertEqual(items[0]["published_at"], "2026-10-09T12:00:00Z")

    def test_rdf_namespace(self):
        rdf = b"""<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
          <item><title>LSU preview</title><link>https://example.com/lsu</link><dc:date>2026-10-09T10:00:00Z</dc:date></item>
        </rdf:RDF>"""
        self.assertEqual(parse_items(rdf, SOURCE, NOW, 96)[0]["title"], "LSU preview")

    def test_rejects_unsafe_links(self):
        self.assertIsNone(canonical_url("javascript:alert(1)"))
        self.assertIsNone(canonical_url("/relative"))

    def test_build_deduplicates_and_publishes_category_feeds(self):
        item = {
            "id": "one", "title": "Saints vs Falcons", "url": "https://example.com/story",
            "published_at": "2026-10-09T11:00:00Z", "source": SOURCE["title"],
            "source_category": SOURCE["category"],
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_path = root / "sources.json"
            source_path.write_text(json.dumps({"sources": [SOURCE] * 5}))
            with patch("build_feeds.fetch_source", return_value=([item, item], None)):
                index = build(source_path, root / "docs", now=NOW)
            self.assertEqual(index["successful_sources"], 5)
            self.assertEqual(json.loads((root / "docs" / "new-orleans.json").read_text())["count"], 1)
            self.assertEqual(json.loads((root / "docs" / "all.json").read_text())["count"], 1)
            ET.parse(root / "docs" / "all.xml")


if __name__ == "__main__":
    unittest.main()
