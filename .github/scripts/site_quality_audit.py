#!/usr/bin/env python3
"""Deterministic pre-publication quality gate for Cylatic.

This is intentionally conservative. It checks the repository for common causes of
low-value / incomplete-site reviews and refuses to pass when the site regresses.
It never publishes content.
"""
from collections import Counter
from pathlib import Path
import html
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
FAILURES = []
WARNINGS = []

REQUIRED_FILES = [
    "index.html", "robots.txt", "sitemap.xml", "ads.txt", "privacy-policy.html",
    "about/index.html", "contact/index.html", "editorial-policy/index.html",
    "tools/index.html",
]

REQUIRED_ROUTES = ["/", "/about/", "/contact/", "/editorial-policy/", "/tools/", "/blog/", "/privacy-policy.html"]


def fail(message):
    FAILURES.append(message)


def warn(message):
    WARNINGS.append(message)


def text_of(doc):
    return re.sub(r"\s+", " ", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", doc, flags=re.I | re.S)).strip()


def meta(doc, name):
    m = re.search(r'<meta[^>]+name=["\']' + re.escape(name) + r'["\'][^>]*content=["\']([^"\']*)', doc, re.I)
    return m.group(1).strip() if m else ""


def canonical(doc):
    m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', doc, re.I)
    return m.group(1).strip() if m else ""


def title(doc):
    m = re.search(r'<title[^>]*>(.*?)</title>', doc, re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""


def audit():
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            fail(f"Missing required file: {rel}")

    robots = (ROOT / "robots.txt").read_text(encoding="utf-8", errors="ignore") if (ROOT / "robots.txt").exists() else ""
    if "Sitemap: https://cylatic.com/sitemap.xml" not in robots:
        fail("robots.txt does not advertise the canonical sitemap")
    if re.search(r"User-agent:\s*\*[^\n]*\nDisallow:\s*/\s*$", robots, re.I | re.M):
        fail("robots.txt blocks the entire site")

    sitemap_path = ROOT / "sitemap.xml"
    urls = []
    if sitemap_path.exists():
        try:
            root = ET.fromstring(sitemap_path.read_text(encoding="utf-8"))
            urls = [x.text.strip() for x in root.iter() if x.tag.lower().endswith("loc") and x.text]
        except Exception as exc:
            fail(f"sitemap.xml is not valid XML: {exc}")
    for route in REQUIRED_ROUTES:
        expected = "https://cylatic.com" + route
        if expected not in urls:
            warn(f"Required route is not currently in sitemap: {route}")

    html_files = [p for p in ROOT.rglob("*.html") if ".git" not in p.parts]
    title_counts = Counter()
    canonical_counts = Counter()
    indexable_pages = 0

    for path in html_files:
        doc = path.read_text(encoding="utf-8", errors="ignore")
        plain = text_of(doc)
        t = title(doc)
        c = canonical(doc)
        if t:
            title_counts[t.lower()] += 1
        if c:
            canonical_counts[c] += 1
        noindex = bool(re.search(r'<meta[^>]+name=["\']robots["\'][^>]+content=["\'][^"\']*noindex', doc, re.I))
        if not noindex:
            indexable_pages += 1
            if not t:
                fail(f"Indexable HTML page has no title: {path}")
            if not c:
                warn(f"Indexable HTML page has no canonical: {path}")
            if len(plain) < 350:
                warn(f"Very thin HTML page ({len(plain)} chars of visible text): {path}")
        if "your-form-id" in doc.lower():
            fail(f"Legacy placeholder form action remains: {path}")
        if re.search(r"href=[\"']#(?:\"|')", doc, re.I):
            warn(f"Empty anchor link found: {path}")

    duplicates = [t for t, count in title_counts.items() if count > 1]
    for t in duplicates:
        fail(f"Duplicate HTML title appears {title_counts[t]} times: {t}")

    if len(html_files) > 20 and indexable_pages < 10:
        fail("Site has many HTML files but too few indexable pages; review noindex/archive strategy")

    # Existing source-driven research is not allowed to become an automatic publishing loop.
    workflow = ROOT / ".github/workflows/daily-cybersecurity-research.yml"
    if workflow.exists():
        w = workflow.read_text(encoding="utf-8", errors="ignore")
        if "git add blog sitemap.xml" in w or "Publish cybersecurity research" in w:
            fail("Research workflow still contains the old automatic-publication path")
        if "generate_blog.py" in w and "site_quality_audit.py" not in w:
            fail("Research workflow invokes the generator without the quality gate")

    privacy = ROOT / "privacy-policy.html"
    if privacy.exists():
        p = privacy.read_text(encoding="utf-8", errors="ignore").lower()
        if "google" not in p or "adsense" not in p:
            warn("Privacy policy should explicitly explain Google/AdSense processing before ads are enabled")

    ads = ROOT / "ads.txt"
    if ads.exists() and "google.com, pub-9788655168653957, DIRECT" not in ads.read_text(encoding="utf-8", errors="ignore"):
        fail("ads.txt does not contain the expected Cylatic Google publisher record")

    print(f"Audited {len(html_files)} HTML pages; {indexable_pages} are currently indexable.")
    for item in WARNINGS:
        print(f"WARNING: {item}")
    if FAILURES:
        for item in FAILURES:
            print(f"FAIL: {item}")
        print(f"\nQuality gate failed with {len(FAILURES)} failure(s).")
        return 1
    print("Quality gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(audit())
