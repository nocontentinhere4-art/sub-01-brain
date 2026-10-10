"""One money / hype lexicon for every filter (S3): what he may not read, search, watch, hear in the chat or say.

Three lists, matched on `norm()` (lower case, accents folded, everything but letters, digits and "$" read as a
space, so "pump.fun", "Pump Fun" and "PUMP-FUN" are one phrase). Every entry is a phrase or a word with boundaries,
never a bare stem: his activity is `buy_bread`, viewers ask the price of ramen, and "pumpkin", "dumpling", "soup
stock" and "Stockholm" pass (owner). Memecoin / altcoin NEWS stays readable as neutral news: a bare coin name is in
the chat list only, not in HYPE or BUY_ADVICE.
- HYPE          trading / get-rich promotion: "learn to trade like a pro", "presale is live", "fomo app", "100x gems"
- BUY_ADVICE    telling anyone what to buy or where a price goes: "should you buy", "price prediction", "stocks to
                buy", "buy this coin"
- BUY_PRESSURE  the chat (on everyone's screen) and his own words: a push to buy / sell / ape a coin ("should I buy
                sol", "buy it now", "ape into pepe")
- COIN_NAMES    the coin names themselves ("bitcoin", "memecoin"): a chat message or a caption, never a search or a
                page title ("memecoin news" stays a readable search: owner)
Users: chat.blocked (messages: HYPE + BUY_ADVICE + BUY_PRESSURE; chat.message_blocked adds COIN_NAMES; song and video
titles: HYPE + BUY_ADVICE), browse.title_ok / media_title_ok (MONEY_HYPE), eyes.query_ok, mind.FINANCE / reply_problem,
clips.safe, diary.BLOCK, search_sources.parse_hn. A rule table, no model: `money_talk()` returns the matched phrase
(for a log line), else None.
"""
import re
import unicodedata

_COINS = r"(?:bitcoin|btc|ethereum|eth|solana|sol|dogecoin|doge|pepe|bonk|shib|xrp|coins?|\w+coins?|cryptos?|tokens?|nfts?)"
_ASSETS = _COINS + r"|stocks?|shares|etfs?|forex|crypto ?currenc(?:y|ies)"
_ADV = r"(?:this|that|the|a|an|some|more|my|our|your|these|those|their|his|new|cheap)"
_AMOUNT = r"\$\s?\d[\d,.]*[kmb]?|\d[\d,.]*[kmb]|\d[\d,.]* ?(?:dollars?|usd|bucks|euros?)"   # "$5", "10k", "500 dollars"

HYPE = re.compile(r"\b(?:"
                  r"fomo(?: app)?|pump ?fun|pump and dumps?|"
                  r"crypto (?:trading|signals?|gems?|calls?|course|guru|bros?|tips?|picks?)|"
                  r"(?:day|swing|copy|paper|margin|leverage) ?trad(?:e|ing|er|ers)|scalp(?:ing|er|ers)|prop firms?|"
                  r"ict trader|options trading|forex|"
                  r"trad(?:e|ing) (?:like a pro|signals?|bots?|course|calls?|strateg(?:y|ies)|setups?|alerts?|academy|"
                  r"mentors?(?:hip)?|challenge|101|basics|tutorial|masterclass|for beginners)|"
                  r"(?:trading|investing|crypto|stock market|forex) (?:for beginners|101|basics|tutorial|course|"
                  r"masterclass|secrets?)|funded (?:trader|account)|(?:vip )?signals? group|"
                  r"learn (?:how )?to (?:trade|day trade|invest)|"
                  r"get rich(?: quick)?|(?:become|became|becoming) a millionaire|millionaire by \d+|"
                  r"make (?:" + _AMOUNT + r"|millions?|thousands?|money|bank|profits?) (?:fast|quick|online|daily|a day|"
                  r"per day|a week|a month|with|from|on|trading|while)|how to make (?:millions?|money|" + _AMOUNT + r")|"
                  r"passive income|financial freedom|side hustles?|"
                  r"(?:10|50|100|500|1000|10000)x (?:gems?|coins?|returns?|gains?|potential|altcoins?|memecoins?|"
                  r"plays?|opportunit\w*)|next (?:10|50|100|1000)x|"
                  r"to the moon|wen moon|wagmi|ngmi|hodl|diamond hands|paper hands|"
                  r"(?:free|claim|claiming|crypto|token|nft|solana|eth) airdrops?|airdrops? (?:is|are|now) live|"
                  r"airdrop (?:farming|hunting|season|checker|alerts?|campaign|guide|eligibility|points|tokens?|snapshot|"
                  r"claim)|"
                  r"presale (?:is |now )?live|presale (?:price|stage|allocation|bonus|tokens?)|"
                  r"(?:token|coin|crypto|ico|nft) presales?|(?:buy|join) (?:the )?presale|"
                  r"(?:get|join|free|nft|presale|mint) (?:the |a )?whitelist(?:ed)?|whitelist (?:spots?|is open|open|giveaway|only|"
                  r"mint|presale)|mint (?:is )?live|shill(?:ing|ed|s)?"
                  r")\b")

BUY_ADVICE = re.compile(r"\b(?:"
                        r"should (?:you|i|we|u|one|anyone) (?:buy|sell|invest|hold|ape|short|long)|"
                        r"(?:good|great|smart|safe|bad|terrible|best|worst) (?:buy|investment|time to (?:buy|sell|invest))|"
                        r"buy now|buy the dips?|buy low|sell high|buy and hold|"
                        r"price (?:predictions?|targets?|forecasts?)|(?:buy|sell) (?:signals?|zones?)|"
                        r"will (?:\w+ ){1,3}(?:moon|pump|10x|100x|1000x)|"
                        r"will (?:it|" + _COINS + r"|(?:the )?price) hit|"
                        r"(?:" + _ASSETS + r") to (?:buy|invest in|watch|hold|ape)|"
                        r"how to (?:invest|buy " + _ADV + r"? ?(?:" + _ASSETS + r"))|where to buy (?:" + _COINS + r")|"
                        r"invest(?:ing|ed)? in (?:" + _ASSETS + r"|real estate|gold|silver)|"
                        r"(?:investment|financial|trading) advice|not financial advice|nfa|dyor|"
                        r"next (?:bitcoin|solana|ethereum|pepe|doge|big (?:coin|thing in crypto)|\w+coin)|"
                        r"(?:coin|token|crypto|stock|memecoin|altcoin|trading) (?:picks?|tips?|recommendations?)|"
                        r"hot (?:stocks?|coins?)|"
                        r"(?:buy|sell|ape into|ape in|hodl) (?:\w+ ){0,2}(?:" + _COINS + r"|stocks?|shares|dips?)"
                        r")\b")

BUY_PRESSURE = re.compile(r"\b(?:"
                          r"(?:buy|sell|invest|ape|mint|hodl) (?:\w+ ){0,3}(?:" + _COINS + r"|stocks?|shares|this|it|now)|"
                          r"stonks|mcap|market cap|presales?|whitelists?|whitelisted"
                          r")\b")
COIN_NAMES = re.compile(r"\b(?:bitcoin|btc|ethereum|solana|memecoins?|altcoins?|shitcoins?|cryptos?|"
                        r"crypto ?currenc(?:y|ies)|dogecoin)\b")


def norm(text):
    """Lower case, accents folded, every run of anything but letters, digits and "$" one space."""
    t = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", str(text or "")))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9$]+", " ", t).strip()


def money_talk(text, chat=False, names=False):
    """The matched phrase when `text` promotes trading or getting rich (HYPE) or tells what to buy (BUY_ADVICE); with
    chat=True also a push to buy a coin (BUY_PRESSURE), with names=True also a bare coin name. None when it passes."""
    t = norm(text)
    if not t:
        return None
    for rx in (HYPE, BUY_ADVICE) + ((BUY_PRESSURE,) if chat else ()) + ((COIN_NAMES,) if names else ()):
        if m := rx.search(t):
            return m.group()
    return None
