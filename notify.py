import os, re, json, urllib.request
import xml.etree.ElementTree as ET

# === CONFIG ===
CHANNEL_ID    = "UC8gaXxPaH7IhqO4k4KYruPQ"   # canal MCD ANIMES
ROLE_ID       = "1511784484142452749"         # cargo "Avisos de video"
SHORT_MAX_SEC = 180                           # video com ate 180s = Short (ignorado)
WEBHOOK       = os.environ["DISCORD_WEBHOOK"]
YT_KEY        = os.environ.get("YT_API_KEY", "").strip()
STATE         = "state.json"
UA            = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def http_get(url, tries=3):
    err = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20)
        except Exception as e:
            err = e
    raise err


def iso_to_sec(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def via_api():
    pl = "UU" + CHANNEL_ID[2:]   # playlist de uploads do canal
    d = json.load(http_get("https://www.googleapis.com/youtube/v3/playlistItems"
        "?part=contentDetails&maxResults=10&playlistId=%s&key=%s" % (pl, YT_KEY)))
    ids = [i["contentDetails"]["videoId"] for i in d.get("items", [])]
    durs, titles = {}, {}
    if ids:
        d2 = json.load(http_get("https://www.googleapis.com/youtube/v3/videos"
            "?part=contentDetails,snippet&id=%s&key=%s" % (",".join(ids), YT_KEY)))
        for it in d2.get("items", []):
            durs[it["id"]] = iso_to_sec(it["contentDetails"]["duration"])
            titles[it["id"]] = it["snippet"]["title"]
    return ids, titles, durs


def via_rss():
    A = "{http://www.w3.org/2005/Atom}"
    Y = "{http://www.youtube.com/xml/schemas/2015}"
    root = ET.fromstring(http_get(
        "https://www.youtube.com/feeds/videos.xml?channel_id=" + CHANNEL_ID).read())
    ids, titles = [], {}
    for e in root.findall(A + "entry"):
        v = e.findtext(Y + "videoId")
        if v:
            ids.append(v)
            titles[v] = e.findtext(A + "title") or "(video novo)"
    return ids, titles, {}


def is_short_rss(vid):
    try:
        return "/shorts/" in http_get("https://www.youtube.com/shorts/" + vid).geturl()
    except Exception:
        return False


def post(title, link):
    body = json.dumps({
        "content": "<@&%s> \U0001F3AC **Video novo no canal!**\n%s\n%s" % (ROLE_ID, title, link),
        "allowed_mentions": {"parse": ["roles"]}}).encode("utf-8")
    urllib.request.urlopen(urllib.request.Request(WEBHOOK, data=body,
        headers={"Content-Type": "application/json", "User-Agent": UA}), timeout=20)


def main():
    first_run = not os.path.exists(STATE)
    seen = [] if first_run else json.load(open(STATE)).get("seen", [])
    seen_set = set(seen)

    if YT_KEY:
        ids, titles, durs = via_api()
        is_short = lambda v: durs.get(v, 9999) <= SHORT_MAX_SEC
        modo = "API"
    else:
        ids, titles, _ = via_rss()
        is_short = is_short_rss
        modo = "RSS"

    new_ids = []
    for vid in reversed(ids):              # do mais antigo pro mais novo
        if vid in seen_set:
            continue
        new_ids.append(vid)
        if first_run:
            continue
        if is_short(vid):
            print("skip short:", vid)
            continue
        print("POST:", titles.get(vid, vid))
        post(titles.get(vid, "(video novo)"), "https://www.youtube.com/watch?v=" + vid)

    json.dump({"seen": (seen + new_ids)[-300:]}, open(STATE, "w"))
    print("ok first_run=%s novos=%d modo=%s" % (first_run, len(new_ids), modo))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("WARN: rodada pulada (feed/api indisponivel):", repr(e))
