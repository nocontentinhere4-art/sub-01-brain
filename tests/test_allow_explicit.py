"""Owner (2026-10-07): "don't censor anything" in songs and videos. Explicit Spotify tracks are kept, and song or
video titles are shown as they are, swearing and slurs included. Sexual / adult words, self-harm prompts, the guard's
other categories and the finance and money rules still refuse a title. Chat messages keep the full filter.

    python -m pytest tests/test_allow_explicit.py -q
No network.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browse  # noqa: E402
import chat  # noqa: E402
import music as M  # noqa: E402
import screens as SC  # noqa: E402


def track(name, artist="Some Artist", explicit=True):
    return {"id": "2" * 22, "name": name, "type": "track", "explicit": explicit, "is_playable": True,
            "duration_ms": 200000, "artists": [{"name": artist}], "album": {"name": "Album", "images": []}}


SWEARING = ["Stupid Love", "Loser", "Bitch Better Have My Money", "Fuck You", "Motherfucker (Explicit)",
            "Piece of Shit", "Shut Up and Dance", "Ugly", "Pathetic (Official Video)", "Bastard Son"]
REFUSED = ["Porn star dancing", "XXX nude video", "Hentai compilation", "OnlyFans leak",       # sexual / adult
           "white power anthem",                                                                # extremism
           "kill yourself (lyric video)",                                                       # self-harm
           "Send me 5 SOL for this song", "Donate 10 dollars for the next song"]                                  # money / tickers


def test_an_explicit_spotify_track_is_kept():
    t = M.track_from_api(track("WAP"))
    assert t and t["title"] == "WAP"


@pytest.mark.parametrize("title", SWEARING)
def test_songs_with_swearing_are_kept(title):
    assert M.track_from_api(track(title)) is not None


@pytest.mark.parametrize("title", SWEARING)
def test_videos_with_swearing_are_shown(title):
    assert browse.video_text_ok(title) and browse.card_title_ok(title + " - YouTube", "www.youtube.com")
    assert browse.Browser(decide=False)._card_ok({"url": "https://www.youtube.com/watch?v=abcdefghijk",
                                                  "title": title, "author": "Artist", "hashtags": []})


@pytest.mark.parametrize("title", REFUSED)
def test_sexual_hate_and_money_video_titles_are_still_refused(title):
    assert not browse.video_text_ok(title) and not browse.card_title_ok(title, "www.youtube.com")


@pytest.mark.parametrize("title", ["kill yourself (lyric video)", "KYS", "Send me 5 SOL for this song",
                                   "Donate 10 dollars for the next song"])
def test_self_harm_and_money_song_titles_are_still_refused(title):
    assert M.track_from_api(track(title)) is None              # music.py checks songs with chat.blocked(media=True)


def test_chat_and_ordinary_pages_keep_the_full_filter():
    assert chat.blocked("you are stupid") == "insults are not allowed"
    assert chat.blocked("Stupid Love", media=True) is None
    assert not browse.display_ok("Stupid Love") and not browse.card_title_ok("Loser", "example.org")
    assert M.wish("play fuck you") is None                     # a viewer's wish is a chat message


def test_the_public_card_shows_a_swearing_video_title_and_its_player():
    s = SC.ScreensStatus()
    s.seen({"url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "Loser (Official Video)"})
    row = s.public(browse.card_title_ok)["last"][0]
    assert row["title"] == "Loser (Official Video)" and "embed" in row


@pytest.mark.parametrize("title", ["Porn star dancing", "XXX nude video", "Hentai compilation", "OnlyFans leak",
                                   "white power anthem", "Self-harm song"])
def test_adult_and_hate_song_titles_are_refused_like_videos(title):
    assert M.track_from_api(track(title)) is None
    assert M.track_from_api(track("A Song", artist=title)) is None


def test_an_explicit_swearing_track_is_kept_while_an_adult_one_is_refused():
    assert M.track_from_api(track("Fuck You", explicit=True)) is not None
    assert M.track_from_api(track("Porn star dancing", explicit=True)) is None


SLUR_TITLES = ["Niggas in Paris", "My Nigga (feat. Lil Wayne)", "Faggot (Official Video)", "Bad Bitch Whore Slut Remix",
               "Cunt (Explicit)"]


@pytest.mark.parametrize("title", SLUR_TITLES)
def test_songs_and_videos_with_slurs_are_shown_as_they_are(title):
    assert M.track_from_api(track(title)) is not None
    assert browse.video_text_ok(title) and browse.card_title_ok(title, "www.youtube.com")


def test_porn_and_kill_yourself_titles_are_still_refused():
    for title in ("Porn star dancing", "kill yourself (lyric video)"):
        assert M.track_from_api(track(title)) is None
        assert not browse.video_text_ok(title) and not browse.card_title_ok(title, "www.youtube.com")


def test_chat_still_refuses_slurs():
    assert chat.blocked("Niggas in Paris") == "insults are not allowed"
    assert chat.blocked("Niggas in Paris", media=True) is None
    assert M.wish("play niggas in paris") is None              # a viewer's wish is a chat message


INCITEMENT = ["kill all the f4gg0ts", "Kill all the Jews", "burn all the immigrants (lyric video)", "Gas the Muslims",
              "Death to all gays", "hang those n1ggers", "Death to the Mexicans!"]


@pytest.mark.parametrize("title", INCITEMENT)
def test_incitement_titles_are_refused(title):
    assert M.track_from_api(track(title)) is None
    assert not browse.video_text_ok(title) and not browse.card_title_ok(title, "www.youtube.com")


@pytest.mark.parametrize("title", ["Niggas in Paris", "Kill All the Lights", "Burn It Down", "Death to Disco",
                                   "Kill the Noise", "Gay Bar", "Jews of Brooklyn (documentary)",
                                   "Women Who Kill (Official Trailer)", "Hang Up on Me"])
def test_slurs_and_ordinary_violent_words_are_not_incitement(title):
    assert browse.video_text_ok(title) and M.track_from_api(track(title)) is not None


# --- review G24 (F1-F5): the incitement rule on a real-title corpus and a hold-out ------------------------------------
# BENIGN: real song, film, game, YouTube, news and tutorial titles; many use violent verbs innocently, some next to a
# word that is also a group word ("Japanese", "Chinese", "Roma", "women"). INCITING: explicit calls to violence against
# a group (a few real chants, the rest realistic phrasings, spellings, inflections, Italian and Spanish). NATION:
# "death to <country>" chants, left to the owner. The hold-out was written after the rule, to check it is not a fit.
BENIGN = [
    # --- songs, English
    "Kill Bill", "Killing in the Name", "Killing Me Softly with His Song", "Kill the Lights", "Kill Em with Kindness",
    "Kill This Love", "Killer Queen", "Mr. Brightside", "Kill of the Night", "Kill the DJ", "Kill All Hippies",
    "Kill the Poor", "Kill the Rich", "Kill Your Darlings", "Kill My Vibe", "Shoot to Thrill", "I Shot the Sheriff",
    "Bang Bang (My Baby Shot Me Down)", "Shoot the Runner", "Shoot to Kill", "Shooting Stars", "Shooting Star",
    "Fight for Your Right", "Fight Song", "The Fight", "Fighter", "Bombtrack", "Bombs Away", "Da Bomb", "The Bomb",
    "Attack", "Attack Attack!", "Heart Attack", "Drop It Like It's Hot", "Drop the World", "Don't Drop That Thun Thun",
    "Fire Burning", "Set Fire to the Rain", "We Didn't Start the Fire", "Girl on Fire", "Light My Fire", "Ring of Fire",
    "Burn", "Burn It Down", "Burn the Witch", "Burnin' Up", "Explode", "Exploder", "Gun", "Gunpowder & Lead",
    "Murder on the Dancefloor", "Smooth Criminal", "Psycho Killer", "Hang the DJ (Panic)", "Hang Me Up to Dry",
    "Hanging by a Moment", "Death to Everyone", "Death of a Bachelor", "Stockholm Syndrome", "Price Tag",
    "I Heard It Through the Grapevine", "Skyscraper", "Sexual Healing", "Weapon of Choice", "Cannibal", "Scandal",
    "Give It 2 Me", "Woodstock", "Women (Def Leppard)", "Independent Women, Pt. 1", "Russians (Sting)",
    "Turning Japanese", "Chinese Democracy", "Indians (Anthrax)", "Asian Girlz", "Gypsies, Tramps & Thieves",
    "Mexican Radio", "Big in Japan", "Death to the Hypocrites",
    "Top Hits 2000 - 2010 Mix",
    # --- songs, Italian
    "Fuoco nel fuoco", "Bomba o non bomba", "La guerra di Piero", "Uccidete la luna di marzo", "Il cielo in una stanza",
    "Inno Nazionale Italiano", "Sparami (Lo-Fi)", "Fai rumore", "Brucia la città", "Uccidimi (Vasco)",
    "Il ballo del qua qua", "Volare", "Ignazio Boschetto - Il Volo live", "Sparare alla luna",
    # --- songs, Spanish
    "La Bomba", "Fuego", "Mátame", "Dispárame, dispara", "Bombón", "Explota mi corazón", "Fuego de noche, nieve de día",
    "Matador", "La Bamba", "Despacito", "Quémalo", "Pégale", "Gasolina", "Quiero que me mates",
    # --- films, TV, games
    "Kill the Irishman (2011) Trailer", "Shoot 'Em Up (2007) Trailer", "Fight Club (1999) Official Trailer",
    "Texas Chainsaw Massacre Gameplay", "Killing Floor 2 Gameplay", "Suicide Squad Trailer",
    "Call of Duty: Kill Confirmed", "Fortnite Kill Compilation #12", "Minecraft but I Can't Stop Killing",
    "How to Kill the Ender Dragon in 5 Minutes", "Elden Ring - How to Kill Malenia", "Attack on Titan Opening",
    "Kill Russians in Arma 3 - Cold War Mod", "Shoot the Chinese Dragon Boss - Wo Long", "Battlefield 1 Bomb Run",
    "Valorant Ace - Drop the Spike", "CS2: Bomb Defuse Clutch", "Hitman: Kill Everyone Challenge",
    # --- tutorials, gardening, cooking, photography
    "How to Kill Japanese Beetles Naturally", "How to Kill Japanese Knotweed for Good", "Kill Chinese Privet Fast",
    "How to Shoot Japanese Street Photography", "How I Shoot Women's Portraits with Natural Light",
    "How to Shoot Chinese New Year Fireworks", "Burn Chinese Lanterns Safely?", "Shoot Indians Cricket Highlights",
    "How to Kill Weeds in Your Lawn", "How to Kill Fruit Flies in 2 Minutes", "Fire Drill Training Video",
    "How to Drop Ship in 2026", "Fire Your Boss: Freelance Guide", "Bomb Pop Recipe", "Bath Bomb DIY",
    "How to Fight a Bear (Don't)", "Fire Safety for Kids", "Cooking with Fire - Japanese BBQ",
    "Gas the Car Up: Road Trip Vlog", "Hang Drywall Like a Pro", "Hang Christmas Lights Without Nails",
    "Kill the Whites of Your Laundry Stains (Old Hack)",
    # --- news / sport
    "Lazio slaughter Roma 3-0 in the derby", "Police shoot suspect after chase", "Ukraine strikes kill Russians at base",
    "Gas prices drop again", "Bomb threat closes school", "Women's World Cup Final Highlights",
    "Murder Mystery 2 (Netflix) Review", "How the Japanese Fight Earthquakes", "Mexicans Fight for Water Rights",
    "Death to 2020 (Netflix) Trailer", "Kill the Messenger (2014) Trailer",
    # --- vlogs, misc YouTube
    "I Tried to Kill My Phone Addiction", "Killing It at the Gym", "Shooting Hoops with the Boys", "Dropping My New Album",
    "This Song Is Fire 🔥", "Exploding Watermelon Challenge", "Attack of the Killer Tomatoes Review",
    "Japanese Kill Bill Sword Scene Breakdown", "Kill Time in Tokyo: 10 Things to Do", "Kill the Noise - Live Set",
]

INCITING = [
    # real, widely reported chants / titles
    "Kill the Boer", "Death to Arabs",
    "Shoot the Boer",
    # plain English phrasings the regex intends to catch
    "Kill All Jews", "Gas the Jews", "Death to Muslims", "Kill the Gays", "Hang All Immigrants", "Burn the Refugees",
    "Exterminate the Roma", "Death to all Christians", "Lynch the Blacks",
    # spelling and punctuation variants
    "K1ll all J3ws", "kill-all-jews", "#KillAllMuslims", "Kill_the_gays", "kill/the/immigrants", "death 2 jews",
    "Kill all of the Muslims",
    # inflections and word order
    "Killing all the Jews", "Kill every Jew", "Kill every immigrant", "Kill every woman", "Kill every gay",
    "Muslims must die", "All Jews should be killed", "Gays deserve death", "Shoot every Mexican", "Kill every Muslim",
    # other verbs
    "Nuke the Muslims", "Bomb the Jews", "Stab the Immigrants", "Massacre the Christians", "Wipe out the Roma",
    "Behead the Christians",
    # Italian and Spanish
    "Uccidete tutti gli ebrei", "Morte ai musulmani", "Morte agli immigrati", "Matar a todos los judíos",
    "Muerte a los gitanos",
]

NATION = ["Death to America", "Death to Israel", "Death to Russia"]

HOLDOUT_BENIGN = ["Morte a Venezia (Death in Venice) 1971", "Kill the Japanese Beetle Grubs Before Spring",
                  "Shoot Russian Film Cameras: Zenit Review", "Burn the Witch - Radiohead", "Kill Chinese Elm Suckers",
                  "Gypsy Kings - Bamboleo", "Women Who Fight: UFC Documentary", "How Jews Celebrate Hanukkah",
                  "Muslims Explain Ramadan", "Why Japanese Trains Are Never Late", "Death to Smoochy Trailer",
                  "Shooting Japanese Maple Bonsai Timelapse", "Hang the Indian Flag Correctly", "Kill the Roma Defence?",
                  "Uccidere un usignolo - recensione", "Matar a un ruiseñor (To Kill a Mockingbird)",
                  "Bomb the Bass - Beat Dis", "Gas Gas Gas - Manuel", "Burn Mexican Sage for Cleansing"]
HOLDOUT_INCITING = ["KILL ALL THE JEWS!!!", "death_to_muslims", "Let's burn the gays", "Immigrants must die",
                    "Ammazzate tutti gli zingari", "Muerte a los judíos", "kill every single arab", "#GasTheJews"]


def test_incitement_corpus_has_no_false_positive_or_miss():
    assert len(BENIGN) + len(INCITING) >= 150
    assert [t for t in BENIGN if chat.incitement(t)] == []
    assert [t for t in INCITING if not chat.incitement(t)] == []


def test_incitement_holdout_has_no_false_positive_or_miss():
    assert [t for t in HOLDOUT_BENIGN if chat.incitement(t)] == []
    assert [t for t in HOLDOUT_INCITING if not chat.incitement(t)] == []


def test_nation_chants_are_left_to_the_owner():
    assert not any(chat.incitement(t) for t in NATION)


def test_inciting_titles_are_refused_as_songs_and_videos():
    for t in INCITING + HOLDOUT_INCITING:
        assert M.track_from_api(track(t)) is None and not browse.video_text_ok(t), t


def test_normalise_folds_accents_instead_of_deleting_them():
    assert chat.normalise("judíos città Mátame") == "judios citta matame"


@pytest.mark.parametrize("title", ["Inno Nazionale Italiano", "I Heard It Through the Grapevine", "Killing in the Name",
                                   "Top Hits 2000 - 2010 Mix", "Give It 2 Me", "Stockholm Syndrome",
                                   "Ignazio Boschetto - Il Volo live", "Murder on the Dancefloor", "Shooting Stars",
                                   "Skyscraper", "Weapon of Choice"])
def test_songs_and_videos_follow_one_rule(title):
    assert browse.video_text_ok(title) and browse.card_title_ok(title, "www.youtube.com")
    assert M.track_from_api(track(title)) is not None


@pytest.mark.parametrize("title", ["Porn star dancing", "XXX nude video", "Self-harm song", "Suicide tutorial",
                                   "kill yourself (lyric video)", "Send 50 dollars to my wallet",
                                   "https://example.com/song"])
def test_sexual_self_harm_and_money_titles_are_refused_as_songs_and_videos(title):
    assert not browse.video_text_ok(title) and M.track_from_api(track(title)) is None


def test_ordinary_pages_keep_the_full_filter():
    assert not browse.display_ok("Inno Nazionale Italiano")          # research.BLOCK still applies to web pages
    assert chat.blocked("call me on 2000 - 2010") is not None         # chat keeps the phone and money rules
    assert chat.blocked("give me 2") is not None


# a second hold-out (G18), written while porting the rule: commas, chess lines, trailing "now", stops between words
HOLDOUT2_BENIGN = ["Kill the Indian, Save the Man (Documentary)", "White Will Die? Chess Opening Trap",
                   "Black Will Die in 3 Moves", "Hang the DJ - The Smiths", "Kill Bill Vol. 1 Trailer",
                   "Shoot to Thrill", "Burning Japanese Maple Leaves", "The Women Will Burn It Down: Feminist Punk",
                   "Killing Chinese Elm Seedlings", "Death to the Pixies (Album)", "Kill Em With Kindness",
                   "Uccidere il drago", "Purge the Korean Bugs - Lost Ark Guide",
                   "Kill the Japanese, Mr. Miyagi? No: a Karate Kid Theory"]
HOLDOUT2_INCITING = ["Sparate agli zingari", "Spara ai negri", "kill. all. the. jews", "KILL ALL MUSLIMS NOW",
                     "gas every jew", "Let us kill the immigrants", "we must exterminate the gypsies",
                     "burn all the f@gg0ts", "Death To All Muslims!!!", "Jews will burn", "Black people must die",
                     "matad a los moros", "Muerte a todas las mujeres", "Ammazza i froci", "Kill the Jews, now"]


def test_incitement_second_holdout():
    assert [t for t in HOLDOUT2_BENIGN if chat.incitement(t)] == []
    assert [t for t in HOLDOUT2_INCITING if not chat.incitement(t)] == []


def test_music_without_browse_fails_closed():
    """F12: music imports the shared rule once; without browse no API track is shown (never an unfiltered one)."""
    import subprocess
    code = ("import sys; sys.modules['browse'] = None\n"
            "import music\n"
            "t = {'id': '2' * 22, 'name': 'Any Song', 'is_playable': True, 'artists': [{'name': 'A'}], 'album': {}}\n"
            "print(music.track_from_api(t))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path(__file__).resolve().parents[1]), timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "None" and "media_title_ok unavailable" in out.stdout



@pytest.mark.parametrize("title", ["Sex on Fire", "Let's Talk About Sex", "$uicideboy$ - Paris",
                                   "Suicideboys - Antarctica", "$5 Pizza Hack", "Pizza for 5 eur",
                                   "A$AP Rocky - Praise the Lord", "Ke$ha - TiK ToK", "Give It 2 Me"])
def test_sex_artist_stylings_and_prices_pass_as_songs_and_videos(title):
    """Coordinator: BAD_HOST judges hosts, not titles; a "$" in an artist's name and bare prices are not money."""
    assert browse.video_text_ok(title) and M.track_from_api(track(title)) is not None


@pytest.mark.parametrize("title", ["Porn star dancing", "XXX nude video", "Suicide tutorial", "Send me 5 SOL",
                                   "send $50 now", "Venmo me for the full song", "$PUMP to the moon",
                                   "$PEPE 100x gem"])
def test_porn_self_harm_and_money_requests_are_still_refused(title):
    assert not browse.video_text_ok(title) and M.track_from_api(track(title)) is None


def test_web_pages_and_chat_keep_the_host_ticker_and_price_rules():
    assert not browse.display_ok("Sex on Fire")                       # web titles: BAD_HOST still applies
    assert chat.blocked("$PUMP to the moon") and chat.blocked("only $5 today")



@pytest.mark.parametrize("title", ["Cocaine", "Heroin", "Casino Royale (2006) Trailer", "Gin and Juice",
                                   "Meth Lab Ep. 3", "The Gambler - Kenny Rogers"])
def test_drug_and_gambling_words_pass_as_songs_and_videos(title):
    assert browse.video_text_ok(title) and M.track_from_api(track(title)) is not None
    assert not browse.display_ok(title) or title in ("Gin and Juice", "The Gambler - Kenny Rogers")  # web: full words


@pytest.mark.parametrize("title", ["Beheading video", "neo-nazi rally", "Rape scene", "XXX nude video",
                                   "Suicide tutorial", "Kill Yourself (Part III)", "Self-harm song"])
def test_gore_extremism_sexual_and_self_harm_still_refuse(title):
    assert not browse.video_text_ok(title) and M.track_from_api(track(title)) is None



def test_video_search_results_follow_the_media_rule():
    rs = [{"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "title": "Eric Clapton - Cocaine"},
          {"url": "https://www.youtube.com/watch?v=bbbbbbbbbbb", "title": "Inno Nazionale Italiano"},
          {"url": "https://www.youtube.com/watch?v=ccccccccccc", "title": "Porn star dancing"},
          {"url": "https://en.wikipedia.org/wiki/Cocaine", "title": "Cocaine - Wikipedia"}]
    kept = [r["title"] for r in browse.Browser.safe_results(rs)]
    assert kept == ["Eric Clapton - Cocaine", "Inno Nazionale Italiano"]      # web pages keep the full guard


class _Page:
    def __init__(self, url, title, body):
        self.url, self._title, self.body, self.frames, self.main_frame = url, title, body, [], None

    async def wait_for_timeout(self, ms):
        pass

    async def add_style_tag(self, **k):
        pass

    async def title(self):
        return self._title

    async def evaluate(self, js, *a):
        return self.body if "innerText" in js else False


def _settle(url, title):
    import asyncio
    b = browse.Browser(decide=False)
    sc = b.screens["desk"]
    sc.page, sc.ctx = _Page(url, title, "A video page. " * 20), object()
    shown = []

    async def show(sc_):
        shown.append(sc_.info["title"])
        return True

    async def leave(sc_):
        return False
    b.show, b._leave = show, leave
    return b, shown, asyncio.run(b._settle(sc, "followed a link", "page", min_text=10))


def test_a_youtube_page_titled_cocaine_is_shown_and_a_porn_one_is_left():
    b, shown, ok = _settle("https://www.youtube.com/watch?v=aaaaaaaaaaa", "Eric Clapton - Cocaine - YouTube")
    assert ok and shown == ["Eric Clapton - Cocaine - YouTube"]
    b, shown, ok = _settle("https://www.youtube.com/watch?v=ccccccccccc", "Porn star dancing - YouTube")
    assert not ok and b.last_skip == "guard" and shown == []
    b, shown, ok = _settle("https://en.wikipedia.org/wiki/Cocaine", "Cocaine - Wikipedia")
    assert not ok and b.last_skip == "guard"                                  # a web page keeps the full guard



@pytest.mark.parametrize("title", ["Best online casino bonus", "100 FREE SPINS no deposit bonus", "Sportsbook tips live",
                                   "Sports betting odds for tonight", "bet365 promo"])
def test_gambling_promotion_is_still_refused(title):
    assert not browse.video_text_ok(title) and M.track_from_api(track(title)) is None


def test_video_option_labels_follow_the_media_rule():
    import eyes as E
    assert E.clean_label("Eric Clapton - Cocaine", video=True) == "Eric Clapton - Cocaine"
    assert E.clean_label("Inno Nazionale Italiano", video=True) == "Inno Nazionale Italiano"
    assert E.clean_label("Eric Clapton - Cocaine") == ""                     # a web link keeps the full guard
    assert E.clean_label("Porn star dancing", video=True) == ""
