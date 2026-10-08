"""Logged-in, view-only TikTok and YouTube (#60): sessions from env, scoped cookies, fallback when missing or expired,
the private-page blocklist, actions never clicked or offered, the account's avatar hidden.

    python -m pytest tests/test_logged_in_feeds.py -q
No network. The Chromium tests use local HTML only and are skipped without a browser.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sessions as S  # noqa: E402
import view_only as V  # noqa: E402

NOW = 1_800_000_000.0
SECRET = "s3cr3t-session-value-do-not-leak"


def cookie_editor(name, value=SECRET, domain=".tiktok.com", exp=NOW + 86400, **kw):
    """One cookie as Cookie-Editor's JSON export writes it."""
    c = {"domain": domain, "expirationDate": exp, "hostOnly": not domain.startswith("."), "httpOnly": True,
         "name": name, "path": "/", "sameSite": "no_restriction", "secure": True, "session": exp is None,
         "storeId": "0", "value": value}
    if exp is None:
        del c["expirationDate"]
    c.update(kw)
    return c


def playwright_cookie(name, value=SECRET, domain=".youtube.com", expires=NOW + 86400, **kw):
    c = {"name": name, "value": value, "domain": domain, "path": "/", "expires": expires, "httpOnly": True,
         "secure": True, "sameSite": "Lax"}
    c.update(kw)
    return c


def tiktok_env(*cookies):
    return {"SUB01_SESSION_TIKTOK": json.dumps(list(cookies))}


# --- parsing both formats ---------------------------------------------------------------------------------------------
def test_cookie_editor_export_is_parsed():
    out = S.parse_cookies(json.dumps([cookie_editor("sessionid"), cookie_editor("tt_csrf_token", domain="www.tiktok.com"),
                                      cookie_editor("s_v_web_id", exp=None, sameSite="unspecified", secure=False)]),
                          now=NOW)
    by = {c["name"]: c for c in out}
    assert by["sessionid"] == {"name": "sessionid", "value": SECRET, "domain": ".tiktok.com", "path": "/",
                               "expires": NOW + 86400, "httpOnly": True, "secure": True, "sameSite": "None"}
    assert by["tt_csrf_token"]["domain"] == "www.tiktok.com"           # host-only: no leading dot
    assert by["s_v_web_id"]["expires"] == -1 and by["s_v_web_id"]["sameSite"] == "Lax"


def test_playwright_cookies_and_storage_state_are_parsed():
    cs = [playwright_cookie("SID"), playwright_cookie("YSC", expires=-1, sameSite="None")]
    a = S.parse_cookies(json.dumps(cs), now=NOW)
    b = S.parse_cookies(json.dumps({"cookies": cs, "origins": []}), now=NOW)
    assert a == b and [c["name"] for c in a] == ["SID", "YSC"]
    assert a[1]["expires"] == -1 and a[1]["sameSite"] == "None"


def test_samesite_none_without_secure_becomes_lax():
    out = S.parse_cookies(json.dumps([cookie_editor("x", secure=False)]), now=NOW)
    assert out[0]["sameSite"] == "Lax"


def test_expired_cookies_are_dropped():
    out = S.parse_cookies(json.dumps([cookie_editor("old", exp=NOW - 1), cookie_editor("new")]), now=NOW)
    assert [c["name"] for c in out] == ["new"]


@pytest.mark.parametrize("raw", [
    "", "   ", "not json", "{}", '{"a": 1}', "[1]", json.dumps([{"name": "a"}]),
    json.dumps([cookie_editor("bad name")]), json.dumps([cookie_editor("a", value="x;y")]),
    json.dumps([cookie_editor("a", value="x\ny")]), json.dumps([cookie_editor("a", domain="ti..k.com")]),
    json.dumps([cookie_editor("a", path="nope")]), json.dumps([cookie_editor("a", expirationDate="soon")]),
    "[" + ",".join(['{"name":"a","value":"b","domain":"tiktok.com"}'] * 201) + "]", "x" * 70_000,
])
def test_unusable_secrets_raise_without_their_content(raw):
    with pytest.raises(S.SessionError) as e:
        S.parse_cookies(raw, now=NOW)
    assert SECRET not in str(e.value) and "x;y" not in str(e.value) and len(str(e.value)) < 40


# --- scoping: cookies stay on their own site ----------------------------------------------------------------------
def test_cookies_are_scoped_to_their_domains(capsys):
    env = tiktok_env(cookie_editor("sessionid"), cookie_editor("sid_tt", domain="www.tiktok.com"),
                     cookie_editor("SID", domain=".youtube.com"), cookie_editor("NID", domain=".google.com"),
                     cookie_editor("evil", domain=".tiktok.com.evil.example"), cookie_editor("x", domain="nottiktok.com"))
    s = S.load_session("tiktok", env, now=NOW)
    assert s.logged_in and s.dropped == 4
    assert sorted(c["name"] for c in s.cookies()) == ["sessionid", "sid_tt"]
    assert all(S.host_in(c["domain"], ("tiktok.com",)) for c in s.cookies())
    assert "4 cookies of other domains ignored" in capsys.readouterr().out


def test_host_matching_is_exact_on_labels():
    assert S.host_in("www.tiktok.com", ("tiktok.com",)) and S.host_in(".tiktok.com", ("tiktok.com",))
    assert not S.host_in("nottiktok.com", ("tiktok.com",)) and not S.host_in("tiktok.com.evil.io", ("tiktok.com",))
    assert S.site_for_url("https://m.youtube.com/watch?v=x") == "youtube"
    assert S.site_for_url("https://www.tiktok.com/foryou") == "tiktok"
    assert S.site_for_url("https://example.com/") is None and S.site_for_url("http://[bad") is None


def test_youtube_keeps_restricted_mode_when_logged_in():
    env = {"SUB01_SESSION_YOUTUBE": json.dumps([playwright_cookie("SID"),
                                                playwright_cookie("PREF", value="f6=40000000&tz=Asia.Tokyo")])}
    s = S.load_session("youtube", env, now=NOW)
    prefs = [c for c in s.cookies() if c["name"] == "PREF"]
    assert prefs == [S.RESTRICTED_PREF] and s.cookies() is not s.cookies()


def test_cookies_returns_copies():
    s = S.load_session("tiktok", tiktok_env(cookie_editor("sessionid")), now=NOW)
    s.cookies()[0]["domain"] = ".evil.example"
    assert s.cookies()[0]["domain"] == ".tiktok.com"


# --- never logged, never shown ----------------------------------------------------------------------------------------
def test_secret_values_never_reach_logs_repr_or_status(capsys):
    for raw in [json.dumps([cookie_editor("sessionid"), cookie_editor("other", domain=".youtube.com")]),
                SECRET, json.dumps([cookie_editor("sessionid", exp=NOW - 5)])]:
        s = S.load_session("tiktok", {"SUB01_SESSION_TIKTOK": raw}, now=NOW)
        s.check(now=NOW)
        s.expire("login_wall")
        text = repr(s) + str(s) + json.dumps(s.status()) + capsys.readouterr().out
        assert SECRET not in text and "sessionid" not in text


def test_sessions_stay_out_of_chromium_env():
    import browse
    env = dict(PATH="/usr/bin", HOME="/home/sub01", SUB01_SESSION_TIKTOK=SECRET, SUB01_SESSION_YOUTUBE=SECRET)
    kw = browse.launch_kwargs(True, environ=env)
    assert SECRET not in json.dumps(kw)
    assert not set(S.secret_env_names()) & set(kw.get("env") or {})
    assert not set(S.secret_env_names()) & set(browse.CHROMIUM_ENV)


# --- fallback when missing or expired -------------------------------------------------------------------------------
def test_missing_secret_means_logged_out():
    ss = S.load_sessions({}, now=NOW)
    assert set(ss) == {"tiktok", "youtube"}
    for s in ss.values():
        assert not s.logged_in and s.cookies() == [] and s.status()["state"] == "logged_out"
        assert s.status()["reason"] == "missing"


def test_invalid_secret_means_logged_out(capsys):
    s = S.load_session("tiktok", {"SUB01_SESSION_TIKTOK": "{not json"}, now=NOW)
    assert not s.logged_in and s.reason == "invalid" and s.cookies() == []
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "not JSON" in out and "{not json" not in out


def test_session_without_login_cookie_is_logged_out():
    s = S.load_session("tiktok", tiktok_env(cookie_editor("tt_csrf_token")), now=NOW)
    assert not s.logged_in and s.reason == "expired"


def test_expired_login_cookie_falls_back_once(capsys):
    s = S.load_session("tiktok", tiktok_env(cookie_editor("sessionid", exp=NOW + 60)), now=NOW)
    assert s.logged_in and s.status()["expires"] == int(NOW + 60) and s.status()["reason"] is None
    capsys.readouterr()
    assert not s.check(now=NOW + 61)
    assert not s.check(now=NOW + 62)
    assert s.status() == {"site": "tiktok", "state": "logged_out", "reason": "expired", "expires": None}
    assert capsys.readouterr().out.count("\n") == 1                    # one line, not one per check


def test_expired_at_load():
    s = S.load_session("tiktok", tiktok_env(cookie_editor("sessionid", exp=NOW - 1)), now=NOW)
    assert not s.logged_in and s.reason == "expired"


def test_session_login_cookie_without_expiry_stays_logged_in():
    s = S.load_session("tiktok", tiktok_env(cookie_editor("sessionid", exp=None)), now=NOW)
    assert s.check(now=NOW + 10 ** 6) and s.status()["expires"] is None


def test_login_wall_logs_out_for_good():
    s = S.load_session("tiktok", tiktok_env(cookie_editor("sessionid")), now=NOW)
    assert not s.looks_signed_out([]) and not s.looks_signed_out(['[data-e2e="like-icon"]'])
    assert s.looks_signed_out(['[data-e2e="top-login-button"]'])
    s.expire("login_wall")
    assert s.cookies() == [] and s.status()["reason"] == "login_wall" and not s.check()
    y = S.Session("youtube")
    assert y.looks_signed_out(['ytd-masthead a[href*="ServiceLogin"]'])


# --- private pages ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "https://www.tiktok.com/messages", "https://www.tiktok.com/messages?lang=en", "https://www.tiktok.com/inbox",
    "https://www.tiktok.com/notifications", "https://www.tiktok.com/setting", "https://www.tiktok.com/settings/privacy",
    "https://www.tiktok.com/upload", "https://www.tiktok.com/tiktokstudio/content", "https://www.tiktok.com/coin",
    "https://www.tiktok.com/live/abc", "https://www.tiktok.com/logout", "https://www.tiktok.com/login",
    "https://www.tiktok.com/@sub01/edit", "https://www.tiktok.com/@sub01/liked", "https://www.tiktok.com/@sub01?edit=1",
    "https://www.tiktok.com/analytics", "https://seller.tiktok.com/", "https://ads.tiktok.com/x",
    "https://www.youtube.com/account", "https://www.youtube.com/account_privacy", "https://www.youtube.com/feed/history",
    "https://www.youtube.com/feed/you", "https://www.youtube.com/feed/library", "https://m.youtube.com/feed/history",
    "https://www.youtube.com/playlist?list=WL", "https://www.youtube.com/playlist?list=LL",
    "https://www.youtube.com/watch?v=abc&list=WL&index=2", "https://www.youtube.com/upload",
    "https://www.youtube.com/paid_memberships", "https://www.youtube.com/premium", "https://www.youtube.com/channel_switcher",
    "https://studio.youtube.com/channel/UCx/videos", "https://accounts.google.com/ServiceLogin",
    "https://myaccount.google.com/", "https://pay.google.com/", "https://www.youtube.com/feed/purchases",
    "https://www.youtube.com/reporthistory",
])
def test_private_urls_are_blocked(url):
    assert V.private_url(url)


@pytest.mark.parametrize("url", [
    "https://www.tiktok.com/", "https://www.tiktok.com/foryou", "https://www.tiktok.com/following",
    "https://www.tiktok.com/explore", "https://www.tiktok.com/@sub01", "https://www.tiktok.com/@sub01/video/7312345",
    "https://www.tiktok.com/@someone/video/7312345?is_from_webapp=1", "https://www.tiktok.com/search?q=ramen",
    "https://www.tiktok.com/tag/ramen", "https://www.youtube.com/", "https://www.youtube.com/feed/subscriptions",
    "https://www.youtube.com/shorts/abc", "https://www.youtube.com/watch?v=abc", "https://www.youtube.com/@sub01",
    "https://www.youtube.com/playlist?list=PL12345", "https://www.youtube.com/results?search_query=ramen",
    "https://m.youtube.com/", "https://en.wikipedia.org/wiki/Settings", "https://example.com/messages",
])
def test_public_urls_pass(url):
    assert V.private_url(url) is None


def test_private_dom_by_selector_and_heading():
    assert V.private_dom({"selectors": ['ytd-browse[page-subtype="history"]'], "headings": []}).startswith("dom:")
    assert V.private_dom({"selectors": ['[data-e2e="inbox-list"]']})
    assert V.private_dom({"selectors": ['input[type="password"]']})
    assert V.private_dom({"headings": ["Settings - YouTube"]}) == "heading"
    assert V.private_dom({"headings": ["Messages | TikTok"]}) == "heading"
    assert V.private_dom({"headings": ["Watch history"]}) == "heading"
    assert V.private_dom({"headings": ["Edit profile"]}) == "heading"
    assert V.private_dom({"selectors": ["not-a-known-selector"]}) is None
    assert V.private_dom({"headings": ["Best ramen in Kichijoji - YouTube", "Settings of a Tokyo apartment"]}) is None
    assert V.private_dom(None) is None and V.private_dom({}) is None


# --- actions: never clicked, never offered ----------------------------------------------------------------------
@pytest.mark.parametrize("target", [
    dict(role="button", label="Like"), dict(role="button", label="Like video 12.3K likes"),
    dict(role="button", label="Follow"), dict(role="button", label="Subscribe"), dict(label="Subscribed"),
    dict(role="link", label="Comment"), dict(label="Share"), dict(label="Send message"), dict(label="Upload"),
    dict(label="Go LIVE"), dict(label="Send a gift"), dict(label="Get Coins"), dict(label="Buy now"),
    dict(label="Save to playlist"), dict(label="Watch later"), dict(label="Report"), dict(label="Join"),
    dict(label="Thanks"), dict(label="Download"), dict(label="Add to Favorites"), dict(label="Duet"),
    dict(label="Log in"), dict(label="Like this video along with 1,234 other people", role="link"),
    dict(label="I dislike this", role="button"),
    dict(href="https://www.tiktok.com/upload?lang=en"), dict(href="https://www.youtube.com/@x?sub_confirmation=1"),
    dict(href="https://www.tiktok.com/messages"), dict(href="https://www.youtube.com/playlist?list=WL"),
    dict(href="javascript:void(0)"), dict(href="https://studio.youtube.com/"),
    dict(testid="like-icon"), dict(testid="browse-follow"), dict(testid="share-icon"), dict(testid="comment-icon"),
    dict(element="ytd-subscribe-button-renderer"), dict(element="like-button-view-model"), dict(element="textarea"),
    dict(role="button", label=""), dict(role="menuitem", label="Not interested"), dict(pressed="false"),
])
def test_action_targets_are_refused(target):
    assert V.action_target(**target)
    assert not V.click_ok(target)


@pytest.mark.parametrize("target", [
    dict(role="link", label="Tokyo night walk in the rain 4K", href="https://www.youtube.com/watch?v=abc"),
    dict(role="link", label="I tried every ramen shop you should follow in Kichijoji",
         href="https://www.youtube.com/watch?v=x"),
    dict(role="link", label="For You", href="https://www.tiktok.com/foryou"),
    dict(role="link", label="Following feed", href="https://www.tiktok.com/following"),
    dict(role="link", label="@chef_tanaka", href="https://www.tiktok.com/@chef_tanaka"),
    dict(role="link", label="#ramen", href="https://www.tiktok.com/tag/ramen"),
    dict(role="link", label="Next", href="https://www.youtube.com/results?search_query=x&page=2"),
    dict(role="link", label="", href="https://www.tiktok.com/@a/video/123", element="a"),
    dict(role="link", label="Shorts", href="https://www.youtube.com/shorts/abc", element="a"),
])
def test_navigation_targets_pass(target):
    assert V.action_target(**{k: v for k, v in target.items() if k != "element"}) is None
    assert V.click_ok(target)


def test_safe_links_drop_actions_and_private_pages():
    rows = [["https://www.youtube.com/watch?v=a", "Ramen in Tokyo", 100, True, "", False, ""],
            ["https://www.youtube.com/feed/history", "History", 100, True, "", False, ""],
            ["https://www.youtube.com/@x?sub_confirmation=1", "Ramen channel", 100, True, "", False, ""],
            ["https://www.tiktok.com/@a/video/1", "", 100, True, "", False, "Like"],
            ["https://www.tiktok.com/@a/video/2", "cats", 100, True, "", False, "Video by a"],
            ["https://www.tiktok.com/upload", "Upload", 100, True, "", False, ""]]
    assert [r[0] for r in V.safe_links(rows)] == ["https://www.youtube.com/watch?v=a", "https://www.tiktok.com/@a/video/2"]


def test_options_with_actions_never_reach_the_vote():
    links = {1: ["https://www.youtube.com/watch?v=a", "Tokyo walk", 1, True, "", False, ""],
             2: ["https://www.youtube.com/@x?sub_confirmation=1", "x", 1, True, "", False, ""],
             3: {"href": "https://www.tiktok.com/messages", "text": "Inbox"}}
    ok = [{"action": "open_video", "target": 1, "label": "Tokyo walk"},
          {"action": "scroll", "label": "keep watching the feed"},
          {"action": "leave", "label": "wander somewhere else"},
          {"action": "search", "target": "ramen", "label": "search ramen"}]
    bad = [{"action": "click", "target": 2, "label": "x"}, {"action": "click", "target": 3, "label": "Inbox"},
           {"action": "click", "target": 99, "label": "unknown link"},
           {"action": "click", "target": 1, "label": "like this video"},
           {"action": "scroll", "label": "Follow the creator"}, {"action": "scroll", "label": "subscribe to the channel"},
           {"action": "scroll", "label": "share it"}, {"action": "click", "target": 1}]
    assert all(V.option_ok(o, links) for o in ok)
    assert not any(V.option_ok(o, links) for o in bad[:-1])
    assert not V.option_ok(bad[-1], None)                                         # a link we cannot check


def test_brain_vote_never_sees_an_action_option():
    """Whatever the brain prefers, a filtered option list cannot contain an action: the vote picks only from it."""
    import random
    links = {i: [f"https://www.tiktok.com/@a/video/{i}", f"clip {i}", 1, True, "", False, ""] for i in range(5)}
    links[5] = ["https://www.tiktok.com/@a", "", 1, True, "", False, "Follow"]
    labels = ["Like", "Follow", "Share", "Comment", "Send a gift", "Subscribe", "Save", "Upload", "Report"]
    rng = random.Random(3)
    for _ in range(200):
        opts = [{"action": "click", "target": rng.randrange(6), "label": rng.choice(labels + ["clip"])}
                for _ in range(6)]
        opts += [{"action": "scroll", "label": rng.choice(labels).lower() + " this"}]
        kept = [o for o in opts if V.option_ok(o, links)]
        for o in kept:
            assert o["label"] == "clip" and o["target"] != 5


# --- avatar / name / buttons hidden -----------------------------------------------------------------------------------
def test_hide_css_covers_avatar_name_and_actions_on_both_sites():
    css = V.HIDE_ACCOUNT_CSS
    for sel in ["#avatar-btn", "ytd-topbar-menu-button-renderer", "#account-name", "ytm-topbar-menu-button-renderer",
                '[data-e2e="profile-icon"]', '[data-e2e="nav-profile"]', '[data-e2e="nav-messages"]',
                '[data-e2e="like-icon"]', '[data-e2e="follow-button"]', '[data-e2e="share-icon"]',
                "ytd-subscribe-button-renderer", "like-button-view-model"]:
        assert sel in css, sel
    assert css.count("{") == 1 and "visibility: hidden !important" in css and "pointer-events: none" in css


async def _page():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    pw = await async_playwright().start()
    try:
        br = await pw.chromium.launch(args=["--no-sandbox"])
    except Exception as e:                                                       # no usable Chromium here
        await pw.stop()
        pytest.skip(f"chromium did not start: {e!r}"[:200])
    return pw, br, await br.new_page()


YT_PAGE = """<html><body><ytd-masthead><div id="buttons"></div>
<button id="avatar-btn" aria-label="Account menu"><img src="data:," alt="Avatar image"></button></ytd-masthead>
<header><img class="x" alt="Profile picture of sub01"><span id="account-name">SUB-01</span>
<a href="/feed/subscriptions" id="subs">Subscriptions</a></header>
<h1>Tokyo night walk</h1><ytd-subscribe-button-renderer><button id="sub">Subscribe</button></ytd-subscribe-button-renderer>
<like-button-view-model><button id="like">Like</button></like-button-view-model>
<a id="video" href="/watch?v=x">Ramen in Kichijoji</a></body></html>"""
TT_PAGE = """<html><body><nav><a data-e2e="nav-profile" href="/@sub01">Profile</a><a data-e2e="nav-messages" href="/messages">Messages</a>
<a href="/foryou" id="fy">For You</a></nav><div data-e2e="profile-icon"><img alt="sub01"></div>
<button data-e2e="like-icon" id="like">Like</button><button data-e2e="follow-button" id="follow">Follow</button>
<a id="video" href="/@a/video/1">cats</a></body></html>"""


def test_chromium_hides_avatar_name_and_buttons_before_the_screenshot():
    async def go():
        pw, br, page = await _page()
        try:
            vis = "id => getComputedStyle(document.querySelector(id)).visibility"
            await page.set_content(YT_PAGE)
            await page.add_style_tag(content=V.HIDE_ACCOUNT_CSS)
            assert await page.evaluate(V.HIDE_ACCOUNT_JS) >= 1
            for sel in ["#avatar-btn", "#account-name", "header img", "#sub", "#like"]:
                assert await page.evaluate(vis, sel) == "hidden", sel
            for sel in ["#video", "#subs", "h1"]:
                assert await page.evaluate(vis, sel) == "visible", sel
            await page.set_content(TT_PAGE)
            await page.add_style_tag(content=V.HIDE_ACCOUNT_CSS)
            await page.evaluate(V.HIDE_ACCOUNT_JS)
            for sel in ['[data-e2e="nav-profile"]', '[data-e2e="nav-messages"]', '[data-e2e="profile-icon"]',
                        "#like", "#follow"]:
                assert await page.evaluate(vis, sel) == "hidden", sel
            for sel in ["#video", "#fy"]:
                assert await page.evaluate(vis, sel) == "visible", sel
            # the hidden buttons cannot be clicked either, and TARGET_JS describes them as actions
            for sel in ["#like", "#follow"]:
                assert not V.click_ok(await page.eval_on_selector(sel, V.TARGET_JS))
            assert V.click_ok(await page.eval_on_selector("#video", V.TARGET_JS))
        finally:
            await br.close()
            await pw.stop()
    asyncio.run(go())


def test_chromium_private_dom_and_signed_out_checks():
    async def go():
        pw, br, page = await _page()
        try:
            await page.set_content('<title>Watch history - YouTube</title><ytd-browse page-subtype="history"></ytd-browse>')
            assert V.private_dom(await page.evaluate(V.PRIVATE_DOM_JS, V.PRIVATE_SELECTORS))
            await page.set_content('<title>Tokyo walk - YouTube</title><h1>Tokyo walk</h1>')
            assert V.private_dom(await page.evaluate(V.PRIVATE_DOM_JS, V.PRIVATE_SELECTORS)) is None
            await page.set_content('<button data-e2e="top-login-button">Log in</button>')
            seen = await page.evaluate(S.SIGNED_OUT_JS, S.SIGNED_OUT_SELECTORS["tiktok"])
            assert S.Session("tiktok").looks_signed_out(seen)
            await page.set_content('<button data-e2e="top-login-button" style="display:none">Log in</button>')
            assert not await page.evaluate(S.SIGNED_OUT_JS, S.SIGNED_OUT_SELECTORS["tiktok"])
        finally:
            await br.close()
            await pw.stop()
    asyncio.run(go())


def test_new_modules_are_copied_into_the_image():
    from test_dockerfile import copied_paths
    assert {"sessions.py", "view_only.py"} <= copied_paths()


def test_no_session_secret_in_the_repo():
    root = Path(__file__).resolve().parents[1]
    for p in [root / "sessions.py", root / "view_only.py", root / "Dockerfile", root / "docs" / "OPERATIONS.md"]:
        text = p.read_text()
        assert "SUB01_SESSION_TIKTOK=" not in text.replace("SUB01_SESSION_TIKTOK=<", "")
        assert '"sessionid": "' not in text


def test_time_is_real_by_default():
    s = S.load_session("tiktok", tiktok_env(cookie_editor("sessionid", exp=time.time() + 3600)))
    assert s.logged_in and s.check()


# --- integration: browse.py / browse_service.py ----------------------------------------------------------------------
def logged_in(*sites):
    env = {"SUB01_SESSION_TIKTOK": json.dumps([cookie_editor("sessionid", exp=time.time() + 86400)]),
           "SUB01_SESSION_YOUTUBE": json.dumps([playwright_cookie("SID", expires=time.time() + 86400)])}
    return {site: S.load_session(site, env if site in sites else {}) for site in S.SITES}


def browser(*sites):
    import browse
    return browse.Browser(decide=True, sessions=logged_in(*sites))


RAW = [["https://www.tiktok.com/@chef/video/1", "Ramen at midnight in Kichijoji", 9000, True, "", False, ""],
       ["https://www.tiktok.com/@chef", "chef tanaka profile", 900, True, "", False, "Follow chef tanaka"],
       ["https://www.tiktok.com/messages", "Messages inbox", 900, True, "", False, ""],
       ["https://www.tiktok.com/upload?lang=en", "Upload video", 900, True, "", False, ""],
       ["https://www.tiktok.com/coin", "Get Coins now", 900, True, "", False, ""],
       ["https://www.tiktok.com/@chef/video/2", "Like", 900, True, "", False, ""],
       ["https://www.tiktok.com/tag/ramen", "#ramen tag page", 900, True, "", False, ""]]


def test_logged_in_pages_never_offer_actions_or_private_pages():
    import eyes as E
    from browse import Screen
    b = browser("tiktok")
    sc = Screen("phone")
    sc.info, sc.site = {"title": "For You", "host": "tiktok.com", "kind": "page"}, "tiktok"
    page = b.pick_links(RAW, "https://www.tiktok.com/foryou", "feed", sc)
    hrefs = [l["href"] for l in page["links"]]
    assert hrefs == ["https://www.tiktok.com/@chef/video/1", "https://www.tiktok.com/tag/ramen"]
    rows = {l["id"]: [l["href"], l["text"], 0, True, "", False, ""] for l in page["links"]}
    import random
    for seed in range(20):                       # the vote's options come only from these links
        for o in E.local_options(page, "ramen", random.Random(seed)):
            assert V.option_ok(o, rows) or o["action"] not in ("click", "open_video", "play_video")
            if o.get("target") in rows:
                assert V.link_ok(rows[o["target"]][0])


def test_logged_out_keeps_the_old_link_rules():
    from browse import Screen
    b = browser()
    sc = Screen("phone")
    sc.info = {"title": "For You", "host": "tiktok.com", "kind": "page"}
    hrefs = [l["href"] for l in b.pick_links(RAW, "https://www.tiktok.com/foryou", "feed", sc)["links"]]
    assert "https://www.tiktok.com/@chef" in hrefs                     # no session: #60's filter is not applied


def test_links_to_a_logged_in_site_are_filtered_from_any_page():
    from browse import Screen
    b = browser("youtube")
    sc = Screen("desk")
    sc.info = {"title": "ramen blog", "host": "example.com", "kind": "page"}
    raw = [["https://www.youtube.com/watch?v=abc", "Ramen in Tokyo, a night walk", 900, True, "", False, ""],
           ["https://www.youtube.com/@ramen?sub_confirmation=1", "Ramen channel page", 900, True, "", False, ""],
           ["https://www.youtube.com/feed/history", "Your watch history", 900, True, "", False, ""]]
    assert [l["href"] for l in b.pick_links(raw, "https://example.com/", "x", sc)["links"]] == [
        "https://www.youtube.com/watch?v=abc"]


def test_result_pages_on_a_logged_in_site_drop_private_results():
    from browse import Screen
    b = browser("youtube")
    sc = Screen("desk")
    sc.site = "youtube"
    sc.info = {"title": "results", "host": "youtube.com", "kind": "search", "results": [
        {"url": "https://www.youtube.com/watch?v=a", "title": "Tokyo ramen walk at night"},
        {"url": "https://www.youtube.com/playlist?list=WL", "title": "Watch later playlist"}]}
    page = b.result_page(sc, "https://www.youtube.com/results?search_query=ramen")
    assert [l["href"] for l in page["links"]] == ["https://www.youtube.com/watch?v=a"]


def test_accounts_status_for_api_browsing_has_no_secret():
    b = browser("tiktok")
    acc = b.accounts()
    assert acc == {"tiktok": {"state": "logged in", "reason": None},
                   "youtube": {"state": "logged out", "reason": "missing"}}
    b.sessions["tiktok"].expire("login wall")
    assert b.accounts()["tiktok"] == {"state": "logged out", "reason": "login wall"}
    assert SECRET not in json.dumps(acc)


def test_service_state_shows_accounts_without_cookies():
    from aiohttp.test_utils import TestClient, TestServer
    from browse_service import make_app
    b = browser("tiktok", "youtube")

    async def main():
        client = TestClient(TestServer(make_app(b, token="t")))
        await client.start_server()
        try:
            return await (await client.get("/state", headers={"X-Browse-Token": "t"})).text()
        finally:
            await client.close()
    raw = asyncio.run(main())
    st = json.loads(raw)
    assert st["accounts"]["tiktok"]["state"] == "logged in" and st["accounts"]["youtube"]["state"] == "logged in"
    assert SECRET not in raw and "sessionid" not in raw


def test_sessions_reach_the_browser_process_but_not_chromium():
    import browse
    import browse_service
    assert set(S.secret_env_names()) <= set(browse_service.ENV_KEEP)
    assert not set(S.secret_env_names()) & set(browse.CHROMIUM_ENV)


def test_api_browsing_lists_accounts(tmp_path):
    from types import SimpleNamespace
    from live_server import Live
    live = Live("m", True, time_scale=1e6, data_dir=tmp_path)
    acc = {"tiktok": {"state": "logged in", "reason": ""}}
    live.browser = SimpleNamespace(log=[], searches={"per_source_today": {}}, accounts=acc)
    v = live.browsing_view()                                    # GET /api/browsing
    assert v["accounts"] == acc and v["synced"] is True


def test_open_refuses_private_and_action_urls_without_loading_them():
    b = browser("youtube", "tiktok")

    class NoPage:
        url = "about:blank"

        async def goto(self, *a, **k):
            raise AssertionError("must not navigate")

    from browse import Screen
    sc = Screen("desk")
    sc.page = NoPage()
    for url in ["https://www.tiktok.com/messages", "https://www.youtube.com/feed/history",
                "https://studio.youtube.com/", "https://www.youtube.com/playlist?list=WL"]:
        assert asyncio.run(b._open(sc, url, "x", "page")) is False
    assert asyncio.run(b._open(sc, "https://www.youtube.com/@x?sub_confirmation=1", "x", "page")) is False
    assert b.last_skip.startswith("a YouTube page")            # #89 live: YouTube's pages are never opened at all


async def _browser_screen(b, device="desk"):
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed")
    try:
        sc = await b._ensure(device)
    except Exception as e:                                                       # no usable Chromium here
        pytest.skip(f"chromium did not start: {e!r}"[:200])
    return sc


def test_chromium_session_cookies_live_only_in_their_sites_context():
    b = browser("tiktok", "youtube")

    async def go():
        sc = await _browser_screen(b)
        try:
            public_ctx = sc.ctx
            await b._use(sc, "https://www.tiktok.com/foryou")
            assert sc.site == "tiktok" and sc.ctx is not public_ctx
            tt = await sc.ctx.cookies()
            assert {c["name"] for c in tt} == {"sessionid"}
            assert all(S.host_in(c["domain"], ("tiktok.com",)) for c in tt if c["name"] == "sessionid")
            await b._use(sc, "https://www.youtube.com/")
            yt = await sc.ctx.cookies()
            assert {c["name"] for c in yt} == {"SID", "PREF"} and "sessionid" not in {c["name"] for c in yt}
            assert next(c for c in yt if c["name"] == "PREF")["value"] == "f2=8000000"    # Restricted Mode kept
            await b._use(sc, "https://example.com/")
            assert sc.site is None and sc.ctx is public_ctx
            pub = await public_ctx.cookies()
            assert {c["name"] for c in pub} == {"PREF"}                         # logged out: no session cookie
            assert b.sessions["tiktok"].logged_in
            await b._use(sc, "https://www.tiktok.com/foryou")
            await b._logout(sc, "login wall")                                   # the fallback
            assert sc.site is None and sc.ctx is public_ctx and "tiktok" not in sc.sites
            assert not b.sessions["tiktok"].logged_in and b.accounts()["tiktok"]["state"] == "logged out"
            await b._use(sc, "https://www.tiktok.com/foryou")
            assert sc.site is None and sc.ctx is public_ctx
        finally:
            await b.close()
    asyncio.run(go())


def test_chromium_private_page_never_shot_and_avatar_hidden():
    b = browser("youtube")

    async def go():
        sc = await _browser_screen(b)
        try:
            await b._use(sc, "https://www.youtube.com/")
            await sc.page.set_content('<title>Watch history - YouTube</title><ytd-browse page-subtype="history">'
                                      '<a href="/watch?v=a">a video he watched</a></ytd-browse>')
            sc.shot, before = None, sc.shot_id
            assert not await b._shoot(sc) and sc.shot is None and sc.shot_id == before
            assert b.last_skip == "private"
            await sc.page.set_content(YT_PAGE)
            assert await b._shoot(sc) and sc.shot
            vis = "id => getComputedStyle(document.querySelector(id)).visibility"
            for sel in ["#avatar-btn", "#account-name", "#sub", "#like"]:
                assert await sc.page.evaluate(vis, sel) == "hidden", sel
            assert await sc.page.evaluate(vis, "#video") == "visible"
            assert await b._shoot(sc) and await b._shoot(sc)
            assert await sc.page.evaluate("() => document.querySelectorAll('#sub01-hide-account').length") == 1
        finally:
            await b.close()
    asyncio.run(go())
