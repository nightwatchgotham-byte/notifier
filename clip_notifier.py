#!/usr/bin/env python3
"""
Clipping campaign notifier.

Checks a few sources for new campaigns matching your keywords (default: GTA 6,
IShowSpeed) and sends an alert to Telegram and/or Discord. Remembers what it
already sent in seen.json so you never get the same alert twice.

Setup:
  pip install requests
  export TELEGRAM_BOT_TOKEN="123:abc"     # from @BotFather
  export TELEGRAM_CHAT_ID="123456789"     # your chat id
  export DISCORD_WEBHOOK_URL=""           # optional
  python clip_notifier.py                 # runs forever, checks every 15 min
  python clip_notifier.py --once          # single check (good for cron)
"""
import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path

import requests

KEYWORDS = ["gta 6", "gta6", "gta vi", "ishowspeed", "speed"]
CAMPAIGN_WORDS = ["clip", "clipping", "clipper", "campaign", "per 1,000 views", "cpm"]

# Pages to watch. Add or remove freely. NOTE: some of these sites load their
# list with JavaScript, so a plain fetch may see nothing. If a page never
# triggers an alert, open it in your browser, look in DevTools > Network for the
# JSON request that returns the campaign list, and put that URL here instead.
WATCH_PAGES = {
    "Content Rewards": "https://contentrewards.com/",
    "Whop Content Rewards": "https://whop.com/discover/content-rewards/",
}

REDDIT_QUERIES = [
    "GTA 6 clipping campaign",
    "clippers needed GTA 6",
    "IShowSpeed clipping campaign",
]

HEADERS = {"User-Agent": "clip-notifier/1.0 (personal use)"}
SEEN_FILE = Path(__file__).with_name("seen.json")
INTERVAL_SECONDS = 15 * 60


def load_seen():
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        return set()


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen)))


def matches(text):
    t = text.lower()
    return any(k in t for k in KEYWORDS) and any(w in t for w in CAMPAIGN_WORDS)


def check_reddit():
    found = []
    for q in REDDIT_QUERIES:
        try:
            r = requests.get(
                "https://www.reddit.com/search.json",
                params={"q": q, "sort": "new", "limit": 15, "t": "week"},
                headers=HEADERS,
                timeout=20,
            )
            r.raise_for_status()
            for child in r.json()["data"]["children"]:
                d = child["data"]
                text = f'{d.get("title", "")} {d.get("selftext", "")}'
                if matches(text):
                    found.append(
                        (f"reddit:{d['id']}", f"Reddit: {d['title']}", "https://reddit.com" + d["permalink"])
                    )
        except Exception as e:
            print(f"[reddit] '{q}' failed: {e}")
    return found


def check_pages():
    """Alert when a watched page newly contains a keyword + campaign word."""
    found = []
    for name, url in WATCH_PAGES.items():
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            text = re.sub(r"<[^>]+>", " ", r.text)
            text = re.sub(r"\s+", " ", text)
            for k in KEYWORDS:
                for m in re.finditer(re.escape(k), text, flags=re.I):
                    snippet = text[max(0, m.start() - 80): m.end() + 120].strip()
                    if matches(snippet):
                        sig = hashlib.md5(f"{name}:{snippet}".encode()).hexdigest()
                        found.append((f"page:{sig}", f"{name}: ...{snippet}...", url))
                        break
        except Exception as e:
            print(f"[page] {name} failed: {e}")
    return found


def notify(title, url):
    msg = f"New clipping campaign match\n{title}\n{url}"
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    hook = os.getenv("DISCORD_WEBHOOK_URL")
    sent = False
    if token and chat:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat, "text": msg},
                timeout=20,
            )
            sent = True
        except Exception as e:
            print(f"[telegram] failed: {e}")
    if hook:
        try:
            requests.post(hook, json={"content": msg}, timeout=20)
            sent = True
        except Exception as e:
            print(f"[discord] failed: {e}")
    if not sent:
        print(msg)  # no channel configured: just print
    return sent or True


MATCHES_FILE = Path(__file__).with_name("matches.json")
HTML_FILE = Path(__file__).with_name("docs") / "index.html"


def write_dashboard(matches):
    """Write the web page (docs/index.html) that works as the notification feed."""
    from html import escape

    HTML_FILE.parent.mkdir(exist_ok=True)
    rows = "".join(
        f'<li data-ts="{m.get("ts", 0)}"><span class="new">NEW</span>'
        f'<a href="{escape(m["url"])}" target="_blank" rel="noopener">{escape(m["title"])}</a>'
        f'<small>{escape(m["time"])}</small></li>'
        for m in reversed(matches)
    ) or "<li>No matches yet. This page updates itself, check back soon.</li>"
    page = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Clipping campaigns</title>
<style>
body{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem}
ul{padding:0}li{margin:.8rem 0;list-style:none;padding:.8rem;border:1px solid #8884;border-radius:8px}
li.fresh{border-color:#2a7;background:#2a71}
small{display:block;opacity:.6;margin-top:.3rem}a{text-decoration:none}
.new{display:none;background:#2a7;color:#fff;font-size:.7rem;padding:.1rem .4rem;border-radius:4px;margin-right:.5rem}
li.fresh .new{display:inline}
button{padding:.5rem .9rem;border-radius:8px;border:1px solid #8886;cursor:pointer}
</style>
<h1>GTA 6 / IShowSpeed clipping campaigns</h1>
<p>New campaign links show up here. Keywords: __KW__</p>
<p><button id=n>Turn on browser alerts</button> <span id=s></span></p>
<ul>__ROWS__</ul>
<script>
const items=[...document.querySelectorAll('li[data-ts]')];
const now=Date.now()/1000;
items.forEach(li=>{if(now-li.dataset.ts<86400)li.classList.add('fresh')});
const top=items.length?items[0].dataset.ts:'0';
let last='0';try{last=localStorage.getItem('last')||'0'}catch(e){}
const btn=document.getElementById('n'),st=document.getElementById('s');
btn.onclick=()=>Notification.requestPermission().then(p=>st.textContent=p==='granted'?'Alerts on (keep this tab open)':'Blocked');
if('Notification' in window&&Notification.permission==='granted'&&+top>+last&&last!=='0'){
  new Notification('New clipping campaign',{body:items[0].querySelector('a').textContent});
}
try{localStorage.setItem('last',top)}catch(e){}
setTimeout(()=>location.reload(),300000); // refresh every 5 min
</script>"""
    page = page.replace("__KW__", escape(", ".join(KEYWORDS))).replace("__ROWS__", rows)
    HTML_FILE.write_text(page)


def run_once():
    seen = load_seen()
    try:
        matches = json.loads(MATCHES_FILE.read_text())
    except Exception:
        matches = []
    new = 0
    for uid, title, url in check_reddit() + check_pages():
        if uid in seen:
            continue
        notify(title, url)
        seen.add(uid)
        matches.append({"title": title, "url": url, "ts": int(time.time()),
                        "time": time.strftime("%d %b %Y, %H:%M UTC", time.gmtime())})
        new += 1
    matches = matches[-100:]
    MATCHES_FILE.write_text(json.dumps(matches))
    write_dashboard(matches)
    save_seen(seen)
    print(f"Check done, {new} new alert(s).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    if args.once:
        run_once()
    else:
        while True:
            run_once()
            time.sleep(INTERVAL_SECONDS)
