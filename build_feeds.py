"""Fetch attributed sports headlines and publish small JSON/RSS feeds."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
NOLA_TERMS = re.compile(
    r"\b(?:new orleans|nola|pelicans|lsu|tulane|green wave|superdome)\b",
    re.IGNORECASE,
)
NFL_SAINTS_CONTEXT = re.compile(r"\b(?:nfl|falcons|buccaneers|bucs|panthers|vikings|football)\b", re.IGNORECASE)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def text_of(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join(unescape("".join(element.itertext())).split())


def first_element(entry: ET.Element, *paths: str) -> ET.Element | None:
    for path in paths:
        found = entry.find(path)
        if found is not None:
            return found
    return None


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def canonical_url(value: str) -> str | None:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    query = urlencode([
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_KEYS
    ])
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, query, ""))


def parse_items(xml_bytes: bytes, source: dict, now: datetime, max_age_hours: int) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    tag = root.tag.rsplit("}", 1)[-1].lower()
    if tag in ("rss", "rdf"):
        entries = root.findall("./channel/item") or root.findall(".//item") or root.findall(".//{*}item")
        atom = False
    elif tag == "feed":
        entries = root.findall(f"./{ATOM}entry") or root.findall("./entry")
        atom = True
    else:
        raise ValueError(f"Unsupported feed root: {tag}")

    cutoff = now - timedelta(hours=max_age_hours)
    items = []
    for entry in entries[:60]:
        if atom:
            title = text_of(first_element(entry, f"{ATOM}title", "title"))
            links = entry.findall(f"{ATOM}link") or entry.findall("link")
            link = next(
                (node.get("href", "") for node in links if node.get("rel", "alternate") == "alternate"),
                "",
            )
            published = text_of(first_element(entry, f"{ATOM}published", f"{ATOM}updated", "published", "updated"))
        else:
            title = text_of(first_element(entry, "title", "{*}title"))
            link = text_of(first_element(entry, "link", "{*}link"))
            published = text_of(first_element(entry, "pubDate", "{*}pubDate", f"{DC}date"))

        date = parse_date(published)
        url = canonical_url(link)
        if not title or not url or not date or date < cutoff or date > now + timedelta(hours=1):
            continue
        items.append(
            {
                "id": hashlib.sha1(url.encode("utf-8")).hexdigest()[:16],
                "title": title,
                "url": url,
                "published_at": date.isoformat().replace("+00:00", "Z"),
                "source": source["title"],
                "source_category": source["category"],
            }
        )
    return items[:30]


def fetch_source(source: dict, now: datetime, max_age_hours: int) -> tuple[list[dict], str | None]:
    command = [
        "curl", "--location", "--fail", "--silent", "--show-error", "--compressed",
        "--max-time", "15", "--max-filesize", "2000000", "--proto", "=https",
        "--proto-redir", "=https", "--user-agent", "BestSportsBarsNOLA/1.0 (+https://www.bestsportsbarsnola.com)",
        source["url"],
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=18, check=False)
        if result.returncode:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            return [], error[:180] or f"curl exit {result.returncode}"
        return parse_items(result.stdout, source, now, max_age_hours), None
    except (OSError, subprocess.TimeoutExpired, ET.ParseError, ValueError) as error:
        return [], str(error)[:180]


def rss_xml(title: str, description: str, site_url: str, feed_url: str, items: list[dict]) -> bytes:
    from email.utils import format_datetime

    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    for name, value in (
        ("title", title), ("link", site_url), ("description", description),
        ("language", "en-us"), ("generator", "Best Sports Bars NOLA sports feed"),
        ("atom:link", ""),
    ):
        if name == "atom:link":
            ET.SubElement(
                channel, "{http://www.w3.org/2005/Atom}link",
                {"href": feed_url, "rel": "self", "type": "application/rss+xml"},
            )
        else:
            ET.SubElement(channel, name).text = value
    for item in items:
        node = ET.SubElement(channel, "item")
        ET.SubElement(node, "title").text = item["title"]
        ET.SubElement(node, "link").text = item["url"]
        ET.SubElement(node, "guid", {"isPermaLink": "true"}).text = item["url"]
        ET.SubElement(node, "pubDate").text = format_datetime(
            datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
        )
        ET.SubElement(node, "description").text = f"Headline from {item['source']}. Read the original story."
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build(sources_path: Path, out_dir: Path, max_age_hours: int = 96, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    sources = [source for source in json.loads(sources_path.read_text())["sources"] if source["enabled"]]
    if not sources:
        raise RuntimeError("No enabled sources")
    all_items: list[dict] = []
    failures = []
    successful = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results = pool.map(lambda source: fetch_source(source, now, max_age_hours), sources)
        for source, (items, error) in zip(sources, results):
            if error:
                failures.append({"source": source["title"], "error": error})
            else:
                successful += 1
                all_items.extend(items)
    if successful < 5 or len(all_items) < 10:
        raise RuntimeError(f"Only {successful} sources and {len(all_items)} recent items; refusing empty publication")

    unique = {}
    for item in sorted(all_items, key=lambda item: item["published_at"], reverse=True):
        unique.setdefault(item["url"], item)
    items = list(unique.values())
    site_url = "https://www.bestsportsbarsnola.com"
    base_url = "https://clawdaddy504.github.io/nola-sports-news-feeds"
    definitions = {"all": ("All sports", items[:300])}
    definitions["new-orleans"] = (
        "New Orleans & Louisiana sports",
        [
            item for item in items
            if item["source_category"] == "New Orleans & Louisiana"
            or NOLA_TERMS.search(item["title"])
            or (
                re.search(r"\bsaints\b", item["title"], re.IGNORECASE)
                and (
                    item["source_category"] == "NFL & American Football"
                    or NFL_SAINTS_CONTEXT.search(item["title"])
                )
            )
        ][:120],
    )
    for category in sorted({source["category"] for source in sources}):
        definitions[slugify(category)] = (
            category,
            [item for item in items if item["source_category"] == category][:120],
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / ".nojekyll").touch()
    index = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "source_count": len(sources),
        "successful_sources": successful,
        "failed_sources": failures,
        "feeds": [],
    }
    for slug, (label, entries) in definitions.items():
        clean = entries
        payload = {"generated_at": index["generated_at"], "title": label, "count": len(clean), "items": clean}
        (out_dir / f"{slug}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        (out_dir / f"{slug}.xml").write_bytes(
            rss_xml(
                f"Best Sports Bars NOLA — {label}",
                f"Attributed sports headlines for {label.lower()}.",
                site_url,
                f"{base_url}/{slug}.xml",
                clean,
            )
        )
        index["feeds"].append(
            {"slug": slug, "title": label, "count": len(clean), "json": f"{slug}.json", "rss": f"{slug}.xml"}
        )
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    print(f"Published {len(items)} unique recent headlines from {successful}/{len(sources)} sources")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=Path(__file__).with_name("sources.json"))
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("docs"))
    parser.add_argument("--max-age-hours", type=int, default=96)
    args = parser.parse_args()
    build(args.sources, args.out, args.max_age_hours)
