#!/usr/bin/env python3
"""Cylatic hourly cybersecurity research publisher.

The job is intentionally conservative: it monitors news hourly, publishes only
high-value unseen developments, and never treats a quiet hour as an error.
"""
import datetime as dt
import email.utils
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://cylatic.com"
DAILY_CAP = 6
MIN_SCORE = 20
MAX_AGE_HOURS = 36
IST = ZoneInfo("Asia/Kolkata")

FEEDS = [
    ("Google News Cybersecurity", "https://news.google.com/rss/search?q=" + urllib.parse.quote("cybersecurity when:6h") + "&hl=en-US&gl=US&ceid=US:en", 1.45),
    ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews", 1.30),
    ("BleepingComputer", "https://www.bleepingcomputer.com/feed/", 1.30),
    ("SecurityWeek", "https://feeds.feedburner.com/securityweek", 1.15),
    ("CISA Cybersecurity Advisories", "https://www.cisa.gov/cybersecurity-advisories/all.xml", 1.45),
]

KEYWORDS = {
    "zero-day": 12, "0-day": 12, "actively exploited": 14, "exploited in the wild": 14,
    "critical vulnerability": 9, "ransomware": 9, "mass exploitation": 11,
    "remote code execution": 9, "authentication bypass": 9, "privilege escalation": 7,
    "supply chain": 9, "critical infrastructure": 8, "malware": 5, "phishing": 4,
    "credential": 4, "remote access": 5, "kubernetes": 4, "data theft": 6,
    "botnet": 6, "infostealer": 6, "vpn": 5, "fortinet": 5, "palo alto": 5,
    "citrix": 5, "ivanti": 5, "microsoft": 3, "aws": 3, "azure": 3,
}


def now_ist():
    return dt.datetime.now(IST)


def fetch(url, timeout=25):
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 Cylatic-ResearchBot/4.0 (+https://cylatic.com)"
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def child_text(node, *names):
    wanted = {n.lower() for n in names}
    for child in list(node):
        if local_name(child.tag) in wanted:
            return " ".join(child.itertext()).strip()
    return ""


def parse_datetime(value):
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except Exception:
            return None


def parse_feed(name, url, weight):
    root = ET.fromstring(fetch(url))
    result = []
    for item in list(root.iter()):
        if local_name(item.tag) not in {"item", "entry"}:
            continue
        title = child_text(item, "title")
        link = child_text(item, "link")
        if not link:
            for child in list(item):
                if local_name(child.tag) == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        summary = child_text(item, "description", "summary", "content")
        published = child_text(item, "pubDate", "published", "updated")
        published_at = parse_datetime(published)
        if title and link:
            result.append({
                "source": name,
                "title": re.sub(r"\s+", " ", title).strip(),
                "link": link.strip(),
                "summary": re.sub(r"\s+", " ", summary).strip()[:2200],
                "published": published,
                "published_at": published_at,
                "weight": weight,
            })
    return result[:50]


def normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def score(item):
    text = (item["title"] + " " + item["summary"]).lower()
    value = item["weight"] * 10
    value += sum(points for word, points in KEYWORDS.items() if word in text)
    published = item.get("published_at")
    if published:
        age = (dt.datetime.now(dt.timezone.utc) - published).total_seconds() / 3600
        if age <= 6:
            value += 8
        elif age <= 18:
            value += 5
        elif age <= MAX_AGE_HOURS:
            value += 2
    return value


def read_existing():
    parts = []
    blog = ROOT / "blog"
    for path in blog.rglob("*.html"):
        try:
            parts.append(path.read_text(encoding="utf-8", errors="ignore")[:30000])
        except OSError:
            pass
    return "\n".join(parts).lower()


def select_candidate(items, existing):
    candidates = []
    for item in items:
        normalized = normalize(item["title"])
        if len(normalized) < 15:
            continue
        if normalize(item["title"]) in existing or item["link"].lower() in existing:
            continue
        published = item.get("published_at")
        if published:
            age = (dt.datetime.now(dt.timezone.utc) - published).total_seconds() / 3600
            if age > MAX_AGE_HOURS:
                continue
        item["score"] = score(item)
        if item["score"] >= MIN_SCORE:
            candidates.append(item)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[0] if candidates else None


def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise RuntimeError("Gemini did not return valid JSON")
        return json.loads(match.group(0))


def call_gemini(item):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY GitHub secret is missing")

    date = now_ist().date().isoformat()
    prompt = f"""You are the senior technical editor for Cylatic, a cybersecurity engineering company. Today is {date}.

Create ONE original, publication-ready cybersecurity research article from the current development below.

SOURCE
Publisher: {item['source']}
Headline: {item['title']}
URL: {item['link']}
Summary: {item['summary']}

Audience: SOC, SIEM, detection, threat-hunting, cloud, network and security-architecture professionals.

Write technical defensive analysis, NOT a rewritten news article. Use only facts supported by the supplied material. Never invent CVEs, versions, affected products, threat actors, dates, statistics or indicators. Clearly label uncertainty. Do not reproduce source wording.

Cover the technical significance, attack surface, high-level attack chain, relevant identity/endpoint/network/cloud telemetry, SIEM correlation, detection engineering, hunting, containment, hardening and architecture implications where applicable. Do not provide exploit code, weaponization, credential theft instructions or instructions for attacking real systems.

Return ONLY JSON:
{{"title":"...","slug":"...","excerpt":"...","category":"...","keywords":["..."],"read_time":"...","body_html":"...","sources":[{{"title":"...","url":"..."}}]}}

Requirements:
- 1400-1900 words.
- Use only p,h2,h3,ul,ol,pre,strong,code in body_html.
- Include at least one practical defensive detection example in a pre element.
- Include a section titled exactly "What defenders should do now".
- Include 8-12 concrete SEO keywords.
- Include the supplied source in sources.
- No AI disclosure and no clickbait.
"""
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 7000,
        },
    }).encode("utf-8")

    models = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    last_error = None
    for model in models:
        endpoint = "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent?key=" + urllib.parse.quote(key)
        request = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    data = json.loads(response.read())
                candidates = data.get("candidates", [])
                text = "".join(
                    part.get("text", "")
                    for candidate in candidates
                    for part in candidate.get("content", {}).get("parts", [])
                )
                if not text:
                    raise RuntimeError("Gemini returned no text")
                return extract_json(text)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:1000]
                last_error = RuntimeError(f"Gemini {model} HTTP {exc.code}: {body}")
                if exc.code in (400, 401, 403):
                    break
                time.sleep(6 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(6 * (attempt + 1))
    raise last_error or RuntimeError("Gemini generation failed")


def esc(value):
    return html.escape(str(value), quote=True)


def safe_slug(value):
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return slug[:90] or "cybersecurity-research"


def sanitize_body(body):
    body = str(body or "")
    body = re.sub(r"<(?!/?(?:p|h2|h3|ul|ol|li|pre|strong|code)\b)[^>]*>", "", body, flags=re.I)
    body = re.sub(r"\son\w+\s*=\s*(['\"]).*?\1", "", body, flags=re.I | re.S)
    body = re.sub(r"javascript:", "", body, flags=re.I)
    return body.strip()


def validate_post(post, candidate):
    required = ["title", "slug", "excerpt", "body_html"]
    missing = [key for key in required if not str(post.get(key, "")).strip()]
    if missing:
        raise RuntimeError("Gemini response missing: " + ", ".join(missing))
    post["title"] = str(post["title"]).strip()[:180]
    post["slug"] = safe_slug(post["slug"])
    post["excerpt"] = str(post["excerpt"]).strip()[:320]
    post["body_html"] = sanitize_body(post["body_html"])
    post["category"] = str(post.get("category") or "Cybersecurity").strip()[:60]
    post["read_time"] = str(post.get("read_time") or "8 min read").strip()[:30]
    post["keywords"] = [str(x).strip() for x in post.get("keywords", []) if str(x).strip()][:12]
    if not post["keywords"]:
        post["keywords"] = ["cybersecurity", "threat intelligence", "security operations"]
    sources = post.get("sources") if isinstance(post.get("sources"), list) else []
    if not any(isinstance(s, dict) and s.get("url") == candidate["link"] for s in sources):
        sources.insert(0, {"title": candidate["source"], "url": candidate["link"]})
    post["sources"] = [s for s in sources if isinstance(s, dict) and s.get("url")][:8]
    return post


ARTICLE_CSS = '''<style>
.article-page{background:var(--paper)}
.article-hero{padding:150px 0 90px;position:relative;overflow:hidden;border-bottom:1px solid var(--line)}
.article-hero:before{content:'RESEARCH';position:absolute;right:-25px;top:100px;font:700 120px/.8 'Space Grotesk';letter-spacing:-.09em;color:#e5e5dd;z-index:0}
.article-hero:after{content:'';position:absolute;width:520px;height:520px;right:-180px;bottom:-300px;border:1px solid #cccac1;border-radius:50%;box-shadow:0 0 0 80px rgba(201,200,192,.10),0 0 0 160px rgba(201,200,192,.06)}
.article-hero .container{position:relative;z-index:1}
.article-kicker{display:flex;align-items:center;gap:12px;font-size:10px;font-weight:700;letter-spacing:.17em;text-transform:uppercase;color:#70726a}
.article-kicker:before{content:'';width:8px;height:8px;border-radius:50%;background:#a8bd00;box-shadow:0 0 0 5px rgba(168,189,0,.12)}
.article-title{max-width:1050px;margin:30px 0 32px;font:700 clamp(55px,8vw,108px)/.88 'Space Grotesk';letter-spacing:-.08em}
.article-dek{max-width:790px;margin:0;color:#5e6059;font-size:19px;line-height:1.75}
.article-meta-row{display:flex;flex-wrap:wrap;gap:12px 28px;margin-top:48px;padding-top:18px;border-top:1px solid var(--line);font-size:10px;font-weight:700;letter-spacing:.12em;color:#777970}
.article-body-wrap{padding:95px 0 125px;background:var(--paper)}
.article-layout{display:grid;grid-template-columns:minmax(0,820px) 250px;gap:80px;align-items:start}
.article{font-family:'DM Sans',sans-serif}
.article p,.article li{font-size:16px;line-height:1.9;color:#3f413c}
.article p{margin:0 0 25px}
.article strong{color:var(--ink)}
.article h2{font:600 clamp(32px,4vw,48px)/1.02 'Space Grotesk';letter-spacing:-.055em;margin:70px 0 22px}
.article h3{font:600 23px/1.1 'Space Grotesk';letter-spacing:-.03em;margin:40px 0 15px}
.article ul,.article ol{margin:0 0 30px;padding-left:28px}
.article li{padding:5px 0}
.article a{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}
.callout{background:var(--ink);color:#e9ebe2;padding:28px 30px;margin:38px 0;border-left:4px solid var(--lime);font-size:15px;line-height:1.8}
.callout strong{color:var(--lime)}
.article pre{background:#e7e8e1;border:1px solid #d0d1c9;padding:24px;overflow:auto;font:13px/1.8 ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;color:#292b26;margin:35px 0}
.article code{background:#e4e5dd;padding:2px 6px;font:13px ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace}
.article-sources{margin-top:75px;padding-top:30px;border-top:1px solid var(--line)}
.article-sources h2{margin-top:0}
.source{font-size:12px!important;color:#6b6d65!important}
.source a{text-decoration:underline}
.article-side{position:sticky;top:110px;border-top:1px solid var(--line);padding-top:20px}
.article-side-label{font-size:10px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;color:#777970;margin-bottom:16px}
.article-side a{display:block;padding:12px 0;border-bottom:1px solid var(--line);font-size:12px;font-weight:600;line-height:1.4}
.article-side a:hover{color:#687400}
.article-back{display:inline-flex;align-items:center;gap:9px;margin-top:30px;font-size:10px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;border-bottom:1px solid var(--ink);padding-bottom:6px}
.article-back:hover{color:#687400;border-color:#687400}
@media(max-width:1000px){.article-layout{grid-template-columns:1fr}.article-side{display:none}.article-hero:before{font-size:85px}.article-title{font-size:clamp(52px,9vw,88px)}}
@media(max-width:700px){.article-hero{padding:120px 0 65px}.article-hero:before{font-size:55px;top:95px;right:-10px}.article-title{font-size:clamp(47px,14vw,68px);margin:25px 0}.article-dek{font-size:16px;line-height:1.7}.article-meta-row{margin-top:35px;line-height:1.7}.article-body-wrap{padding:65px 0 90px}.article p,.article li{font-size:15px;line-height:1.8}.article h2{font-size:34px;margin-top:55px}.article h3{font-size:21px}.article pre{padding:18px;font-size:11px}}
</style>'''


def article_page(post, date):
    slug = safe_slug(post["slug"])
    url = f"{BASE}/blog/{date:%Y/%m/%d}/{slug}.html"
    sources = "".join(
        f'<li class="source"><a href="{esc(source["url"])}" rel="noopener noreferrer">{esc(source["title"])}</a></li>'
        for source in post.get("sources", [])
    )
    keywords = ", ".join(post.get("keywords", []))
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta name="theme-color" content="#f5f4ef">
<meta name="robots" content="index,follow,max-image-preview:large">
<meta name="author" content="Cylatic Research">
<link rel="canonical" href="{url}">
<title>{esc(post["title"])} | Cylatic Research</title>
<meta name="description" content="{esc(post["excerpt"])}">
<meta name="keywords" content="{esc(keywords)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(post["title"])}">
<meta property="og:description" content="{esc(post["excerpt"])}">
<meta property="og:url" content="{url}">
<meta property="og:site_name" content="Cylatic">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(post["title"])}">
<meta name="twitter:description" content="{esc(post["excerpt"])}">
<link rel="icon" href="../../../../assets/img/favicon.png">
<link rel="stylesheet" href="../../../../assets/css/style.css">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-9788655168653957" crossorigin="anonymous"></script>
{ARTICLE_CSS}
</head>
<body class="article-page">
<nav class="navbar" id="navbar">
  <div class="container">
    <div class="nav-wrapper">
      <div class="logo"><a href="../../../../" aria-label="Cylatic home">Cylatic</a></div>
      <button class="mobile-menu-toggle" id="mobileMenuToggle" aria-label="Toggle navigation" aria-expanded="false"><span></span><span></span><span></span></button>
      <ul class="nav-menu" id="navMenu">
        <li><a href="../../../../">Home</a></li>
        <li><a href="../../../../#services">Capabilities</a></li>
        <li><a href="../../../../tools/">Tools</a></li>
        <li><a class="active" href="../../../../blog/">Research</a></li>
        <li><a href="../../../../#about">Approach</a></li>
        <li><a href="../../../../#contact">Contact</a></li>
      </ul>
    </div>
  </div>
</nav>
<main>
<section class="article-hero">
  <div class="container">
    <div class="article-kicker">Cylatic Research · {esc(post["category"]).upper()}</div>
    <h1 class="article-title">{esc(post["title"])}</h1>
    <p class="article-dek">{esc(post["excerpt"])}</p>
    <div class="article-meta-row"><span>{date:%d %b %Y}</span><span>{esc(post["category"]).upper()}</span><span>{esc(post["read_time"])}</span><span>{esc(" · ".join(post.get("keywords", [])[:4]).upper())}</span></div>
    <a class="article-back" href="../../../../blog/">← Back to Research</a>
  </div>
</section>
<section class="article-body-wrap">
  <div class="container article-layout">
    <article class="article">
      {post["body_html"]}
      <div class="article-sources"><h2>Sources &amp; further reading</h2><ul>{sources}</ul></div>
      <div class="article-note"><strong>CYLATIC RESEARCH</strong><br>Defensive analysis for security engineers. Validate vendor-specific indicators and detection logic against your own telemetry before production use.</div>
    </article>
    <aside class="article-side">
      <div class="article-side-label">Research</div>
      <a href="../../../../blog/">All research ↗</a>
      <a href="../../../../tools/">Cybersecurity tools ↗</a>
      <a href="../../../../#contact">Talk to Cylatic ↗</a>
    </aside>
  </div>
</section>
</main>
<footer class="footer">
  <div class="container">
    <div class="footer-content">
      <div class="footer-brand"><h3>Cylatic</h3><p>Cybersecurity &amp; IT Infrastructure Services</p></div>
      <div class="footer-links">
        <div class="footer-column"><h4>Capabilities</h4><ul><li><a href="../../../../#services">SIEM Integration</a></li><li><a href="../../../../#services">Privileged Access</a></li><li><a href="../../../../#services">Network Infrastructure</a></li><li><a href="../../../../#services">Secure Deployment</a></li></ul></div>
        <div class="footer-column"><h4>Resources</h4><ul><li><a href="../../../../tools/">Cybersecurity Tools</a></li><li><a href="../../../../blog/">Security Research</a></li><li><a href="../../../../privacy-policy.html">Privacy Policy</a></li><li><a href="../../../../#contact">Contact</a></li></ul></div>
      </div>
    </div>
    <div class="footer-bottom"><p>© 2026 Cylatic. All rights reserved.</p></div>
  </div>
</footer>
<script src="../../../../assets/js/main.js"></script>
</body>
</html>'''


def render_card(post, date):
    slug = safe_slug(post["slug"])
    tags = " · ".join(esc(x) for x in post.get("keywords", [])[:4])
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
    if url not in sitemap and "</urlset>" in sitemap:
        addition = f'<url><loc>{url}</loc><lastmod>{date.isoformat()}</lastmod></url>'
        path.write_text(sitemap.replace("</urlset>", addition + "</urlset>"), encoding="utf-8")


def count_today_articles(date):
    folder = ROOT / "blog" / f"{date:%Y}" / f"{date:%m}" / f"{date:%d}"
    return len(list(folder.glob("*.html"))) if folder.exists() else 0


def main():
    today = now_ist().date()
    published_today = count_today_articles(today)
    if published_today >= DAILY_CAP:
        print(f"Daily publication cap reached: {published_today}/{DAILY_CAP}")
        return

    items = []
    for name, url, weight in FEEDS:
        try:
            feed_items = parse_feed(name, url, weight)
            print(f"Feed OK: {name} ({len(feed_items)} items)")
            items.extend(feed_items)
        except Exception as exc:
            print(f"Feed unavailable: {name}: {exc}")

    if not items:
        print("No news feeds were available; this is a successful monitoring run, not a publication failure.")
        return

    candidate = select_candidate(items, read_existing())
    if not candidate:
        print(f"No unseen cybersecurity development met score threshold {MIN_SCORE}.")
        return

    print(f"Selected: score={candidate['score']} source={candidate['source']} title={candidate['title']}")
    post = validate_post(call_gemini(candidate), candidate)
    out_dir = ROOT / "blog" / f"{today:%Y}" / f"{today:%m}" / f"{today:%d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{safe_slug(post['slug'])}.html"
    if out_path.exists():
        print(f"Generated slug already exists: {out_path}; no publication.")
        return
    out_path.write_text(article_page(post, today), encoding="utf-8")
    update_index(post, today)
    update_sitemap(post, today)
    print(f"PUBLISHED: {out_path}")


if __name__ == "__main__":
    main()
