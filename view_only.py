"""View-only rules for his logged-in TikTok and YouTube (#60). Pure checks, used by the browser process.

1. Private pages never reach a public screen (`private_url`, `private_dom`): settings, inbox, messages, notifications,
   account, profile edit, studio, analytics, upload, billing, watch history and the like. Checked on the URL before
   a page is opened and on the DOM before it is shown. The account's own public profile page is fine.
2. No action is ever clicked or offered (`action_target`, `safe_links`): like, follow, subscribe, comment, share, DM,
   upload, live, gift, buy, save, report... by role, label, test id and URL. Links that fail are removed before the
   eyes list options, so the brain vote never sees them; a click is re-checked just before it is made.
3. The logged-in avatar, name and the action buttons are hidden before every screenshot (`HIDE_ACCOUNT_CSS`,
   `HIDE_ACCOUNT_JS`).
"""
import re
import urllib.parse

from sessions import host_in

# --- 1. private pages ---------------------------------------------------------------------------------------------
# hosts that are private as a whole (accounts, studios, payments)
PRIVATE_HOSTS = ("studio.youtube.com", "accounts.google.com", "myaccount.google.com", "myactivity.google.com",
                 "pay.google.com", "payments.google.com", "takeout.google.com", "seller.tiktok.com",
                 "ads.tiktok.com", "business.tiktok.com", "affiliate.tiktok.com", "shop.tiktok.com",
                 "seller-us.tiktok.com", "partner.tiktokshop.com", "effecthouse.tiktok.com")
# paths on tiktok.com that show private or account pages, or lead to an action
TIKTOK_PRIVATE = re.compile(
    r"^/(messages?|inbox|notifications?|activity|setting(s)?|upload|tiktokstudio|creator(-center|-tools)?|studio|"
    r"analytics|coin(s)?|wallet|recharge|balance|payment(s)?|billing|order(s)?|shop|live|logout|passport|login|"
    r"signup|account|business-suite|ads|promote|favorites?|collection|liked?|saved|downloads?|privacy|"
    r"safety-center|feedback|report|transparency/request|qr)(/|$|\?)", re.I)
# paths on youtube.com
YOUTUBE_PRIVATE = re.compile(
    r"^/(account(_\w+)?|feed/(history|you|library|playlists|downloads|purchases|clips|storefront)|upload|"
    r"paid_memberships|purchases|premium|musicpremium|red|channel_switcher|create_channel|signin|logout|"
    r"notifications?|reporthistory|my_videos|my_live_events|live_dashboard|studio|analytics|"
    r"ServiceLogin|verify|copyright_complaint_form)(/|$|\?)", re.I)
# private playlists: Watch Later, Liked videos, Liked music
PRIVATE_LIST = re.compile(r"(^|&)list=(WL|LL|LM)(&|$)")
# words in the URL's query that open a private overlay on an otherwise public page
PRIVATE_QUERY = re.compile(r"(^|&)(edit|edit_profile|settings|inbox|messages|lang_setting|upload)=", re.I)


def private_url(url):
    """Why this URL is private ('host', 'path', 'playlist', 'query'), or None if it may be shown."""
    try:
        u = urllib.parse.urlsplit(url or "")
    except ValueError:
        return "unparsable"
    host = (u.hostname or "").lower()
    if host_in(host, PRIVATE_HOSTS):
        return "host"
    path = u.path or "/"
    if host_in(host, ("tiktok.com",)):
        if TIKTOK_PRIVATE.search(path) or re.match(r"^/@[^/]+/(edit|settings|analytics|liked?|favorites?)", path, re.I):
            return "path"
    elif host_in(host, ("youtube.com", "youtu.be")):
        if YOUTUBE_PRIVATE.search(path):
            return "path"
        if path.startswith(("/playlist", "/watch")) and PRIVATE_LIST.search(u.query):
            return "playlist"
    else:
        return None
    if PRIVATE_QUERY.search(u.query):
        return "query"
    return None


# DOM: elements that only exist on private pages, and page headings that name one
PRIVATE_SELECTORS = [
    # YouTube (desktop + mobile): the browse pages of history, "You", library, playlists, purchases; account settings
    'ytd-browse[page-subtype="history"]', 'ytd-browse[page-subtype="you"]', 'ytd-browse[page-subtype="library"]',
    'ytd-browse[page-subtype="playlists"]', 'ytd-browse[page-subtype="purchases"]', 'ytd-account-settings',
    'ytm-account-header-renderer',
    # TikTok: inbox, chat, profile edit, settings, upload
    '[data-e2e="inbox-list"]', '[data-e2e="inbox-notifications"]', '[data-e2e="chat-list-item"]',
    '[data-e2e="message-input-area"]', '[data-e2e="edit-profile-popup"]', '[data-e2e="setting-container"]',
    '[data-e2e="upload-container"]',
    # anywhere: a password or payment field means an account page
    'input[type="password"]', 'input[autocomplete^="cc-"]',
]
PRIVATE_HEADING = re.compile(
    r"^\s*(settings|account settings|manage (your )?account|edit profile|inbox|messages?|direct messages|"
    r"notifications?|activity|watch history|history|your (data|videos|channel|account|clips|movies|purchases)|"
    r"watch later|liked videos|library|you|privacy|security|payments?|billing|purchases|memberships|"
    r"wallet|coins|recharge|balance|creator (center|tools)|tiktok studio|youtube studio|analytics|upload( video)?|"
    r"switch account|sign in|log in)\s*$", re.I)
# JS for page.evaluate(PRIVATE_DOM_JS, PRIVATE_SELECTORS) -> {"selectors": [...], "headings": [...]}
PRIVATE_DOM_JS = """sels => ({
  selectors: sels.filter(s => { try { return !!document.querySelector(s); } catch (e) { return false; } }),
  headings: [...document.querySelectorAll('h1, h2, [role="heading"][aria-level="1"], title')]
            .map(h => (h.innerText || h.textContent || '').trim().slice(0, 80)).filter(Boolean).slice(0, 12)})"""


def private_dom(found):
    """Why the page is private from PRIVATE_DOM_JS's result, or None."""
    found = found or {}
    hit = [s for s in found.get("selectors") or () if s in PRIVATE_SELECTORS]
    if hit:
        return "dom:" + hit[0]
    for h in found.get("headings") or ():
        # "Settings - YouTube", "Messages | TikTok": the part before the site name
        head = re.split(r"\s+[-|–·]\s+", h)[0]
        if PRIVATE_HEADING.match(head):
            return "heading"
    return None


# --- 2. actions: never clicked, never offered ------------------------------------------------------------------------
ACTION_LABEL = re.compile(
    r"\b(un)?(like[ds]?|dislike[ds]?|love|heart|follow(ing|ed|s)?|subscribe[ds]?|subscription|join|"
    r"comment(s|ing)?|reply|replies|post|repost(ed)?|share[ds]?|send|message|dm|chat|upload|create|go live|"
    r"live ?stream(ing)?|gifts?|coins?|recharge|tip|donate|super ?(chat|thanks|sticker)s?|thanks|buy|purchase|"
    r"order|shop(ping)?|add to (cart|bag|basket|playlist|favou?rites|queue)|cart|checkout|pay|subscribe now|"
    r"save[ds]?|saved|watch later|favou?rites?|bookmark|collect|download|report|block|mute|not interested|"
    r"don't recommend|notify|notifications? on|bell|duet|stitch|remix|use (this )?sound|edit|sign ?(in|out|up)|"
    r"log ?(in|out)|switch account|connect|wallet|swap|sell)\b", re.I)
# a link's text is a video title or a name when it is long: only short labels (button-like) are read as actions
ACTION_LABEL_WORDS = 3
# an option label that starts with an action verb ("like this video", "follow the creator")
ACTION_VERB = re.compile(r"^\W*(un)?(like|dislike|love|heart|follow|subscribe|join|comment|reply|post|repost|share|send|"
                         r"message|dm|chat|upload|create|go live|gift|tip|donate|buy|purchase|order|shop|add to|pay|"
                         r"save|bookmark|favou?rite|collect|download|report|block|mute|notify|duet|stitch|remix|"
                         r"use (this )?sound|edit|sign|log ?in|switch|connect|swap|sell)\b", re.I)
# labels that look like actions but are plain navigation of the feed
ACTION_LABEL_OK = re.compile(r"^(for you|following feed|home|shorts|explore|trending|next|previous|more|show more|"
                             r"read more|see more)$", re.I)
# test ids and class / element names of action controls on TikTok and YouTube
ACTION_TESTID = re.compile(
    r"like|comment|share|follow|subscribe|favorite|collect|repost|gift|live|upload|message|inbox|download|report|"
    r"duet|stitch|send|reply|playlist|save|notif|bell|wallet|coin|recharge|shop|cart|sponsor|join|thanks|super", re.I)
ACTION_ELEMENT = re.compile(
    r"^(ytd-subscribe-button-renderer|ytd-toggle-button-renderer|like-button-view-model|dislike-button-view-model|"
    r"segmented-like-dislike-button-view-model|ytd-download-button-renderer|ytd-menu-renderer|ytd-button-renderer|"
    r"yt-button-shape|ytd-comment-simplebox-renderer|ytd-comments|ytd-live-chat-frame|ytd-sponsorships-.*|"
    r"ytm-subscribe-button-renderer|ytm-slim-video-action-bar-renderer|ytm-like-button-renderer|form|textarea|"
    r"input|select)$", re.I)
ACTION_HREF = re.compile(
    r"/(upload|share|messages?|inbox|live|coin|recharge|gift|shop|cart|checkout|subscription_center|"
    r"sharing|intent|comment|favorites?|liked?|playlist\?list=(WL|LL|LM))(/|\?|$)|"
    r"[?&](sub_confirmation|action_[a-z_]+|feature=share|share_?)=|^javascript:|^mailto:|^sms:|^tel:", re.I)
# roles that can only be controls (a link to another video or feed is role "link")
ACTION_ROLES = ("button", "switch", "checkbox", "menuitem", "menuitemcheckbox", "menuitemradio", "radio", "option",
                "textbox", "combobox", "slider", "tab")


def action_target(role="", label="", href="", testid="", element="", pressed=None):
    """Why a click target is an action he may not take ('label', 'href', 'testid', 'element', 'role', 'private'),
    or None if it is plain navigation (a link to a video, a feed, a profile, the next page)."""
    t = " ".join((label or "").split())
    short = len(t.split()) <= ACTION_LABEL_WORDS or (role or "").lower() not in ("link", "")
    if t and short and not ACTION_LABEL_OK.match(t) and ACTION_LABEL.search(t):
        return "label"
    if t and ACTION_VERB.match(t) and not ACTION_LABEL_OK.match(t):
        return "label"
    if href and (ACTION_HREF.search(href) or private_url(href)):
        return "private" if private_url(href) else "href"
    if testid and ACTION_TESTID.search(testid):
        return "testid"
    if element and ACTION_ELEMENT.match(element):
        return "element"
    if pressed is not None:                     # aria-pressed: a toggle (like, subscribe, save)
        return "role"
    if (role or "").lower() in ACTION_ROLES:
        return "role"
    return None


def link_ok(href, label="", aria=""):
    """A page link that may become an option (and be clicked): navigation only, never an action or a private page."""
    return (action_target("link", label, href) is None
            and (not aria or action_target("link", aria, "") is None))


def safe_links(links):
    """LINKS_JS rows ([href, text, area, visible, rel, external, aria]) without actions or private pages."""
    return [r for r in links if link_ok(r[0], r[1] if len(r) > 1 else "", r[6] if len(r) > 6 else "")]


def option_ok(option, links=None):
    """An eyes / brain-vote option ({"action", "target", "label"}) on a logged-in site: its label does not start
    with an action verb, and a link option only if its link passes `link_ok`. `links` maps a link id to its LINKS_JS
    row (or to {"href", "text", "aria"})."""
    if ACTION_VERB.match(str(option.get("label") or "")):
        return False
    if option.get("action") in ("click", "open_video", "play_video", "next_page", "open_comments"):
        row = (links or {}).get(option.get("target")) if isinstance(links, dict) else None
        if row is None:
            return False                        # a link we cannot check is never offered
        if isinstance(row, dict):
            return link_ok(row.get("href", ""), row.get("text", ""), row.get("aria", ""))
        return link_ok(row[0], row[1] if len(row) > 1 else "", row[6] if len(row) > 6 else "")
    return True


# describe a click target just before the click (page.evaluate(TARGET_JS, element_handle))
TARGET_JS = """el => { let a = el.closest('a, button, [role], [data-e2e]') || el, c = el, testids = [];
  for (let i = 0; c && i < 4; i++, c = c.parentElement) if (c.getAttribute && c.getAttribute('data-e2e')) testids.push(c.getAttribute('data-e2e'));
  return {role: a.getAttribute('role') || (a.tagName === 'BUTTON' ? 'button' : a.tagName === 'A' ? 'link' : ''),
          label: (a.getAttribute('aria-label') || a.innerText || a.title || '').trim().slice(0, 120),
          href: a.href || a.getAttribute('href') || '', testid: testids.join(' '),
          element: a.tagName.toLowerCase(), pressed: a.hasAttribute('aria-pressed') ? a.getAttribute('aria-pressed') : null}; }"""


def click_ok(target):
    """TARGET_JS's description -> True if the click may be made."""
    t = target or {}
    return action_target(t.get("role", ""), t.get("label", ""), t.get("href", ""), t.get("testid", ""),
                         t.get("element", "") if t.get("element") not in ("a", "div", "span", "img") else "",
                         t.get("pressed")) is None


# --- 3. the account's avatar, name and action buttons are hidden before every screenshot ----------------------------
HIDE_ACCOUNT_CSS = """
/* YouTube: avatar and account menu, the "You" guide section, notifications, create / upload */
#avatar-btn, button#avatar-btn, ytd-topbar-menu-button-renderer, ytd-notification-topbar-button-renderer,
ytd-active-account-header-renderer, ytd-multi-page-menu-renderer, #account-name, #channel-handle,
ytm-topbar-menu-button-renderer, .mobile-topbar-header-avatar, ytm-profile-icon, img.yt-spec-avatar-shape__avatar,
ytd-masthead #buttons, ytd-guide-entry-renderer:has(a[href="/feed/you"]), ytd-guide-entry-renderer:has(a[href^="/feed/history"]),
ytd-guide-entry-renderer:has(a[href^="/playlist?list=WL"]), ytd-guide-entry-renderer:has(a[href^="/playlist?list=LL"]),
ytd-guide-entry-renderer:has(a[href*="studio.youtube.com"]), ytd-guide-section-renderer:has(a[href="/feed/you"]),
ytd-mini-guide-entry-renderer:has(a[href="/feed/you"]), ytd-guide-section-renderer:has(a[href^="/feed/subscriptions"]) #items > ytd-guide-entry-renderer:has(img),
/* YouTube: action buttons under a video, Shorts actions */
ytd-subscribe-button-renderer, #subscribe-button, #sponsor-button, like-button-view-model, dislike-button-view-model,
segmented-like-dislike-button-view-model, ytd-download-button-renderer, #actions, ytd-menu-renderer,
ytd-reel-player-overlay-renderer #actions, ytm-slim-video-action-bar-renderer, ytm-subscribe-button-renderer,
ytd-comments, #comments, ytd-comment-simplebox-renderer, ytd-live-chat-frame,
/* TikTok: profile icon, inbox, messages, activity, upload, coins, the account's name in the side nav */
[data-e2e="profile-icon"], [data-e2e="nav-profile"], [data-e2e="nav-messages"], [data-e2e="inbox-icon"],
[data-e2e="nav-activity"], [data-e2e="upload-icon"], [data-e2e="nav-upload"], [data-e2e="nav-more-menu"],
[data-e2e="top-get-coins"], [data-e2e="nav-live"], a[href^="/messages"], a[href^="/upload"], a[href*="tiktokstudio"],
a[href^="/coin"], [class*="DivProfileContainer"] [class*="Avatar"], [class*="DivHeaderRightContainer"] [class*="Avatar"],
/* TikTok: like, comment, save, share, follow, gift on every video */
[data-e2e="like-icon"], [data-e2e="browse-like-icon"], [data-e2e="comment-icon"], [data-e2e="browse-comment-icon"],
[data-e2e="share-icon"], [data-e2e="undefined-icon"], [data-e2e="favorite-icon"], [data-e2e="follow-button"],
[data-e2e="feed-follow"], [data-e2e="browse-follow"], [data-e2e="video-author-avatar"] + button,
[data-e2e="comment-list"], [data-e2e="comment-input"], [data-e2e="gift-icon"]
{ visibility: hidden !important; pointer-events: none !important; }
"""
# avatars and account names a selector may miss: header / nav images labelled as the account, hidden by attribute
HIDE_ACCOUNT_JS = """() => {
  const re = /avatar|profile (picture|photo|icon)|account|your channel|my profile|switch account/i;
  let n = 0;
  for (const root of document.querySelectorAll('header, nav, [role="banner"], [role="navigation"], ytd-masthead, ytm-mobile-topbar-renderer')) {
    for (const el of root.querySelectorAll('img, button, a, [aria-label], [alt]')) {
      const t = (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('alt') || '') + ' ' + (el.className && el.className.baseVal === undefined ? el.className : '');
      if (re.test(t)) { el.style.setProperty('visibility', 'hidden', 'important'); el.style.setProperty('pointer-events', 'none', 'important'); n++; }
    }
  }
  return n; }"""
# page.evaluate(ADD_STYLE_JS, HIDE_ACCOUNT_CSS): the CSS goes in once per document, however often it is called
ADD_STYLE_JS = """css => { if (document.getElementById('sub01-hide-account')) return false;
  const s = document.createElement('style'); s.id = 'sub01-hide-account'; s.textContent = css;
  (document.head || document.documentElement).appendChild(s); return true; }"""
