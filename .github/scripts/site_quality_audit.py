#!/usr/bin/env python3
"""Deterministic quality gate for Cylatic's content and monetization rebuild."""
from collections import Counter
from pathlib import Path
import html
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
FAILURES = []
WARNINGS = []
REQUIRED_FILES = ["index.html","robots.txt","sitemap.xml","ads.txt","privacy-policy.html","about/index.html","contact/index.html","editorial-policy/index.html","research/index.html","tools/index.html"]
REQUIRED_ROUTES = ["/","/about/","/contact/","/editorial-policy/","/research/","/tools/","/blog/","/privacy-policy.html"]

def fail(message): FAILURES.append(message)
def warn(message): WARNINGS.append(message)
def text_of(doc): return re.sub(r"\s+", " ", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", doc, flags=re.I|re.S)).strip()
def canonical(doc):
    m=re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',doc,re.I); return m.group(1).strip() if m else ""
def title(doc):
    m=re.search(r'<title[^>]*>(.*?)</title>',doc,re.I|re.S); return re.sub(r"\s+"," ",html.unescape(m.group(1))).strip() if m else ""

def audit():
    for rel in REQUIRED_FILES:
        if not (ROOT/rel).is_file(): fail(f"Missing required file: {rel}")
    robots=(ROOT/"robots.txt").read_text(encoding="utf-8",errors="ignore") if (ROOT/"robots.txt").exists() else ""
    if "Sitemap: https://cylatic.com/sitemap.xml" not in robots: fail("robots.txt does not advertise the canonical sitemap")
    sitemap=ROOT/"sitemap.xml"; urls=[]
    if sitemap.exists():
        try:
            root=ET.fromstring(sitemap.read_text(encoding="utf-8")); urls=[x.text.strip() for x in root.iter() if x.tag.lower().endswith("loc") and x.text]
        except Exception as exc: fail(f"sitemap.xml is not valid XML: {exc}")
    for route in REQUIRED_ROUTES:
        if "https://cylatic.com"+route not in urls: warn(f"Required route is not currently in sitemap: {route}")

    html_files=[p for p in ROOT.rglob("*.html") if ".git" not in p.parts]; titles=Counter(); indexable=0
    for path in html_files:
        doc=path.read_text(encoding="utf-8",errors="ignore"); plain=text_of(doc); t=title(doc); c=canonical(doc)
        if t: titles[t.lower()]+=1
        noindex=bool(re.search(r'<meta[^>]+name=["\']robots["\'][^>]+content=["\'][^"\']*noindex',doc,re.I))
        if not noindex:
            indexable+=1
            if not t: fail(f"Indexable page has no title: {path}")
            if not c: warn(f"Indexable page has no canonical: {path}")
            if len(plain)<350: warn(f"Very thin indexable page ({len(plain)} visible chars): {path}")
        if "your-form-id" in doc.lower() or "your-formspree" in doc.lower(): fail(f"Placeholder form action remains: {path}")
        if "pagead2.googlesyndication.com/pagead/js/adsbygoogle.js" in doc.lower(): fail(f"AdSense code is present during rebuild: {path}")
        if re.search(r'href=["\']#["\']',doc,re.I): warn(f"Empty anchor link found: {path}")
        if path.parts[-2:] and "blog" in path.parts and "2026" in path.parts and path.name!="index.html" and not noindex:
            fail(f"Legacy source-driven briefing remains indexable: {path}")
    for t,count in titles.items():
        if count>1: fail(f"Duplicate HTML title appears {count} times: {t}")

    workflow=ROOT/".github/workflows/daily-cybersecurity-research.yml"
    if workflow.exists():
        w=workflow.read_text(encoding="utf-8",errors="ignore")
        if "Publish cybersecurity research" in w or "git add blog sitemap.xml" in w: fail("Old automatic publication path remains in workflow")
        for required in ("research_monitor.py","site_migration.py","site_quality_audit.py"): 
            if required not in w: fail(f"Workflow missing required quality component: {required}")
    privacy=ROOT/"privacy-policy.html"
    if privacy.exists():
        p=privacy.read_text(encoding="utf-8",errors="ignore").lower()
        if "google" not in p or "adsense" not in p: warn("Privacy policy should retain explicit Google/AdSense disclosure for future monetization")
    ads=ROOT/"ads.txt"
    if ads.exists() and "google.com, pub-9788655168653957, DIRECT" not in ads.read_text(encoding="utf-8",errors="ignore"): fail("ads.txt publisher record is incorrect")
    print(f"Audited {len(html_files)} HTML pages; {indexable} are currently indexable.")
    for item in WARNINGS: print("WARNING:",item)
    if FAILURES:
        for item in FAILURES: print("FAIL:",item)
        print(f"Quality gate failed with {len(FAILURES)} failure(s)."); return 1
    print("Quality gate passed."); return 0

if __name__=="__main__": sys.exit(audit())
