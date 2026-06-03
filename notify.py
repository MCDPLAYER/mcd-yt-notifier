import os, json, urllib.request
import xml.etree.ElementTree as ET

RSS = "https://www.youtube.com/feeds/videos.xml?channel_id=UC8gaXxPaH7IhqO4k4KYruPQ"
ROLE_ID = "1511784484142452749"            # cargo "Avisos de video"
WEBHOOK = os.environ["DISCORD_WEBHOOK"]
STATE = "state.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=20)


def is_short(vid):
    # Short fica em /shorts/<id>; video normal redireciona pra /watch.
    try:
        return "/shorts/" in fetch("https://www.youtube.com/shorts/" + vid).geturl()
    except Exception:
        return False  # na duvida, trata como video normal


def post(title, link):
    body = json.dumps({
        "content": "<@&%s> \U0001F3AC **Video novo no canal!**\n%s\n%s" % (ROLE_ID, title, link),
        "allowed_mentions": {"parse": ["roles"]},
    }).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK, data=body,
        headers={"Content-Type": "application/json", "User-Agent": UA})
    urllib.request.urlopen(req, timeout=20)


first_run = not os.path.exists(STATE)
seen = []
if not first_run:
    try:
        seen = json.load(open(STATE)).get("seen", [])
    except Exception:
        seen = []
seen_set = set(seen)

root = ET.fromstring(fetch(RSS).read())
entries = root.findall(ATOM + "entry")
entries.reverse()  # do mais antigo pro mais novo

new_ids = []
for e in entries:
    vid = e.findtext(YT + "videoId")
    if not vid or vid in seen_set:
        continue
    new_ids.append(vid)
    title = e.findtext(ATOM + "title") or "(sem titulo)"
    if first_run:
        continue  # primeira rodada nao dispara o historico
    if is_short(vid):
        print("skip short:", title)
        continue
    print("POST:", title)
    post(title, "https://www.youtube.com/watch?v=" + vid)

all_ids = (seen + new_ids)[-300:]
json.dump({"seen": all_ids}, open(STATE, "w"))
print("ok first_run=%s novos=%d" % (first_run, len(new_ids)))
