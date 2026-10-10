"""#89 live check (2026-10-04 10:05 UTC): he opened "90min | PSG - WhatsApp channel" on whatsapp.com (an app wall);
three myanimelist.net pages in a row titled only "myanimelist.net" (a bot-check interstitial), one of them counted as
"finance". Here: messaging / app pages are never link targets; a bot check (a bare-host title or the usual challenge
texts) is left at once, not shown or counted, and its site is left alone for a while (never solved or waited out); an
anime page with in-game words is not finance.

    python -m pytest tests/test_browse_walls.py -q
No network, no Chromium.
"""
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browse  # noqa: E402
import readings  # noqa: E402
import screens as SC  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("url", [
    "https://www.whatsapp.com/channel/0029VaPSG", "https://whatsapp.com/channel/x", "https://wa.me/123456",
    "https://t.me/psg_channel", "https://telegram.me/x", "https://discord.gg/abcd", "https://discord.com/invite/abcd",
    "https://www.messenger.com/t/x", "https://m.me/page", "https://apps.apple.com/app/id1", "https://line.me/R/ti/p/x",
    "https://play.google.com/store/apps/details?id=x", "https://psg.onelink.me/abc", "https://x.app.link/open"])
def test_messaging_and_app_pages_are_walls(url):
    assert browse.app_wall(url)
    host = browse.urllib.parse.urlsplit(url).hostname
    if browse.APP_WALL_HOST.search(host):                      # a whole messaging host: never opened at all
        assert not browse.Browser(decide=False).host_ok(host)


@pytest.mark.parametrize("url", ["https://www.90min.com/posts/psg", "https://discord.com/blog/x",
                                 "https://play.google.com/books", "https://www.apple.com/iphone/"])
def test_ordinary_pages_are_not_app_walls(url):
    assert not browse.app_wall(url)


def test_open_and_the_link_picker_never_take_an_app_wall():
    b = browse.Browser(decide=False)
    sc = b.screens["desk"]
    sc.page, sc.ctx = SimpleNamespace(url="about:blank"), object()
    assert not run(b._open(sc, "https://www.whatsapp.com/channel/0029VaPSG", "x", "page"))
    assert "messaging or app" in b.last_skip
    raw = [("https://www.whatsapp.com/channel/0029VaPSG", "90min | PSG - WhatsApp channel", 9000, True),
           ("https://discord.gg/abc", "Join our Discord server now", 9000, True),
           ("https://www.90min.com/posts/psg-win", "PSG win again in a thriller at the Parc", 9000, True)]
    sc.info = {"url": "https://www.90min.com/", "host": "90min.com", "title": "90min", "kind": "page"}
    links = b.pick_links(raw, "https://www.90min.com/", "", sc)["links"]
    hrefs = [l["href"] for l in links]
    assert "https://www.90min.com/posts/psg-win" in hrefs and not [h for h in hrefs if browse.app_wall(h)]


@pytest.mark.parametrize("title, url, wall", [
    ("myanimelist.net", "https://myanimelist.net/anime/1/x", True),
    ("www.myanimelist.net", "https://myanimelist.net/anime/1/x", True),
    ("Just a moment...", "https://myanimelist.net/", True),
    ("Attention Required! | Cloudflare", "https://x.com/", True),
    ("Checking your browser before accessing", "https://a.org/", True),
    ("Pardon Our Interruption", "https://shop.example/", True),
    ("Access to this page has been denied.", "https://www.zillow.com/", True),
    ("Cowboy Bebop - MyAnimeList.net", "https://myanimelist.net/anime/1/Cowboy_Bebop", False),
    ("Airport security: what to expect", "https://www.bbc.com/travel/x", False)])
def test_bot_check_titles(title, url, wall):
    assert browse.challenge_title(title, url) is wall


@pytest.mark.parametrize("body", [
    "Please enable JS and disable any ad blocker",                                   # DataDome
    "Press & Hold to confirm you are a human (and not a bot).",                       # PerimeterX
    "Checking if the site connection is secure. Ray ID: 8c1f2a3b4d5e6f70 Performance & security by Cloudflare"])
def test_bot_check_bodies(body):
    assert browse.Browser.wall_text(body)


class Page:
    def __init__(self, url, title, body):
        self.url, self._title, self.body, self.frames, self.main_frame = url, title, body, [], None

    async def wait_for_timeout(self, ms):
        pass

    async def add_style_tag(self, **k):
        pass

    async def title(self):
        return self._title

    async def goto(self, url, **k):
        self.url = url

    async def evaluate(self, js, *a):
        if "innerText" in js:
            return self.body
        return False


def test_a_bot_check_is_left_not_counted_and_its_site_cools_down():
    b = browse.Browser(decide=False)
    sc = b.screens["desk"]
    sc.page, sc.ctx = Page("https://myanimelist.net/anime/5114/x", "myanimelist.net", "Loading... " * 20), object()
    shown = []

    async def show(sc_):
        shown.append(sc_.info["url"])
        return True

    async def leave(sc_):
        sc_.page.url = "about:blank"
        return False
    b.show, b._leave = show, leave
    assert not run(b._settle(sc, "followed a link", "page", min_text=10))
    assert b.last_skip == "bot wall" and shown == [] and b.walled["myanimelist.net"] > time.time()
    sc.page.url = "about:blank"
    assert not run(b._open(sc, "https://myanimelist.net/anime/1/Cowboy_Bebop", "x", "page"))
    assert "bot check" in b.last_skip                          # left alone: no second try at the same check
    st = b.to_dict()
    assert "myanimelist.net" in st["walled"]
    assert browse.Browser(state=st).walled["myanimelist.net"] > time.time()   # survives a restart
    b.walled["myanimelist.net"] = time.time() - 1              # after WALL_COOLDOWN_S it may be read again
    assert "myanimelist.net" not in b.to_dict()["walled"]


def test_an_anime_page_with_in_game_words_is_not_finance():
    body = ("Trading cards and tokens in the gacha game. Fans trade shares of screenshots. "
            "The anime adaptation airs in spring.")
    assert not browse.is_finance("https://myanimelist.net/anime/52991/Sousou_no_Frieren", "Sousou no Frieren", body)
    assert browse.url_ok("https://myanimelist.net/anime/52991/x")                 # S2: not a trading host either
    st = {"why": "w", "url": "https://myanimelist.net/anime/52991/x", "title": "Sousou no Frieren", "kind": "page"}
    assert readings.kind_of(st) == "page" and SC.screen_kind(st) == "other"
    assert browse.is_finance("https://example.org/a", "Bitcoin and Solana prices", "crypto trading and memecoins")


# --- #89 live (2026-10-05 09:10 Tokyo, his phone): "We noticed that ads aren't being displayed" over the article -------

@pytest.mark.parametrize("body", [
    "Article text... We noticed that ads aren't being displayed. Please support us.",
    "Ad blocker detected. Please disable your ad blocker to continue.",
    "We've detected that you're using an ad blocker. Whitelist this site to keep reading.",
    "You've reached your free article limit. Subscribe to continue reading.",
    "This article is for subscribers only."])
def test_ad_block_and_paywall_overlays_are_walls(body):
    assert browse.overlay_wall(body)


@pytest.mark.parametrize("body", [
    "How ad blockers work, and why publishers worry about them.",
    "The best ad blockers for 2026 compared.", "Subscribe to our newsletter for weekly updates."])
def test_articles_about_ad_blockers_are_not_walls(body):
    assert not browse.overlay_wall(body)


def test_an_overlay_wall_is_left_and_its_site_cools_down_briefly():
    b = browse.Browser(decide=False)
    sc = b.screens["phone"]
    body = "Today in Tokyo. " * 40 + "We noticed that ads aren't being displayed. Please disable your ad blocker."
    sc.page, sc.ctx = Page("https://www.example-news.com/story/1", "A story", body), object()
    shown = []

    async def show(sc_):
        shown.append(sc_.info["url"])
        return True

    async def leave(sc_):
        sc_.page.url = "about:blank"
        return False
    b.show, b._leave = show, leave
    assert not run(b._settle(sc, "followed a link", "page"))
    assert b.last_skip == "overlay wall" and shown == []
    until = b.walled["example-news.com"]
    assert time.time() + browse.OVERLAY_COOLDOWN_S - 60 < until < time.time() + browse.WALL_COOLDOWN_S


def test_an_overlay_that_appears_after_the_page_loaded_is_left_at_the_next_screenshot():
    b = browse.Browser(decide=False)
    sc = b.screens["phone"]
    sc.page = Page("https://www.example-news.com/story/2", "A story", "Ad blocker detected. Please disable your ad blocker.")
    left = []

    async def leave(sc_):
        left.append(sc_.page.url)
    b._leave = leave
    assert run(b._shoot(sc)) is False and left and b.last_skip == "overlay wall"
    assert b.walled["example-news.com"] > time.time()


# 2026-10-07 08:00 UTC live: after "Parental Controls – BBC iPlayer" he opened a page saying "Sorry, BBC iPlayer isn't
# available in your region" and it was shown in the card. A geo-block is a wall: left, not shown, its site cooled down.
IPLAYER_GEO_BODY = ("BBC\nHome\nNews\nSport\nWeather\niPlayer\nSounds\nBitesize\n"
                    "Sorry, BBC iPlayer isn't available in your region\n"
                    "BBC iPlayer only works in the UK. Sorry, it's due to rights issues.\n"
                    "Find out more about BBC iPlayer abroad\n" + "Terms of Use About the BBC Privacy Policy Cookies "
                    "Accessibility Help Parental Guidance Contact the BBC Get Personalised Newsletters " * 30
                    + "Copyright © 2026 BBC. The BBC is not responsible for the content of external sites.")
YOUTUBE_GEO_BODY = ("Video unavailable\nThe uploader has not made this video available in your country\n"
                    "Watch on YouTube")


@pytest.mark.parametrize("title", [
    "Sorry, BBC iPlayer isn't available in your region",
    "BBC iPlayer - Sorry, BBC iPlayer isn’t available in your region",
    "This video is not available in your country - YouTube",
    "Content not available in your location",
    "This content isn't available where you are",
    "Content is not available in your area",
    "Unavailable in your region | Hulu"])
def test_geo_block_titles_are_walls(title):
    assert browse.challenge_title(title, "https://www.bbc.co.uk/iplayer")


@pytest.mark.parametrize("body", [
    IPLAYER_GEO_BODY, YOUTUBE_GEO_BODY,
    "This video is not available in your country.",
    "We're sorry, this content is not available in your area.",
    "Sorry, this programme isn't available where you are.",
    "The content you requested is currently unavailable in your region due to licensing restrictions.",
    "This service is not available in your location."])
def test_geo_block_bodies_are_walls(body):
    assert browse.Browser.wall_text(body)


@pytest.mark.parametrize("title, body", [
    ("Wine regions of France: a guide", "Bordeaux is the best-known region. Pick the region of your choice; "
     "each country has its own grapes. Your region's climate decides the harvest. " * 3),
    ("Weather for your area", "Forecast for your location and region: sunny spells, available sunshine all day."),
    ("Is Netflix available in my country?", "Netflix is available in your country and in over 190 others. "
     "Plans differ by region."),
    ("BBC iPlayer - Parental Controls", "Parental Controls. Set a PIN to stop children watching programmes "
     "with guidance labels. Available on all devices in the UK region settings.")])
def test_pages_that_only_mention_region_are_not_walls(title, body):
    assert not browse.challenge_title(title, "https://www.example.org/a")
    assert not browse.Browser.wall_text(body)


def test_a_long_article_quoting_a_geo_block_is_not_a_wall():
    body = ("Travellers often see the message 'this video is not available in your country' when abroad. "
            + "Here is how licensing works across Europe and why streaming catalogues differ. " * 120)
    assert len(body) > browse.GEO_WALL_MAX_CHARS and not browse.Browser.wall_text(body)


def _settle_once(url, title, body):
    b = browse.Browser(decide=False)
    sc = b.screens["desk"]
    sc.page, sc.ctx = Page(url, title, body), object()
    shown = []

    async def show(sc_):
        shown.append(sc_.info["url"])
        return True

    async def leave(sc_):
        sc_.page.url = "about:blank"
        return False
    b.show, b._leave = show, leave
    return b, sc, shown, run(b._settle(sc, "followed a link", "page", min_text=10))


def test_the_iplayer_geo_block_is_left_not_shown_and_its_site_cools_down():
    for title in ("BBC iPlayer - Home", "Sorry, BBC iPlayer isn't available in your region"):  # by body, by title
        b, sc, shown, ok = _settle_once("https://www.bbc.co.uk/iplayer", title, IPLAYER_GEO_BODY)
        assert not ok and b.last_skip == "bot wall" and shown == []
        assert b.walled["bbc.co.uk"] > time.time() + browse.WALL_COOLDOWN_S - 60    # 6 h
        sc.page.url = "about:blank"
        assert not run(b._open(sc, "https://www.bbc.co.uk/iplayer/episode/x", "x", "page"))
        assert "left alone" in b.last_skip                     # not opened again while cooling down


def test_a_youtube_region_block_is_left_not_shown():
    b, sc, shown, ok = _settle_once("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "YouTube", YOUTUBE_GEO_BODY)
    assert not ok and b.last_skip == "bot wall" and shown == []


def test_a_page_that_turns_into_a_geo_block_is_left_at_the_next_screenshot():
    b = browse.Browser(decide=False)
    sc = b.screens["desk"]
    sc.page = Page("https://www.bbc.co.uk/iplayer", "BBC iPlayer", IPLAYER_GEO_BODY)
    left = []

    async def leave(sc_):
        left.append(sc_.page.url)
        return False
    b._leave = leave
    assert not run(b._shoot(sc)) and left == ["https://www.bbc.co.uk/iplayer"]


def test_a_normal_page_mentioning_region_is_shown():
    b, sc, shown, ok = _settle_once("https://www.example.org/wine", "Wine regions of France",
                                    "Bordeaux is the best-known region; your region's climate decides the harvest. " * 5)
    assert ok and shown == ["https://www.example.org/wine"] and not b.walled


# (G14, on top of GEO_WALL) the US / EU walls and the licence wording it did not catch, and an article title about
# geo-blocking that it took for the wall
@pytest.mark.parametrize("body", [
    "We're sorry, this service is not available outside the United States.",
    "This content is not available to viewers outside the UK.",
    "This service is only available in the US.",
    "Due to licensing restrictions this programme cannot be played in your country."])
def test_more_geo_block_bodies_are_walls(body):
    assert browse.Browser.wall_text(body)


@pytest.mark.parametrize("title", ["Why Netflix shows aren't available in your country",
                                   "How to watch shows that are not available in your region",
                                   "Is BBC iPlayer not available in your country? Here's why"])
def test_a_title_asking_about_geo_blocks_is_an_article_not_a_wall(title):
    assert not browse.challenge_title(title, "https://www.example-news.com/streaming")
    assert browse.challenge_title("Sorry, BBC iPlayer isn't available in your region", "https://www.bbc.co.uk/iplayer")


# 2026-10-07 14:39 UTC live: he opened "The Drive - Permission Request Form" (permissions.thedrive.threesai.com) and it
# went into the browsing log. A consent / permission / cookie-request page is a wall: left, not shown, its site cooled.
PERMISSION_BODY = ("Permission Request Form\nPlease fill in the form below to request permission to use content.\n"
                   "Name\nEmail\nCompany\nDescribe the intended use\nSubmit\n")


@pytest.mark.parametrize("title, url", [
    ("The Drive - Permission Request Form", "https://permissions.thedrive.threesai.com/"),
    ("The Drive - Permission Request Form", "https://www.thedrive.com/permissions"),
    ("Request form", "https://permissions.thedrive.threesai.com/form"),           # by the host alone
    ("Cookie preferences | BBC", "https://www.bbc.co.uk/usingthebbc/cookies"),
    ("Your Privacy Choices - Example", "https://www.example.com/privacy"),
    ("Consent Management", "https://consent.example.com/"),
    ("Manage cookies", "https://cookies.example-news.com/")])
def test_permission_and_consent_request_pages_are_walls(title, url):
    assert browse.challenge_title(title, url)


@pytest.mark.parametrize("title, url", [
    ("How to manage your privacy settings on iPhone", "https://www.example.com/a"),
    ("Permission to Dance: the video, explained", "https://www.example.com/b"),
    ("The Drive: car news and reviews", "https://www.thedrive.com/"),
    ("Cookie recipes for the weekend - Food & Wine", "https://www.foodandwine.com/x"),
    ("Privacy policy", "https://example.com/privacy")])
def test_pages_about_permissions_or_cookies_are_not_walls(title, url):
    assert not browse.challenge_title(title, url)


def test_the_permission_request_form_is_left_not_shown_and_its_site_cools_down():
    b, sc, shown, ok = _settle_once("https://permissions.thedrive.threesai.com/", "The Drive - Permission Request Form",
                                    PERMISSION_BODY)
    assert not ok and b.last_skip == "bot wall" and shown == [] and not b.log
    assert b.walled and min(b.walled.values()) > time.time() + browse.WALL_COOLDOWN_S - 60    # 6 h
    sc.page.url = "about:blank"
    assert not run(b._open(sc, "https://permissions.thedrive.threesai.com/other", "x", "page"))
    assert "left alone" in b.last_skip


# COORD: "consent" anywhere in a title made it a wall, so an article about cookie consent was left. Only a title part that
# is the request itself is one (as consent_wall); Google's "Before you continue" stays a wall.
@pytest.mark.parametrize("title, wall", [
    ("Why websites ask for cookie consent - The Verge", False),
    ("Informed consent in medicine: a guide | Example Health", False),
    ("The age of consent debate, explained", False),
    ("Consent", True),
    ("Your consent | BBC", True),
    ("Privacy & consent - Example News", True),
    ("Cookie consent", True),
    ("Before you continue", True),
    ("Before you continue to YouTube", True)])
def test_only_a_consent_request_title_is_a_wall(title, wall):
    assert browse.challenge_title(title, "https://www.example.com/x") is wall
