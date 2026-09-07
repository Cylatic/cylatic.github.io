import datetime as dt
import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://cylatic.com"
FEEDS = [
    ("Google News Cybersecurity", "https://news.google.com/rss/search?q=" + urllib.parse.quote("cybersecurity when:2d") + "&hl=en-US&gl=US&ceid=US:en", 1.35),
    ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews", 1.25),
    ("BleepingComputer", "https://www.bleepingcomputer.com/feed/", 1.25),
    ("SecurityWeek", "https://feeds.feedburner.com/securityweek", 1.10),
]
KEYWORDS = {"zero-day":9,"0-day":9,"actively exploited":10,"critical vulnerability":8,"ransomware":8,"exploitation":6,"breach":5,"supply chain":7,"identity":4,"cloud":3,"microsoft":3,"ai security":6,"apt":6,"cisa":5,"critical infrastructure":7,"malware":5,"phishing":4,"credential":4,"remote access":5,"zero trust":4,"kubernetes":4}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent":"Cylatic-ResearchBot/2.0"})
    with urllib.request.urlopen(req, timeout=25) as r: return r.read()


def text_of(node): return " ".join(node.itertext()).strip() if node is not None else ""


def parse_feed(name, url, weight):
    root = ET.fromstring(fetch(url)); items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry"); out=[]
    for item in items[:35]:
        title=text_of(item.find("title")) or text_of(item.find("{http://www.w3.org/2005/Atom}title")); ln=item.find("link"); link=(ln.text or "").strip() if ln is not None and ln.text else ""
        if not link:
            ln=item.find("{http://www.w3.org/2005/Atom}link"); link=ln.attrib.get("href","") if ln is not None else ""
        summary=text_of(item.find("description")) or text_of(item.find("{http://www.w3.org/2005/Atom}summary")); pub=text_of(item.find("pubDate")) or text_of(item.find("{http://www.w3.org/2005/Atom}published"))
        if title and link: out.append({"source":name,"title":title,"link":link,"summary":re.sub(r"\s+"," ",summary)[:1400],"published":pub,"weight":weight})
    return out


def score(item):
    t=(item["title"]+" "+item["summary"]).lower(); return item["weight"]*10+sum(v for k,v in KEYWORDS.items() if k in t)+(1 if item["published"] else 0)


def call_gemini(items):
    key=os.environ.get("GEMINI_API_KEY")
    if not key: raise RuntimeError("GEMINI_API_KEY GitHub secret is not configured")
    today=dt.date.today().isoformat(); sources="\n".join(f"- {x['source']} | {x['title']} | {x['link']} | {x['summary']}" for x in items[:18])
    prompt=f'''You are the senior technical editor for Cylatic, a cybersecurity engineering company. Today is {today}.
Create THREE distinct, publication-ready cybersecurity research articles from the supplied recent news. Select three different high-value developments; do not write three variants of the same story. Prefer current, material topics such as actively exploited vulnerabilities, major breaches, identity attacks, cloud incidents, ransomware, supply-chain compromise, security tooling abuse or important defensive developments.
Audience: SOC engineers, SIEM engineers, detection engineers, cloud/security engineers, network defenders and security architects.
Articles must be original defensive technical analysis, NOT rewritten news reports. Never invent CVEs, dates, vendors, threat actors, statistics, affected versions or claims. Current-event claims must be supported by the supplied sources. If a detail is uncertain, state that it is uncertain. Do not reproduce source wording.
For each article explain, where applicable: attack surface, intrusion chain at a high level, likely telemetry, identity/network controls, SIEM detection opportunities, threat hunting, containment, hardening, architecture implications, and practical defensive priorities. Do not provide exploit code, weaponization steps, credential theft instructions or instructions for attacking real systems.
Return ONLY valid JSON with this exact top-level shape:
{{"posts":[{{"title":"...","slug":"...","excerpt":"...","category":"...","keywords":["..."],"read_time":"...","body_html":"...","sources":[{{"title":"...","url":"..."}}]}}]}}
Rules: exactly 3 posts; unique slugs; each article 1400-2000 words; body_html may use only p,h2,h3,ul,ol,pre,strong,code; include at least one defensive detection example in a pre block; include a short "What defenders should do now" section; keywords 8-12 specific search terms; end the body with a brief Sources & further reading heading.
RECENT SOURCES:\n{sources}'''
    payload=json.dumps({"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"temperature":0.35,"responseMimeType":"application/json"}}).encode()
    url="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key="+urllib.parse.quote(key)
    req=urllib.request.Request(url,data=payload,headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=180) as r: data=json.loads(r.read())
    text="".join(p.get("text","") for c in data.get("candidates",[]) for p in c.get("content",{}).get("parts",[]))
    if not text: raise RuntimeError("Gemini returned no generated content")
    return json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())


def esc(s): return html.escape(str(s),quote=True)
def safe_slug(value): return re.sub(r"[^a-z0-9]+","-",str(value).lower()).strip("-")[:90]


def article_page(post,date):
    slug=safe_slug(post["slug"]); url=f"{BASE}/blog/{date:%Y/%m/%d}/{slug}.html"; keywords=", ".join(post.get("keywords",[]))
    body=post["body_html"]
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#11120f"><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="{url}"><title>{esc(post["title"])} | Cylatic Research</title><meta name="description" content="{esc(post["excerpt"])}"><meta name="keywords" content="{esc(keywords)}"><meta property="og:type" content="article"><meta property="og:title" content="{esc(post["title"])}"><meta property="og:description" content="{esc(post["excerpt"])}"><meta property="og:url" content="{url}"><meta name="twitter:card" content="summary_large_image"><script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-9788655168653957" crossorigin="anonymous"></script><link rel="stylesheet" href="../../../../assets/css/blog.css"><style>.article-wrap{{max-width:920px;margin:auto;padding:110px 32px 120px}}.article-kicker{{font-size:10px;letter-spacing:.18em;font-weight:700;color:#70736a}}.article-title{{font:700 clamp(50px,7vw,92px)/.91 'Space Grotesk';letter-spacing:-.075em;margin:24px 0 30px;max-width:1000px}}.article-dek{{font-size:20px;line-height:1.7;color:#5b5e56;max-width:780px;border-bottom:1px solid var(--line);padding-bottom:42px}}.article{{margin-top:55px}.article h2{{font:600 36px/1.08 'Space Grotesk';letter-spacing:-.045em;margin:58px 0 18px}.article h3{{font:600 23px/1.2 'Space Grotesk';margin:38px 0 12px}.article p,.article li{{font-size:16px;line-height:1.9;color:#393c36}.article ul,.article ol{{padding-left:28px}}.article pre{{background:#171914;color:#e7e9df;padding:22px;border-radius:2px;overflow:auto;font:13px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace}.article code{{background:#e6e7df;padding:2px 6px;font-family:ui-monospace,monospace}}.article .source{{font-size:13px!important;line-height:1.6}.article .source a{{text-decoration:underline}}.article-note{{margin-top:55px;padding:24px;background:var(--soft);font-size:12px;line-height:1.7;color:#565951}}@media(max-width:700px){{.article-wrap{{padding:75px 20px 90px}}.article-title{{font-size:49px}}.article h2{{font-size:30px}}}}</style></head><body><header><a class="brand" href="../../../../">CYLATIC</a><nav><a href="../../../../tools/">Tools</a><a class="active" href="../../../../blog/">Research</a><a href="../../../../#contact">Contact</a></nav></header><main class="article-wrap"><div class="article-kicker">{date:%d %b %Y} · {esc(post["category"]).upper()} · {esc(post["read_time"])}</div><h1 class="article-title">{esc(post["title"])}</h1><p class="article-dek">{esc(post["excerpt"])}</p><article class="article">{body}<h2>Sources &amp; further reading</h2><ul>{''.join(f'<li class="source"><a href="{esc(s["url"])}" rel="noopener noreferrer">{esc(s["title"])}</a></li>' for s in post.get("sources",[]))}</ul><div class="article-note"><strong>CYLATIC RESEARCH</strong><br>Defensive analysis for security engineers. Validate vendor-specific indicators and detection logic against your own telemetry before production use.</div></article></main><footer>© 2026 CYLATIC · <a href="../../../../">Cybersecurity &amp; IT Infrastructure</a> · <a href="../../../../privacy-policy.html">Privacy</a></footer></body></html>'''


def render_card(post,date):
    slug=safe_slug(post["slug"]); tags=" · ".join(esc(k) for k in post.get("keywords",[])[:4])
    return f'''<article class="post-card"><div class="post-main"><span>{date:%d %b %Y} · {esc(post["category"]).upper()}</span><h2>{esc(post["title"])}</h2><p>{esc(post["excerpt"])}</p><div class="post-tags">{tags}</div></div><a class="post-link" href="{date:%Y/%m/%d}/{slug}.html">READ ANALYSIS <b>↗</b></a></article>'''


def update_index(posts,date):
    idx=ROOT/"blog/index.html"; text=idx.read_text(encoding="utf-8")
    new_cards="".join(render_card(p,date) for p in posts)
    m=re.search(r"<!-- POSTS_START -->(.*?)<!-- POSTS_END -->",text,re.S)
    existing=m.group(1) if m else ""
    # Keep the archive and put the newest three articles first; cap the landing page at 30 cards.
    combined=new_cards+existing
    cards=re.findall(r"<article class=\"post-card\">.*?</article>",combined,re.S)[:30]
    replacement="<!-- POSTS_START -->"+"".join(cards)+"<!-- POSTS_END -->"
    if m: text=text[:m.start()]+replacement+text[m.end():]
    idx.write_text(text,encoding="utf-8")


def update_sitemap(posts,date):
    sm=ROOT/"sitemap.xml"; sitemap=sm.read_text(encoding="utf-8")
    additions="".join(f'<url><loc>{BASE}/blog/{date:%Y/%m/%d}/{safe_slug(p["slug"])}.html</loc><lastmod>{date.isoformat()}</lastmod></url>' for p in posts)
    sm.write_text(sitemap.replace("</urlset>",additions+"</urlset>"),encoding="utf-8")


def main():
    today=dt.date.today(); items=[]
    for name,url,weight in FEEDS:
        try: items.extend(parse_feed(name,url,weight))
        except Exception as e: print(f"Feed failed: {name}: {e}")
    if not items: raise RuntimeError("No current cybersecurity news could be retrieved")
    items.sort(key=score,reverse=True)
    existing="\n".join(p.read_text(errors="ignore") for p in (ROOT/"blog").rglob("*.html"))
    candidates=[x for x in items if x["title"][:90].lower() not in existing.lower()]
    if len(candidates)<3: candidates=items
    result=call_gemini(candidates[:18]); posts=result.get("posts",[])
    if len(posts)!=3: raise RuntimeError(f"Gemini returned {len(posts)} posts; exactly 3 are required")
    used=set(); out=ROOT/"blog"/f"{today:%Y}"/f"{today:%m}"/f"{today:%d}"; out.mkdir(parents=True,exist_ok=True)
    for post in posts:
        slug=safe_slug(post.get("slug",post.get("title","")))
        if not slug or slug in used: raise RuntimeError("Gemini returned duplicate/invalid article slugs")
        used.add(slug); post["slug"]=slug
        (out/f"{slug}.html").write_text(article_page(post,today),encoding="utf-8")
    update_index(posts,today); update_sitemap(posts,today)
    print("Published 3 cybersecurity research articles:")
    for p in posts: print(f" - {p['slug']}")

if __name__=="__main__": main()
