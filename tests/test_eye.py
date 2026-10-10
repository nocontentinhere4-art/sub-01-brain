"""The eye (eye.py): scene, thought and world objects pass the shared filters (S7); no market mood; the image is kept
when the scene did not change and when the image call fails (D5). Every provider is mocked: no paid call.

    python -m pytest tests/test_eye.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import costs
import eye as E


# --- the filters -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("thought", ["I feel alive", "I should buy the dip", "I am conscious now", "my hands are cold",
                                     "the coin is pumping", "I am conscious of myself", "send me 5 sol",
                                     "watch porno tonight"])
def test_thought_refused(thought):
    assert not E.thought_ok(thought)


@pytest.mark.parametrize("thought", ["warm loaves on the counter", "the park is quiet at this hour",
                                     "rain again on the window", "a dumpling shop over a canal", "pumpkin soup stock"])
def test_thought_allowed(thought):
    assert E.thought_ok(thought)


@pytest.mark.parametrize("scene", ["a candlestick chart on the desk", "a price ticker glowing over the bed",
                                   "a human hand holding the phone", "crypto tokens falling like rain"])
def test_scene_refused(scene):
    assert not E.scene_ok(scene)


def test_scene_allowed_and_neutral_fallback():
    assert E.scene_ok("the bakery counter, warm loaves in paper, morning light through the window")
    assert E.scene_ok("the monitor on the desk shows an encyclopedia page; a cup beside the keyboard")
    n = E.neutral_scene("AWAKE", "reading at the desk")
    assert "reading at the desk" in n and E.scene_ok(n)
    assert E.scene_ok(E.neutral_scene("REM")) and E.scene_ok(E.neutral_scene("NREM"))


def test_world_objects_pass_the_raw_name_filter():
    w = E.World()
    t = time.time()
    w.add(["$PEPE", "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU", "0x" + "a" * 40], t, "x")   # (3 names a call)
    w.add(["https://x.y/z", "warm loaves", "buy the dip"], t, "warm loaves on the counter")
    w.add(["a human hand", "price chart"], t, "y")
    assert set(w.objects) == {"warm loaves"}
    assert not E.object_ok("$PEPE") and not E.object_ok("7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU")
    assert E.object_ok("bread") and E.object_ok("pane caldo")


def test_mood_has_no_market():
    m = E.mood({"reward": 2.0, "fear": 1.0}, "AWAKE", "pumping")
    assert "market" not in m and m["stage"] == "awake"
    assert E.market_mood([(time.time(), "buy", 1e6)]) == "calm"       # the stub: nothing market-shaped comes out


# --- the frames -----------------------------------------------------------------------------------------------------
class Script:
    """What the mocked language model answers, frame after frame; `fail_image` makes the image call raise."""

    def __init__(self):
        self.replies, self.fail_image, self.images = [], False, 0


def mocked_eye(tmp_path, monkeypatch, script):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-not-a-token")

    def fake_post(url, token, payload, **kw):
        assert "llama" in url
        reply = script.replies.pop(0) if script.replies else '{"scene": "a desk", "thought": "quiet"}'
        return {"output": [reply], "metrics": {"input_token_count": 900, "output_token_count": 40}}
    monkeypatch.setattr(E, "replicate_post", fake_post)

    def fake_generate(self, prompt, seed, w, h):
        from PIL import Image
        if script.fail_image:
            raise RuntimeError("replicate: queue full")
        script.images += 1
        return Image.new("RGB", (w, h), (200, 200, 200))
    monkeypatch.setattr(E.ReplicateImages, "generate", fake_generate)
    eye = E.Eye(tmp_path / "frames", tmp_path / "world.json", width=64, height=36)
    eye.ledger = costs.Ledger(tmp_path)
    return eye


def test_refused_scene_and_thought_never_reach_the_frame(tmp_path, monkeypatch):
    s = Script()
    s.replies = [json.dumps({"new_objects": [{"said": "$PEPE", "en": "pepe coin"}, {"said": "pane", "en": "bread"}],
                             "scene": "a candlestick chart glowing on the desk", "thought": "I feel alive today"})]
    eye = mocked_eye(tmp_path, monkeypatch, s)
    eye.hear("pane caldo e $PEPE", time.time())
    rec = eye.step(time.time(), "AWAKE", {}, "pumping", ["ciao"], "12:00", doing="reading at the desk")
    assert "chart" not in rec["scene"] and "reading at the desk" in rec["scene"]
    assert rec["thought"] == "" and "market" not in rec["why"]["mood"]
    assert set(eye.world.objects) == {"bread"} and eye.refused == {"scene": 1, "thought": 1, "objects": 1}
    assert "market" not in json.dumps(rec)


def test_image_failure_returns_the_previous_frame_untouched(tmp_path, monkeypatch):
    s = Script()
    s.replies = [json.dumps({"scene": "the bakery counter, warm loaves", "thought": "bread"}),
                 json.dumps({"scene": "the park bench under the trees", "thought": "cold"})]
    eye = mocked_eye(tmp_path, monkeypatch, s)
    first = eye.step(time.time(), "AWAKE", {}, None, [], "12:00")
    files = sorted((tmp_path / "frames").glob("*.jpg"))
    s.fail_image = True
    rec = eye.step(time.time() + 90, "NREM", {}, None, [], "12:01")
    assert rec["img"] == first["img"] and rec["scene"] == first["scene"] and rec["thought"] == first["thought"]
    assert rec["stage"] == first["stage"] and rec["reused"] and rec["resting"] == "resting its eyes"
    assert sorted((tmp_path / "frames").glob("*.jpg")) == files              # no new file...
    assert len([x for x in eye.log.read_text().splitlines() if x]) == 1       # ...and no new frame in the log
    assert eye.ledger.spent_today("eye") == pytest.approx(costs.FLUX_SCHNELL_USD + 2 * costs.llm_usd(900, 40))


def test_image_failure_with_no_previous_frame_raises(tmp_path, monkeypatch):
    s = Script()
    s.fail_image = True
    eye = mocked_eye(tmp_path, monkeypatch, s)
    with pytest.raises(RuntimeError):
        eye.step(time.time(), "AWAKE", {}, None, [], "12:00")


def test_unchanged_scene_keeps_the_image_and_bills_only_the_thought(tmp_path, monkeypatch):
    s = Script()
    s.replies = [json.dumps({"scene": "the desk, a cup beside the keyboard, the page on the monitor", "thought": "a"}),
                 json.dumps({"scene": "the desk, the cup beside the keyboard, the page on the monitor", "thought": "b"}),
                 json.dumps({"scene": "the park bench, trees, a quiet path", "thought": "c"})]
    eye = mocked_eye(tmp_path, monkeypatch, s)
    t = time.time()
    a = eye.step(t, "AWAKE", {}, None, [], "12:00")
    b = eye.step(t + 90, "AWAKE", {}, None, [], "12:01")
    c = eye.step(t + 180, "AWAKE", {}, None, [], "12:03")
    assert b["img"] == a["img"] and b["thought"] == "b" and b["reused"] and b["same_scene"]
    assert c["img"] != a["img"] and not c["reused"]
    assert s.images == 2
    rows = [json.loads(x) for x in eye.ledger.path.read_text().splitlines()]
    assert [r["note"] for r in rows] == ["thought", "frame", "thought", "thought", "frame"]
    # the eye remembers its last frame across a restart (from the log)
    again = E.Eye(tmp_path / "frames", tmp_path / "world.json", width=64, height=36)
    assert again.last_rec["img"] == c["img"]


def test_nrem_frame_is_not_darkened_twice(tmp_path, monkeypatch):
    from PIL import Image
    s = Script()
    s.replies = [json.dumps({"scene": "dark slow shapes", "thought": ""}),
                 json.dumps({"scene": "dark slow shapes", "thought": ""})]
    eye = mocked_eye(tmp_path, monkeypatch, s)
    t = time.time()
    a = eye.step(t, "NREM", {}, None, [], "03:00")
    b = eye.step(t + 90, "NREM", {}, None, [], "03:02")
    assert b["img"] == a["img"]
    px = Image.open(tmp_path / "frames" / Path(a["img"]).name).convert("RGB").getpixel((0, 0))
    assert 40 <= px[0] <= 60                                                  # 200 x 0.25 once, not twice


def test_replays_in_the_prompt_are_deduplicated(tmp_path, monkeypatch):
    seen = {}
    s = Script()
    eye = mocked_eye(tmp_path, monkeypatch, s)

    def fake_post(url, token, payload, **kw):
        seen.update(json.loads(payload["input"]["prompt"]))
        return {"output": ['{"scene": "a desk", "thought": ""}'], "metrics": {}}
    monkeypatch.setattr(E, "replicate_post", fake_post)
    rec = eye.step(time.time(), "REM", {}, None, ["gm", "gm", "ciao", "gm"], "03:00")
    assert seen["replayed_messages"] == ["gm", "ciao"] and "market" not in seen
    assert rec["why"]["replayed"] == ["gm", "ciao"]
