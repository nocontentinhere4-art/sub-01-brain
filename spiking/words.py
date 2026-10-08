"""Content words of an item, as the spiking memory hashes them (no torch: the server uses it too).

An item needs at least two content words to be tested from a half cue (spiking/memory.py `test`)."""
import re

STOP = set("""a an the and or but if of to in on at by for with from as is are was were be been am it its this that
these those there here i me my we our you your he she they them his her their what which who whom do does did
not no so than too very can will just il lo la le gli i un una e o di da in con su per tra fra che non è sono
mi ti si ci vi del della dei delle al alla ai alle""".split())


def words(text, max_words=12):
    toks = re.findall(r"[^\W\d_]{2,}", (text or "").lower())
    seen, out = set(), []
    content = [w for w in toks if w not in STOP] or toks
    for w in content:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out[:max_words]


def half_cue_ok(text):
    """True if the next-day test can cue it with half its words (two or more content words)."""
    return len(words(text)) >= 2
