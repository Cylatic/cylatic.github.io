#!/usr/bin/env python3
"""Hourly Cylatic cybersecurity research publisher."""
import datetime as dt
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://cylatic.com"
DAILY_CAP = 6
MIN_SCORE = 20

FEEDS = [
    ("Google News Cybersecurity", "https://news.google.com/rss/search?q=" + urllib.parse.quote("cybersecurity when:2h") + "&hl=en-US&gl=US&ceid=US:en", 1.45),
    ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews", 1.30),
    ("BleepingComputer", "https://www.bleepingcomputer.com/feed/", 1.30),
    ("SecurityWeek", "https://feeds.feedburner.com/securityweek", 1.15),
    ("CISA Cybersecurity Advisories", "https://www.cisa.gov/cybersecurity-advisories/all.xml", 1.45),
]

KEYWORDS = {
    "zero-day": 11, "0-day": 11, "actively exploited": 12, "exploited in the wild": 12,
    "critical vulnerability": 9, "ransomware": 9, "mass exploitation": 10,
    "remote code execution": 8, "authentication bypass": 8, "privilege escalation": 7,
    "supply chain": 8, "identity": 4, "cloud": 3, "microsoft": 3, "ai security": 6,
    "apt": 6, "cisa": 6, "critical infrastructure": 8, "malware": 5, "phishing": 4,
    "credential": 4, "remote access": 5, "zero trust": 4, "kubernetes": 4, "data theft": 6,
    "botnet": 6, "infostealer": 6, "vpn": 5, "fortinet": 5, "palo alto": 5,
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Cylatic-ResearchBot/3.1"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read()


def text_of(node):
    return " ".join(node.itertext()).strip() if node is not None else ""


def parse_feed(name, url, weight):
    root = ET.fromstring(fetch(url))
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    result = []
    for item in items[:40]:
        title = text_of(item.find("title")) or text_of(item.find("{http://www.w3.org/2005/Atom}title"))
        link_node = item.find("link")
        link = (link_node.text or "").strip() if link_node is not None and link_node.text else ""
        if not link:
            link_node = item.find("{http://www.w3.org/2005/Atom}link")
            link = link_node.attrib.get("href", "") if link_node is not None else ""
        summary = text_of(item.find("description")) or text_of(item.find("{http://www.w3.org/2005/Atom}summary"))
        published = text_of(item.find("pubDate")) or text_of(item.find("{http://www.w3.org/2005/Atom}published"))
        if title and link:
            result.append({"source": name, "title": title, "link": link,
                           "summary": re.sub(r"\s+", " ", summary)[:1800],
                           "published": published, "weight": weight})
    return result


def normalize_title(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def score(item):
    text = (item["title"] + " " + item["summary"]).lower()
    return item["weight"] * 10 + sum(v for k, v in KEYWORDS.items() if k in text) + (3 if item["published"] else 0)


def select_candidate(items, existing_text):
    existing = existing_text.lower()
    candidates = []
    for item in items:
        normalized = normalize_title(item["title"])
        if len(normalized) < 15 or normalized in existing or item["link"].lower() in existing:
            continue
        item["score"] = score(item)
        if item["score"] >= MIN_SCORE:
            candidates.append(item)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[0] if candidates else None


def call_gemini(item):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY GitHub secret is not configured")
    today = dt.date.today().isoformat()
    prompt = f'''You are the senior technical editor for Cylatic, a cybersecurity engineering company. Today is {today}.

Create ONE publication-ready cybersecurity research article based on the supplied current development.

ARTICLE SOURCE
Source: {item["source"]}
Title: {item["title"]}
URL: {item["link"]}
Summary: {item["summary"]}

Audience: SOC engineers, SIEM engineers, detection engineers, cloud/security engineers, network defenders and security architects.

The article must be ORIGINAL defensive technical analysis, not a rewritten news report. Never invent CVEs, dates, vendors, threat actors, affected versions, statistics, indicators or claims. Use only facts supported by the supplied source; clearly qualify anything uncertain. Do not reproduce source wording.

Focus on why the development matters technically and what defenders can do. Cover attack surface, intrusion chain at a high level, identity controls, endpoint/network/cloud telemetry, SIEM detection opportunities, threat hunting, containment, hardening, architecture implications and practical defensive priorities where applicable. Do not provide exploit code, weaponization steps, credential theft instructions or instructions for attacking real systems.

Return ONLY valid JSON with this exact shape:
{{"title":"...","slug":"...","excerpt":"...","category":"...","keywords":["..."],"read_time":"...","body_html":"...","sources":[{{"title":"...","url":"..."}}]}}

Rules:
- 1400-2000 words.
- body_html may use only p,h2,h3,ul,ol,pre,strong,code.
- Include at least one practical defensive detection example in a pre block.
- Include a section titled "What defenders should do now".
- Include 8-12 specific search keywords.
- Include the supplied source in sources.
- Do not mention that AI generated the article.
- Do not use sensational or clickbait language.
'''
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.25, "responseMimeType": "application/json"},
    }).encode()
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + urllib.parse.quote(key)
    request = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                data = json.loads(response.read())
            text = "".join(part.get("text", "") for candidate in data.get("candidates", []) for part in candidate.get("content", {}).get("parts", []))
            if not text:
                raise RuntimeError("Gemini returned no generated content")
            return json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
        except Exception:
            if attempt == 2:
                raise
            time.sleep(8 * (attempt + 1))


def esc(value):
    return html.escape(str(value), quote=True)


def safe_slug(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")[:90]


ARTICLE_CSS = '''<style>.article-wrap{max-width:920px;margin:auto;padding:110px 32px 120px}.article-kicker{font-size:10px;letter-spacing:.18em;font-weight:700;color:#70736a}.article-title{font:700 clamp(50px,7vw,92px)/.91 'Space Grotesk';letter-spacing:-.075em;margin:24px 0 30px;max-width:1000px}.article-dek{font-size:20px;line-height:1.7;color:#5b5e56;max-width:780px;border-bottom:1px solid var(--line);padding-bottom:42px}.article{margin-top:55px}.article h2{font:600 36px/1.08 'Space Grotesk';letter-spacing:-.045em;margin:58px 0 18px}.article h3{font:600 23px/1.2 'Space Grotesk';margin:38px 0 12px}.article p,.article li{font-size:16px;line-height:1.9;color:#393c36}.article ul,.article ol{padding-left:28px}.article pre{background:#171914;color:#e7e9df;padding:22px;border-radius:2px;overflow:auto;font:13px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace}.article code{background:#e6e7df;padding:2px 6px;font-family:ui-monospace,monospace}.article .source{font-size:13px!important;line-height:1.6}.article .source a{text-decoration:underline}.article-note{margin-top:55px;padding:24px;background:var(--soft);font-size:12px;line-height:1.7;color:#565951}@media(max-width:700px){.article-wrap{padding:75px 20px 90px}.article-title{font-size:49px}.article h2{font-size:30px}}</style>'''


def article_page(post, date):
    slug = safe_slug(post["slug"])
    url = f"{BASE}/blog/{date:%Y/%m/%d}/{slug}.html"
    keywords = ", ".join(post.get("keywords", []))
    sources = "".join(
        f'<li class="source"><a href="{esc(source["url"])}" rel="noopener noreferrer">{esc(source["title"])}</a></li>'
        for source in post.get("sources", []) if source.get("url")
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#11120f"><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="{url}"><title>{esc(post["title"])} | Cylatic Research</title><meta name="description" content="{esc(post["excerpt"])}"><meta name="keywords" content="{esc(keywords)}"><meta property="og:type" content="article"><meta property="og:title" content="{esc(post["title"])}"><meta property="og:description" content="{esc(post["excerpt"])}"><meta property="og:url" content="{url}"><meta name="twitter:card" content="summary_large_image"><script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-9788655168653957" crossorigin="anonymous"></script><link rel="stylesheet" href="../../../../assets/css/blog.css">{ARTICLE_CSS}</head><body><header><a class="brand" href="../../../../">CYLATIC</a><nav><a href="../../../../tools/">Tools</a><a class="active" href="../../../../blog/">Research</a><a href="../../../../#contact">Contact</a></nav></header><main class="article-wrap"><div class="article-kicker">{date:%d %b %Y} · {esc(post["category"]).upper()} · {esc(post["read_time"])}</div><h1 class="article-title">{esc(post["title"])}</h1><p class="article-dek">{esc(post["excerpt"])}</p><article class="article">{post["body_html"]}<h2>Sources &amp; further reading</h2><ul>{sources}</ul><div class="article-note"><strong>CYLATIC RESEARCH</strong><br>Defensive analysis for security engineers. Validate vendor-specific indicators and detection logic against your own telemetry before production use.</div></article></main><footer>© 2026 CYLATIC · <a href="../../../../">Cybersecurity &amp; IT Infrastructure</a> · <a href="../../../../privacy-policy.html">Privacy</a></footer></body></html>'''


def render_card(post, date):
    slug = safe_slug(post["slug"])
    tags = " · ".join(esc(keyword) for keyword in post.get("keywords", [])[:4])
    return f'''<article class="post-card"><div class="post-main"><span>{date:%d %b %Y} · {esc(post["category"]).upper()}</span><h2>{esc(post["title"])}</h2><p>{esc(post["excerpt"])}</p><div class="post-tags">{tags}</div></div><a class="post-link" href="{date:%Y/%m/%d}/{slug}.html">READ ANALYSIS <b>↗</b></a></article>'''


def update_index(post, date):
    path = ROOT / "blog" / "index.html"
    text = path.read_text(encoding="utf-8")
    marker = re.search(r"<!-- POSTS_START -->(.*?)<!-- POSTS_END -->", text, re.S)
    if not marker:
        raise RuntimeError("blog/index.html is missing POSTS_START/POSTS_END markers")
    combined = render_card(post, date) + marker.group(1)
    cards = re.findall(r'<article class="post-card">.*?</article>', combined, re.S)[:30]
    replacement = "<!-- POSTS_START -->" + "".join(cards) + "<!-- POSTS_END -->"
    path.write_text(text[:marker.start()] + replacement + text[marker.end():], encoding="utf-8")


def update_sitemap(post, date):
    path = ROOT / "sitemap.xml"
    sitemap = path.read_text(encoding="utf-8")
    url = f'{BASE}/blog/{date:%Y/%m/%d}/{safe_slug(post["slug"])}.html'
    if url not in sitemap:
        addition = f'<url><loc>{url}</loc><lastmod>{date.isoformat()}</lastmod></url>'
        path.write_text(sitemap.replace("</urlset>", addition + "</urlset>"), encoding="utf-8")


def count_today_articles(today):
    folder = ROOT / "blog" / f"{today:%Y}" / f"{today:%m}" / f"{today:%d}"
    return len(list(folder.glob("*.html"))) if folder.exists() else 0


def main():
    today = dt.date.today()
    if count_today_articles(today) >= DAILY_CAP:
        print(f"Daily publication cap reached ({DAILY_CAP}); monitoring run skipped.")
        return
    items = []
    for name, url, weight in FEEDS:
        try:
            items.extend(parse_feed(name, url, weight))
        except Exception as exc:
            print(f"Feed failed: {name}: {exc}")
    if not items:
        raise RuntimeError("No current cybersecurity news could be retrieved")
    existing_text = "\n".join(path.read_text(errors="ignore") for path in (ROOT / "blog").rglob("*.html"))
    candidate = select_candidate(items, existing_text)
    if not candidate:
        print(f"No sufficiently important unseen cybersecurity development found; threshold={MIN_SCORE}.")
        return
    print(f"Selected candidate: score={candidate['score']} | {candidate['title']}")
    post = call_gemini(candidate)
    slug = safe_slug(post.get("slug", post.get("title", "")))
    if not slug:
        raise RuntimeError("Gemini returned an invalid article slug")
    post["slug"] = slug
    post.setdefault("sources", [{"title": candidate["source"], "url": candidate["link"]}])
    post.setdefault("keywords", [])
    post.setdefault("category", "Cybersecurity")
    post.setdefault("read_time", "8 min read")
    out_dir = ROOT / "blog" / f"{today:%Y}" / f"{today:%m}" / f"{today:%d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}.html"
    if out_path.exists():
        print(f"Article already exists: {out_path}")
        return
    out_path.write_text(article_page(post, today), encoding="utf-8")
    update_index(post, today)
    update_sitemap(post, today)
    print(f"Published: {out_path}")


if __name__ == "__main__":
    main()
