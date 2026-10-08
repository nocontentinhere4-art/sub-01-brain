"""#89 evening (2026-10-04 19:46-21:10 Tokyo): 10 desk videos in a row on /api/screens, three "w/ Casey Muratori"
talks one after another and three coffee-gear "best of 2026" lists. Here: at most CHANNEL_STREAK_MAX videos in a row
from one channel or with one guest; after VIDEO_RUN_MAX desk videos in a row a short break of pages / searches; a
shopping list goes to the back of the queue (not banned).

    python -m pytest tests/test_video_mix.py -q
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browse  # noqa: E402


def card(vid, title, author):
    return {"url": f"https://www.youtube.com/watch?v={vid}", "title": title, "author": author, "hashtags": [],
            "thumb": "", "embed": f"https://www.youtube-nocookie.com/embed/{vid}", "host": "youtube.com"}


def shown(b, vid, title, channel):
    b._desk_run({"url": f"https://www.youtube.com/watch?v={vid}", "title": title, "channel": channel,
                 "embed": "https://www.youtube-nocookie.com/embed/" + vid})


def test_guests_and_channels_are_keys():
    assert browse.video_keys("Zen 5 And AI Doom w/ Casey Muratori", "ThePrimeTime") == {"casey muratori", "theprimetime"}
    assert browse.video_keys("Designing My First Game with Casey Muratori", "") == {"casey muratori"}


def test_a_third_video_with_the_same_guest_or_channel_in_a_row_is_not_offered():
    b = browse.Browser(decide=False)
    shown(b, "aaaaaaaaaa1", "The Magic Of ARM w/ Casey Muratori", "ChannelA")
    shown(b, "aaaaaaaaaa2", "Zen 5 And AI Doom w/ Casey Muratori", "ChannelB")
    assert not b._card_ok(card("aaaaaaaaaa3", "Designing My First Game w/ Casey Muratori", "ChannelC"))   # the guest
    assert b._card_ok(card("aaaaaaaaaa4", "Legendary Game Dev Jonathan Blow", "ChannelB"))   # one ChannelB so far
    shown(b, "aaaaaaaaaa4", "Legendary Game Dev Jonathan Blow", "ChannelB")
    assert not b._card_ok(card("aaaaaaaaaa5", "Another talk", "ChannelB"))                  # two ChannelB in a row
    b._desk_run({"url": "https://www.theverge.com/x", "title": "a story"})                 # a page in between
    assert b.video_run == 0


def test_after_four_desk_videos_in_a_row_a_break_of_pages(monkeypatch):
    b = browse.Browser(decide=False)
    for i in range(browse.VIDEO_RUN_MAX):
        shown(b, f"bbbbbbbbbb{i}", f"talk {i}", f"Channel{i}")
    assert b.video_break_until > time.time() and b.video_run == 0
    assert b._video_break("desk", "video") is None and b._video_break("phone", "shorts") == "shorts"
    b.video_break_until = time.time() - 1                      # the break is over: videos again
    assert b._video_break("desk", "video") == "video"


def test_shopping_lists_go_to_the_back_not_away():
    for t in ("Top 10 Home Coffee Roasters You Need in 2026!", "Discover the Best Automatic Pour Over Coffee Makers of 2026!",
              "Best headphones to buy", "Espresso machine buying guide"):
        assert browse.SHOPPING_LIST.search(t), t
    for t in ("Coffee Roasting Basics", "The best goal of the season", "Top 10 anime fights"):
        assert not browse.SHOPPING_LIST.search(t), t
    cands = [card("c1", "Top 10 Home Coffee Roasters You Need in 2026!", "x"), card("c2", "Coffee Roasting Basics", "y")]
    order = sorted(cands, key=lambda c: bool(browse.SHOPPING_LIST.search(c["title"])))
    assert [c["title"] for c in order][0] == "Coffee Roasting Basics"
