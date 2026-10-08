"""The sleep fix (2026-10-02): no trade feed without our mint, correct pump.fun / PumpSwap decoding, absurd trades
ignored, bounded arousal, and a corrupted saved state that loads and sleeps normally again.

The fixture tests/fixtures/solana_trades.json holds the logs of real mainnet transactions (look them up by signature
on any Solana block explorer):
- pump: bonding-curve TradeEvents; the SOL amount equals the bonding curve account's lamport change in that tx;
- amm: PumpSwap Buy/SellEvents (base = the token, quote = WSOL); the pool is the event's pool pubkey;
- launchlab: a Raydium LaunchLab trade of the old default mint 6GmAFS…: its Anchor "TradeEvent" has the same
  8-byte discriminator as pump.fun's, and the old decoder read it as a 793,100 SOL buy (the "$97M trades");
- other_pool: a routed swap that mentions the old mint but trades two other PumpSwap pools.
"""
import asyncio
import json
import random
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import live_server  # noqa: E402
import sleep as S  # noqa: E402

FIX = {f["what"] + ("" if f["what"] not in ("pump", "amm") else ":" + f["expected"][0]["kind"]): f
       for f in json.loads((Path(__file__).parent / "fixtures" / "solana_trades.json").read_text())}
OLD_MINT = "6GmAFSYs4gk3FDao5FzzySQpPZaWsa4rUJHacpMpUNgx"


# --- 1. no feed without our mint -----------------------------------------------------------------------------
def test_default_mint_is_empty(monkeypatch):
    monkeypatch.delenv("MINT", raising=False)
    assert live_server.build_parser().parse_args([]).mint == ""
    monkeypatch.setenv("MINT", " OurMint111 ")
    assert live_server.build_parser().parse_args([]).mint == "OurMint111"


def test_no_feed_when_mint_is_empty(tmp_path, monkeypatch):
    live = live_server.Live("", False, data_dir=tmp_path)
    assert live.pool_name == "no coin yet"

    def boom(*a, **k):
        raise AssertionError("no network without a mint")
    monkeypatch.setattr(live_server.aiohttp, "ClientSession", boom)
    asyncio.run(asyncio.wait_for(live.rpc_trades(), 2))       # returns at once, opens nothing
    assert live.pending == []


def test_no_feed_when_mint_is_not_an_address(tmp_path, monkeypatch, capsys):
    live = live_server.Live("not-a-mint!", False, data_dir=tmp_path)

    def boom(*a, **k):
        raise AssertionError("no network with a bad mint")
    monkeypatch.setattr(live_server.aiohttp, "ClientSession", boom)
    asyncio.run(asyncio.wait_for(live.rpc_trades(), 2))
    assert "not a valid Solana address" in capsys.readouterr().out


# --- 2. decoding against real events ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", ["pump:buy", "pump:sell"])
def test_pump_bonding_curve_trade_event(key):
    f = FIX[key]
    exp = f["expected"][0]
    got = live_server.decode_trades(f["logs"], mint=exp["mint"])
    assert got == [{"kind": exp["kind"], "sol": exp["lamports"] / 1e9}]
    assert live_server.decode_trades(f["logs"], mint=OLD_MINT) == []          # another mint's trade: not ours


def test_known_pump_amounts():
    """Spelled out, so the numbers can be checked by hand on an explorer."""
    assert live_server.decode_trades(FIX["pump:buy"]["logs"]) == [{"kind": "buy", "sol": 0.041110908}]
    assert live_server.decode_trades(FIX["pump:sell"]["logs"]) == [{"kind": "sell", "sol": 1.210097952}]


@pytest.mark.parametrize("key", ["amm:buy", "amm:sell"])
def test_pumpswap_events(key):
    f = FIX[key]
    exp = f["expected"][0]
    got = live_server.decode_trades(f["logs"], pools={exp["pool"]})
    assert got == [{"kind": exp["kind"], "sol": exp["lamports"] / 1e9}]
    assert live_server.decode_trades(f["logs"], pools={"SomeOtherPool1111111111111111111111111111111"}) == []
    assert live_server.decode_trades(f["logs"], pools=set()) == []            # no pool known yet: nothing


def test_known_pumpswap_amounts():
    assert live_server.decode_trades(FIX["amm:sell"]["logs"]) == [{"kind": "sell", "sol": 0.084564054}]
    assert live_server.decode_trades(FIX["amm:buy"]["logs"]) == [{"kind": "buy", "sol": 0.023704801}]


def test_launchlab_trade_event_is_not_pump():
    """The bug: same discriminator, another program, another layout -> it must not decode at all."""
    logs = FIX["launchlab"]["logs"]
    assert any(l.startswith("Program data: vdt/") for l in logs)              # bddb7fd34ee661ee, base64
    assert live_server.decode_trades(logs) == []
    assert live_server.decode_trades(logs, mint=OLD_MINT, pools=set()) == []


def test_routed_swap_through_other_pools_is_not_ours():
    logs = FIX["other_pool"]["logs"]
    assert len(live_server.decode_trades(logs)) == 2                          # two PumpSwap events in the tx...
    assert live_server.decode_trades(logs, mint=OLD_MINT, pools={"OurPool111"}) == []   # ...neither in our pool


def test_emitter_tracking():
    data = FIX["pump:buy"]["logs"]
    lines = [l for l in data if l.startswith("Program data: ")]
    fake = [f"Program {live_server.PUMP_PROGRAM} invoke [1]", "Program X1111 invoke [2]", lines[0],
            "Program X1111 success", f"Program {live_server.PUMP_PROGRAM} success"]
    assert live_server.decode_trades(fake) == []                              # emitted by X1111, not pump.fun


def test_base58_round_trip():
    for a in (OLD_MINT, live_server.PUMP_PROGRAM, "11111111111111111111111111111111"):
        assert live_server.b58encode(live_server.b58decode(a)) == a


# --- 2b. absurd trades never reach the brain ------------------------------------------------------------------
def test_absurd_trade_ignored_and_logged_once_a_minute(tmp_path, capsys):
    live = live_server.Live("OurMint", False, data_dir=tmp_path)
    live.sol_usd = 150.0
    assert live.take_trade({"kind": "buy", "sol": 793_100.0}, "sigA") is False
    assert live.take_trade({"kind": "buy", "sol": 650_000.0}, "sigB") is False
    assert live.pending == []
    assert capsys.readouterr().out.count("ignored an absurd trade") == 1
    assert live.take_trade({"kind": "sell", "sol": 2.0}, "sigC") is True
    assert live.pending[0]["usd"] == 300.0 and live.pending[0]["tx"] == "sigC"


# --- 3. bounded arousal ---------------------------------------------------------------------------------------
def test_total_arousal_is_capped():
    e = S.SleepEngine(datetime(2026, 10, 2, 23, 0, tzinfo=S.TZ).timestamp(), random.Random(0))
    for i in range(500):
        e.stimulus(e.t, "trade", 10_000_000)
        e.stimulus(e.t, "message")
    assert e.arousal == S.AROUSAL_MAX == 2 * S.WAKE_THRESHOLD


def test_no_stream_pins_him_awake_for_days():
    """A nonstop stream of the largest allowed trades, one a minute, for 3 days: he still sleeps every day and the
    debt levels off (live, before the fix: debt 105 h and climbing)."""
    t0 = datetime(2026, 10, 1, 20, 0, tzinfo=S.TZ).timestamp()
    e = S.SleepEngine(t0, random.Random(1))
    t, asleep = t0, 0
    while t < t0 + 3 * 86400:
        t += 60
        e.stimulus(t, "trade", live_server.MAX_TRADE_USD)
        e.update(t)
        asleep += 60 if e.asleep else 0
    assert asleep / 3600 / 3 > 5.0
    assert e.debt < 30.0


# --- 4. a corrupted saved state repairs itself -----------------------------------------------------------------
def corrupted_state(now):
    """What Railway held on 2026-10-02: awake, arousal 215, sleep debt ~105 h, tonight's night record open."""
    e = S.SleepEngine(now - 3600, random.Random(3))
    e.update(now)
    d = e.to_dict()
    d.pop("repairs")                                  # saved before this fix
    d["arousal"] = 215.0
    d["arousal_log"] = [[now - i, 4.5, "trade", 97_297_508.0] for i in range(300)]
    d["asleep"], d["stage"], d["rem"] = False, "AWAKE", False
    d["V_m"], d["V_v"] = 0.6, -10.0                   # the wake branch of the flip-flop
    ref = S.Reference.get()
    d["H"] = ref.at(now)[2] + 105.0 * ref.dh_per_h
    d["night"] = {"date": S.night_date(now), "timezone": S.TZ_NAME, "sleep_onset": None, "woke_up": None,
                  "timeline": [], "wakeups": [{"t": S.stamp(now - 600), "cause": "a large trade ($97,297,508)"}],
                  "sleep_debt": {"start": 104.0, "end": None}, "replays": []}
    d["last_night"] = {"date": "2026-10-01", "timezone": S.TZ_NAME, "sleep_onset": "2026-10-02T11:38",
                       "woke_up": "2026-10-02T13:08", "timeline": [], "wakeups": [], "replays": [],
                       "sleep_debt": {"start": 90.0, "end": 98.0}}
    return d


def test_from_dict_clamps_and_repairs_once():
    now = datetime(2026, 10, 2, 22, 30, tzinfo=S.TZ).timestamp()
    d = corrupted_state(now)
    e = S.SleepEngine.from_dict(d, random.Random(4))
    assert e.arousal == 0.0 and e.arousal_log == []
    assert e.debt == pytest.approx(S.REPAIR_DEBT_H, abs=1e-6)           # the fake trades' debt is gone
    assert e.night is None                                    # tonight's broken record is gone...
    assert e.last_night["date"] == "2026-10-01"               # ...last night stays as history
    assert "2026-10-02-trades" in e.repairs
    # a later restart keeps the general clamps but does not repeat the one-time repair
    ref = S.Reference.get()
    d2 = e.to_dict() | {"arousal": 50.0, "arousal_log": [[now, 1.0, "message", 0.0]] * 50,
                        "H": ref.at(e.t)[2] + 30.0 * ref.dh_per_h}
    d2["night"] = {"date": S.night_date(now), "timezone": S.TZ_NAME, "sleep_onset": None, "woke_up": None,
                   "timeline": [], "wakeups": [], "sleep_debt": {"start": 1.0, "end": None}, "replays": []}
    e2 = S.SleepEngine.from_dict(d2, random.Random(5))
    assert e2.arousal == S.WAKE_THRESHOLD and len(e2.arousal_log) == 20
    assert e2.debt == pytest.approx(S.DEBT_MAX_RESTART_H, abs=1e-6)       # every restart: debt <= 12 h
    assert e2.night is not None                               # not reset again


def test_corrupted_state_sleeps_normally_within_24h():
    """Loaded at 22:30 Tokyo with arousal 215 and 105 h of debt: he falls asleep in the normal window, has REM
    cycles and replays, and the next night is a normal one."""
    now = datetime(2026, 10, 2, 22, 30, tzinfo=S.TZ).timestamp()
    e = S.SleepEngine.from_dict(corrupted_state(now), random.Random(6))
    t, events = now, []
    while t < now + 24 * 3600:
        t += 30
        events += [(t, ev) for ev in e.update(t, dt_real=30)]
    sleeps = [t for t, ev in events if ev["type"] == "sleep"]
    assert sleeps, "never fell asleep"
    first = S.local(sleeps[0])
    assert first.hour >= 22 or first.hour < 2                 # tonight, around midnight
    rem = [x for x in e.last_night["timeline"] if x["stage"] == "REM"]
    assert rem
    night = e.last_night
    assert night["date"] == "2026-10-02"
    assert sum(1 for x in night["timeline"] if x["stage"] == "REM") >= 3
    assert len([1 for t, ev in events if ev["type"] == "replay"]) >= 8
    assert not night["wakeups"]                               # nothing woke him
    assert S.local(datetime.fromisoformat(night["woke_up"]).replace(tzinfo=S.TZ).timestamp()).hour >= 5
