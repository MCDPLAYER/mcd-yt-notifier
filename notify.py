# -*- coding: utf-8 -*-
"""Avisa no Discord (MCD SPACE) quando sai video novo ou quando entra live no YouTube.

Dois canais monitorados: MCD ANIMES (principal, so video) e Outro MCD
(secundario, video + LIVE). Cada bucket pinga so o SEU cargo.
Custo por rodada: ~2 unidades de quota por canal (playlistItems + videos.list).
"""
import os, re, json, urllib.request
import xml.etree.ElementTree as ET

CANAIS = [
    {
        "key": "mcd-animes",
        "nome": "MCD ANIMES",
        "yt": "UC8gaXxPaH7IhqO4k4KYruPQ",
        "video": {
            "webhook_env": "DISCORD_WEBHOOK",          # #videos-novos
            "role": "1511784484142452749",             # Avisos de video
            "titulo": "\U0001F3AC **Video novo no canal!**",
        },
        "live": None,                                  # nao faz live no principal
        "pula_short": True,
    },
    {
        "key": "outro-mcd",
        "nome": "Outro MCD",
        "yt": "UCy6YnMSx2jXGAy9lhPf0-sw",
        "video": {
            "webhook_env": "DISCORD_WEBHOOK_OUTRO",    # #outro-mcd
            "role": "1539635991898365983",             # Video do Outro MCD
            "titulo": "\U0001F3AE **Video novo no Outro MCD!**",
        },
        "live": {
            "webhook_env": "DISCORD_WEBHOOK_LIVES",    # #lives
            "role": "1511784487493701673",             # Live
            "titulo": "\U0001F534 **AO VIVO AGORA!**",
        },
        "pula_short": True,
    },
]

SHORT_MAX_SEC = 180          # video com ate 180s = Short (ignorado)
YT_KEY = os.environ.get("YT_API_KEY", "").strip()
STATE = "state.json"
DRY = os.environ.get("DRY_RUN") == "1"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


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


# ---------------------------------------------------------------- descoberta
# Tres fontes de videoId. A playlist de uploads OMITE item de forma
# intermitente, entao a uniao com RSS + pagina /live e o que evita furo.

def ids_playlist(yt):
    """1 unidade de quota. Fonte principal."""
    pl = "UU" + yt[2:]
    d = json.load(http_get("https://www.googleapis.com/youtube/v3/playlistItems"
        "?part=contentDetails&maxResults=10&playlistId=%s&key=%s" % (pl, YT_KEY)))
    return [i["contentDetails"]["videoId"] for i in d.get("items", [])]


def ids_rss(yt):
    """De graca. Pode dar 404 em IP de datacenter - se der, so ignora."""
    A = "{http://www.w3.org/2005/Atom}"
    Y = "{http://www.youtube.com/xml/schemas/2015}"
    root = ET.fromstring(http_get(
        "https://www.youtube.com/feeds/videos.xml?channel_id=" + yt).read())
    return [e.findtext(Y + "videoId") for e in root.findall(A + "entry")
            if e.findtext(Y + "videoId")]


def id_live_html(yt):
    """De graca. A pagina /live do canal aponta pro stream que esta no ar."""
    html = http_get("https://www.youtube.com/channel/%s/live" % yt).read().decode("utf-8", "replace")
    if '"isLiveNow":true' not in html and '"isLive":true' not in html:
        return None
    m = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
    return m.group(1) if m else None


def coleta_ids(yt):
    """Uniao das fontes que responderam. Fonte que falha nao derruba a rodada."""
    ids, fontes = [], []
    for nome, fn in (("playlist", ids_playlist), ("rss", ids_rss), ("live-html", id_live_html)):
        if nome == "playlist" and not YT_KEY:
            continue
        try:
            r = fn(yt)
            r = [r] if isinstance(r, str) else (r or [])
            for v in r:
                if v not in ids:
                    ids.append(v)
            fontes.append("%s:%d" % (nome, len(r)))
        except Exception as e:
            fontes.append("%s:ERRO(%s)" % (nome, type(e).__name__))
    return ids, fontes


def detalhes(ids):
    """1 unidade. Traz titulo, duracao e se esta ao vivo."""
    if not ids or not YT_KEY:
        return {}
    d = json.load(http_get("https://www.googleapis.com/youtube/v3/videos"
        "?part=contentDetails,snippet,liveStreamingDetails&id=%s&key=%s"
        % (",".join(ids[:50]), YT_KEY)))
    out = {}
    for it in d.get("items", []):
        sn = it["snippet"]
        out[it["id"]] = {
            "titulo": sn.get("title", "(video novo)"),
            "dur": iso_to_sec(it.get("contentDetails", {}).get("duration")),
            "estado": sn.get("liveBroadcastContent", "none"),   # live | upcoming | none
            "foi_live": "liveStreamingDetails" in it,
        }
    return out


# ------------------------------------------------------------------ postagem
def post(webhook, role, titulo, nome_video, vid):
    body = json.dumps({
        "content": "<@&%s> %s\n%s\nhttps://www.youtube.com/watch?v=%s"
                   % (role, titulo, nome_video, vid),
        "allowed_mentions": {"parse": ["roles"]}}).encode("utf-8")
    # ?wait=true devolve a mensagem criada - unica prova real de que o ping saiu
    url = webhook + ("&" if "?" in webhook else "?") + "wait=true"
    r = urllib.request.urlopen(urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": UA}), timeout=20)
    msg = json.load(r)
    print("   -> postado msg=%s mention_roles=%s" % (msg.get("id"), msg.get("mention_roles")))


# -------------------------------------------------------------------- estado
def carrega():
    if not os.path.exists(STATE):
        return {"canais": {}}
    st = json.load(open(STATE))
    if "canais" not in st:   # formato antigo ({"seen": [...]}) era so o canal principal
        st = {"canais": {"mcd-animes": {
            "seen": st.get("seen", []), "watch": [], "live_avisado": []}}}
        print("estado antigo migrado para mcd-animes (%d ids)"
              % len(st["canais"]["mcd-animes"]["seen"]))
    return st


def roda_canal(cfg, st):
    key = cfg["key"]
    novo_canal = key not in st["canais"]
    e = st["canais"].setdefault(key, {"seen": [], "watch": [], "live_avisado": []})
    seen, watch, avisados = e["seen"], e.get("watch", []), e.get("live_avisado", [])

    ids, fontes = coleta_ids(cfg["yt"])
    print("[%s] fontes: %s" % (cfg["nome"], " ".join(fontes)))

    if novo_canal:
        # primeira vez: so grava o que existe hoje, nao dispara aviso retroativo
        e["seen"] = ids[-300:]
        print("[%s] primeira rodada - %d ids gravados, nada postado" % (cfg["nome"], len(ids)))
        return

    # 'watch' = live agendada ja vista: reconfere sempre, senao some da playlist
    checar = [v for v in ids if v not in seen] + [v for v in watch if v not in ids]
    if not checar:
        print("[%s] nada novo" % cfg["nome"])
        return

    det = detalhes(checar)
    novo_watch = []

    for vid in reversed(checar):            # do mais antigo pro mais novo
        d = det.get(vid)
        if not d:                           # sem YT_KEY, ou video sumiu/privado
            continue
        estado = d["estado"]

        if estado == "live":
            if not cfg["live"] or vid in avisados:
                continue
            print("[%s] LIVE: %s" % (cfg["nome"], d["titulo"]))
            if not DRY:
                post(os.environ[cfg["live"]["webhook_env"]], cfg["live"]["role"],
                     cfg["live"]["titulo"], d["titulo"], vid)
            avisados.append(vid)
            seen.append(vid)                # o VOD depois nao vira "video novo"
            continue

        if estado == "upcoming":
            # live agendada: nao avisa ainda, so nao perde de vista ate comecar
            novo_watch.append(vid)
            print("[%s] agendada (aguardando comecar): %s" % (cfg["nome"], d["titulo"]))
            continue

        if vid in seen:
            continue
        if cfg["pula_short"] and not d["foi_live"] and d["dur"] <= SHORT_MAX_SEC:
            print("[%s] pula short: %s" % (cfg["nome"], vid))
            seen.append(vid)
            continue
        print("[%s] VIDEO: %s" % (cfg["nome"], d["titulo"]))
        if not DRY:
            post(os.environ[cfg["video"]["webhook_env"]], cfg["video"]["role"],
                 cfg["video"]["titulo"], d["titulo"], vid)
        seen.append(vid)

    e["seen"] = seen[-300:]
    e["watch"] = novo_watch[-20:]
    e["live_avisado"] = avisados[-50:]


def main():
    st = carrega()
    for cfg in CANAIS:
        try:
            roda_canal(cfg, st)
        except Exception as ex:
            # um canal com problema nao pode derrubar o outro
            print("WARN [%s] rodada pulada: %r" % (cfg["nome"], ex))
    if not DRY:
        json.dump(st, open(STATE, "w"), indent=1)
    print("ok modo=%s dry=%s" % ("API" if YT_KEY else "RSS", DRY))


if __name__ == "__main__":
    main()
