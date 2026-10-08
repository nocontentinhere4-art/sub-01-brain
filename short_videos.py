"""Short videos on his phone (#56 part 2): YouTube Shorts and TikTok, one place per site.

- YouTube Shorts: a results search for "<query> #shorts" (Restricted Mode: the PREF f2=8000000 cookie every context
  carries); the Shorts in its ytInitialData are parsed by search_sources.parse_youtube (/shorts/<id> links).
- TikTok: a tag page (www.tiktok.com/tag/<tag>; robots.txt disallows /search and /search/video, allows /tag), logged
  out unless #60's session exists (browse.Browser._use picks the context; view_only.py filters private pages and
  actions on both). Comments, likes, follow and login boxes are hidden (HIDE_TIKTOK); a login wall is left; a page
  whose caption fails the guard is left.
- Every short plays muted (Chromium --mute-audio + browse.VIDEO_JS) for at most SHORTS_MAX_S, then the next shorts
  in the queue are the vote's options (local options: no paid call).
Pure helpers; browse.Browser._shorts drives the feed.
"""
import re
import urllib.parse

from search_sources import _dedup, _result, parse_html, strip_tags

SHORTS_MAX_S = 45.0                    # a short is watched at most this long (real seconds), then the next one
TIKTOK_SHARE = 0.5                     # feeds that start on TikTok (else YouTube Shorts); #89: the owner wants TikTok
TIKTOK_VIDEO = re.compile(r"^https://www\.tiktok\.com/@([\w.]{2,30})/video/(\d{8,25})$")


def parse_tiktok(text, base="https://www.tiktok.com/"):
    """A TikTok tag page as Chromium renders it (logged out): its video links, the caption next to each, the
    creator. Nothing when the page is only a login wall."""
    out = []
    for a in parse_html(text).find_all("a"):
        url = urllib.parse.urljoin(base, a.attrs.get("href", "")).split("?")[0]
        m = TIKTOK_VIDEO.match(url)
        if not m:
            continue
        box = a.parent
        cap = ""
        for _ in range(3):                                   # the caption sits next to the link in the item
            if box is None:
                break
            d = next((n for n in box.iter() if n.attrs.get("data-e2e") in ("video-desc", "challenge-item-desc")
                      or "desc" in " ".join(n.cls()).lower()), None)
            if d is not None and d.text():
                cap = d.text()
                break
            box = box.parent
        cap = cap or a.attrs.get("title") or a.text()
        out.append(_result(url, strip_tags(cap) or f"a video by @{m.group(1)}", f"@{m.group(1)}", video=True,
                           short=True, channel=f"@{m.group(1)}", hashtags=re.findall(r"#\w+", cap)[:6]))
    return _dedup(out)


def tiktok_tag(q):
    return re.sub(r"[^a-z0-9]", "", (q or "").lower())[:40]


def tiktok_url(q):
    return f"https://www.tiktok.com/tag/{tiktok_tag(q)}"


TIKTOK_HOST = re.compile(r"(^|\.)tiktok\.com$", re.I)
HIDE_TIKTOK = """[data-e2e*="comment"],[class*="CommentList"],[class*="DivCommentContainer"],[data-e2e="browse-like"],
[data-e2e="follow-button"],[class*="DivActionItemContainer"],[class*="LoginModal"],[id*="login"]{display:none !important}"""


def feed_order(rng, share=TIKTOK_SHARE):
    """Which feed to try first: TikTok `share` of the time, else YouTube Shorts; the other one is the fallback."""
    return ["tiktok", "shorts"] if rng.random() < share else ["shorts", "tiktok"]


def watch_seconds(w):
    """A short's watch time: never longer than SHORTS_MAX_S."""
    return min(float(w), SHORTS_MAX_S)


def is_tiktok(host):
    return bool(TIKTOK_HOST.search((host or "").rstrip(".")))


def caption_ok(page_title):
    """A TikTok page's caption (its title without " | TikTok"): the guard and the chat filter (browse.video_text_ok)."""
    from browse import video_text_ok
    return video_text_ok(re.sub(r"\s*\|\s*TikTok$", "", page_title or ""))


async def settle(page, host, page_title):
    """On a TikTok page before it is shown: hide comments, likes, follow and login boxes; None if it may be shown,
    else why it must be left."""
    if not is_tiktok(host):
        return None
    await page.add_style_tag(content=HIDE_TIKTOK)
    return None if caption_ok(page_title) else "guard"


# --- TikTok embed cards (#89): what the server can show when TikTok's feed is empty for it -------------------------
NOTE_BLOCKED = "TikTok blocked from the server today → YouTube Shorts"
NOTE_CARDS = "TikTok's feed is closed to the server: public TikTok videos shown as embed cards (not played)"


def oembed_url(video_url):
    return "https://www.tiktok.com/oembed?" + urllib.parse.urlencode({"url": video_url})


def parse_oembed(text, video_url):
    """TikTok's public oEmbed JSON -> {url, title, author, thumb, hashtags} or None."""
    import json
    try:
        d = json.loads(text or "")
    except ValueError:
        return None
    if not isinstance(d, dict) or not d.get("title") and not d.get("author_name"):
        return None
    cap = " ".join(str(d.get("title") or "").split())[:200]
    thumb = str(d.get("thumbnail_url") or "")
    return {"url": video_url, "title": strip_tags(cap) or f"a video by {d.get('author_name', '')}"[:140],
            "author": " ".join(str(d.get("author_name") or "").split())[:60],
            "thumb": thumb if thumb.startswith("https://") else "", "hashtags": re.findall(r"#\w+", cap)[:6]}


def card_html(card):
    """A dark phone-sized card: thumbnail, caption, creator, and what it is (no video, no buttons, no links)."""
    import html as h
    img = f'<img src="{h.escape(card["thumb"], quote=True)}" alt="">' if card.get("thumb") else ""
    return ("<!doctype html><meta charset=utf-8><style>body{margin:0;background:#000;color:#eee;font:15px/1.35 "
            "-apple-system,Helvetica,Arial,sans-serif}.w{max-width:420px;margin:0 auto;padding:14px}img{width:100%;"
            "border-radius:10px;max-height:70vh;object-fit:cover}.c{margin-top:10px}.a{color:#9aa;margin-top:4px}"
            ".n{color:#667;font-size:12px;margin-top:12px}</style><div class=w>" + img
            + f'<div class=c>{h.escape(card["title"])}</div><div class=a>@{h.escape(card["author"])}</div>'
            + f"<div class=n>{h.escape(card.get('site', 'TikTok'))} · public video · "
            + f"{h.escape(card.get('how', 'its embed card (TikTok oEmbed)'))}; the video is not played</div></div>")


NOTE_EMBEDS = "TikTok: public videos in TikTok's official embed player (the logged-in feed showed none to the server)"
TIKTOK_PLAYER = "https://www.tiktok.com/player/v1/{id}?autoplay=1&muted=1&loop=1&rel=0&description=1"


def tiktok_player(video_url):
    """TikTok's official embed player for a public video (tiktok.com/player/v1/<id>; robots.txt disallows /embed/v2
    and /embed/@ for crawlers, not /player)."""
    m = TIKTOK_VIDEO.match(str(video_url).split("?")[0])
    return TIKTOK_PLAYER.format(id=m.group(2)) if m else None


NOTE_SHORTS_CARDS = "YouTube Shorts pages blocked from the server: shorts shown as cards (thumbnail, title; not played)"
YT_SHORT = re.compile(r"^https://(?:www\.|m\.)?youtube\.com/shorts/([\w-]{6,20})(?:[?#]|$)")


def youtube_card(result):
    """A YouTube Short from the results page (already guarded) -> a card when the short's own page is blocked for the
    server: its title, channel and YouTube's public thumbnail (no extra request beyond the image)."""
    m = YT_SHORT.match(str((result or {}).get("url") or ""))
    if not m:
        return None
    return {"url": result["url"], "title": str(result.get("title") or "")[:140],
            "author": str(result.get("channel") or "")[:60], "hashtags": [],
            "thumb": f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg", "host": "youtube.com",
            "site": "YouTube Shorts", "how": "title and thumbnail from the results page"}

