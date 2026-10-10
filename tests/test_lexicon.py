"""The shared money / hype lexicon (S3) and the chat filter's lists (S3, S6, T2): one table per filter, the lines the
plan names plus the live cases, blocked and allowed. Every filter that takes the lexicon must agree on the blocked
list; the ones other modules wire in (browse.title_ok / media_title_ok, eyes.query_ok, mind.reply_problem) are checked
as soon as their module imports `lexicon` (skipped, with the reason, until then)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chat  # noqa: E402
import clips  # noqa: E402
import lexicon as L  # noqa: E402

# --- S3: trading promotion and buy advice, in any filter -------------------------------------------------------------
MONEY_BLOCKED = [
    "Is Bitcoin a good buy right now? Price prediction 2026", "Should you buy Ethereum before it moons",
    "Learn how to trade like a pro", "Presale is live now", "buy this coin now", "should I buy sol",
    "Top 5 stocks to buy now",
    # live 2026-10-09 (chat and the monitor)
    "take a look on pump fun, and learn how to trade like a pro", "when you wake up, look on fomo",
    "How to make millions on FOMO app... newbie tutorial!",
    "#1 Prop Firm Scalper: The ICT Trader Who Made $2.5+ Million With A 40% Win Rate",
    "Day Trading for beginners", "make money online fast", "crypto gems 100x", "$PEPE 100x gem",
    "how to make $5 a day", "passive income ideas", "join the whitelist", "buy the dip", "investing in crypto 101",
    "not financial advice but ape in", "best altcoins to buy before the next bull run", "wagmi",
]
MONEY_ALLOWED = [
    "what is the price of ramen", "do you like dumplings", "pumpkin soup stock", "Stockholm syndrome", "I bought bread",
    "buy bread", "did you buy bread?", "goodbye", "How to make 10 minute ramen", "How to use AirDrop on iPhone",
    "Taylor Swift presale tickets", "Galaxy S23 100x zoom", "Pokemon trading cards", "Price Tag",
    "How 1 Person Solved A $1,000,000 Puzzle!", "How to make magnetic slime at home", "Bitch Better Have My Money",
    "Kill the Rich", "Bitcoin falls 5% as markets wobble",                 # a coin in the NEWS is neutral news (owner)
    "the fear of heights", "give me a hug", "who removed it",
]
# ... and in the chat: a push to buy a coin (BUY_PRESSURE) or the coin itself (COIN_NAMES) is never on everyone's screen
CHAT_PUSHES = ["buy it now", "sell this before it drops", "whitelist me", "mint this now", "invest in it"]
COIN_NAMES = ["bitcoin", "did you see btc today", "solana is pumping", "crypto is the future"]
CHAT_ONLY_BLOCKED = CHAT_PUSHES + COIN_NAMES


@pytest.mark.parametrize("text", MONEY_BLOCKED)
def test_lexicon_blocks(text):
    assert L.money_talk(text), text
    assert L.money_talk(text, chat=True), text


@pytest.mark.parametrize("text", MONEY_ALLOWED)
def test_lexicon_allows(text):
    assert L.money_talk(text) is None, text


@pytest.mark.parametrize("text", CHAT_PUSHES)
def test_coin_pushes_are_chat_only(text):
    assert L.money_talk(text, chat=True) and L.money_talk(text) is None, text


@pytest.mark.parametrize("text", COIN_NAMES)
def test_coin_names_are_for_messages_only_a_search_may_name_a_coin(text):
    """Owner: memecoin / altcoin news is readable, so a search or a title may name a coin; a chat line may not."""
    assert L.money_talk(text, names=True) and L.money_talk(text, chat=True) is None, text
    assert chat.blocked(text) is None and chat.message_blocked(text) == "no trading or get-rich talk", text
    import eyes
    assert eyes.query_ok("memecoin news") == "memecoin news" and eyes.query_ok("bitcoin price") == "bitcoin price"


def test_norm_reads_punctuation_as_spaces_and_keeps_digits_and_dollars():
    assert L.norm("Pump.Fun — PUMP-FUN!") == "pump fun pump fun"
    assert L.norm("make $5k/day, 100x") == "make $5k day 100x"
    assert L.norm("Mátame, judíos") == "matame judios"
    assert L.money_talk("") is None and L.money_talk(None) is None


def test_no_bare_stems_in_the_lexicon():
    """Owner: never ban bare buy / price / stock / pump / dump as whole words (buy_bread, price of ramen, soup stock)."""
    for word in ("buy", "price", "stock", "stocks", "pump", "dump", "coin", "trading", "invest", "money", "moon"):
        assert L.money_talk(word) is None, word
        assert L.money_talk(f"the {word} of the day") is None, word


# --- chat.blocked: the message rules (text) and the song / video rule (media) ---------------------------------------
# the chat keeps its older rules too (a "$" amount, a ticker, "airdrop" and a swear word are refused on their own), so a
# message is checked for *a* reason; the lexicon's reason where no other rule fires first. chat.check (a message),
# clean_nick and check_teach go through message_blocked.
@pytest.mark.parametrize("text", MONEY_BLOCKED + CHAT_ONLY_BLOCKED)
def test_chat_drops_money_talk(text):
    assert chat.message_blocked(text), text
    assert chat.check(text, "k", chat.RateLimiter(), chat.Dedupe()) == (False, chat.message_blocked(text))


@pytest.mark.parametrize("text", ["Learn how to trade like a pro", "should I buy sol", "buy this coin now",
                                  "when you wake up, look on fomo", "Top 5 stocks to buy now"])
def test_chat_names_the_lexicon_rule(text):
    assert chat.blocked(text) == chat.message_blocked(text) == "no trading or get-rich talk", text


CHAT_ALLOWED = ["what is the price of ramen", "do you like dumplings", "pumpkin soup stock", "Stockholm syndrome",
                "I bought bread", "buy bread", "did you buy bread?", "goodbye", "How to make 10 minute ramen",
                "Galaxy S23 100x zoom", "Pokemon trading cards", "Price Tag", "How to make magnetic slime at home",
                "Kill the Rich", "the fear of heights", "give me a hug", "who removed it", "good morning sub-01"]


@pytest.mark.parametrize("text", CHAT_ALLOWED)
def test_chat_keeps_ordinary_messages(text):
    assert chat.blocked(text) is None and chat.message_blocked(text) is None, text


def test_chat_de_leets_before_the_lexicon():
    assert chat.blocked("g3t r1ch w1th cryp70 s1gnals") == "no trading or get-rich talk"
    assert chat.blocked("pump fun is live") == "no trading or get-rich talk"
    assert chat.blocked("pump.fun is live")                             # (a link, refused earlier)


def test_song_and_video_titles_refuse_promotion_and_advice_but_not_coin_names():
    for t in ("Get Rich or Die Tryin'", "Learn to trade like a pro (full course)", "Top 5 stocks to buy now"):
        assert chat.blocked(t, media=True) == "no trading or get-rich talk", t
    for t in ("Price Tag", "Bitcoin (Official Video)", "Bitch Better Have My Money", "Stockholm Syndrome"):
        assert chat.blocked(t, media=True) is None, t
    assert chat.HYPE is L.HYPE                                      # one list, re-exported


# --- S6: slurs and self-harm with spaced letters or other wordings -----------------------------------------------
@pytest.mark.parametrize("text", ["n i g g e r", "k y s", "kys", "KYS!", "hang yourself", "go die in a fire",
                                  "neck yourself", "end yourself", "cut yourself", "off yourself", "drink bleach",
                                  "you f a g", "k.y.s", "k-y-s"])
def test_spaced_slurs_and_self_harm_wordings_are_blocked(text):
    assert chat.blocked(text) == "insults are not allowed", text


@pytest.mark.parametrize("text", ["the rope bridge in Kyoto", "a b c d", "i am ok", "die hard is on tonight",
                                  "bleach the anime", "cut the cake yourself", "hang in there"])
def test_ordinary_letters_and_words_pass(text):
    assert chat.blocked(text) is None, text


def test_normalise_joins_runs_of_single_letters_only():
    assert chat.normalise("k y s") == "kys" and chat.normalise("n i g g e r please") == "nigger please"
    assert chat.normalise("a b") == "a b"                           # two letters: not a word spelt out
    assert chat.normalise("judíos città Mátame") == "judios citta matame"


# --- clips.safe: captions take the lexicon too -----------------------------------------------------------------------
def test_clip_captions_drop_money_talk():
    assert clips.safe("learns how to trade like a pro") == "" and clips.safe("should you buy the dip") == ""
    assert clips.safe("reads about Inokashira Park") == "reads about Inokashira Park"
    assert clips.safe("buys bread at the bakery") == ""            # clips.FINANCE: bare buy stays out of a clip


# --- S4: a `why` from the chat never quotes the viewer -----------------------------------------------------------
def test_public_why_cuts_the_viewer_text_after_a_chat_origin():
    from live_server import public_why
    a = {"title": "Kichijoji", "why": "a viewer's wish in chat: “look up Kichijoji please”"}
    assert public_why(a)["why"] == "a viewer's wish in chat" and "Kichijoji please" in a["why"]   # a copy by default
    assert public_why({"why": "from chat: “buying cheap sneakers”"})["why"] == "from chat"
    b = {"why": "from chat: \"hello\""}
    assert public_why(b, copy=False) is b and b["why"] == "from chat"
    for keep in ("followed a link from “Tokyo” · chose it: memory", "one of his interests (anime)", "", None):
        assert public_why({"why": keep})["why"] == keep
    assert public_why(None) is None and public_why({"title": "x"}) == {"title": "x"}


# --- every filter agrees on the blocked list (the other modules' wiring: browse, eyes, mind) -------------------------
def _wired(mod):
    return "lexicon" in Path(mod.__file__).read_text(encoding="utf-8")


def test_every_screen_filter_refuses_the_blocked_list():
    import browse
    import eyes
    import mind
    missing = [m.__name__ for m in (browse, eyes, mind) if not _wired(m)]
    if missing:
        pytest.skip(f"S3: {', '.join(missing)} not yet wired to lexicon.money_talk (other workers)")
    leaks = [(name, t) for t in MONEY_BLOCKED for name, ok in (
        ("title_ok", browse.title_ok(t)), ("media_title_ok", browse.media_title_ok(t)),
        ("query_ok", eyes.query_ok(t) is not None), ("reply_problem", mind.reply_problem(t) is None)) if ok]
    assert leaks == []
