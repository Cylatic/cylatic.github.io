#!/usr/bin/env python3
"""One-time/idempotent cleanup for the AdSense quality rebuild.

- Removes AdSense tags while the site is being rebuilt.
- Keeps the legacy source-driven 2026 briefing archive out of Search.
- Leaves the curated sitemap under version control instead of rebuilding it from
  every historical page.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]

ADSENSE_RE = re.compile(r'<script\b[^>]*src=["\']https://pagead2\.googlesyndication\.com/pagead/js/adsbygoogle\.js[^>]*></script>\s*', re.I)
ROBOTS_RE = re.compile(r'(<meta\s+name=["\']robots["\']\s+content=["\'])[^"\']*(["\'])', re.I)

changed = 0
legacy = 0
ad_tags = 0

for path in ROOT.rglob('*.html'):
    if '.git' in path.parts:
        continue
    original = path.read_text(encoding='utf-8', errors='ignore')
    updated = ADSENSE_RE.sub('', original)
    if updated != original:
        ad_tags += 1

    if 'blog' in path.parts and '2026' in path.parts and path.name != 'index.html':
        if re.search(r'<meta\s+name=["\']robots["\']', updated, re.I):
            updated = ROBOTS_RE.sub(r'\1noindex,follow\2', updated, count=1)
        elif re.search(r'</head>', updated, re.I):
            updated = re.sub(r'</head>', '<meta name="robots" content="noindex,follow"></head>', updated, count=1, flags=re.I)
        legacy += 1

    if updated != original:
        path.write_text(updated, encoding='utf-8')
        changed += 1

print(f'Updated {changed} HTML files; removed AdSense tags from {ad_tags}; marked {legacy} legacy briefings noindex.')
