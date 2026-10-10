"""What is on his screens: a real headless browser on the open web, for the computer and for the phone.

While the life simulation is at the computer ("research") or on the phone, a headless Chromium really loads web pages:
it searches (Bing, SafeSearch strict) for words from the chat or from what he read last, opens results, follows links
that match his interests, scrolls, and takes a screenshot every few seconds. The page shows the screenshots on the
monitor and on the phone in his hand. The desk uses a desktop viewport, the phone a mobile one.

Read-only except for one thing (#29): it may type a filtered query into a site's own search box and press Enter
(`site_search`). The field is checked here, in the browser's process, right before typing (search_field_ok): a
search input (type=search, role=searchbox, or a GET form whose action looks like search) that is not a password,
email, comment, message, login or payment field, in a form without a password field. Nothing else is ever typed; it
never logs in, signs up, submits other forms, downloads, buys or touches a wallet. Cookie / consent banners are
dismissed with their reject or "necessary only" button (choose_dismiss; never an accept button), other modals with
their close button; a sign-in wall is left, never passed. Because the screens are shown live to everyone, a guard
skips pages before they are shown: adult, gore, self-harm, extremism and drug sites/pages, gambling, crypto trading
and wallets (no buy pressure), login / sign-up / checkout pages and bot walls. Everything else that is legal and
safe-for-work is allowed. Requests to private or internal addresses (localhost, cloud metadata, LAN) are blocked for
every resource, not only pages. A chain of pages ends after MAX_CHAIN (30) pages; the brain can leave earlier.

Brain decides (`decide=True`, the default in browse_service.py): when he has finished a page, step() does not move on
by itself; it returns the page (title, visible text, up to 40 safe links) so that the live server can have an AI list
options (eyes.py) and the brain model pick one (brain_vote.py); act() then carries the chosen action out (click,
search, site_search, next_page, open_comments, open_video, play_video, back, scroll, leave). Bot checks
(CAPTCHA, "unusual traffic") are never solved: such pages are left.

YouTube (#17): every context carries YouTube's Restricted Mode cookie (PREF f2=8000000). With the "video" mode (life
activity watch_video) the desk opens a YouTube search for his interest (a URL, the query through eyes.query_ok; he
types nothing), the brain picks a video among the options, and it plays muted (Chromium runs with --mute-audio and the
<video> element is muted again at every screenshot) for a bounded time (act's `watch_s`, at most MAX_WATCH_S); then
the brain decides again. While he watches, each screenshot is compared with the previous one (scene_change) and the
live server turns that into visual drive. Titles and channel names pass the guard and the chat filter
(video_text_ok); comments and live chat are hidden, never opened; nothing is liked, subscribed or signed in to.

More of the web (#56): a search goes to the source that fits the query (search_sources.route: DuckDuckGo, Bing,
Wikipedia, Wikimedia Commons, arXiv, Hacker News, Open Library, YouTube, or a recipes / news site's own search box),
rotated and limited to search_sources.PER_HOST_HOUR requests per host per hour, with robots.txt respected (also
before typing into any site's search box). Results are parsed from the page (or the source's public JSON API), and
every result's URL and title passes the guard before it is numbered for the brain; the card says where he searched,
for what, and why ("searched arXiv for “sleep spindles” — from his reading notes").

Logged in, view-only (#60): with `SUB01_SESSION_TIKTOK` / `SUB01_SESSION_YOUTUBE` set (sessions.py), pages of that
site open in a separate in-memory context per screen that alone carries the session's cookies; everything else stays
in the logged-out context. There, links that are actions (like, follow, comment, share, DM, upload, live, buy...) or
private pages (settings, inbox, studio, history, billing...) are never offered or opened, private pages are left
before they are shown (URL and DOM, view_only.py), and the account's avatar, name and the action buttons are hidden
before every screenshot. A sign-in button or wall logs that site out for good (until a restart).

Optional: needs `pip install playwright` + a Chromium (`playwright install --with-deps chromium`). Without it the
server runs as before (Wikipedia reading only).
"""
import asyncio
import ipaddress
import os
import random
import re
import socket
import time
import urllib.parse

import interests as I
import memory_guard as MG
import novelty as NV
import youtube_api as YT
import search_sources as SS
import short_videos as SV
import sessions as SE
import view_only as VO

KEEP = 60                              # visits kept in the log
SCROLL_EVERY_S = 7.0                   # seconds between scroll + screenshot on a page
SCROLLS = (3, 7)                       # scrolls per page before moving on
NAV_TIMEOUT_MS = 20000
DECIDE_WAIT_S = 90                     # waiting longer than this for the brain's choice: wander on as before
PAGE_LINKS = 40
VIDEO_LINK = re.compile(r"(youtube\.com/watch|youtube\.com/shorts/|youtu\.be/|vimeo\.com/\d|nicovideo\.jp/watch|"
                        r"dailymotion\.com/video|tiktok\.com/@[\w.]+/video/|/videos?/|/watch\b)", re.I)
MAX_CHAIN = 30                         # pages in a row before he wanders off to something new (#29)
# YouTube (#17): Restricted Mode for every context, bounded muted watching, scene changes as visual drive
YOUTUBE_COOKIES = [{"name": "PREF", "value": "f2=8000000", "domain": ".youtube.com", "path": "/", "secure": True}]
YOUTUBE_HOST = re.compile(r"(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$", re.I)
# #89 evening (2026-10-04 19:46-21:10 Tokyo): 10 desk videos in a row, three with the same guest, three coffee-gear
# "best of 2026" lists. At most CHANNEL_STREAK_MAX videos in a row from one channel or with one guest; after
# VIDEO_RUN_MAX videos in a row at the desk, VIDEO_BREAK_S of pages / searches; shopping lists go to the back.
CHANNEL_STREAK_MAX = 2
VIDEO_RUN_MAX = 4
VIDEO_BREAK_S = 300.0
GUEST = re.compile(r"\b(?:w/|with|ft\.?|feat\.?|featuring)\s+([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+)?)")
SHOPPING_LIST = re.compile(r"\b(best|top \d+)\b.{0,60}\b(20\d\d|to buy|you need|money can buy|on amazon|deals?)\b|"
                           r"\bbuying guide\b|\bwhich (one )?should you buy\b", re.I)


def video_keys(title, channel):
    """A video's channel and guests (lower case), for the streak cap."""
    keys = {str(channel or "").strip().lower()} - {""}
    keys |= {g.strip().lower() for g in GUEST.findall(str(title or ""))}
    return keys


MEM_CHECK_S = 10.0                     # #89: how often the browser reads its own memory
SOFT_MEM_MB = float(os.environ.get("BROWSE_SOFT_MEM_MB") or 0.75 * float(os.environ.get("BROWSE_MEM_MB") or 1200))
MAX_WATCH_S = 600.0                    # a watch never lasts longer than this (real seconds), whatever is asked
MIN_WATCH_S = 10.0                     # ...nor shorter (the accelerated demo clock: a few screenshots at least)
VIDEO_SHOT_S = 4.0                     # a screenshot (and a scene-change measure) every few seconds while watching
SCENE_FULL = 32.0                      # mean grey-level change (0..255) of the thumbnails that counts as a full cut
HIDE_YOUTUBE = """ytd-comments,#comments,ytd-live-chat-frame,#chat,#chat-container,ytd-engagement-panel-section-list-renderer,
#sponsor-button,#subscribe-button,ytd-subscribe-button-renderer,#actions,ytd-menu-renderer,tp-yt-paper-dialog,
ytd-popup-container,ytd-consent-bump-v2-lightbox{display:none !important}"""
# every <video> is muted and locked muted: the page's own `muted = false` / `volume = 1` become no-ops
VIDEO_JS = """mode => { const P = HTMLMediaElement.prototype, d = n => Object.getOwnPropertyDescriptor(P, n);
  const vs = [...document.querySelectorAll('video, audio')];
  for (const v of vs) {
    d('muted').set.call(v, true); d('volume').set.call(v, 0);
    if (!v.__sub01_muted) {
      Object.defineProperty(v, 'muted', {get: () => d('muted').get.call(v), set: () => {}, configurable: false});
      Object.defineProperty(v, 'volume', {get: () => d('volume').get.call(v), set: () => {}, configurable: false});
      v.__sub01_muted = true;
    }
  }
  const v = vs.find(x => x.tagName === 'VIDEO');
  if (!v) return null;
  if (mode === 'play') { const p = v.play(); if (p && p.catch) p.catch(() => {}); }
  if (mode === 'pause') v.pause();
  return {muted: v.muted, volume: v.volume, paused: v.paused, t: v.currentTime || 0, duration: v.duration || 0}; }"""
CHANNEL_JS = """() => { const a = document.querySelector('ytd-video-owner-renderer ytd-channel-name a, #owner #channel-name a, ytd-channel-name a');
  return a ? (a.innerText || '').trim().slice(0, 80) : ''; }"""
SITE_SEARCH_NAV_MS = 8000              # wait for the results page after Enter (some sites update in place)
LINKS_JS = """() => [...document.querySelectorAll('a[href]')].map(a => {
  const r = a.getBoundingClientRect(), cs = getComputedStyle(a);
  return [a.href, (a.innerText || a.title || a.getAttribute('aria-label') || '').trim().slice(0, 120), r.width * r.height,
          r.bottom > 0 && r.top < innerHeight * 3 && cs.visibility !== 'hidden' && cs.display !== 'none',
          (a.getAttribute('rel') || '').toLowerCase(), a.classList.contains('external'),
          (a.getAttribute('aria-label') || '').trim().slice(0, 60)];
})"""
# link kinds the eyes may propose as their own actions: the next page of a list, a comment thread
NEXT_TEXT = re.compile(r"^(next|next page|next ?[›»→>]+|older( posts| entries| stories)?|more|more stories|"
                       r"load more|show more|[›»→]|page suivante)$", re.I)
COMMENTS_TEXT = re.compile(r"^\d[\d,.]*k?\s+(comments?|replies|answers)$|^(comments?|discuss|discussion|"
                           r"(view|read|show|see|all) (all )?(\d+ )?comments?|join the discussion)$", re.I)
COMMENTS_HREF = re.compile(r"/comments/|[#?&]comments?\b|/item\?id=\d+$|#disqus|/discussion", re.I)


def link_kind(href, label, rel="", aria=""):
    """'next' for pagination / "next" links, 'comments' for a comment thread, else None."""
    t = " ".join((label or aria or "").split())
    if "next" in rel.split() or NEXT_TEXT.match(t) or (re.match(r"^next\b", aria or "", re.I) and len(t) <= 12):
        return "next"
    if COMMENTS_TEXT.match(t) or (COMMENTS_HREF.search(href or "") and re.search(r"comment|discuss|repl", t, re.I)):
        return "comments"
    return None
DESK = {"viewport": {"width": 1280, "height": 800}, "device_scale_factor": 1}
PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True,
         "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                       "Version/17.6 Mobile/15E148 Safari/604.1"}
DESK_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/129.0.0.0 Safari/537.36")

# actions that open a link of the page, and the link flag each one needs (None: any guarded link)
LINK_ACTIONS = {"click": None, "open_video": "video", "play_video": "video", "next_page": "next",
                "open_comments": "comments"}

# --- guard ---------------------------------------------------------------------------------------------------------
# Owner rules: no money-hype or trading content on the monitor, no financial advice, no buy pressure. Trading hosts
# (exchanges, DEX, launchpads, chart and quote sites: TRADING_HOST) are refused like the harmful categories, so
# they never reach a screen, a reading, the diary or the reward; wallet apps stay blocked (he never connects a
# wallet), and nothing with money is ever clicked (MONEY_ACTION). Neutral memecoin / altcoin / market NEWS on a news
# site stays readable (the owner's choice): only price / chart / ticker / trading titles go (trading_title). The
# harmful categories stay: adult, gore, self-harm, extremism, illegal; gambling too.
BAD_HOST = re.compile(
    r"porn|xxx|xvideo|xhamster|redtube|youporn|sex|nsfw|onlyfans|fansly|hentai|escort|camgirl|chaturbate|stripchat|"
    r"livejasmin|adult|nude|naked|erotic|fetish|"
    r"casino|poker|betting|bet365|sportsbet|stake\.com|gambl|slots|lottery|"
    r"phantom\.app|metamask|walletconnect|"
    r"4chan|8kun|kiwifarms|bestgore|liveleak|theync|"
    r"railway\.app|up\.railway", re.I)
# B7: the same list for titles and link labels, word-bounded: "Sussex Cricket Club", "Adulthood in Japan" and
# "Sextant navigation" pass; "free sex cams" does not. BAD_HOST (substrings) stays for host names.
TITLE_BAD_HOST = re.compile(
    r"\b(porn\w*|xxx|xvideos?|xhamster|redtube|youporn|sex|nsfw|onlyfans|fansly|hentai|escorts?|camgirls?|chaturbate|"
    r"stripchat|livejasmin|adult|nudes?|naked|erotic\w*|fetish\w*|casinos?|poker|betting|bet365|sportsbet|stake\.com|"
    r"gambl\w*|slots|lottery|phantom\.app|metamask|walletconnect|4chan|8kun|kiwifarms|bestgore|liveleak|theync)\b", re.I)
# words that must not be on a page shown live (title anywhere; body when repeated)
_HARM_WORDS = (r"porn\w*|xxx|nsfw|nude|nudes|naked|hentai|onlyfans|escort\w*|camgirl\w*|fetish\w*|erotic\w*|"
               r"gore|beheading|dismember\w*|suicide|self[- ]?harm|rape|raped|child abuse|"
               r"terrorist\w*|jihad\w*|neo-?nazi\w*|white power")
BAD_WORDS = re.compile(r"\b(" + _HARM_WORDS + r"|cocaine|heroin|meth|fentanyl|casino\w*|sportsbook|gambling)\b", re.I)
# song and video titles: the same words without drugs and gambling ("Cocaine", "Heroin", "Casino Royale" pass)
MEDIA_BAD_WORDS = re.compile(r"\b(" + _HARM_WORDS + r")\b", re.I)
# ... but gambling promotion still counts, like coin pressure ("Best online casino bonus", "free spins")
GAMBLING_PROMO = re.compile(r"\b(online casinos?|casino bonus(es)?|free spins?|no deposit bonus|sportsbooks?|"
                            r"sports betting|betting (tips|odds)|bet365|stake\.com)\b", re.I)
# money-making and trading promotion (owner rules: no financial advice or buy pressure, no Fomo / trading on the monitor;
# live 2026-10-09 09:03 Tokyo: "How to make millions on FOMO app", "Prop Firm Scalper ... Made $2.5+ Million"): never
# searched, opened or shown, as a page, a video or a song; plain finance words ("Stockholm", "stock photo") pass
MONEY_HYPE = re.compile(r"\b(fomo app|pump\.fun|crypto (trading|signals|gems?)|day ?trad(ing|er|ers)|forex|scalp(ing|er|ers)|prop firms?|ict trader|options trading|trading (strategy|signals|bot|course)|get rich|make (\$?\d[\d,.]*[kmb]?|millions?|thousands?|money) (fast|online|daily|a day|with|from|on|trading)|how to make (millions?|money|\$\d)|passive income|100x|1000x|to the moon|financial freedom)\b", re.I)
BOT_WALL = re.compile(r"attention required|just a moment|access denied|are you a (robot|human)|verify you are human|"
                      r"checking your browser|pardon our interruption|access to this page has been denied|"
                      r"ddos-guard|please wait while we verify|"
                      r"captcha|403 forbidden|404 not found|page not found|enable javascript|unusual traffic|"
                      r"before you continue", re.I)   # ("consent" alone: see CONSENT_TITLE, a title part that is only that)
# bot checks recognised in the page text or by their challenge frames: he leaves these pages, never solves them
# (only on short pages: a real bot check is a page of its own, not a sentence inside an article)
WALL_MAX_CHARS = 2000
BODY_WALL = re.compile(r"unusual traffic from your (computer|network)|verify you are (a )?human|"
                       r"checking (if the site connection is secure|your browser)|"
                       r"complete the security check|please solve (this|the) (captcha|puzzle)|"
                       r"bots use duckduckgo too|confirm this search was made by a human|"
                       r"sign in to confirm (you|that you)['’ ]?re not a bot|error 153|video player configuration error|"
                       r"playback on other websites has been disabled|drag the slider|verify to continue|"
                       r"please enable js and disable any ad blocker|press (&|and) hold to confirm you are|"
                       r"access to this page has been denied|pardon our interruption|ray id: [0-9a-f]{8}|"
                       r"performance & security by cloudflare|request unsuccessful\. incapsula", re.I)
# 2026-10-07 live: "Sorry, BBC iPlayer isn't available in your region" was shown in the card. A geo-block / region
# wall is a wall like a bot check: left at once, not shown or counted, its site left alone (never worked around).
# Whole phrases only ("region" alone is not enough), on a page of its own (GEO_WALL_MAX_CHARS of text at most:
# such pages carry the site's header and footer, so they run longer than a bot check)
GEO_WALL_MAX_CHARS = 6000
GEO_WALL = re.compile(r"(?:(?:not|n['’]t)\s+(?:currently\s+|yet\s+)?available|unavailable)\s+(?:to (?:watch|stream|view)\s+)?"
                      r"(?:in|from|for)\s+your\s+(?:region|country|location|area|territory|part of the world)|"
                      r"(?:not|n['’]t)\s+(?:currently\s+)?available where you are|"
                      r"(?:blocked|restricted) in your (?:region|country|location)|"
                      r"bbc iplayer only works in the uk|only available (?:to watch )?in the uk\b|"
                      r"not made this video available in your country|geo-?(?:blocked|restricted)|"
                      # (G14: the US / EU walls and the licence wording - "not available outside the United States",
                      # "only available in the US", "due to licensing restrictions ... in your country")
                      r"not available (?:to (?:users|viewers) )?outside (?:of )?the (?:uk|united kingdom|us|usa|united states|eu)\b|"
                      r"only (?:works|available|playable) (?:to (?:users|viewers|people) )?in the (?:us|usa|united states)\b|"
                      r"due to (?:licensing|rights|legal) restrictions[^.]{0,60}\b(?:country|region|location)\b", re.I)
# a title asking about it is an article, not the wall ("Why Netflix shows aren't available in your country")
GEO_TITLE_ASK = re.compile(r"^\s*(?:why|how|what|which|when|where|is|are|can|do|does)\b", re.I)
# a visible, checkbox-sized challenge frame (the invisible reCAPTCHA v3 badge and tiny widgets do not count)
WALL_FRAMES = """() => [...document.querySelectorAll('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], '
  + 'iframe[src*="challenges.cloudflare.com"], iframe[src*="captcha-delivery"]')].some(f => {
    if (f.closest('.grecaptcha-badge')) return false;
    const r = f.getBoundingClientRect(), cs = getComputedStyle(f);
    return r.width >= 200 && r.height >= 60 && cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity > 0.1; })"""
# links whose URL path leads to an account, a form or a purchase, whatever their text says
LOGIN_HREF = re.compile(r"/(log-?in|sign-?in|sign-?up|signin|signup|servicelogin|register|join|account|my-?account|checkout|cart|"
                        r"basket|subscribe|donate|password|auth|oauth2?|sso)(/|\?|$|\.)", re.I)
# place names that contain a blocked fragment ("sex" in Sussex): removed before the host check
HOST_FALSE_HITS = re.compile(r"sussex|essex|middlesex|wessex", re.I)
# a sign-in wall: the page is mostly a login / sign-up prompt (he leaves; he never signs in to get past it)
LOGIN_WALL = re.compile(r"(log|sign) ?in to (continue|view|see|read|keep reading|tiktok|watch)|sign up to (continue|read|see|view)|"
                        r"create (a free |an )?account to (continue|read|view)|you must be (logged|signed) in|"
                        r"please (log|sign) in|see (photos|posts), videos and more|log in or sign up|"
                        r"sign up to see|join [\w ]{1,30} to see|new to (x|instagram|facebook)\?", re.I)
# #89 live (2026-10-04): social sites whose public pages are a login / sign-up modal for a logged-out visitor; he
# never opens them (TikTok and YouTube are reached through their official players instead)
WALLED_SOCIAL = re.compile(r"(^|\.)(instagram\.com|facebook\.com|fb\.com|x\.com|twitter\.com|threads\.(net|com)|"
                           r"linkedin\.com|pinterest\.[a-z.]+|snapchat\.com)$", re.I)
# #89 live (2026-10-04 18:49 Tokyo: "90min | PSG - WhatsApp channel"): messaging apps and "open in the app" pages are
# a login or install wall for him: never a link target
APP_WALL_HOST = re.compile(r"(^|\.)(whatsapp\.com|wa\.me|t\.me|telegram\.(me|org|dog)|discord\.gg|messenger\.com|m\.me|"
                           r"line\.me|signal\.me|kakao\.com|viber\.com|apps\.apple\.com|itunes\.apple\.com|"
                           r"onelink\.me|app\.link|page\.link|appsflyer\.com|adj\.st)$", re.I)
APP_WALL_PATH = re.compile(r"^https?://([\w-]+\.)*(discord\.com/invite/|discordapp\.com/invite/|play\.google\.com/store/|"
                           r"facebook\.com/messages/|apps\.microsoft\.com/)", re.I)


def app_wall(url):
    """A messaging app or app-store / open-in-app page: a wall, not something to read."""
    u = str(url or "")
    return bool(APP_WALL_HOST.search(urllib.parse.urlsplit(u).hostname or "") or APP_WALL_PATH.match(u))


LOGIN_WALL_MAX_CHARS = 3000

# --- the only typing: a site's own search box (#29) ------------------------------------------------------------------
# descriptor of every visible text-like field: tag, type, role, name, id, placeholder, aria, autocomplete, form facts
FIELD_JS = """el => { const r = el.getBoundingClientRect(), cs = getComputedStyle(el), f = el.form || el.closest('form');
  return {i: +el.getAttribute('data-sub01-field'), tag: el.tagName.toLowerCase(),
          type: (el.getAttribute('type') || '').toLowerCase(), role: (el.getAttribute('role') || '').toLowerCase(),
          name: el.getAttribute('name') || '', id: el.id || '', placeholder: el.getAttribute('placeholder') || '',
          aria: el.getAttribute('aria-label') || '', title: el.getAttribute('title') || '',
          autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
          editable: el.isContentEditable && el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA',
          readonly: !!(el.readOnly || el.disabled),
          visible: r.width > 20 && r.height > 8 && cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity > 0.1,
          form: !!f, form_action: f ? (f.getAttribute('action') || '') : '', form_role: f ? (f.getAttribute('role') || '') : '',
          form_method: f ? (f.getAttribute('method') || 'get').toLowerCase() : '',
          form_id: f ? ((f.id || '') + ' ' + (typeof f.className === 'string' ? f.className : '') + ' ' + (f.getAttribute('name') || '')) : '',
          form_password: f ? !!f.querySelector('input[type=password]') : false,
          form_fields: f ? f.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select').length : 0};
}"""
# every text-like field of the page, numbered (data-sub01-field) and described by FIELD_JS
FIELDS_JS = ("() => { const describe = " + FIELD_JS + ";\n  return [...document.querySelectorAll('input, textarea, "
             "[contenteditable=\"\"], [contenteditable=\"true\"], [role=searchbox], [role=textbox]')].map((el, i) => "
             "{ el.setAttribute('data-sub01-field', String(i)); return describe(el); }); }")
SEARCH_WORDS = re.compile(r"search|query|find|look ?up|recherche|suche|buscar|検索", re.I)
SEARCH_NAMES = re.compile(r"^(q|s|k|p|query|search|search_?query|searchterm|term|keywords?|text|wd|search-field)$", re.I)
# anything that is a personal, account, message or payment field, whatever else it claims to be
FORBIDDEN_FIELD = re.compile(r"pass(word|wd)?|e-?mail|user(name)?|log-?in|sign-?(in|up)|register|account|comment|"
                             r"message|reply|subject|chat|feedback|review|phone|address|wallet|coupon|promo|token|"
                             r"captcha|birth|credit|iban|cvc|cvv|"
                             r"(?<![a-z])(name|post|body|tel|card|cc|pay|otp|code|age|zip)(?![a-z])", re.I)
FORBIDDEN_TYPES = ("password", "email", "tel", "url", "number", "hidden", "file", "checkbox", "radio", "submit",
                   "button", "image", "reset", "date", "datetime-local", "month", "week", "time", "color", "range")
FORBIDDEN_AUTOCOMPLETE = re.compile(r"email|username|password|cc-|tel|name|address|postal|one-time|bday|street", re.I)


def search_field_ok(f):
    """True only for a site's search box (see the module docstring). `f` is one FIELDS_JS descriptor. Everything
    that is not clearly a search input is refused: textareas, editable divs, password / email / comment / message /
    login / payment fields, fields in a form with a password field, and POST forms."""
    if not isinstance(f, dict) or not f.get("visible") or f.get("readonly") or f.get("editable"):
        return False
    if f.get("tag") != "input" or f.get("type", "") not in ("", "search", "text"):
        return False
    if f.get("type") in FORBIDDEN_TYPES or FORBIDDEN_AUTOCOMPLETE.search(f.get("autocomplete", "") or ""):
        return False
    own = " ".join(str(f.get(k, "")) for k in ("name", "id", "placeholder", "aria", "title"))
    if FORBIDDEN_FIELD.search(re.sub(r"search\w*", " ", own, flags=re.I)):
        return False
    if f.get("form_password") or (f.get("form") and f.get("form_method", "get") not in ("get", "")):
        return False
    if f.get("form") and int(f.get("form_fields") or 0) > 3:          # a search box stands (nearly) alone in its form
        return False
    form = f"{f.get('form_action', '')} {f.get('form_role', '')} {f.get('form_id', '')}"
    if f.get("form") and (LOGIN_HREF.search(f.get("form_action", "") or "")
                          or FORBIDDEN_FIELD.search(re.sub(r"search\w*", " ", form, flags=re.I))):
        return False
    return (f.get("type") == "search" or f.get("role") == "searchbox"
            or (bool(f.get("form")) and bool(SEARCH_WORDS.search(form)))
            or (f.get("form_role") == "search")
            or (bool(SEARCH_NAMES.match(f.get("name", "") or "")) and bool(SEARCH_WORDS.search(own))))


# --- cookie / consent banners and modals (#29) ----------------------------------------------------------------------
REJECT_BUTTON = re.compile(r"\b(reject|decline|refuse|deny|disagree)\b|"
                           r"\b(necessary|essential|required|functional)\b.*\bonly\b|\bonly\b.*\b(necessary|essential|required)\b|"
                           r"continue without (accepting|agreeing|consent)|do not (accept|agree|consent)|"
                           r"(don't|do not) (allow|sell)|use necessary cookies", re.I)
ACCEPT_BUTTON = re.compile(r"\b(accept|agree|allow|consent|got it|ok|okay|i understand|yes|continue|enable)\b", re.I)
CLOSE_BUTTON = re.compile(r"^(close|×|✕|✖|x|dismiss|no,? thanks?|not now|maybe later|skip|no thanks, continue|"
                          r"close (dialog|modal|banner|this))$", re.I)
BUTTONS_JS = """() => {
  const consentRe = /cookie|consent|gdpr|privacy|tracking|partners|personal data|your choices/i;
  const out = [], seen = new Set();
  const inFrame = window !== window.top && /consent|cmp|privacy|cookie|sp_message|gdpr/i.test(location.href);
  for (const el of document.querySelectorAll('button, [role=button], a, input[type=button], input[type=submit]')) {
    if (out.length >= 80) break;
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (r.width < 4 || r.height < 4 || cs.visibility === 'hidden' || cs.display === 'none') continue;
    if (el.tagName === 'A') { const h = el.getAttribute('href') || ''; if (h && h !== '#' && !h.startsWith('javascript')) continue; }
    let box = el.parentElement, overlay = null;
    while (box && box !== document.body) {
      const bs = getComputedStyle(box);
      if (bs.position === 'fixed' || bs.position === 'sticky' || box.getAttribute('role') === 'dialog'
          || box.getAttribute('aria-modal') === 'true' || box.tagName === 'DIALOG') { overlay = box; }
      box = box.parentElement;
    }
    if (!overlay && !inFrame) continue;
    const text = ((overlay || document.body).innerText || '').slice(0, 3000);
    const label = (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').trim().slice(0, 80);
    const aria = (el.getAttribute('aria-label') || '').trim().slice(0, 60);
    const i = out.length; el.setAttribute('data-sub01-btn', String(i));
    out.push({i, label, aria, consent: inFrame || consentRe.test(text), modal: true});
  }
  return out;
}"""


def choose_dismiss(buttons):
    """Index of the button to press to get rid of a banner or modal, or None (then it is hidden, not clicked).
    Consent banners: the reject / "necessary only" button; if there is none, a close button. Other modals: their
    close button. An accept / agree / allow button is never pressed, whatever else it says."""
    def label(b):
        return " ".join(str(b.get("label") or "").split())

    def close(b):
        return bool(CLOSE_BUTTON.match(label(b)) or re.match(r"^(close|dismiss)\b", str(b.get("aria") or ""), re.I))

    for b in buttons:
        t = label(b)
        if b.get("consent") and REJECT_BUTTON.search(t) and len(t) <= 60:
            if ACCEPT_BUTTON.search(t) and not re.search(r"only|reject|decline|refuse|without|do not|don't", t, re.I):
                continue
            return b["i"]
    for b in buttons:
        if close(b) and (CLOSE_BUTTON.match(label(b)) or not ACCEPT_BUTTON.search(label(b))):
            return b["i"]
    return None


def display_ok(text):
    """Text in his words or in the card's own lines (mind notes, the card title, video titles): no links, addresses,
    tickers, money, slurs, blocked topics or finance talk (the chat filter's rules, without its phone-number rule,
    which catches year ranges). Web titles and link labels use the looser title_ok (#56); song and video titles use
    media_title_ok."""
    import chat
    t = text or ""
    return (title_ok(t) and not (chat.TICKER.search(t) or chat.MONEY.search(t) or FINANCE_TALK.search(t)))


def title_ok(text):
    """A web page's title, a link label or a search result on the public screen: plain market words may show
    (neutral memecoin / stock news is readable), but never links, addresses, e-mails, money requests, slurs, the
    guard's blocked words and topics, money hype, or a price / chart / ticker / trading title (trading_title)."""
    import chat
    from research import BLOCK as TOPIC_BLOCK
    t = text or ""
    return not (chat.URL.search(t) or chat.SOL_ADDR.search(t) or chat.ETH_ADDR.search(t) or chat.EMAIL.search(t)
                or MONEY_ASK.search(t) or chat.SLUR_RE.search(chat.normalise(t))
                or BAD_WORDS.search(t) or TITLE_BAD_HOST.search(t) or TOPIC_BLOCK.search(t) or MONEY_HYPE.search(t)
                or trading_title(t))


def media_title_ok(text):
    """A song or video title, channel or artist (owner: "don't censor anything", shown as it is): one rule for
    Spotify tracks and YouTube / TikTok cards (review G24, F5). Refused: the guard's sexual / porn, gore, extremism
    and self-harm words (MEDIA_BAD_WORDS, word-bounded; drugs and gambling words pass, gambling
    promotion does not: GAMBLING_PROMO), and chat.blocked(media=True): links, addresses, e-mails,
    requests for money, "kys" and calls to violence against a group. Not applied: slurs and swearing, BAD_HOST (a host
    list: "Sex on Fire"), a "$" in an artist's styling ("$uicideboy$"), prices ("$5 Pizza Hack"), research.BLOCK's topic substrings ("nazi"
    in "Nazionale", "Killing in the Name"), FINANCE_TALK ("Stockholm Syndrome") and the phone rule ("2000 - 2010")."""
    import chat
    t = text or ""
    return (not (MEDIA_BAD_WORDS.search(t) or GAMBLING_PROMO.search(t) or MONEY_HYPE.search(t))
            and chat.blocked(t, media=True) is None)


# finance talk kept out of his own words (mind.py's FINANCE rule for replies stays; research.BLOCK had these before #56)
FINANCE_TALK = re.compile(r"stock|crypto|bitcoin|token|price|trading", re.I)


# requests for money on a public card (the chat filter's money rule without plain prices: finance titles show them)
MONEY_ASK = re.compile(r"\b(send|give|pay|tip|donate|lend|transfer|spare)\b.{0,20}\b(sol|eth|btc|usdc|usdt|crypto|"
                       r"money|cash|funds|coins?|tokens?|dollars?|bucks|euros?)\b|\b(donations?|donate|giveaway|"
                       r"venmo|paypal|cash ?app|zelle|seed phrase|private key)\b", re.I)
# links and buttons that act with money or a wallet: never offered, never clicked, whatever the brain picks
MONEY_ACTION = re.compile(r"\b(buy|sell|swap|trade( now)?|connect( (your )?wallet)?|sign( (the )?(message|transaction))?|"
                          r"deposit|withdraw|stake|unstake|bridge|claim|mint|launch (a )?(coin|token)|create (a )?"
                          r"(coin|token)|place (an )?order|invest( now)?|bet|get started|open (an )?account)\b", re.I)
MONEY_HREF = re.compile(r"/(buy|sell|connect|deposit|withdraw|stake|bridge|claim|mint|create|launch|wallet)"
                        r"(/|\?|$|-)|[?&](action|side)=(buy|sell)", re.I)
# S2: trading hosts (exchanges, DEX, launchpads, chart / quote / "social trading" sites) are refused by host_ok, so
# no page, link, result or screenshot of them ever reaches a screen. News sites that also cover markets (coindesk,
# cointelegraph, decrypt, bloomberg, reuters, cnbc, nikkei...) are not here: neutral news stays readable.
TRADING_HOST = re.compile(r"(^|\.)(binance|coinbase|kraken|bybit|okx|kucoin|bitget|mexc|gate|htx|huobi|crypto|"
                          r"dexscreener|dextools|pump|gmgn|birdeye|raydium|jup|jupiter|uniswap|pancakeswap|"
                          r"coinmarketcap|coingecko|tradingview|solscan|etherscan|investing|morningstar|nasdaq|"
                          r"kabutan|minkabu|stocktwits|seekingalpha|robinhood|etoro|bitflyer|bitbank|coincheck|"
                          r"photon-sol|bullx|moonshot|dexlab|geckoterminal|defillama|cryptobubbles)\.\w+|"
                          r"finance\.yahoo\.\w+", re.I)
TRADING_PATH = re.compile(r"^/finance(/|$)", re.I)              # google.com/finance: the quote pages only
# a title that is a price, chart, ticker or trading item, as opposed to a news headline: a market word next to a
# coin / stock word. "memecoin news", "Nikkei 225 today", "Pokemon trading cards", "soup stock", "Stockholm",
# "pumpkin" and "dumpling" pass; "Bitcoin price today", "$WIF jumps 20%", "SOL/USDT chart" do not.
_COIN = (r"crypto\w*|bitcoin|btc|ethereum|eth|solana|sol|dogecoin|doge|pepe|xrp|bnb|shib|memecoins?|altcoins?|"
         r"coins?|tokens?|stocks?|shares|nikkei|nasdaq|dow jones|s&p ?500|forex|usdt|usdc")
TRADING_TITLE = re.compile(r"\b(prices?|price (chart|today|prediction|target|action|analysis)|live price|charts?|"
                           r"candles?|candlesticks?|market cap|trading|traders?|to the moon|airdrop|presale|"
                           r"whitelist|pump(ed|ing|s)?|dump(ed|ing|s)?|rally|rallies|plunge[sd]?|surge[sd]?|"
                           r"jumps|soars|tanks|moon(ed|ing)?|buy the dip|long|short|leverage|futures|"
                           r"[+-]?\d+(\.\d+)?\s?%)(?=\W|$)", re.I)
COIN_WORD = re.compile(r"\b(" + _COIN + r")\b", re.I)
TICKER_WORD = re.compile(r"(?<![A-Za-z0-9$])\$[A-Za-z][A-Za-z0-9]{1,10}\b")     # "$WIF" (not "$5", not "A$AP")
PAIR = re.compile(r"\b[A-Z]{2,6}[/-](USDT?|USDC|SOL|ETH|BTC|JPY|EUR)\b")        # "SOL/USDT", "BTC-USD"
# a page body that reads like a trading terminal (distinct terms, first 6000 characters)
TRADING_PAGE = re.compile(r"\b(market cap|24h volume|liquidity|connect wallet|slippage|order book|limit order|"
                          r"candlestick|price chart|buy/sell|long/short|leverage|spot trading|futures trading|"
                          r"fully diluted|circulating supply|all[- ]time high|watchlist|portfolio tracker|"
                          r"pre-?market|after[- ]hours|bid/ask|stop[- ]loss|take[- ]profit)\b", re.I)


def trading_host(host):
    return bool(TRADING_HOST.search((host or "").lower().rstrip(".")))


def trading_url(url):
    """A trading host, or Google Finance's quote pages."""
    u = urllib.parse.urlsplit(url or "")
    host = (u.hostname or "").lower().rstrip(".")
    return trading_host(host) or (host.split(".")[-2:-1] == ["google"] and bool(TRADING_PATH.match(u.path)))


def trading_title(text):
    """A price / chart / ticker / trading title (never on a screen); a neutral market headline is not one."""
    t = " ".join(str(text or "").split())
    if PAIR.search(t) or TICKER_WORD.search(t):                 # a pair or a coin ticker is a trading item by itself
        return True
    return bool(COIN_WORD.search(t) and TRADING_TITLE.search(t))


def is_finance(url, title="", text=""):
    """A trading page: a trading host, a trading title, or a body that reads like a trading terminal (at least 3
    distinct terminal terms). #89 live: an anime page with in-game "tokens" and "trading" cards is not one."""
    if trading_url(url) or trading_title(title):
        return True
    terms = {m.group(0).lower() for m in TRADING_PAGE.finditer((text or "")[:6000])}
    return len(terms) >= 3


def money_action(label, href=""):
    """A link or button that would act with money or a wallet (buy, sell, swap, connect, sign, ...)."""
    return bool(MONEY_ACTION.search(label or "") or MONEY_HREF.search(urllib.parse.urlsplit(href or "").path + "?"
                                                                       + urllib.parse.urlsplit(href or "").query))


def is_youtube(host):
    return bool(YOUTUBE_HOST.search((host or "").rstrip(".")))


def is_video_host(host):
    """YouTube or TikTok: titles, captions and creator names also pass the chat filter (video_text_ok)."""
    h = (host or "").rstrip(".")
    return bool(YOUTUBE_HOST.search(h)) or SV.is_tiktok(h)


def video_text_ok(text):
    """A video title, caption or channel name on the public screen: the song and video rule (media_title_ok)."""
    return media_title_ok(text)


def card_title_ok(title, host=""):
    """The public card's title: a video's (YouTube / TikTok host) by video_text_ok, any other page's by display_ok."""
    return video_text_ok(title) if is_video_host(host) else display_ok(title)


def screen_showable(st):
    """S2: a screen status the public card and the screenshot route may show: not a finance / trading page, and a
    title that passes card_title_ok. The live server returns the restarting-style placeholder (device only) and a
    404 screenshot otherwise."""
    st = st or {}
    if st.get("finance") or trading_url(st.get("url") or ""):
        return False
    return card_title_ok(str(st.get("title") or ""), str(st.get("host") or ""))


def scene_change(prev_jpeg, jpeg):
    """0..1: how much the picture changed between two screenshots (mean absolute grey-level difference of 64x36
    thumbnails, SCENE_FULL = a full cut). 0 without a previous shot."""
    if not prev_jpeg or not jpeg:
        return 0.0
    import io
    from PIL import Image, ImageChops, ImageStat
    a, b = (Image.open(io.BytesIO(x)).convert("L").resize((64, 36)) for x in (prev_jpeg, jpeg))
    return round(min(1.0, ImageStat.Stat(ImageChops.difference(a, b)).mean[0] / SCENE_FULL), 3)


def youtube_search_url(q):
    return "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": q})


LOGIN_LINK = re.compile(r"log ?in|sign ?(in|up)|register|account|cart|checkout|basket|subscribe|donate|password|"
                        r"privacy|cookie|terms|legal|imprint|impressum|careers|advertis", re.I)
SKIP_EXT = re.compile(r"\.(pdf|zip|rar|7z|exe|dmg|apk|mp3|mp4|mov|avi|mkv|iso|tar|gz|docx?|xlsx?|pptx?)(\?|$)", re.I)
HIDE_BANNERS = """#onetrust-banner-sdk,#onetrust-consent-sdk,.fc-consent-root,#CybotCookiebotDialog,.qc-cmp2-container,
#usercentrics-root,#didomi-host,.truste_overlay,.truste_box_overlay{display:none !important}"""
# fixed/sticky overlays about cookies, consent, sign-ups, or covering most of the screen are hidden (never clicked)
UNBLOCK_JS = """() => {
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    const t = (el.innerText || '').toLowerCase();
    if (t.length < 1500 && /cookie|consent|gdpr|we use|accept all|newsletter|subscribe|sign up|log in to|open in app|get the app/.test(t))
      el.style.setProperty('display', 'none', 'important');
  }
  for (const el of [document.documentElement, document.body]) if (el) { el.style.setProperty('overflow', 'auto', 'important'); }
}"""
# #89 live (2026-10-04): an F1 video's embed said "Video unavailable … blocked it from display on this website". The
# player's own error text, checked a few seconds after it opens and during the watch: such a video is never shown.
EMBED_ERROR = re.compile(r"video unavailable|this video is unavailable|video currently unavailable|blocked it from "
                         r"display|playback on other websites has been disabled|sign in to confirm|"
                         r"an error occurred|this video is private|video has been removed|something went wrong|"
                         r"advertisement playing", re.I)      # an ad is never skipped by us: the next video instead
EMBED_CHECK_MS = 3000
PLAYER_REFUSALS = ("bot wall", "sign-in wall", "did not load")   # the player page itself refused, whatever the video
EMBED_ERROR_JS = """() => { const e = document.querySelector('.ytp-error, .ytp-error-content-wrap');
  const ad = document.querySelector('.ad-showing, .ytp-ad-player-overlay, .ytp-ad-module .ytp-ad-text, .ytp-ad-skip-button');
  const t = (document.body && document.body.innerText || '').slice(0, 2000);
  return (ad ? 'advertisement playing ' : '') +
         (e && getComputedStyle(e).display !== 'none' ? (e.innerText || 'player error') + ' ' : '') + t; }"""
EMBED_REFERER = os.environ.get("SUB01_SITE_URL") or "https://sub01-production.up.railway.app/"   # embeds want a page
# #89 teen re-seed: front pages of sites people his age read, per interest topic (docs/research/teen_online.md);
# every front page was allowed by its robots.txt on 2026-10-04, and robots.txt is checked again before each page.
# Cooking sites only while he is hungry or ordering food.
SEED_TOPICS = {
    "cars": ["https://www.topgear.com/", "https://www.carscoops.com/", "https://www.autoblog.com/",
             "https://www.formula1.com/en/latest", "https://www.thedrive.com/"],
    "games": ["https://www.ign.com/", "https://www.pcgamer.com/", "https://www.polygon.com/",
              "https://www.gamesradar.com/", "https://www.nintendolife.com/"],
    "football": ["https://www.bbc.com/sport/football", "https://www.skysports.com/football", "https://www.90min.com/",
                 "https://www.espn.com/soccer/", "https://www.theguardian.com/football"],
    "anime": ["https://myanimelist.net/", "https://www.crunchyroll.com/news", "https://www.cbr.com/category/anime-news/"],
    "music": ["https://www.nme.com/", "https://www.billboard.com/", "https://www.rollingstone.com/music/"],
    "tech": ["https://www.theverge.com/", "https://9to5mac.com/", "https://www.gsmarena.com/", "https://arstechnica.com/"],
    "sneakers": ["https://www.highsnobiety.com/", "https://www.complex.com/sneakers"],
    "memes": ["https://knowyourmeme.com/", "https://www.boredpanda.com/"],
    "creators": ["https://www.tubefilter.com/"],
    "movies": ["https://www.themoviedb.org/", "https://editorial.rottentomatoes.com/", "https://www.empireonline.com/"],
    "tokyo": ["https://www.timeout.com/tokyo", "https://www.japan-guide.com/", "https://www.tokyocheapo.com/"],
    "science": ["https://apod.nasa.gov/apod/astropix.html", "https://www.sciencenews.org/"],
    "food": ["https://www.justonecookbook.com/", "https://www.seriouseats.com/"],
}
SEEDS = [u for t, us in SEED_TOPICS.items() if t != "food" for u in us]
HOST_STREAK_MAX = 3                    # #89 teen: at most this many pages in a row on one site, then elsewhere
HOST_DAY_CAP = 20                      # pages a day on one site (the video players excepted)
RECIPE_HOST = re.compile(r"(^|\.)(kingarthurbaking|justonecookbook|seriouseats|allrecipes|recipetineats|bbcgoodfood|"
                         r"foodnetwork|delish|tasty|bonappetit|epicurious|food52|thekitchn|simplyrecipes)\.(com|co|co\.uk)$",
                         re.I)                 # cooking sites: only while he is hungry or ordering (#89 teen)
HOST_CAP_FREE = ("youtube.com", "www.youtube-nocookie.com", "youtube-nocookie.com", "tiktok.com", "www.tiktok.com")
VIDEO_TOPICS = ["Toyota GR Supra", "Tokyo night walk", "Elden Ring", "Premier League highlights", "One Piece",
                "train window Japan", "lo-fi music", "space documentary", "cat videos", "Studio Ghibli"]
FAMILIAR = ["Kichijoji", "Inokashira Park", "Tokyo bakery", "how dreams work", "sleep science", "ramen", "Ghibli Museum",
            "night city photography", "lo-fi music", "how the brain works", "Japanese convenience store", "Tokyo trains"]
STOP = set("the a an and or but if of to in on at for with from by is are was were be been it this that these those "
           "i you he she we they me my your his her our their what why how who when where which not no yes so very "
           "just can will would could should do does did have has had il lo la gli le un una e o ma di da con su "
           "per tra fra che chi non si sono sei era ciao hello hi lol ok".split())


def words(text):
    return [w for w in re.findall(r"[a-zA-ZÀ-ÿ]{4,}", (text or "").lower()) if w not in STOP]


def content_words(text):
    """B1: the words a request and a video can share ("cat", "supra"): 3+ letters, no stop words, no filler
    ("video", "best": search_sources.GENERIC)."""
    return {w for w in re.findall(r"[a-zA-ZÀ-ÿ0-9]{3,}", (text or "").lower()) if w not in STOP and w not in SS.GENERIC}


def host_ok(host):
    """Hostname is public and not on the block list (DNS is checked separately, see Guard.resolves_public)."""
    if (not host or BAD_HOST.search(HOST_FALSE_HITS.sub("", host)) or trading_host(host)
            or host.rstrip(".").lower() in ("localhost", "metadata", "metadata.google.internal")):
        return False
    try:                                                    # literal IPs: only public ones
        ip = ipaddress.ip_address(host.strip("[]"))
        return ip.is_global
    except ValueError:
        return not host.endswith((".local", ".internal", ".localhost", ".lan", ".home", ".corp"))


def url_ok(url):
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return (u.scheme in ("http", "https") and u.port in (None, 80, 443) and not u.username
            and host_ok(u.hostname or "") and not SKIP_EXT.search(u.path) and not trading_url(url))


def text_ok(title, body, media=False):
    """Title must be clean; the body may mention a word once (news) but not be about it. media=True (a YouTube /
    TikTok page): the song and video words (MEDIA_BAD_WORDS: drugs and gambling pass)."""
    words = MEDIA_BAD_WORDS if media else BAD_WORDS
    if words.search(title or ""):
        return False
    return len(words.findall((body or "")[:6000])) < 3


WALL_COOLDOWN_S = 6 * 3600              # #89: a site that showed him a bot check is left alone this long
OVERLAY_COOLDOWN_S = 2 * 3600           # ... and one that put an ad-block or paywall overlay over the page
# #89 live (2026-10-05 09:10 Tokyo, his phone): "We noticed that ads aren't being displayed" over the article. An
# ad-block / paywall overlay is a wall: the page is left, never dismissed or worked around (the ads stay blocked)
OVERLAY_WALL = re.compile(
    r"ads? (aren't|are not|isn't|is not) being (displayed|shown)|"
    r"(please )?(disable|turn off|pause|deactivate) (your |the )?ad[ -]?block(er|ing)?s?\b|"
    r"(we('ve| have)? )?(noticed|detected|see) (that )?you('re| are) (using |running )?an? ad[ -]?block|"
    r"ad[ -]?block(er)? (detected|is enabled|is on)|(white|allow)[ -]?list (us|this site|our site|our domain)|"
    r"you('ve| have) reached your (free )?(article )?limit|subscribe to (continue|keep) reading|"
    r"(this|the) (article|story|content) is (only )?(available )?(for|to) (subscribers|members) only", re.I)


def overlay_wall(body):
    """#89: an ad-block or paywall overlay's text in the page (it covers the content: not something to read)."""
    return bool(OVERLAY_WALL.search(str(body or "")[:40000]))


# #89 live (2026-10-05 11:08 Tokyo, his phone): sciencenews.org's "Looks like your ad blocker is on" modal stayed on
# screen. The page's first 20000 characters of text do not reach a modal appended at the end of a long article, and
# a modal can live in a shadow root or a script-written frame. Read: the start and end of the text, every visible
# dialog / fixed / sticky box (also inside open shadow roots), and (in Python) the page's child frames.
OVERLAY_TEXT_JS = """() => {
  const out = [], b = document.body ? (document.body.innerText || '') : '';
  out.push(b.slice(0, 20000));
  if (b.length > 20000) out.push(b.slice(-8000));
  const shown = el => { const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    return r.width >= 100 && r.height >= 30 && cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity > 0.05; };
  let n = 0;
  const walk = (root, depth) => {
    for (const el of root.querySelectorAll('*')) {
      if (++n > 20000 || out.length > 60) return;
      if (el.shadowRoot && depth < 4) {
        for (const c of el.shadowRoot.children) if (c.innerText && shown(c)) out.push(c.innerText.slice(0, 3000));
        walk(el.shadowRoot, depth + 1);
      }
      const role = (el.getAttribute('role') || '').toLowerCase();
      const box = el.tagName === 'DIALOG' ? el.open : role === 'dialog' || role === 'alertdialog'
        || el.getAttribute('aria-modal') === 'true' || ['fixed', 'sticky'].includes(getComputedStyle(el).position);
      if (box && shown(el)) { const t = el.innerText || ''; if (t.length < 3000) out.push(t); }
    }
  };
  walk(document, 0);
  return out.join('\\n').slice(0, 40000);
}"""


# 2026-10-07 14:39 UTC live: "The Drive - Permission Request Form" (permissions.thedrive.threesai.com) was shown and
# logged. A consent / permission / cookie-request page is a wall like a bot check: left, not shown, its site cooled off.
# By the title (one of its parts is only such a request: an article about privacy settings is not) or by a host whose
# first label is one (permissions.*, consent.*, cookies.*, cmp.*, gdpr.*).
CONSENT_TITLE = re.compile(r"(\w+ )?(permissions? request|request (for )?permissions?|permissions? required|"
                           r"cookie (consent|preferences|settings|policy|choices)|privacy (choices|preferences|center)|"
                           r"manage (cookies|consent|your privacy)|consent( management| preferences| request)?|"
                           r"(privacy|cookies?) (and|&) consent|consent (and|&) (privacy|cookies?))"
                           r"( form| page)?")
CONSENT_HOST = re.compile(r"^(permissions?|consent|cookies?|cmp|gdpr)\.[\w-]+\.[\w.-]+$")


def consent_wall(title, url):
    t = " ".join(str(title or "").split()).lower().rstrip(".")
    host = (urllib.parse.urlsplit(url or "").hostname or "").lower()
    return (any(CONSENT_TITLE.fullmatch(part.strip()) for part in re.split(r"\s[-|–—:·]\s|\|", t))
            or bool(CONSENT_HOST.match(host)))


def challenge_title(title, url):
    """#89 live (2026-10-04 18:50 Tokyo: three myanimelist.net pages titled "myanimelist.net"): a bot check's title,
    a geo-block title ("... isn't available in your region"), a consent / permission request, or a title that is only
    the bare host name (an interstitial, not content)."""
    t = " ".join(str(title or "").split()).lower().rstrip(".")
    host = (urllib.parse.urlsplit(url or "").hostname or "").lower()
    return (bool(BOT_WALL.search(t)) or bool(GEO_WALL.search(t)) and not GEO_TITLE_ASK.search(t)
            or consent_wall(title, url)
            or bool(t) and t in (host, host.removeprefix("www."), "www." + host))


# S9: an error page (a 404 / 500 body with a real title, or a site's own "oops" page) is not something to read: left,
# not shown. The title is matched part by part ("404 - Not Found | Example"), never as a substring ("Error handling
# in Rust" is an article); the body only on a short page (ERROR_BODY_MAX_CHARS).
ERROR_TITLE = re.compile(r"^(?:(?:error|http)\s*)?(?:\d{3}\b\s*[-:|·.]?\s*)?(?:(?:page |article |file )?not found|"
                         r"error|oops!?|internal server error|page (?:not|cannot|can.?t) be found|something went wrong|"
                         r"service unavailable|access denied|forbidden|bad gateway|gateway time-?out|"
                         r"page (?:doesn.?t|does not) exist|this page isn.?t available|unavailable)(?:\s*[.!])?$", re.I)
ERROR_BODY = re.compile(r"does not have an article with this exact name|"
                        r"the page you (?:requested|are looking for|were looking for) (?:could not be found|"
                        r"doesn.?t exist|does not exist|cannot be found|can.?t be found|was not found)|"
                        r"\b(?:error )?404\b.{0,40}\b(?:not found|page)\b", re.I)
ERROR_BODY_MAX_CHARS = 6000


def error_page(title, body=""):
    t = " ".join(str(title or "").split()).lower()
    if any(ERROR_TITLE.fullmatch(p.strip()) for p in re.split(r"\s[-|–—:·]\s|\|", t) if p.strip()):
        return True
    b = str(body or "")
    return len(b.strip()) < ERROR_BODY_MAX_CHARS and bool(ERROR_BODY.search(b))


def why_ok(why):
    """S9: the card's own line ("followed “…” from host"): title_ok without its link rule (the line names hosts)."""
    import chat
    from research import BLOCK as TOPIC_BLOCK
    t = str(why or "")
    return not (chat.SOL_ADDR.search(t) or chat.ETH_ADDR.search(t) or MONEY_ASK.search(t)
                or chat.SLUR_RE.search(chat.normalise(t)) or BAD_WORDS.search(t) or TITLE_BAD_HOST.search(t)
                or TOPIC_BLOCK.search(t) or MONEY_HYPE.search(t) or trading_title(t))


def cross_site_frame(req, host):
    """#89 memory: an iframe from another site than the page it is in (ads, video players, social embeds)."""
    try:
        frame = req.frame
        if frame.parent_frame is None:
            return False
        top = urllib.parse.urlsplit(frame.page.main_frame.url).hostname or ""
    except Exception:                                       # no frame (a service worker) or a detached one
        return False
    return bool(top) and not MG.frame_allowed(top, host)


class Guard:
    """Blocks requests to private/internal addresses (SSRF) for every resource the browser loads."""

    def __init__(self, via_proxy=False):
        self.cache = {}                                     # host -> (ok, expires)
        self.via_proxy = via_proxy                          # behind a proxy, DNS is resolved by the proxy

    async def resolves_public(self, host):
        if self.via_proxy:
            return True
        now = time.time()
        if host in self.cache and self.cache[host][1] > now:
            return self.cache[host][0]
        try:
            ip = ipaddress.ip_address(host.strip("[]"))
            ok = ip.is_global
        except ValueError:
            try:
                infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
                ok = bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)
            except OSError:
                ok = False
        self.cache[host] = (ok, now + 300)
        if len(self.cache) > 5000:
            self.cache.clear()
        return ok

    async def route(self, route):
        req = route.request
        url = req.url
        if url.startswith(("data:", "blob:")):
            return await route.continue_()
        u = urllib.parse.urlsplit(url)
        if (u.scheme not in ("http", "https") or u.port not in (None, 80, 443) or not host_ok(u.hostname or "")
                or req.resource_type in ("media", "websocket", "eventsource", "manifest")
                or (req.is_navigation_request() and SKIP_EXT.search(u.path))
                or not await self.resolves_public(u.hostname)):
            return await route.abort()
        if req.method not in ("GET", "HEAD") and req.is_navigation_request():
            return await route.abort()                      # never submits anything
        if MG.ad_host(u.hostname) or (req.is_navigation_request() and cross_site_frame(req, u.hostname)):
            return await route.abort()                      # #89: ads and cross-site iframes were most of the memory
        if req.is_navigation_request() and req.frame.parent_frame is None and YT.page_video(url)[1]:
            return await route.abort()                      # #89 live: never YouTube's own pages (a redirect, a click)
        await route.continue_()


class Screen:
    """One device (desk or phone): its browser context, current page and latest screenshot."""

    def __init__(self, name):
        self.name = name
        self.ctx = None
        self.page = None
        self.shot = None                                    # latest JPEG bytes
        self.shot_id = 0
        self.info = None                                    # {title, url, host, why, t, kind}
        self.scrolls_left = 0
        self.next_at = 0.0
        self.pending_link = None                            # result to open next (after a search page)
        self.history = []                                   # urls shown on this screen, newest last (for "back")
        self.awaiting = None                                # page handed to the brain for a decision
        self.awaiting_since = 0.0
        self.chain = 0                                      # pages shown in a row since he last wandered off
        self.mode = None                                    # "video": YouTube at the desk; "shorts": the phone's
        self.queue = []                                     # short-video feed (#56); else browsing. queue: next shorts
        self.cards = {}                                     # TikTok embed cards by video URL (#89)
        self.feed_topic, self.feed_fresh = None, False      # the feed's current topic; its first clip not shown yet
        self.sess = [0.0, 0, 0]                             # scroll session: last clip time, clips, new-topic clips
        self.watch_until = 0.0                              # wall time the current video ends (0: not watching)
        self.watch_s = 0.0
        self.scene = 0.0                                    # change between the last two screenshots while watching
        self.public = None                                  # (ctx, page) logged out: every site but a logged-in one
        self.sites = {}                                     # site -> (ctx, page) carrying that site's session (#60)
        self.site = None                                    # the logged-in site sc.ctx / sc.page belong to, or None

    def status(self):
        return dict(self.info, id=self.shot_id, device=self.name, chain=self.chain) if self.info and self.shot else None

    def contexts(self):
        return [p for p in [self.public, *self.sites.values()] if p]


CHROMIUM_ARGS = ["--disable-dev-shm-usage", "--mute-audio", "--disable-extensions", "--disable-background-networking",
                 "--disable-sync", "--no-first-run", "--renderer-process-limit=2", "--js-flags=--max-old-space-size=256",
                 "--disable-gpu", "--disable-software-rasterizer"]
CHROMIUM_ENV = ("PATH", "HOME", "LANG", "TZ", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH", "FONTCONFIG_PATH")


def launch_kwargs(sandbox, proxy=None, environ=None):
    """playwright `chromium.launch` arguments; `--no-sandbox` only when `sandbox` is False."""
    environ = os.environ if environ is None else environ
    kw = {"args": CHROMIUM_ARGS + ([] if sandbox else ["--no-sandbox"]),
          "chromium_sandbox": bool(sandbox),
          "env": {k: v for k, v in environ.items() if k in CHROMIUM_ENV}}
    if environ.get("BROWSE_CHROMIUM"):
        kw["executable_path"] = environ["BROWSE_CHROMIUM"]
    if proxy:
        kw["proxy"] = {"server": proxy}
    return kw


class Browser:
    """Drives both screens. `step(device, ...)` is called by the live server every couple of seconds."""

    def __init__(self, state=None, rng=None, proxy=None, ignore_tls=False, decide=False, sessions=None):
        s = state or {}
        self.sessions = SE.load_sessions() if sessions is None else sessions   # #60: logged out without the env vars
        self.login_redirect = None                          # a logged-in context was sent to a login page
        self.decide = decide                                # True: the brain picks the next action (act())
        self.log = s.get("log", [])                         # visits shown: [{t, device, title, url, host, why}]
        self.used = set(s.get("used", []))                  # chat texts already searched
        self.rng = rng or random.Random()
        self.pw = None
        self.browser = None
        self.screens = {"desk": Screen("desk"), "phone": Screen("phone")}
        self.proxy = proxy or os.environ.get("BROWSE_PROXY") or None
        self.ignore_tls = ignore_tls or os.environ.get("BROWSE_IGNORE_TLS") == "1"   # sandbox proxies only
        self.guard = Guard(via_proxy=bool(self.proxy))
        self.lock = asyncio.Lock()
        self.failures = 0
        self.last_skip = None                               # why the last page was left unshown (guard, bot wall...)
        self.typed = []                                     # every text typed: [{t, device, host, field, query}]
        self.feed_note = None                               # #89: what the short-video feed could not do, said plainly
        self.dismissed = []                                 # banners / modals pressed away: [{t, host, label, kind}]
        self.sandbox = None                                 # Chromium's own sandbox on? (None: not launched yet)
        self.no_sandbox = False                             # a sandboxed launch failed once: stay without it
        self.limits = SS.Limits(state=s.get("searches"))    # per-host requests per hour, searches per source today
        self.variety = I.Variety(state=(s.get("searches") or {}).get("variety"))   # today's topics, Wikipedia share
        self.robots = SS.Robots()
        self.visited = NV.Visited(state=s.get("visited"))   # #89: no page, video or near-same title twice in 7 days
        self.seed_t = {}                                    # seed site -> last opened (rotation, SEED_GAP_S)
        self.yt = YT.Quota(state=s.get("youtube"))          # YouTube Data API units today (only with the key)
        self.heavy = MG.HeavyPages(s.get("heavy"))          # #89: pages / hosts that pushed Chromium over its cap
        self.walled = {h: float(t) for h, t in (s.get("walled") or {}).items()     # #89: host -> left alone until
                       if isinstance(h, str) and isinstance(t, (int, float))}
        self.mem_checked = 0.0
        self.desk_videos = []                               # #89: keys of the last desk videos (streak cap)
        self.video_run, self.video_break_until = 0, 0.0     # #89: desk videos in a row; a break of pages after it
        self.yt_used = {}                                   # channel handle -> last used (keyless rotation)
        self.hungry = False                                 # #89 teen: food and cooking sites only while hungry
        self.watched = False                                # a video has been on a screen since the browser started
        self.diag = {}                                      # site -> why its logged-in feed showed no video
        self.diag_shot = {}                                 # site -> masked screenshot of that page (admin only)

    def to_dict(self):
        return {"log": self.log[-KEEP:], "used": list(self.used)[-200:],
                "searches": dict(self.limits.to_dict(), variety=self.variety.to_dict()),
                "visited": self.visited.to_dict(), "youtube": self.yt.to_dict(), "heavy": self.heavy.to_dict(),
                "walled": {h: t for h, t in self.walled.items() if t > time.time()}}

    def host_ok(self, host, current=None):
        """#89 teen variety guard: under HOST_DAY_CAP pages today on this site, not a 4th page in a row on the site he
        is on (`current`), and no cooking site unless he is hungry."""
        h = (host or "").lower().removeprefix("www.")
        if RECIPE_HOST.search(h) and not getattr(self, "hungry", False):
            return False                                        # no recipe loops outside meals
        if WALLED_SOCIAL.search(h) or APP_WALL_HOST.search(h):
            return False                                        # a login / app wall for him: never opened
        if any(h == f.removeprefix("www.") for f in HOST_CAP_FREE):
            return True
        if self.variety.host_count(h) >= HOST_DAY_CAP:
            return False
        cur = (current or "").lower().removeprefix("www.")
        return not (cur and h == cur and self.variety.host_streak >= HOST_STREAK_MAX)

    def fresh(self, url, title=None):
        """Not opened in the last 7 days (the URL / video id, or a near-duplicate title)."""
        return not self.visited.seen(url, title)

    def accounts(self):
        """For /api/browsing: per site "logged in" / "logged out" and why. Never a cookie."""
        out = {}
        for site, s in self.sessions.items():
            s.check()
            out[site] = {"state": "logged in" if s.logged_in else "logged out", "reason": s.status()["reason"]}
        return out

    @staticmethod
    def available():
        try:
            import playwright.async_api  # noqa: F401
            return True
        except ImportError:
            return False

    # --- lifecycle -----------------------------------------------------------------------------------------------
    async def _ensure(self, device):
        if self.browser is None or not self.browser.is_connected():
            from playwright.async_api import async_playwright
            if self.pw is None:
                self.pw = await async_playwright().start()
            # Chromium's own sandbox stays on unless we run as root, where Chromium refuses it (the image drops to
            # uid 1000, #18). If a sandboxed launch fails (no user namespaces in the runtime), relaunch without it.
            # The browser gets a minimal environment: none of the server's secrets (API tokens, site password).
            root = hasattr(os, "geteuid") and os.geteuid() == 0
            sandbox = not (root or self.no_sandbox)
            try:
                self.browser = await self.pw.chromium.launch(**launch_kwargs(sandbox, self.proxy))
            except Exception as e:
                if not sandbox:
                    raise
                self.no_sandbox = True
                print("browse: !!! CHROMIUM SANDBOX FAILED TO START, falling back to --no-sandbox !!!",
                      repr(e)[:300], flush=True)
                sandbox = False
                self.browser = await self.pw.chromium.launch(**launch_kwargs(False, self.proxy))
            if root:
                print("browse: !!! running as root: Chromium sandbox OFF (--no-sandbox) !!!", flush=True)
            self.sandbox = sandbox
            for sc in self.screens.values():
                sc.ctx = sc.page = sc.public = sc.site = None
                sc.sites = {}
                sc.info, sc.history, sc.awaiting, sc.scrolls_left, sc.chain = None, [], None, 0, 0
        sc = self.screens[device]
        if sc.ctx is None:
            sc.public = await self._new_context(device, YOUTUBE_COOKIES, self.guard.route)
            sc.ctx, sc.page = sc.public
            sc.site = None
        return sc

    async def _new_context(self, device, cookies, route):
        opts = dict(DESK if device == "desk" else PHONE, accept_downloads=False, java_script_enabled=True,
                    locale="en-US", timezone_id="Asia/Tokyo", ignore_https_errors=self.ignore_tls,
                    permissions=[], color_scheme="light", service_workers="block")
        if device == "desk":
            opts["user_agent"] = DESK_UA
        ctx = await self.browser.new_context(**opts)
        await ctx.add_cookies(cookies)                      # YouTube's Restricted Mode (and a session), before any page
        await ctx.route("**/*", route)
        page = await ctx.new_page()
        ctx.on("page", lambda p: asyncio.ensure_future(p.close()) if p != page else None)   # no pop-ups
        page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
        page.set_default_timeout(NAV_TIMEOUT_MS)
        return ctx, page

    def _session(self, url):
        """The logged-in session for this URL's site, or None (no secret, expired, or another site)."""
        s = self.sessions.get(SE.site_for_url(url) or "")
        return s if s is not None and s.check() else None

    def _site_route(self, site):
        """A logged-in context: its pages stay on that site's own domains and never open a private page; every
        request also passes the guard."""
        domains = SE.SITES[site]["domains"]

        async def route(route):
            req = route.request
            if req.is_navigation_request() and req.frame.parent_frame is None:
                u = urllib.parse.urlsplit(req.url)
                if not SE.host_in(u.hostname or "", domains) or VO.private_url(req.url):
                    if LOGIN_HREF.search(u.path + "?") or SE.host_in(u.hostname or "", ("accounts.google.com",)):
                        self.login_redirect = site              # sent to a login page: the session has ended
                    return await route.abort()
            return await self.guard.route(route)
        return route

    async def _use(self, sc, url):
        """Point the screen at the context for `url`: the site's logged-in one when it has a session, else the
        logged-out one. The session's cookies are only ever added to its own context."""
        s = self._session(url)
        if s is None:
            if sc.site is not None:
                sc.ctx, sc.page = sc.public
                sc.site = None
            return
        if s.site not in sc.sites:
            sc.sites[s.site] = await self._new_context(sc.name, s.cookies(), self._site_route(s.site))
        sc.ctx, sc.page = sc.sites[s.site]
        sc.site = s.site

    async def _logout(self, sc, reason):
        """A session ended (expired, sign-in button or wall): that site is browsed logged out from now on."""
        site = sc.site
        s = self.sessions.get(site or "")
        if s is not None:
            s.expire(reason)
        for other in self.screens.values():
            pair = other.sites.pop(site, None)
            if pair:
                if other.site == site:
                    other.ctx, other.page, other.site = (*other.public, None) if other.public else (None, None, None)
                try:
                    await pair[0].close()
                except Exception:
                    pass

    async def close(self, device=None):
        """Close one screen (he put the phone down) or everything (asleep / shutting down)."""
        for name, sc in self.screens.items():
            if device in (None, name) and sc.ctx is not None:
                for ctx, _ in sc.contexts():
                    try:
                        await ctx.close()
                    except Exception:
                        pass
                sc.ctx = sc.page = sc.public = sc.site = None
                sc.sites = {}
                sc.scrolls_left, sc.next_at, sc.pending_link = 0, 0.0, None
                sc.info, sc.history, sc.awaiting, sc.chain = None, [], None, 0
                sc.mode, sc.watch_until, sc.scene = None, 0.0, 0.0
        if device is None and self.browser is not None:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None
        if device is None and self.pw is not None:          # the driver itself may be dead: start a fresh one next time
            try:
                await self.pw.stop()
            except Exception:
                pass
            self.pw = None

    async def _over_soft_cap(self):
        """#89 memory: at most every MEM_CHECK_S, this process tree's memory (Chromium's renderers included, read in a
        thread). Over SOFT_MEM_MB the pages on screen are recorded as heavy (HeavyPages) and Chromium is closed: the
        next step starts it afresh on another page, before the watchdog's hard limit kills the whole service."""
        now = time.time()
        if now - self.mem_checked < MEM_CHECK_S or self.browser is None:
            return False
        self.mem_checked = now
        try:
            from browse_service import tree_rss_mb
            mb = await asyncio.to_thread(tree_rss_mb, os.getpid())
        except Exception:
            return False
        if mb <= SOFT_MEM_MB:
            return False
        pages = [(sc.info.get("url"), sc.info.get("host")) for sc in self.screens.values() if sc.info]
        self.heavy.strike(pages)
        print(f"browse: {mb:.0f} MB > {SOFT_MEM_MB:.0f} MB with {[h for _, h in pages]}: Chromium recycled", flush=True)
        self.recycles = getattr(self, "recycles", 0) + 1
        await self.close()
        return True

    # --- one step ------------------------------------------------------------------------------------------------
    async def step(self, device, heard=(), interest=None, mode=None):
        """Scroll the current page or open the next one; returns the new screen status when a screenshot was taken.
        mode "video": he is watching videos (life activity watch_video): pages come from a YouTube search."""
        sc = self.screens[device]
        if time.time() < sc.next_at:
            return None
        self.hungry = bool(isinstance(interest, dict) and interest.get("hungry"))
        if mode is None and device == "phone" and isinstance(interest, dict) and interest.get("feed") == "shorts":
            mode = "shorts"                                     # the rhythm / his phone app: a short-video feed
        if mode is None and device == "desk" and isinstance(interest, dict) and interest.get("feed") == "video":
            mode = "video"                                      # #89 teen: a good share of desk time is YouTube
        mode = self._video_break(device, mode)
        async with self.lock:
            try:
                if await self._over_soft_cap():                 # #89: recycle Chromium before the watchdog kills it
                    return None
                sc = await self._ensure(device)
                moved_on = False
                if mode != sc.mode:                             # switched between browsing, videos and shorts
                    sc.mode, sc.awaiting, sc.watch_until, sc.queue = mode, None, 0.0, []
                    if sc.info:
                        moved_on = True                         # start afresh in the new mode
                if sc.watch_until:                              # watching a video: screenshots until the time is up
                    if time.time() < sc.watch_until and sc.info and sc.info.get("kind") == "page":
                        if not await self._watch(sc):
                            sc.next_at = time.time() + 15
                            return None
                        sc.next_at = time.time() + VIDEO_SHOT_S
                        self.failures = 0
                        return sc.status()
                    await self._end_watch(sc)
                if self.decide and sc.awaiting is not None:      # the brain is choosing: hold the page
                    if not self._fresh_chat(heard) and time.time() - sc.awaiting_since < DECIDE_WAIT_S:
                        return None
                    sc.awaiting, moved_on = None, True          # a new chat message, or no answer: move on
                if sc.scrolls_left > 0 and sc.info and not moved_on:
                    sc.scrolls_left -= 1
                    await sc.page.evaluate("() => window.scrollBy({top: innerHeight * 0.7, behavior: 'smooth'})")
                    await sc.page.wait_for_timeout(900)
                    if not await self._shoot(sc):                   # turned into a bot check: left
                        sc.next_at = time.time() + 15
                        return None
                elif self.decide and sc.chain >= MAX_CHAIN and sc.info and not moved_on:
                    ok = await self._next(sc, list(heard), interest)    # a long chain ends: something new
                    if ok and sc.info:
                        sc.info = dict(sc.info, why=f"after {MAX_CHAIN} pages in a row, wandered off; "
                                                    f"{sc.info.get('why', '')}")
                    if not ok:
                        sc.next_at = time.time() + 15
                        return None
                elif (self.decide and sc.info and sc.info.get("kind") in ("page", "search") and sc.page is not None
                      and (sc.page.url.startswith("http") or sc.info.get("card"))
                      and not self._fresh_chat(heard) and not moved_on):
                    page = await self.page_info(sc)
                    if page["links"] or page["can_back"]:
                        sc.awaiting, sc.awaiting_since = page, time.time()
                        return {"decide": page, "device": sc.name}
                    ok = await self._next(sc, list(heard), interest)
                    if not ok:
                        sc.next_at = time.time() + 15
                        return None
                else:
                    ok = await self._next(sc, list(heard), interest)
                    if not ok:
                        sc.next_at = time.time() + 15
                        return None
                sc.next_at = time.time() + SCROLL_EVERY_S * (0.8 + 0.5 * self.rng.random())
                self.failures = 0
                return sc.status()
            except Exception as e:
                self.failures += 1
                print(f"browse ({device}):", repr(e)[:160], flush=True)
                sc.next_at = time.time() + min(120, 10 * self.failures)
                dead = re.search(r"Connection closed|Target crashed|Browser has been closed|driver", repr(e))
                if dead or self.failures >= 3:                 # crashed renderer or driver: restart everything cleanly
                    await self.close()
                return None

    def _fresh_chat(self, heard):
        return any(text not in self.used for text in list(heard)[-5:])

    async def page_info(self, sc):
        """What the eyes may see: title, visible text and up to PAGE_LINKS links that pass the guard (numbered)."""
        page = sc.page
        text = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 6000)")
        raw = await page.evaluate(LINKS_JS)
        search = sc.info.get("kind") == "search"
        if search and sc.info.get("results"):                   # a results page: its parsed results, guarded again
            return self.result_page(sc, page.url)
        if sc.info.get("card") and sc.queue:                    # a TikTok card: the next cards are the options
            return self.result_page(sc, sc.info["url"], results=sc.queue)
        return self.pick_links(raw, page.url, text, sc, search)

    @staticmethod
    def safe_results(results):
        """Results that may be numbered for the brain and shown: the guard on the URL (url_ok, login/sign-up links)
        and on the title (title_ok; a video's by the song and video rule, video_text_ok); a snippet that fails
        title_ok is dropped."""
        out = []
        for r in results or []:
            url, title = str(r.get("url") or ""), " ".join(str(r.get("title") or "").split())
            host = urllib.parse.urlsplit(url).hostname or ""
            video = is_video_host(host) or r.get("video")                # a video's title: the song and video rule
            if (len(title) < 3 or not url_ok(url) or LOGIN_HREF.search(url) or LOGIN_LINK.search(title)
                    or (not video_text_ok(title) if video else not title_ok(title) or BAD_WORDS.search(title))
                    or money_action(title, url)
                    or not all(video_text_ok(h) for h in r.get("hashtags") or [])):
                continue
            snippet = " ".join(str(r.get("snippet") or "").split())
            if snippet and (not title_ok(snippet) or BAD_WORDS.search(snippet)):
                snippet = ""
            r = dict(r, url=url, title=title[:140], snippet=snippet[:240])
            if r.get("channel") and not video_text_ok(r["channel"]):     # a creator name that fails: not shown
                r["channel"] = ""
                r["snippet"] = "" if r["snippet"].startswith("@") else r["snippet"]
            out.append(r)
        return out

    def result_page(self, sc, url, results=None):
        """A search results page for the eyes: its results (title, snippet, host), numbered, nothing else."""
        links = []
        results = [r for r in self.safe_results(sc.info.get("results") if results is None else results)
                   if (not (sc.site or self._session(r["url"])) or VO.link_ok(r["url"], r["title"]))
                   and (r["url"] in getattr(sc, "cards", {}) or self.fresh(r["url"], r["title"]))]
        for i, r in enumerate(results[:PAGE_LINKS]):
            link = {"id": f"L{i + 1}", "href": r["url"], "text": r["title"][:100], "result": True,
                    "host": (urllib.parse.urlsplit(r["url"]).hostname or "").removeprefix("www."), "area": 0,
                    "video": bool(VIDEO_LINK.search(r["url"]) or r.get("video"))}
            if r.get("snippet"):
                link["snippet"] = r["snippet"]
            links.append(link)
        text = " ".join(f"{l['text']}. {l.get('snippet', '')}" for l in links)
        return {"device": sc.name, "url": url, "title": sc.info.get("title", ""), "host": sc.info.get("host", ""),
                "kind": "search", "text": " ".join(text.split())[:1500], "links": links,
                "can_back": len(sc.history) >= 2, "search_box": False, "chain": sc.chain, "max_chain": MAX_CHAIN,
                "search": sc.info.get("search"), "streak_pull": I.streak_pull(self.variety)}

    def link_ok(self, href, label, page_url, kind=None):
        """S9: the one guard for a link he may be offered or follow (pick_links and the random link-follow,
        _pick_link): the URL (url_ok: hosts, trading sites, files), login / sign-up / checkout links, the label
        (title_ok; a YouTube link's by the video rule), money actions, footer links (unless it is a "next" or
        comments link), the 7-day novelty rule, the per-site cap and app / messaging walls."""
        u = urllib.parse.urlsplit(href or "")
        cur = urllib.parse.urlsplit(page_url or "")
        yt = is_youtube(u.hostname or "")
        return not (len(label) < 4 or not url_ok(href) or LOGIN_LINK.search(label) or LOGIN_HREF.search(href)
                    or not (video_text_ok if yt else title_ok)(label) or money_action(label, href)
                    or (kind not in ("next", "comments") and NV.footer_link(label, href, page_url))
                    or not self.fresh(href, label) or not self.host_ok(u.hostname, cur.hostname) or app_wall(href))

    def pick_links(self, raw, url, text, sc, search=False):
        """Numbered, guarded links for the eyes. Pagination ("next"), comment threads and (on Wikipedia) external
        sources are kept even when they are small or low on the page, so the brain can follow them (#29)."""
        cur = urllib.parse.urlsplit(url)
        wiki = (cur.hostname or "").endswith("wikipedia.org")
        seen, cand = {}, []
        for href, label, area, visible, *extra in raw:
            rel, external, aria = (list(extra) + ["", False, ""])[:3]
            label = " ".join(str(label or "").split())
            kind = link_kind(href, label, rel or "", aria or "")
            if kind == "next" and len(label) < 4:
                label = "next page"
            u = urllib.parse.urlsplit(href)
            ext = bool(external) and wiki and not (u.hostname or "").endswith(("wikipedia.org", "wikimedia.org",
                                                                                "wikidata.org"))
            yt = is_youtube(u.hostname or "")
            if not self.link_ok(href, label, url, kind):
                continue                                        # #89: no footer links, nothing opened this week
            if (sc.site or self._session(href)) and not VO.link_ok(href, label, aria or ""):
                continue                                        # #60: logged in, an action or a private page
            if href in seen:                                    # YouTube: the thumbnail link comes first, labelled
                if yt and len(label) > len(seen[href]["text"]):  # with the duration; the title link is the label
                    seen[href]["text"] = label
                continue
            if (u.netloc, u.path, u.query) == (cur.netloc, cur.path, cur.query) or (
                    search and u.netloc == cur.netloc and kind != "next"):
                continue                                        # same page; on a results page only the results
            seen[href] = {"visible": bool(visible), "area": area, "href": href, "text": label, "host": u.hostname or "",
                          "kind": kind, "external": ext}
            cand.append(seen[href])
        cand.sort(key=lambda c: (not c["visible"], -c["area"]))
        special = [c for c in cand if c["kind"]][:4] + [c for c in cand if c["external"] and not c["kind"]][:8]
        ids = {id(c) for c in special}
        keep = special + [c for c in cand if id(c) not in ids][:max(0, PAGE_LINKS - len(special))]
        keep.sort(key=lambda c: cand.index(c))
        if url in SEEDS or (cur.path in ("", "/") and not search):   # a front page: its headlines are "trending"
            self.variety.offer([c["text"] for c in cand if not c["kind"] and c["host"] == (cur.hostname or "")][:15])
        links = []
        for i, c in enumerate(keep):
            link = {"id": f"L{i + 1}", "href": c["href"], "text": c["text"][:100],
                    "host": c["host"].removeprefix("www."), "area": round(c["area"]),
                    "video": bool(VIDEO_LINK.search(c["href"]))}
            if c["kind"] == "next":
                link["next"] = True
            elif c["kind"] == "comments":
                link["comments"] = True
            if c["external"]:
                link["external"] = True
            links.append(link)
        return {"device": sc.name, "url": url, "title": sc.info.get("title", ""), "host": sc.info.get("host", ""),
                "kind": sc.info.get("kind"), "text": " ".join(text.split())[:1500], "links": links,
                "can_back": len(sc.history) >= 2, "search_box": bool(sc.info.get("search_box")),
                "chain": sc.chain, "max_chain": MAX_CHAIN, "streak_pull": I.streak_pull(self.variety)}

    async def act(self, device, action, why="", interest=None):
        """Carry out the action the brain chose for the page it was given; returns the new screen status or None."""
        sc = self.screens[device]
        kind, why = action.get("action"), why or "his brain picked it"
        async with self.lock:
            page, sc.awaiting = sc.awaiting, None                  # claimed under the lock (no race with step)
            if page is None or sc.page is None:
                return None
            try:
                ok = False
                self.last_skip = None
                if kind in LINK_ACTIONS:
                    want = action.get("href")                       # matched by URL: link ids are per capture
                    link = next((l for l in page["links"] if l["href"] == want), None)
                    flag = LINK_ACTIONS[kind]                       # the link must really be of that kind
                    href = link["href"] if link and (flag is None or link.get(flag)) else None
                    if href and (money_action(link.get("text", ""), href) or money_action(action.get("label", ""))):
                        href, self.last_skip = None, "never acts with money"     # buy / sell / swap / connect / sign
                    if href and href in sc.cards:                   # a TikTok card: shown, never opened (#89)
                        ok = await self._show_card(sc, sc.cards[href], f"{action.get('label', '')} — {why}")
                    else:
                        ok = bool(href) and await self._open(sc, href, f"{action.get('label', '')} — {why}", "page")
                        item = next((r for r in sc.queue if r.get("url") == href), None)
                        if (not ok and item and self.last_skip in ("bot wall", "did not load", "empty")
                                and (card := SV.youtube_card(item))):     # #89: the short's page is blocked for the
                            ok = await self._show_card(sc, card, f"{action.get('label', '')} — {why}")   # server
                            self.feed_note = SV.NOTE_SHORTS_CARDS if ok else self.feed_note
                    sc.queue = [r for r in sc.queue if r.get("url") != href]
                    if ok and kind in ("play_video", "open_video") and await self._play_muted(sc):
                        await self._start_watch(sc, action.get("watch_s"))
                elif kind == "search" and action.get("target"):
                    from eyes import query_ok                       # checked again here, in the browser's process
                    q = query_ok(action["target"])
                    origin = "follow_up" if SS.FOLLOW_LABEL.match(str(action.get("label") or "")) else "page"
                    ok = bool(q) and await self._search(sc, q, f"{SS.ORIGINS[origin]} — {why}", origin)
                elif kind == "site_search" and action.get("target"):
                    from eyes import query_ok                       # the query filter, again in this process
                    q = query_ok(action["target"])
                    ok = bool(q) and await self._site_search(
                        sc, q, f"searched {page.get('host', 'the site')} for “{q}” — {why}")
                elif kind == "back" and len(sc.history) >= 2:
                    saved = list(sc.history)
                    sc.history = saved[:-2]
                    ok = await self._open(sc, saved[-2], f"went back — {why}", "page", revisit=True)
                    if not ok:
                        sc.history = saved
                elif kind == "scroll":
                    sc.scrolls_left = self.rng.randint(1, 3)
                    if sc.info:
                        sc.info = dict(sc.info, why=f"kept reading — {why}")
                    ok = True
                if not ok:                                      # leave, or the chosen page could not be shown
                    missed = None
                    if kind in tuple(LINK_ACTIONS) + ("search", "site_search", "back"):
                        missed = f"could not show “{action.get('label', '')}” ({self.last_skip or 'refused'})"
                    ok = await self._next(sc, [], interest)
                    if ok and missed and sc.info:               # the card must not pretend the choice was shown
                        sc.info = dict(sc.info, why=f"{missed}; {sc.info.get('why', '')}", missed=missed)
                sc.next_at = time.time() + SCROLL_EVERY_S
                self.failures = 0
                return sc.status() if ok else None
            except Exception as e:
                print(f"browse ({device}) act:", repr(e)[:160], flush=True)
                return None

    async def _next(self, sc, heard, interest):
        """Pick where to go: a fresh chat message -> search; a result from the last search; a link that matches
        his interests; else a search on what he read last or something familiar; sometimes a seed site. A new chain
        of pages starts here."""
        from eyes import query_ok
        sc.chain = 0
        if sc.mode == "shorts" and await self._shorts(sc, interest):
            return True
        if not self.watched and sc.mode != "shorts":            # #89 live: the first watch as early as possible
            d = interest if isinstance(interest, dict) else {}
            p = I.pick(self.variety, hour=d.get("hour", I.tokyo_hour()), rng=self.rng, mult=d.get("tastes"),
                       discover=True, hungry=self.hungry)
            if query_ok(p["query"]) and await self._public_videos(
                    sc, "youtube", p["query"], f"watched a video on {p['topic']}", "interests", short=False):
                return True
        if sc.mode == "video":                                  # watching videos: YouTube's Data API + embed player
            d = interest if isinstance(interest, dict) else {}
            q = query_ok(SS.interest_text(interest)) if d.get("from") not in ("", None, "interests") else None
            if not q:                                           # #89 teen: his profile's topics, not old defaults
                q = query_ok(I.pick(self.variety, hour=d.get("hour", I.tokyo_hour()), rng=self.rng,
                                    mult=d.get("tastes"), discover=True, hungry=self.hungry)["query"])
            q = q or self.rng.choice(VIDEO_TOPICS)              # (/results is robots-closed)
            if await self._public_videos(sc, "youtube", q, f"looked for videos about “{q}”", "", short=False):
                return True
        if sc.pending_link:
            url, why = sc.pending_link
            sc.pending_link = None
            if await self._open(sc, url, why, "page"):
                return True
        for text in reversed(heard[-5:]):
            if text in self.used:
                continue
            self.used.add(text)
            wished = query_ok(SS.wish(text))                    # "look up ...": the viewer's words, filtered
            if wished:
                return await self._search(sc, wished, f"{SS.ORIGINS['chat']}: “{text[:60]}”", "chat")
            top = set(sorted(words(text), key=len, reverse=True)[:3])
            q = " ".join(w for w in words(text) if w in top)    # B3: the longest words, in the viewer's order
            if q:
                return await self._search(sc, q, f"from chat: “{text[:60]}”", "chat")
            break
        r = self.rng.random()
        if sc.info and sc.info.get("kind") == "page" and r < 0.4:
            link = await self._pick_link(sc, SS.interest_text(interest))
            if link and await self._open(sc, link[0], f"followed “{' '.join(link[1].split())[:50]}” from {sc.info['host']}",
                                         "page"):
                return True
        if r < 0.88:                                            # #56: he searches more, from his own sources
            topic = query_ok(SS.interest_text(interest))
            origin = interest.get("from", "") if isinstance(interest, dict) and topic else ""
            origin = origin if origin in SS.ORIGINS else ""
            why = None
            if not topic or self.rng.random() < self.profile_share():    # the interest profile, by the hour
                d = interest if isinstance(interest, dict) else {}
                p = I.pick(self.variety, hour=d.get("hour", I.tokyo_hour()), rng=self.rng, mult=d.get("tastes"),
                           hungry=self.hungry)
                if query_ok(p["query"]):
                    topic, origin = p["query"], "interests"
                    why = f"{SS.ORIGINS['interests']} ({p['topic']}, {p['rhythm']})"
            if not topic:
                topic, origin = self.rng.choice(FAMILIAR), "familiar"
            why = why or (SS.ORIGINS[origin] if origin not in ("", "familiar") else f"curious about “{topic[:50]}”")
            return await self._search(sc, topic, why, origin)
        # B4: the front page of a site about what is on his mind (the caption names the topic), by the hour
        d = interest if isinstance(interest, dict) else {}
        topic = I.topic_of(SS.interest_text(interest)) or I.pick(
            self.variety, hour=d.get("hour", I.tokyo_hour()), rng=self.rng, mult=d.get("tastes"),
            hungry=self.hungry)["topic"]
        topic = topic if topic in SEED_TOPICS else None
        return await self._seed(sc, f"opened a site about {topic}" if topic else "opened a site he likes", topic,
                                hungry=self.hungry, hour=d.get("hour", I.tokyo_hour()))

    SEED_GAP_S = 6 * 3600                                      # a seed site's front page at most every 6 hours
    NIGHT_SEEDS_OFF = ("football",)                            # B4: no sports / news fronts in the middle of the night

    async def _seed(self, sc, why, topic=None, hungry=False, only_topic=False, hour=None):
        """A seed site's front page (a feed that changes, so not held to the 7-day rule), rotating: the ones opened in
        the last SEED_GAP_S are left out; the topic's own sites first (only them with only_topic: a failed search
        falls back on a site about it or none); cooking sites only when he is hungry; sports / news fronts not at
        night (B4)."""
        now = time.time()
        mine = SEED_TOPICS.get(topic or "", [])
        h = float(hour) % 24 if hour is not None else None
        night = h is not None and (h >= 23 or h < 6)
        off = {u for t in self.NIGHT_SEEDS_OFF for u in SEED_TOPICS[t]} if night else set()
        pool = [u for u in (mine if only_topic else SEEDS + (SEED_TOPICS["food"] if hungry else []))
                if now - self.seed_t.get(u, 0) > self.SEED_GAP_S and self.host_ok(urllib.parse.urlsplit(u).hostname)
                and u not in off]
        self.rng.shuffle(pool)
        pool.sort(key=lambda u: u not in mine)
        for u in pool[:3]:
            self.seed_t[u] = now
            if await self._open(sc, u, why, "page", revisit=True):
                return True
        return False

    PROFILE_SHARE = 0.45                                       # searches from the interest profile (#56 extension)

    def profile_share(self):
        """How often a search comes from his interest profile rather than his notes / reading: more when he has
        been on one topic for several pages (variety)."""
        return min(0.9, self.PROFILE_SHARE + 0.4 * I.streak_pull(self.variety))

    async def _shorts(self, sc, interest, force=False):
        """The phone's short-video feed: a TikTok tag page or a YouTube Shorts search (Restricted Mode) on his
        interest or the hour's profile topic; the shorts found are queued, and each one is picked by the vote
        among the next ones (local options, no paid call), played muted for at most SHORTS_MAX_S."""
        from eyes import query_ok
        d = interest if isinstance(interest, dict) else {}
        q, origin = query_ok(SS.interest_text(interest)), d.get("from", "")
        if origin in NV.SEEN_ORIGINS and not self.visited.follow_ok():
            q = None                                            # #89: follow-ups at most a quarter of searches
        topic = new = None
        if not q or (not force and self.rng.random() < 1 - I.FOLLOW_SHORTS):
            # #89: most shorts come from topics he has not seen lately, not his notes; B4: on the phone mostly his own
            # topics' neighbours (the profile), the discovery pool only PHONE_DISCOVERY of the time
            p = I.pick(self.variety, hour=d.get("hour", I.tokyo_hour()), rng=self.rng, mult=d.get("tastes"),
                       discover=True, hungry=self.hungry, pool_share=I.PHONE_DISCOVERY)
            q, origin = query_ok(p["query"]), "interests"
            topic, new = p["topic"], p["new"]
        else:
            topic = I.topic_of(q or "") or I.discovery_topic(q or "")
            new = not self.variety.recent(topic)
            self.variety.mark(topic, q)
        sc.feed_topic, sc.feed_fresh = topic, new
        self.visited.search(origin)
        if not q:
            return False
        names = SV.feed_order(self.rng)
        why = SS.ORIGINS.get(origin if origin in SS.ORIGINS else "interests")
        sc.cards = {}
        for name in names:
            if name == "tiktok" and self._session("https://www.tiktok.com/") and self.limits.source_ok("tiktok"):
                # logged in: the account's own TikTok (a tag page in its context); _diag records why when it is empty
                if await self._search_on(sc, "tiktok", q, f"short videos — {why}", origin):
                    sc.queue = [r for r in sc.info.get("results", [])
                                if r.get("video") and self.fresh(r["url"], r["title"])]
                    if sc.queue:
                        self.feed_note = None
                        return True
            if await self._public_videos(sc, name, q, f"short videos — {why}", origin):
                return True
        return False

    # --- short videos the compliant way (#89 live follow-up) -------------------------------------------------------
    async def _public_videos(self, sc, kind, q, why, origin="", short=True):
        """Public videos played in their site's official embed player: YouTube through the Data API (with
        YOUTUBE_API_KEY), TikTok found through the search engines. Captions
        come from the official oEmbed APIs and pass video_text_ok. The first one is shown and played muted; the rest
        are the next options."""
        cands = []
        if (kind == "shorts" or kind == "youtube") and not self.yt.player_up():
            self.feed_note = self.yt.player_note()              # #89 live: YouTube refuses the player: other things
            return False
        if kind == "shorts" or kind == "youtube":
            if YT.key():
                # B1: a search for what he asked for first (100 units); the latest uploads of the topic's channels
                # (3 units) only as a labelled fallback, and only when the query has a topic with channels
                cands = await self._yt_search(sc, q, short)
                if not cands:
                    cands = await self._yt_uploads(sc, q, short)
                    if cands:
                        self.feed_note = YT.NOTE_UPLOADS
                        why = f"latest from {cands[0].get('author') or 'a channel he likes'} (nothing on “{q[:40]}”)"
            if not cands:                                       # no key or no quota: nothing new is looked up
                cands = self._yt_replay(short, q)               # B1: only earlier finds about the same thing
                self.feed_note = (YT.NOTE_REPLAY_KEY if YT.key() else YT.NOTE_REPLAY) if cands else (
                    self.feed_note if YT.key() else YT.NOTE_NO_KEY)
                if cands:
                    why = "nothing new today; an earlier pick"  # never the request text: it is not what he asked
        elif kind == "tiktok":
            cands = await self._tiktok_found(sc, q)
        if not cands:
            return False
        cands = sorted(cands, key=lambda c: bool(SHOPPING_LIST.search(c.get("title") or "")))   # #89: lists last
        self.limits.count("tiktok" if kind == "tiktok" else "shorts" if short else "youtube", q, origin)
        sc.cards = {c["url"]: c for c in cands}
        sc.queue = [{"url": c["url"], "title": c["title"], "snippet": c["author"], "video": True, "short": short,
                     "channel": c["author"]} for c in cands]
        if kind == "tiktok":
            self.feed_note = SV.NOTE_EMBEDS
        return await self._show_card(sc, cands[0], why)

    def _streak(self, c):
        """#89: the last CHANNEL_STREAK_MAX desk videos all share a channel or guest with this one."""
        last = self.desk_videos[-CHANNEL_STREAK_MAX:]
        keys = video_keys(c.get("title"), c.get("author"))
        return len(last) >= CHANNEL_STREAK_MAX and any(all(k in v for v in last) for k in keys)

    def _card_ok(self, c):
        return (c and self.fresh(c["url"], c["title"]) and not self.yt.is_bad(c["url"]) and not self._streak(c)
                and video_text_ok(c["title"])
                and (not c.get("author") or video_text_ok(c["author"]))
                and all(video_text_ok(h) for h in c.get("hashtags") or []) and (not c.get("thumb") or url_ok(c["thumb"])))

    async def _yt_search(self, sc, q, short=True):
        """YouTube Data API search.list (the key in a header, never in a URL), cached per query, within the day's
        free quota. -> cards."""
        results = self.yt.cached(q, short)
        if results is None:
            if not self.yt.allow() or not self.limits.allow("www.googleapis.com"):
                return []
            self.limits.note("www.googleapis.com")
            status, text = await self._fetch(sc, YT.search_url(q, short), headers=YT.headers())
            if status != 200:
                self.yt.error(f"search: HTTP {status}")
                self.limits.refuse("shorts" if short else "youtube", f"YouTube API HTTP {status}")
                return []
            results = YT.parse_search(text, short)
            self.yt.spend(q, short, results)
            if results:                                         # only what the embed will play (1 unit)
                vt = await self._yt_api(sc, YT.videos_url([r["id"] for r in results]))
                if vt:
                    ok = YT.parse_durations(vt)
                    results = [r for r in results if r["id"] in ok]
                    self.yt.cache[self.yt._k(q, short)] = {"t": time.time(), "r": results[:10], "v": 2}
                else:                                           # B6: a failed check is not "no videos" for 6 h
                    self.yt.cache_fail(q, short)
                    results = []
            print(f"browse: YouTube API search ({'shorts' if short else 'videos'}), {len(results)} results, "
                  f"{self.yt.used} units today", flush=True)
        cards = [{"url": r["url"], "title": r["title"], "author": r["channel"], "thumb": r["thumb"], "hashtags": [],
                  "embed": r["embed"], "host": "youtube.com", "site": "YouTube Shorts" if short else "YouTube",
                  "how": "YouTube's official embed player"} for r in self.safe_results(results)]
        cards = [c for c in cards if self._card_ok(c)][:6]
        self.yt.found(cards)
        return cards

    def _yt_cards(self, items, short, author=None):
        cards = []
        for r in self.safe_results([{"url": YT.video_url(it["id"], short), "title": it["title"], "video": True,
                                     "channel": it.get("channel", "")} for it in items]):
            vid = r["url"].rsplit("/", 1)[-1].split("=")[-1]
            cards.append({"url": r["url"], "title": r["title"], "author": author or r.get("channel", ""),
                          "hashtags": re.findall(r"#\w+", r["title"])[:6],
                          "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", "embed": YT.embed_url(vid),
                          "host": "youtube.com", "site": "YouTube Shorts" if short else "YouTube",
                          "how": "YouTube's official embed player"})
        return [c for c in cards if self._card_ok(c)]

    async def _yt_api(self, sc, url):
        """One cheap Data API call (the key in a header, never in a URL). -> text or None."""
        if not self.yt.allow(YT.LIST_UNITS) or not self.limits.allow("www.googleapis.com"):
            return None
        self.limits.note("www.googleapis.com")
        status, text = await self._fetch(sc, url, headers=YT.headers())
        self.yt.spend_units(YT.LIST_UNITS)
        if status != 200:
            self.yt.error(f"{url.split('/v3/')[1].split('?')[0]}: HTTP {status}")
            return None
        return text

    async def _yt_uploads(self, sc, q, short=True):
        """#89 teen: the latest uploads of a well-known channel of the query's topic, through the official API
        (YouTube's Terms forbid automated access to its pages): channels.list forHandle -> uploads playlist (kept),
        playlistItems.list -> latest uploads, videos.list -> durations (Shorts: at most SHORT_MAX_S). 3 units, each
        channel's list cached CHANNEL_CACHE_S. -> cards in the official embed player."""
        topic = I.topic_of(q or "")
        if topic not in YT.CHANNELS:                            # B1: no topic, no channel ("Frank Ocean" -> no MrBeast)
            return []
        handles = sorted((h for h in YT.channels_for(topic) if self.yt.channel_ok(h)),
                         key=lambda h: (self.yt_used.get(h, 0), self.rng.random()))
        want = content_words(q)
        for h in handles[:2]:
            pid = self.yt.uploads.get(h)
            if not pid:
                text = await self._yt_api(sc, YT.channels_url(h))
                pid = YT.parse_uploads_id(text) if text else None
                if not pid:
                    continue
                self.yt.uploads[h] = pid
            ck = f"p:{pid}"
            hit = self.yt.cache.get(ck)
            if hit and hit.get("v") == 2 and time.time() - hit["t"] < YT.CHANNEL_CACHE_S:
                items = hit["r"]
            else:
                text = await self._yt_api(sc, YT.playlist_url(pid))
                items = YT.parse_playlist(text) if text else []
                if not items:
                    continue
                text = await self._yt_api(sc, YT.videos_url([it["id"] for it in items]))
                if not text:                                    # B6: a failed check is not cached as "no uploads"
                    continue
                secs = YT.parse_durations(text)
                items = [dict(it, sec=secs[it["id"]]) for it in items if it["id"] in secs]
                self.yt.cache[ck] = {"t": time.time(), "r": items, "v": 2}     # v2: playable() filtered
                print(f"browse: YouTube API uploads of @{h}: {len(items)} videos, {self.yt.used} units today",
                      flush=True)
            self.yt_used[h] = time.time()
            pick = [it for it in items if (it["sec"] <= YT.SHORT_MAX_S) == bool(short)]
            cards = self._yt_cards(pick, short, author=h)
            self.rng.shuffle(cards)
            cards.sort(key=lambda c: not (want & content_words(c.get("title"))))  # B1: the ones about `q` first
            if cards:
                self.yt.found(cards)
                return cards[:6]
        return []

    def _yt_replay(self, short=True, q=None):
        """No key or no quota: no discovery; the videos already found today and not yet shown. B1: only the ones
        about the same thing as `q` (its profile topic, or a shared content word), so a request for one thing never
        shows a video about another; nothing fits -> [] and the search moves on."""
        kind = "/shorts/" if short else "watch?v="
        topic, want = I.topic_of(q or ""), content_words(q)

        def fits(c):
            text = f"{c.get('title') or ''} {c.get('author') or ''}"
            return (topic is not None and I.topic_of(text) == topic) or bool(want & content_words(text))
        return [c for c in reversed(self.yt.today) if kind in c["url"] and self._card_ok(c) and fits(c)][:6]

    async def _tiktok_found(self, sc, q):
        """Public TikTok videos for `q` found through the search engines (site:tiktok.com), described by TikTok's
        oEmbed. Every request goes through robots.txt, the per-host limit and the guard."""
        fetch = lambda u: self._fetch(sc, u)                       # noqa: E731
        urls = []
        for eng in ("ddg", "bing"):
            src = SS.SOURCES[eng]
            url = src["url"](f"site:tiktok.com {q}")
            host = urllib.parse.urlsplit(url).hostname
            if not self.limits.source_ok(eng) or not await self.robots.check(url, fetch, self.limits):
                continue
            self.limits.note(host)
            status, text = await fetch(url)
            if status == 200 and BODY_WALL.search(text[:20000] or ""):
                self.limits.refuse(eng, "bot check")               # DuckDuckGo's "anomaly" page on datacenter IPs
                continue
            if status == 200:
                urls = [u for u in (r["url"].split("?")[0] for r in src["parse"](text, url)) if SV.TIKTOK_VIDEO.match(u)]
            if urls:
                break
        return await self._oembed_cards(sc, "tiktok", [u for u in dict.fromkeys(urls) if self.fresh(u)])

    async def _oembed_cards(self, sc, kind, urls):
        fetch = lambda u: self._fetch(sc, u)                       # noqa: E731
        cards = []
        for u in urls:
            if len(cards) >= 4:
                break
            o = SV.oembed_url(u) if kind == "tiktok" else YT.oembed_url(u)
            host = urllib.parse.urlsplit(o).hostname
            if not self.limits.allow(host) or not await self.robots.check(o, fetch, self.limits):
                break
            self.limits.note(host)
            status, text = await fetch(o)
            if status != 200:
                continue
            if kind == "tiktok":
                c = SV.parse_oembed(text, u)
                if c:
                    c = dict(c, embed=SV.tiktok_player(u), host="tiktok.com", site="TikTok",
                             how="TikTok's official embed player")
            else:
                m, vid = YT.parse_oembed(text, u), SV.YT_SHORT.match(u)
                c = m and vid and {"url": u, "title": m["title"], "author": m["channel"], "hashtags": [],
                                   "thumb": f"https://i.ytimg.com/vi/{vid.group(1)}/hqdefault.jpg",
                                   "embed": YT.embed_url(vid.group(1)), "host": "youtube.com", "site": "YouTube Shorts",
                                   "how": "YouTube's official embed player"}
            if self._card_ok(c):
                cards.append(c)
        return cards

    async def _open_embed(self, sc, card, why):
        """The video in its site's official embed player (youtube-nocookie.com/embed, tiktok.com/player: both
        allowed by their robots.txt), opened as a page with our site as the referrer, played muted."""
        emb = card.get("embed") or ""
        fetch = lambda u: self._fetch(sc, u)                       # noqa: E731
        host = urllib.parse.urlsplit(emb).hostname or ""
        if not emb or not await self.robots.check(emb, fetch, self.limits):
            self.last_skip = "robots.txt"
            return False
        # opening a video is opening a page (pages are not rate-limited; searches and API calls are)
        if getattr(sc, "site", None) and getattr(sc, "public", None):   # never in a logged-in context
            sc.ctx, sc.page = sc.public
            sc.site = None
        if not await self._open(sc, emb, why, "page", title=card["title"], min_text=0, shoot=False,
                                referer=EMBED_REFERER):
            if self.last_skip in PLAYER_REFUSALS and YOUTUBE_HOST.search(host):
                # #89 live: YouTube's bot check / sign-in screen in the player itself, not this video's fault
                print(f"browse: YouTube's player refused ({self.last_skip})", flush=True)
                self.yt.player_failed(self.last_skip)
            return False
        sc.info = dict(sc.info, url=card["url"], host=card.get("host", host), embed=emb, card=False,
                       channel=(card.get("author") or "")[:80], search_box=False)
        sc.scrolls_left = 0
        state = await self._play_muted(sc)
        why_not = await self._embed_error(sc, state)
        if why_not:                                             # never left on screen: the next video instead
            print(f"browse: embed refused {card['url']} ({why_not[:60]})", flush=True)
            self.yt.refused(card["url"], None if "advertisement" in why_not else card.get("author"))
            self.last_skip = "embed refused"
            await self._leave(sc)
            return False
        if YOUTUBE_HOST.search(host):
            self.yt.player_ok()
        if not await self.show(sc):
            return False
        await self._start_watch(sc)
        return True

    async def _play_video_id(self, sc, vid, why, title=None, short=False):
        """A link to a YouTube video, played as "play this video": checked with videos.list (1 unit: embeddable,
        public, not age-restricted, plays in JP), then opened in the official youtube-nocookie embed. Without a key
        it cannot be checked, so it is not played."""
        url = YT.video_url(vid, short)
        if not YT.key():
            self.last_skip = "a YouTube video link (no API key to check it)"
            return False
        if not self.yt.player_up():
            self.last_skip = "YouTube's player is paused (it refused this browser)"
            return False
        if self.yt.is_bad(url) or not self.fresh(url):
            self.last_skip = "video refused or seen"
            return False
        text = await self._yt_api(sc, YT.videos_url([vid]))
        info = (YT.parse_videos(text) if text else {}).get(vid)
        if not info:
            self.yt.refused(url)
            self.last_skip = "video not playable in the embed"
            return False
        short = short or info["sec"] <= YT.SHORT_MAX_S
        card = {"url": YT.video_url(vid, short), "title": info["title"] or title or "a video", "author": info["channel"],
                "hashtags": [], "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", "embed": YT.embed_url(vid),
                "host": "youtube.com", "site": "YouTube Shorts" if short else "YouTube",
                "how": "YouTube's official embed player"}
        if not self._card_ok(card):
            self.last_skip = "guard"
            return False
        return await self._open_embed(sc, card, why)

    async def _embed_error(self, sc, state=None, wait=True):
        """The player's own error, a few seconds after it opened: its error text, or no video element at all."""
        try:
            if wait:
                await sc.page.wait_for_timeout(EMBED_CHECK_MS)
            text = await sc.page.evaluate(EMBED_ERROR_JS) or ""
        except Exception:
            return None
        hits = [m.group(0) for m in EMBED_ERROR.finditer(text)]
        if hits:                                                # B6: a real player error before "advertisement playing"
            return next((h for h in hits if "advertisement" not in h.lower()), hits[0])
        if wait and state is None:
            again = await self._play_muted(sc)
            if again is None:
                return "no video in the player"
        return None

    async def _show_card(self, sc, card, why):
        """One video on the screen: in its official embed player when it has one (played muted), else (or when the
        player is refused) a card: caption, creator, thumbnail on a local page, no video, no actions."""
        sc.queue = [r for r in sc.queue if r.get("url") != card["url"]]
        if card.get("embed"):
            if await self._open_embed(sc, card, why):
                return True
            # #89 live: a refused player is skipped for the next video in the queue within seconds
            for r in list(sc.queue)[:3]:
                nxt = sc.cards.get(r.get("url"))
                if not self.yt.player_up():
                    break
                if nxt and nxt.get("embed") and self._card_ok(nxt):
                    sc.queue = [x for x in sc.queue if x.get("url") != nxt["url"]]
                    if await self._open_embed(sc, nxt, why):
                        return True
            if YOUTUBE_HOST.search(urllib.parse.urlsplit(card["embed"]).hostname or ""):
                print(f"browse: YouTube embed refused ({self.last_skip}); no card, something else", flush=True)
                if not self.yt.player_up():
                    self.feed_note = self.yt.player_note()
                return False                                    # #89 live: a card is not a video
            print(f"browse: embed refused ({self.last_skip}), showing a card instead", flush=True)
        if getattr(sc, "site", None) and getattr(sc, "public", None):   # cards are never shown in a logged-in context
            sc.ctx, sc.page = sc.public
            sc.site = None
        await sc.page.set_content(SV.card_html(card), wait_until="domcontentloaded")
        await sc.page.wait_for_timeout(1200)                    # the thumbnail
        sc.info = {"title": card["title"][:140], "url": card["url"], "host": card.get("host", "tiktok.com"), "kind": "page",
                   "why": why, "t": time.time(), "card": True, "channel": card["author"][:80]}
        sc.scrolls_left = 2
        return await self.show(sc)

    # --- why a logged-in feed showed nothing ------------------------------------------------------------------------
    DIAG_MASK = """header,nav,[data-e2e*="avatar"],[data-e2e*="profile"],[data-e2e*="nav"],[class*="Avatar"],
    [class*="avatar"],[class*="Header"],[class*="UserName"],[class*="Profile"]{visibility:hidden !important}"""

    async def _diag(self, sc, reason, title, body):
        """A logged-in page with no video: what it showed (reason, captcha / login / empty signs, video links), and a
        screenshot with the header, avatars and names hidden and the top band blacked out (admin only, never public;
        no cookie or account name is kept)."""
        site, page = sc.site, sc.page
        try:
            n = await page.evaluate("() => document.querySelectorAll('a[href*=\"/video/\"]').length")
        except Exception:
            n = None
        b = (body or "").lower()
        self.diag[site] = {"t": round(time.time()), "reason": reason, "path": urllib.parse.urlsplit(page.url).path[:80],
                           "title": title[:80] if display_ok(title) else "", "video_links": n,
                           "captcha": bool(re.search(r"captcha|verify|slider|puzzle|not a robot", b)),
                           "login_prompt": bool(re.search(r"log in|sign up|continue with", b)),
                           "chars": len(body or "")}
        try:
            await page.add_style_tag(content=self.DIAG_MASK)
            await page.evaluate("""() => { const d = document.createElement('div');
                d.style.cssText = 'position:fixed;left:0;top:0;right:0;height:72px;background:#000;z-index:2147483647';
                document.body.appendChild(d); }""")
            self.diag_shot[site] = await page.screenshot(type="jpeg", quality=60)
        except Exception:
            pass
        print(f"browse: {site} logged in but no video ({reason}; video links {n})", flush=True)

    async def _site_search(self, sc, q, why):
        """Type `q` into the page's own search box and press Enter. The field is re-checked right before typing,
        in this process (search_field_ok); any other field is refused and nothing is typed."""
        page = sc.page
        fields = [f for f in await page.evaluate(FIELDS_JS) if search_field_ok(f)]
        if not fields:
            self.last_skip = "no search box"
            return False
        f = fields[0]
        box = page.locator(f'[data-sub01-field="{int(f["i"])}"]').first
        again = await box.evaluate(FIELD_JS)                     # the element itself, just before typing
        if not search_field_ok(again):                             # changed under us: type nothing
            self.last_skip = "not a search box"
            return False
        host = urllib.parse.urlsplit(page.url).hostname or ""
        target = self.site_search_url(page.url, again, q)
        if target and not await self.robots.check(target, lambda u: self._fetch(sc, u), self.limits):
            self.last_skip = "robots.txt"                           # the site asks robots not to search: type nothing
            print(f"browse: site_search on {host} refused by robots.txt", flush=True)
            return False
        field = " ".join(x for x in (again.get("type") or "text", again.get("name"), again.get("placeholder"))
                         if x)[:60]
        self.typed = (self.typed + [{"t": time.time(), "device": sc.name, "host": host.removeprefix("www."),
                                     "field": field, "query": q}])[-100:]
        print(f"browse: site_search on {host} (input {field!r}): {q!r}", flush=True)
        await box.fill(q)
        try:
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=SITE_SEARCH_NAV_MS):
                await box.press("Enter")                           # Enter only: no other button is pressed
        except Exception:                                          # results shown in place (no navigation)
            pass
        return await self._settle(sc, why, "page", min_text=80, revisit=True)    # its own results page

    @staticmethod
    def site_search_url(page_url, f, q):
        """The URL a site search box would load (its GET form's action + ?name=q), for the robots.txt check; None
        on a page that is not on the web (local test pages)."""
        if not str(page_url).startswith(("http://", "https://")):
            return None
        action = urllib.parse.urljoin(page_url, f.get("form_action") or page_url) if f.get("form") else page_url
        u = urllib.parse.urlsplit(action)
        query = urllib.parse.urlencode({f["name"]: q}) if f.get("name") else u.query
        return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path or "/", query, ""))

    async def _fetch(self, sc, url, hops=3, headers=None):
        """GET outside the page (robots.txt, a search source's JSON API), with the browser's guard: public http(s)
        hosts only, every redirect checked again. -> (status, text); (0, "") when refused or failed."""
        for _ in range(hops + 1):
            u = urllib.parse.urlsplit(url)
            if not url_ok(url) or not await self.guard.resolves_public(u.hostname or ""):
                return 0, ""
            ctx = sc.public[0] if getattr(sc, "public", None) else sc.ctx    # never a logged-in context (#60)
            try:
                r = await ctx.request.get(url, timeout=NAV_TIMEOUT_MS, max_redirects=0, fail_on_status_code=False,
                                          headers=headers or None)
            except Exception as e:
                print(f"browse: could not fetch {url[:80]}: {repr(e)[:100]}", flush=True)
                return 0, ""
            if r.status in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = urllib.parse.urljoin(url, r.headers["location"])
                continue
            text = (await r.text())[:2_000_000] if r.status == 200 else ""
            return r.status, text
        return 0, ""

    async def _play_muted(self, sc):
        """A video page: start its first video muted (Chromium also runs with --mute-audio). The <video> state, or
        None when the page has no video element."""
        try:
            return await sc.page.evaluate(VIDEO_JS, "play")
        except Exception:
            return None

    async def _start_watch(self, sc, watch_s=None):
        """He watches the video for a bounded time (MIN_WATCH_S..MAX_WATCH_S real seconds); then the brain decides."""
        try:
            w = float(watch_s)
        except (TypeError, ValueError):
            w = 120.0
        w = min(MAX_WATCH_S, max(MIN_WATCH_S, w if w == w else 120.0))
        if sc.mode == "shorts":
            w = SV.watch_seconds(w)                             # a short, then the next one
        sc.watch_s, sc.watch_until, sc.scene, sc.scrolls_left = w, time.time() + w, 0.0, 0
        sc.next_at = time.time() + VIDEO_SHOT_S
        if sc.info:
            sc.info = dict(sc.info, video={"watching": True, "seconds": round(w), "left_s": round(w), "scene": 0.0,
                                           "muted": True, "channel": sc.info.get("channel", "")})

    async def _watch(self, sc):
        """One screenshot while watching: the video is muted again, the scene change measured. False if the page
        turned into a bot check, or the embed player into an error (then it is left)."""
        state = await sc.page.evaluate(VIDEO_JS, None)
        err = await self._embed_error(sc, state, wait=False) if sc.info and sc.info.get("embed") else None
        if err and "advertisement" in err.lower():              # B6: an ad mid-watch is not the video's fault: no
            sc.watch_until += VIDEO_SHOT_S                      # strike, not left; the watch timer waits for it
            err = None
        if err:
            self.yt.refused(sc.info["url"], sc.info.get("channel"))
            sc.watch_until = 0.0
            await self._leave(sc)
            return False
        prev = sc.shot
        if not await self._shoot(sc):
            sc.watch_until = 0.0
            return False
        sc.scene = scene_change(prev, sc.shot)
        v = dict(sc.info.get("video") or {})
        v.update(watching=True, left_s=max(0, round(sc.watch_until - time.time())), scene=sc.scene,
                 muted=bool(state is None or state.get("muted")), playing=bool(state and not state.get("paused")))
        sc.info = dict(sc.info, video=v)
        return True

    async def _end_watch(self, sc):
        """Time is up: the video is paused and the brain decides what next (the page goes back to the vote)."""
        sc.watch_until, sc.scene = 0.0, 0.0
        try:
            await sc.page.evaluate(VIDEO_JS, "pause")
        except Exception:
            pass
        if sc.info and sc.info.get("video"):
            mins = round(sc.watch_s / 60, 1)
            sc.info = dict(sc.info, video=dict(sc.info["video"], watching=False, left_s=0, scene=0.0),
                           why=f"watched for {mins:g} min (muted); deciding again")
        if sc.mode == "shorts" and sc.queue and not self.new_share_ok(sc):
            sc.queue = []                                       # #89: >= 60 % new topics per scroll session
            if sc.info:
                sc.info = dict(sc.info, kind="left", why="watched a short; next, something new")
        if sc.mode == "shorts" and sc.info and sc.queue:      # the next shorts are the options (no paid call)
            sc.info = dict(sc.info, kind="search", results=sc.queue[:SS.MAX_RESULTS],
                           why=f"watched a short for {round(sc.watch_s)} s (muted); the next one?")

    YT_SEARCH_SHARE = 0.45                                     # searches that go to YouTube when the key is set
    TRIES = 4                                                  # sources tried per search (#89: no Wikipedia fallback)

    async def _search(self, sc, q, why="", origin=""):
        """Search on the source that fits the query (search_sources.route: topic, rotation, per-host limits, robots,
        sources blocked after repeated failures left out), trying up to TRIES working sources; when none gives
        results, a seed site's front page instead (rotating), never the same Wikipedia search again (#89).
        - a follow-up on something he saw beyond FOLLOW_MAX of recent searches becomes a discovery pick;
        - a search with a video word (tiktok, shorts, videos...) goes to the short-video feed on the phone and to the
          video sources at the desk, never to Wikipedia.
        `why` ends the card's line ("searched arXiv for “sleep spindles” — from his reading notes")."""
        again = origin not in ("chat", "interests") and self.variety.query_used(q)    # #89: the same search twice a day (the HN loop)
        if again or (origin in NV.SEEN_ORIGINS and not self.visited.follow_ok()):
            p = I.pick(self.variety, hour=I.tokyo_hour(), rng=self.rng, discover=True, hungry=self.hungry)
            if p.get("query"):
                q, origin = p["query"], "interests"
                why = f"{SS.ORIGINS['interests']} ({p['topic']}, something new)"
        else:
            self.variety.mark(None, q)
        self.visited.search(origin)
        vq = NV.video_query(q)
        if vq is not None:
            return await self._video_search(sc, vq, q, why, origin)
        if YT.key() and self.rng.random() < self.YT_SEARCH_SHARE:
            # #89 live 2026-10-04: with the key, YouTube is a real search engine for him (its official API): a good
            # share of his searches are YouTube searches, played in the official embed
            if await self._public_videos(sc, "shorts" if sc.name == "phone" else "youtube", q, why, origin,
                                         short=sc.name == "phone"):
                return True
        for name in SS.route(q, self.limits, self.rng, video=sc.mode == "video", wiki_share=self.variety.wiki_share(),
                             hungry=self.hungry)[:self.TRIES]:
            if await self._search_on(sc, name, q, why, origin):
                if not self.decide and sc.info.get("results"):  # brain decides: it picks among the results itself
                    res = [r for r in sc.info["results"] if self.fresh(r["url"], r["title"])]
                    if res:
                        r = res[min(len(res) - 1, int(self.rng.random() ** 2 * 4))]    # mostly the top results
                        sc.pending_link = (r["url"], f"searched “{q[:40]}”, opened “{r['title'][:50]}”")
                return True
        topic = I.topic_of(q or "")
        # no fitting site answered: the query becomes a YouTube search (the API with the key, else the topic's
        # channels), never a news site's search page
        if await self._public_videos(sc, "shorts" if sc.name == "phone" else "youtube", q, why, origin,
                                     short=sc.name == "phone"):
            return True
        # else a site about it, or nothing: never one about something else (live 2026-10-08: "Mark Rober" -> a Tokyo
        # guide, "ramen in Osaka" -> a games site, "Day Deals" -> a music magazine)
        if not topic or not SEED_TOPICS.get(topic):
            self.last_skip = f"no search for “{q[:40]}” and no site about it"
            return False
        return await self._seed(sc, f"no search for “{q[:40]}”, opened a site about it instead", topic, self.hungry,
                                only_topic=True)

    async def _video_search(self, sc, vq, q, why, origin):
        """A search asking for videos: the phone's short-video feed, or a video source at the desk."""
        topic = vq or None
        if sc.name == "phone":
            return await self._shorts(sc, {"query": topic, "from": origin}, force=True)
        return await self._public_videos(sc, "youtube", topic or q, why, origin, short=False)

    async def _search_on(self, sc, name, q, why, origin):
        """One search on one source: robots.txt and the per-host limit first, then its results page (or its JSON API
        plus the page for the screen, or its home page's own search box); results parsed and guarded. True when a
        results page with at least one safe result is on the screen."""
        src = SS.SOURCES[name]
        label = src["label"]
        line = f"searched {label} for “{q[:50]}”" + (f" — {why}" if why else "")
        fetch = lambda u: self._fetch(sc, u)                       # noqa: E731
        if src.get("site"):                                     # the site's own search box (#40's rules)
            host = SS.host_of(name)
            if not self.limits.allow(host):
                self.limits.refuse(name, "rate limit")
                return False
            self.limits.note(host)
            if not await self._open(sc, src["site"], line, "page", shoot=False, revisit=True):
                self.limits.refuse(name, self.last_skip or "did not load")
                return False
            self.limits.note(host)
            if not await self._site_search(sc, q, line):
                self.limits.refuse(name, self.last_skip or "site search failed")
                return False
            results = src["parse"](await sc.page.content(), sc.page.url)
            shown = True                                        # _site_search's page is on the screen already
        else:
            shown = False
            url = src["url"](q)
            api = src["api"](q) if src.get("api") else None
            for u in filter(None, (url, api)):
                if not await self.robots.check(u, fetch, self.limits):
                    self.limits.refuse(name, "robots.txt")
                    self.last_skip = "robots.txt"
                    return False
            hosts = {urllib.parse.urlsplit(u).hostname for u in filter(None, (url, api))}
            if not all(self.limits.allow(h) for h in hosts):
                self.limits.refuse(name, "rate limit")
                return False
            results = []
            if api:                                             # results from the public JSON API (not shown)
                self.limits.note(urllib.parse.urlsplit(api).hostname)
                status, text = await fetch(api)
                results = src["parse"](text, api) if status == 200 else []
                if not self.safe_results(results):
                    self.limits.refuse(name, "no results")
                    return False
            self.limits.note(urllib.parse.urlsplit(url).hostname)
            if not await self._open(sc, url, line, "search", title=f"{q} — {label}", min_text=0, shoot=False):
                self.limits.refuse(name, self.last_skip or "did not load")
                return False
            if not api:
                results = src["parse"](await sc.page.content(), sc.page.url)
        safe = self.safe_results(results)
        if not safe and sc.site:                                # logged in and still no video: say what it showed
            body = await sc.page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 20000)")
            await self._diag(sc, "no video links", await sc.page.title(), body)
        if not safe:
            self.limits.refuse(name, "no results")
            self.last_skip = "no results"
            await self._leave(sc)
            return False
        sc.info = dict(sc.info, kind="search", title=f"{q} — {label}"[:140], results=safe[:SS.MAX_RESULTS],
                       search={"source": name, "engine": label, "query": q, "from": SS.ORIGINS.get(origin, "")},
                       search_box=False)
        sc.scrolls_left = 0
        if not shown and not await self.show(sc):
            return False
        if self.log and self.log[-1].get("url") == sc.info["url"]:   # the visit log says where and what he searched
            self.log[-1] = dict(self.log[-1], title=sc.info["title"], search=sc.info["search"])
        self.limits.count(name, q, origin)
        return True

    async def _links(self, sc, selector):
        found = await sc.page.evaluate("""sel => [...document.querySelectorAll(sel)]
            .map(a => [a.href, (a.innerText || '').trim()]).filter(x => x[0].startsWith('http'))""", selector)
        return [(u, " ".join(t.split()[:12])) for u, t in found if url_ok(u) and not BAD_WORDS.search(t)]

    async def _pick_link(self, sc, interest):
        links = await sc.page.evaluate("""() => [...document.querySelectorAll('a[href]')].map(a => {
            const r = a.getBoundingClientRect(); return [a.href, (a.innerText || a.title || '').trim().slice(0, 120), r.width * r.height]; })""")
        want = set(words(interest or "")) | set(words(sc.info.get("title", "")))
        cur = urllib.parse.urlsplit(sc.page.url)
        cand = []
        for href, text, area in links:
            text = " ".join(str(text or "").split())
            if len(text) < 12 or not self.link_ok(href, text, sc.page.url):   # S9: the same guard as pick_links
                continue
            u = urllib.parse.urlsplit(href)
            if (u.netloc, u.path) == (cur.netloc, cur.path):
                continue
            score = 1 + 3 * len(want & set(words(text))) + (0.5 if u.netloc != cur.netloc else 0) + min(1, area / 20000)
            cand.append((score * (0.5 + self.rng.random()), href, text))
        cand.sort(reverse=True)
        return (cand[0][1], cand[0][2]) if cand else None

    async def _open(self, sc, url, why, kind, title=None, min_text=80, shoot=True, revisit=False, referer=None):
        """Load a page; if the guard rejects it, leave it (blank) so nothing of it is shown, scrolled or followed.
        A page (not a results page) opened in the last 7 days is not opened again (#89) unless `revisit` (a seed
        site's front page, a YouTube results page, going back)."""
        if not url_ok(url) or VO.private_url(url):
            return False
        vid, yt_page = YT.page_video(url)
        if yt_page:                                             # #89 live: YouTube's own pages are never opened
            if vid:
                return await self._play_video_id(sc, vid, why, title, short="/shorts/" in url)
            self.last_skip = "a YouTube page (never opened; only its embed player)"
            return False
        if not revisit and kind != "search" and not self.fresh(url):
            self.last_skip = "opened in the last 7 days"
            return False
        if self.heavy.heavy_url(url) or self.heavy.cooling(urllib.parse.urlsplit(url).hostname):
            self.last_skip = "too heavy on memory (left alone for a while)"   # #89: it blew Chromium's cap before
            return False
        if app_wall(url):
            self.last_skip = "a messaging or app page (a wall, not a page)"
            return False
        host_now = (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")
        if self.walled.get(host_now, 0) > time.time():
            self.last_skip = "bot check on this site (left alone for a while)"   # #89: never solved or waited out
            return False
        if kind != "search" and not self.host_ok(urllib.parse.urlsplit(url).hostname):
            self.last_skip = "enough of this site today"            # #89 teen: per-site daily cap
            return False
        if getattr(sc, "public", None) and not await self.robots.check(url, lambda u: self._fetch(sc, u), self.limits):
            self.last_skip = "robots.txt"                               # every page, not only searches
            return False
        if self._session(url) and not VO.link_ok(url):          # #60: re-checked just before it is opened
            self.last_skip = "action"
            return False
        await self._use(sc, url)
        page = sc.page
        self.login_redirect = None
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS, referer=referer)
        except Exception as e:
            if sc.site and self.login_redirect == sc.site:
                await self._logout(sc, "sent to log in")
                self.last_skip = "logged out"
                return await self._leave(sc)
            if "Timeout" not in repr(e):
                print(f"browse: could not open {url[:80]}: {repr(e)[:100]}", flush=True)
                self.last_skip = "did not load"
                return await self._leave(sc)
            resp = None
        status = getattr(resp, "status", None)
        if isinstance(status, int) and status >= 400:              # S9: an error page is never shown or logged
            print(f"browse: skipped {urllib.parse.urlsplit(url).hostname} (HTTP {status})", flush=True)
            self.last_skip = "error page"
            if status in (403, 429, 503) and kind != "search":     # refused / rate-limited: the site is left alone
                self._cool(url, OVERLAY_COOLDOWN_S)
            return await self._leave(sc)
        return await self._settle(sc, why, kind, title, min_text, shoot, revisit)

    async def _settle(self, sc, why, kind, title=None, min_text=80, shoot=True, revisit=False):
        """A page has loaded: banners away, then the guard, bot walls and sign-in walls; then shown."""
        page = sc.page
        await page.wait_for_timeout(1800)
        if not url_ok(page.url):                                       # redirected somewhere it must not be
            self.last_skip = "did not load" if page.url.startswith("chrome-error:") else "guard"
            return await self._leave(sc)
        over = await self._overlay_walled(page)                        # before any banner is pressed or hidden:
        if not over:                                                   # an ad-block / paywall modal is never closed
            await self._dismiss(sc)
        await page.add_style_tag(content=HIDE_BANNERS)
        await page.evaluate(UNBLOCK_JS)
        if not url_ok(page.url):
            return await self._leave(sc)
        if sc.site:                                                    # #60: logged in
            s = self.sessions.get(sc.site)
            if s is not None and s.looks_signed_out(await page.evaluate(SE.SIGNED_OUT_JS,
                                                                         SE.SIGNED_OUT_SELECTORS[sc.site])):
                await self._logout(sc, "signed out")
                self.last_skip = "logged out"
                return await self._leave(sc)
        page_title = (await page.title() or "").strip()
        body = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 20000)")
        video = is_video_host(urllib.parse.urlsplit(page.url).hostname or "")
        # S9 guard parity: a loaded page's title passes the same title rule as the links and results that lead to
        # pages (title_ok; a video page's title is checked by the video rule below), money hype at the top of the
        # body goes, and a trading page (host, title or a terminal-like body: S2) is never shown
        reason = ("guard" if not text_ok(page_title, body, media=video) else "empty" if len(body.strip()) < min_text
                  else "error page" if error_page(page_title, body)
                  else "bot wall" if challenge_title(page_title, page.url) or await self._walled(page, body)
                  else "overlay wall" if over or overlay_wall(body) or await self._overlay_walled(page)
                  else "sign-in wall" if LOGIN_HREF.search(urllib.parse.urlsplit(page.url).path + "?")
                  or await self._login_walled(page, body)
                  else "guard" if (not video and not title_ok(page_title)) or MONEY_HYPE.search(body[:2000])
                  or is_finance(page.url, "" if video else page_title, body) else None)
        if reason and sc.site:                                         # why a logged-in feed shows nothing
            await self._diag(sc, reason, page_title, body)
        if reason == "sign-in wall" and sc.site:                       # #60: the session no longer works
            await self._logout(sc, "login wall")
        if not reason and sc.site and not video_text_ok(re.sub(r"\s*[-|]\s*(YouTube|TikTok)$", "", page_title)):
            reason = "guard"                                           # captions, hashtags, creators (#56 guard)
        if not reason and not revisit and kind != "search" and not self.fresh(page.url, title or page_title):
            reason = "opened in the last 7 days"                       # redirected to, or the same page renamed
        if reason:
            print(f"browse: skipped {urllib.parse.urlsplit(page.url).hostname} ({reason}: {page_title[:40]!r})", flush=True)
            self.last_skip = reason
            if reason in ("bot wall", "overlay wall") and kind != "search":   # #89: left alone a while
                self._cool(page.url, WALL_COOLDOWN_S if reason == "bot wall" else OVERLAY_COOLDOWN_S)
            return await self._leave(sc)
        host = urllib.parse.urlsplit(page.url).hostname or ""
        channel = ""
        if await SV.settle(page, host, page_title):                    # TikTok: boxes hidden, caption guarded
            print(f"browse: skipped a TikTok page ({host}): caption refused", flush=True)
            self.last_skip = "guard"
            return await self._leave(sc)
        if is_youtube(host):                                           # titles and channels: guard + chat filter
            await page.add_style_tag(content=HIDE_YOUTUBE)             # no comments, live chat or buttons on screen
            channel = (await page.evaluate(CHANNEL_JS) or "").strip()
            name = re.sub(r"\s*-\s*YouTube$", "", page_title)
            if not video_text_ok(name):
                print(f"browse: skipped a video ({host}): title refused", flush=True)
                self.last_skip = "guard"
                return await self._leave(sc)
            if channel and not video_text_ok(channel):
                channel = ""
        why = why.replace("opened “”", f"opened {host.removeprefix('www.')}")
        if not why_ok(why):                                            # S9: the card's line passes the title rule too
            why = "browsing"
        sc.info = {"title": (title or page_title or host)[:140], "url": page.url, "host": host.removeprefix("www."),
                   "why": why, "t": time.time(), "kind": kind,
                   "search_box": kind == "page" and await self._has_search_box(page)}
        if channel:
            sc.info["channel"] = channel[:80]
        sc.scrolls_left = self.rng.randint(*SCROLLS) if kind == "page" else 0
        if shoot and not await self.show(sc):
            return False
        return True

    async def _has_search_box(self, page):
        try:
            return any(search_field_ok(f) for f in await page.evaluate(FIELDS_JS))
        except Exception:
            return False

    async def _login_walled(self, page, body):
        """A sign-in / sign-up wall: a visible password field or a 'log in to continue' prompt on a short page."""
        if len(body.strip()) >= LOGIN_WALL_MAX_CHARS:
            return False
        if LOGIN_WALL.search(body):
            return True
        return await page.evaluate("""() => [...document.querySelectorAll('input[type=password]')].some(el => {
            const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
            return r.width > 20 && r.height > 8 && cs.visibility !== 'hidden' && cs.display !== 'none'; })""")

    async def _dismiss(self, sc, rounds=2):
        """Cookie / consent banners: press reject or "necessary only"; modals: press close (choose_dismiss). Never an
        accept button; with nothing safe to press the banner is only hidden (UNBLOCK_JS)."""
        page = sc.page
        host = (urllib.parse.urlsplit(page.url).hostname or "").removeprefix("www.")
        for _ in range(rounds):
            pressed = False
            for frame in list(page.frames):
                if frame != page.main_frame and not url_ok(frame.url):
                    continue
                if YOUTUBE_HOST.search(urllib.parse.urlsplit(frame.url).hostname or ""):
                    continue                                    # #89: never press anything in YouTube's player (its ad "Skip")
                try:
                    buttons = await frame.evaluate(BUTTONS_JS)
                    k = choose_dismiss(buttons)
                    if k is None:
                        continue
                    b = next(x for x in buttons if x["i"] == k)
                    if sc.site and VO.action_target(label=b.get("label") or b.get("aria") or ""):
                        continue                                # #60: logged in, never an action button
                    await frame.evaluate("i => { const el = document.querySelector(`[data-sub01-btn=\"${i}\"]`); "
                                         "if (el) el.click(); }", k)
                except Exception:
                    continue
                kind = "reject" if b.get("consent") and REJECT_BUTTON.search(b.get("label") or "") else "close"
                self.dismissed = (self.dismissed + [{"t": time.time(), "host": host, "label": (b.get("label") or
                                                     b.get("aria") or "")[:40], "kind": kind}])[-100:]
                print(f"browse: {kind} banner on {host}: {(b.get('label') or b.get('aria') or '')[:40]!r}", flush=True)
                pressed = True
                await page.wait_for_timeout(700)
                break
            if not pressed:
                return

    @staticmethod
    def wall_text(body):
        n = len(body.strip())
        return (n < WALL_MAX_CHARS and bool(BODY_WALL.search(body))
                or n < GEO_WALL_MAX_CHARS and bool(GEO_WALL.search(body)))

    async def _walled(self, page, body=None):
        """A bot check (CAPTCHA, 'unusual traffic', browser challenge) or a geo-block fills the page."""
        if body is None:
            body = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 20000)")
        if self.wall_text(body):
            return True
        if len(body.strip()) >= WALL_MAX_CHARS:
            return False
        return await page.evaluate(WALL_FRAMES)

    async def show(self, sc):
        """Screenshot the current page and log the visit (only pages that passed the guard get here).
        False when the page turned out to be a bot check (then nothing is shown or logged)."""
        if not await self._shoot(sc):
            return False
        i = sc.info
        self.log = (self.log + [{"t": i["t"], "device": sc.name, "title": i["title"], "url": i["url"], "host": i["host"],
                                 "why": i["why"]}])[-KEEP:]
        if i.get("kind") != "search" and i["url"] not in SEEDS:
            self.visited.add(i["url"], i["title"])                     # #89: not opened again for 7 days
            if getattr(sc, "mode", None) == "shorts" and (i.get("card") or VIDEO_LINK.search(i["url"])):
                self._clip(sc)
            if i.get("embed") or VIDEO_LINK.search(i["url"]):
                self.watched = True
            if sc.name == "desk":
                self._desk_run(i)
        if not sc.history or sc.history[-1] != i["url"]:
            sc.history = (sc.history + [i["url"]])[-20:]
            sc.chain += 1
            topic = self.variety.note(i["title"], (i.get("search") or {}).get("query", ""), i["host"])
            sc.info = dict(i, topic=topic)
            self.log[-1]["topic"] = topic
        return True

    def _video_break(self, device, mode):
        """#89: during the break after VIDEO_RUN_MAX desk videos the desk browses (a page or a search) instead."""
        return None if mode == "video" and device == "desk" and time.time() < self.video_break_until else mode

    def _desk_run(self, i):
        """#89: count the desk's videos in a row (and their channels / guests); a page resets the run."""
        if i.get("embed") or VIDEO_LINK.search(i["url"]):
            self.desk_videos = (self.desk_videos + [video_keys(i.get("title"), i.get("channel"))])[-10:]
            self.video_run += 1
            if self.video_run >= VIDEO_RUN_MAX:
                self.video_run, self.video_break_until = 0, time.time() + VIDEO_BREAK_S
        else:
            self.video_run = 0

    NEW_MIN = 0.6                                              # #89: new topics per scroll session, at least
    SESSION_GAP_S = 300                                        # clips further apart start a new scroll session

    def _clip(self, sc):
        """A short was shown: counted in the scroll session, as new when it is the first of a topic not seen in 2 h."""
        now = time.time()
        if now - sc.sess[0] > self.SESSION_GAP_S:
            sc.sess = [now, 0, 0]
        sc.sess = [now, sc.sess[1] + 1, sc.sess[2] + (1 if sc.feed_fresh else 0)]
        sc.feed_fresh = False

    def new_share_ok(self, sc):
        """Another clip on the current topic keeps new topics at NEW_MIN of this scroll session."""
        t, n, new = sc.sess
        if sc.feed_fresh or time.time() - t > self.SESSION_GAP_S:
            return True                                         # the next clip is the first of a new topic
        return new / (n + 1) >= self.NEW_MIN

    def session_stats(self, sc):
        t, n, new = sc.sess
        return {"clips": n, "new_topics": new, "new_share": round(new / n, 2) if n else None}

    async def _leave(self, sc):
        sc.scrolls_left = 0
        if sc.info:
            sc.info = dict(sc.info, kind="left")                       # nothing on it is followed or scrolled
        try:
            await sc.page.goto("about:blank")
        except Exception:
            pass
        return False

    async def _private_ok(self, sc):
        """#60: nothing private reaches the screen (the URL, then the DOM), and on a logged-in site the account's
        avatar, name and action buttons are hidden just before the screenshot. False: the page was left."""
        page = sc.page
        why = VO.private_url(page.url)
        if not why and sc.site:
            why = VO.private_dom(await page.evaluate(VO.PRIVATE_DOM_JS, VO.PRIVATE_SELECTORS))
        if why:
            print(f"browse: left {urllib.parse.urlsplit(page.url).hostname} (private page: {why})", flush=True)
            self.last_skip = "private"
            await self._leave(sc)
            return False
        if sc.site:
            await page.evaluate(VO.ADD_STYLE_JS, VO.HIDE_ACCOUNT_CSS)   # once per document, also after SPA moves
            await page.evaluate(VO.HIDE_ACCOUNT_JS)
        return True

    async def _overlay_walled(self, page):
        """#89: an ad-block or paywall overlay on the page: in its text (start and end), a dialog or fixed box (also in
        a shadow root), or a child frame (a script-written or same-site one; cross-site frames are not loaded)."""
        texts = []
        for frame in [None] + [f for f in list(getattr(page, "frames", None) or []) if f is not page.main_frame]:
            if frame is not None:
                fu = getattr(frame, "url", "") or ""
                if YOUTUBE_HOST.search(urllib.parse.urlsplit(fu).hostname or "") or SV.is_tiktok(
                        urllib.parse.urlsplit(fu).hostname or ""):
                    continue                                            # the players' frames: not overlays
            try:
                texts.append(await asyncio.wait_for((frame or page).evaluate(OVERLAY_TEXT_JS), 3))
            except Exception:                                           # a detached or slow frame
                continue
            if len(texts) > 8:
                break
        return any(overlay_wall(t) for t in texts if isinstance(t, str))

    def _cool(self, url, seconds):
        """#89: a site that showed a bot check or an overlay wall is not opened again for `seconds`."""
        h = (urllib.parse.urlsplit(url or "").hostname or "").lower().removeprefix("www.")
        if h and not YOUTUBE_HOST.search(h) and not SV.is_tiktok(h):    # the players have their own pause
            self.walled[h] = max(self.walled.get(h, 0.0), time.time() + seconds)
            self.walled = dict(sorted(self.walled.items(), key=lambda kv: kv[1])[-200:])

    async def _shoot(self, sc):
        if await self._walled(sc.page):                                 # a page can turn into a bot check later
            print(f"browse: left {urllib.parse.urlsplit(sc.page.url).hostname} (bot wall)", flush=True)
            await self._leave(sc)
            return False
        if await self._overlay_walled(sc.page):                         # ... or get an ad-block / paywall overlay
            print(f"browse: left {urllib.parse.urlsplit(sc.page.url).hostname} (overlay wall)", flush=True)
            self.last_skip = "overlay wall"
            self._cool(sc.page.url, OVERLAY_COOLDOWN_S)
            await self._leave(sc)
            return False
        if not await self._private_ok(sc):
            return False
        sc.shot = await sc.page.screenshot(type="jpeg", quality=72 if sc.name == "desk" else 68)
        sc.shot_id += 1
        return True
