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
    ("Google News Cybersecurity", "https://news.google.com/rss/search?q=" + urllib.parse.quote("cybersecurity when:1d") + "&hl=en-US&gl=US&ceid=US:en", 1.35),
    ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews", 1.25),
    ("BleepingComputer", "https://www.bleepingcomputer.com/feed/", 1.25),
    ("SecurityWeek", "https://feeds.feedburner.com/securityweek", 1.10),
]
KEYWORDS = {"zero-day":8,"0-day":8,"ransomware":7,"critical vulnerability":7,"actively exploited":9,"exploitation":5,"breach":5,"supply chain":6,"identity":4,"cloud":3,"microsoft":3,"ai security":6,"apt":5,"cisa":5,"critical infrastructure":6,"malware":5,"phishing":4}

def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Cylatic-ResearchBot/1.0"})
    with urllib.request.urlopen(req,timeout=20) as r:return r.read()

def text_of(node): return " ".join(node.itertext()).strip() if node is not None else ""

def parse_feed(name,url,weight):
    root=ET.fromstring(fetch(url)); items=root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry"); out=[]
    for item in items[:30]:
        title=text_of(item.find("title")) or text_of(item.find("{http://www.w3.org/2005/Atom}title")); ln=item.find("link"); link=(ln.text or "").strip() if ln is not None and ln.text else ""
        if not link:
            ln=item.find("{http://www.w3.org/2005/Atom}link"); link=ln.attrib.get("href","") if ln is not None else ""
        summary=text_of(item.find("description")) or text_of(item.find("{http://www.w3.org/2005/Atom}summary")); pub=text_of(item.find("pubDate")) or text_of(item.find("{http://www.w3.org/2005/Atom}published"))
        if title and link: out.append({"source":name,"title":title,"link":link,"summary":re.sub(r"\s+"," ",summary)[:1200],"published":pub,"weight":weight})
    return out

def score(item):
    t=(item["title"]+" "+item["summary"]).lower(); return item["weight"]*10+sum(v for k,v in KEYWORDS.items() if k in t)+(1 if item["published"] else 0)

def call_openai(items):
    key=os.environ.get("OPENAI_API_KEY")
    if not key: raise RuntimeError("OPENAI_API_KEY GitHub secret is not configured")
    today=dt.date.today().isoformat(); sources="\n".join(f"- {x['source']} | {x['title']} | {x['link']} | {x['summary']}" for x in items[:10])
    prompt=f'''You are the senior technical editor for Cylatic, a cybersecurity engineering company. Today is {today}.
Select ONE most important and technically useful cybersecurity news development from the supplied recent sources and write an original defensive technical analysis. Do not copy article text. Do not invent facts, CVEs, products, dates, groups or statistics. Use only supplied source material for current-event claims and qualify uncertainty.
Audience: SOC engineers, SIEM engineers, cloud/security engineers, network defenders and security architects. Make it useful rather than a news rewrite: explain attack surface, intrusion chain at a high level, telemetry, detection engineering, identity/network controls, containment, threat hunting and architecture implications. Never provide exploit code, weaponization steps, credential theft instructions or instructions for attacking real systems.
Return ONLY valid JSON with keys: title, slug, excerpt, category, keywords (array of 6-10 strings), read_time, body_html, sources (array of objects with title and url).
body_html must be 1400-2200 words and use only p,h2,h3,ul,ol,pre,strong,code elements. Include at least one defensive detection example in a pre block labeled pseudocode or SIEM logic. End with Sources & further reading.
RECENT SOURCES:\n{sources}'''
    payload=json.dumps({"model":"gpt-5.6-luna","input":prompt}).encode(); req=urllib.request.Request("https://api.openai.com/v1/responses",data=payload,headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=120) as r:data=json.loads(r.read())
    text=data.get("output_text") or "".join(c.get("text","") for o in data.get("output",[]) for c in o.get("content",[]) if c.get("type")=="output_text")
    return json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())

def esc(s): return html.escape(str(s),quote=True)

def article_page(post,date):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#11120f"><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="{BASE}/blog/{date:%Y/%m/%d}/{esc(post['slug'])}.html"><title>{esc(post['title'])} | Cylatic Research</title><meta name="description" content="{esc(post['excerpt'])}"><meta property="og:type" content="article"><meta property="og:title" content="{esc(post['title'])}"><meta property="og:description" content="{esc(post['excerpt'])}"><meta property="og:url" content="{BASE}/blog/{date:%Y/%m/%d}/{esc(post['slug'])}.html"><meta name="twitter:card" content="summary"><script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-9788655168653957" crossorigin="anonymous"></script><link rel="stylesheet" href="../../../../assets/css/blog.css"><style>main{{max-width:900px;margin:auto;padding:100px 32px 120px}}.article-meta{{font-size:10px;letter-spacing:.15em;font-weight:700;color:#70726a}}.article-title{{font:700 clamp(48px,7vw,88px)/.92 'Space Grotesk';letter-spacing:-.07em;margin:24px 0 30px}}.dek{{font-size:20px;line-height:1.65;color:#5e6059;max-width:780px;border-bottom:1px solid var(--line);padding-bottom:40px}}.article{{margin-top:55px}}.article h2{{font:600 36px/1.05 'Space Grotesk';letter-spacing:-.045em;margin:55px 0 18px}}.article h3{{font:600 23px 'Space Grotesk';margin-top:35px}}.article p,.article li{{font-size:16px;line-height:1.85;color:#3f413c}}.article ul,.article ol{{padding-left:25px}}.article pre{{background:#e8e9e2;padding:20px;overflow:auto;font:13px/1.7 monospace}}.article .source{{font-size:12px!important;color:#6b6d65!important}.source a{{text-decoration:underline}}code{{background:#e4e5dd;padding:2px 6px;font-family:monospace}}@media(max-width:700px){{main{{padding:75px 20px 90px}}.article-title{{font-size:49px}}.article h2{{font-size:31px}}}}</style></head><body><header><a class="brand" href="../../../../">CYLATIC</a><nav><a href="../../../../tools/">Tools</a><a class="active" href="../../../../blog/">Research</a><a href="../../../../#contact">Contact</a></nav></header><main><div class="article-meta">{date:%d %b %Y} · {esc(post['category']).upper()} · {esc(post['read_time'])}</div><h1 class="article-title">{esc(post['title'])}</h1><p class="dek">{esc(post['excerpt'])}</p><article class="article">{post['body_html']}</article></main><footer>© 2026 CYLATIC · <a href="../../../../">Cybersecurity & IT Infrastructure</a> · <a href="../../../../privacy-policy.html">Privacy</a></footer></body></html>'''

def main():
    now=dt.date.today(); items=[]
    for n,u,w in FEEDS:
        try: items.extend(parse_feed(n,u,w))
        except Exception as e: print(f"Feed failed: {n}: {e}")
    items.sort(key=score,reverse=True)
    if not items: raise RuntimeError("No current cybersecurity news could be retrieved")
    existing="\n".join(p.read_text(errors="ignore") for p in (ROOT/"blog").rglob("*.html")); candidates=[x for x in items if x["title"][:70].lower() not in existing.lower()]
    post=call_openai(candidates[:12]); slug=re.sub(r"[^a-z0-9]+","-",post["slug"].lower()).strip("-")[:80]
    out=ROOT/"blog"/f"{now:%Y}"/f"{now:%m}"/f"{now:%d}"; out.mkdir(parents=True,exist_ok=True); (out/f"{slug}.html").write_text(article_page(post,now),encoding="utf-8")
    idx=ROOT/"blog/index.html"; text=idx.read_text(encoding="utf-8"); card=f'<article class="post-card"><div><span>{now:%d %b %Y} · {esc(post["category"]).upper()}</span><h2>{esc(post["title"])}</h2><p>{esc(post["excerpt"])}</p></div><a href="{now:%Y/%m/%d}/{slug}.html">READ ANALYSIS →</a></article>'; text=re.sub(r'<!-- POSTS_START -->.*?<!-- POSTS_END -->','<!-- POSTS_START -->'+card+'<!-- POSTS_END -->',text,count=1,flags=re.S); idx.write_text(text,encoding="utf-8")
    sm=ROOT/"sitemap.xml"; sitemap=sm.read_text(encoding="utf-8"); url=f'<url><loc>{BASE}/blog/{now:%Y/%m/%d}/{slug}.html</loc><lastmod>{now.isoformat()}</lastmod></url>'; sm.write_text(sitemap.replace("</urlset>",url+"</urlset>"),encoding="utf-8"); print(f"Published: {slug}")

if __name__=="__main__": main()
