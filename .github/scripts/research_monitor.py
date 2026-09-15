#!/usr/bin/env python3
"""Fetch and rank cybersecurity research leads without publishing anything.

Network failures, malformed feeds and a single unavailable source are isolated so
one upstream outage can never fail the whole monitoring cycle. The output is an
internal queue for editorial review, not a public article.
"""
import datetime as dt
import email.utils
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".github" / "research" / "latest-candidates.json"
MAX_AGE_HOURS = 48

FEEDS = [
    ("CISA", "https://www.cisa.gov/cybersecurity-advisories/all.xml", 1.5),
    ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews", 1.2),
    ("BleepingComputer", "https://www.bleepingcomputer.com/feed/", 1.2),
    ("SecurityWeek", "https://feeds.feedburner.com/securityweek", 1.1),
    ("Google News Cybersecurity", "https://news.google.com/rss/search?q=" + urllib.parse.quote("cybersecurity when:24h") + "&hl=en-US&gl=US&ceid=US:en", 1.0),
]
KEYWORDS = {
    "zero-day": 12, "actively exploited": 14, "exploited in the wild": 14,
    "critical vulnerability": 9, "ransomware": 8, "remote code execution": 9,
    "authentication bypass": 9, "privilege escalation": 7, "supply chain": 9,
    "critical infrastructure": 8, "cloud": 3, "kubernetes": 4, "credential": 4,
    "infostealer": 6, "botnet": 6, "vpn": 5, "identity": 4, "aws": 3,
    "azure": 3, "microsoft": 3, "cisco": 3, "fortinet": 4, "ivanti": 4,
}


def fetch(url, attempts=3):
    last = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "CylaticResearchMonitor/1.0 (+https://cylatic.com)"
            })
            with urllib.request.urlopen(req, timeout=20) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise last or RuntimeError("feed fetch failed")


def local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def child(node, names):
    names = {x.lower() for x in names}
    for item in list(node):
        if local(item.tag) in names:
            return " ".join(item.itertext()).strip()
    return ""


def parse_date(value):
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except Exception:
            return None


def feed(name, url, weight):
    root = ET.fromstring(fetch(url))
    result = []
    for node in root.iter():
        if local(node.tag) not in {"item", "entry"}:
            continue
        title = re.sub(r"\s+", " ", child(node, {"title"})).strip()
        link = child(node, {"link"}).strip()
        if not link:
            for x in list(node):
                if local(x.tag) == "link" and x.attrib.get("href"):
                    link = x.attrib["href"].strip()
                    break
        summary = re.sub(r"\s+", " ", child(node, {"description", "summary", "content"})).strip()
        published = child(node, {"pubdate", "published", "updated"})
        date = parse_date(published)
        if not title or not link:
            continue
        if date and (dt.datetime.now(dt.timezone.utc) - date).total_seconds() > MAX_AGE_HOURS * 3600:
            continue
        text = (title + " " + summary).lower()
        score = weight * 10 + sum(v for k, v in KEYWORDS.items() if k in text)
        result.append({
            "source": name, "title": title[:300], "url": link,
            "summary": summary[:1000], "published": published, "score": round(score, 2)
        })
    return result[:40]


def main():
    candidates = []
    errors = []
    for name, url, weight in FEEDS:
        try:
            candidates.extend(feed(name, url, weight))
        except Exception as exc:
            errors.append({"source": name, "error": str(exc)[:300]})
    seen = set()
    unique = []
    for item in sorted(candidates, key=lambda x: x["score"], reverse=True):
        key = re.sub(r"[^a-z0-9]+", " ", item["title"].lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "publication_enabled": False,
        "editorial_note": "Candidates require human/editorial review and original technical work before publication.",
        "feed_errors": errors,
        "candidates": unique[:25],
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Research monitor: {len(unique)} unique candidates; {len(errors)} feed errors isolated.")
    if not unique:
        print("No candidates available. This is a successful monitoring cycle, not a publication failure.")


if __name__ == "__main__":
    main()
