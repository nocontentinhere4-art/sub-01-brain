# Arriving at the desk: "is at the computer" while he still stands by the chair

**Live report:** in six checks in a row, at the start of a desk activity, the caption said "is at the computer" while
he still stood beside the chair for 30–60 s, and only then sat down.

## Measured (main 92395c7)
The fake server replays the live order: `walking` to the desk, then arrived with the activity.

**In the page's own time (manual steps), his plan is short:**

| arrival from | the server's walk ends | he is seated | gap |
|---|---|---|---|
| the door | 6.0 s | 11.0 s | 5.0 s |
| the window | 1.0 s | 11.0 s | 10.0 s |

After the walk he turns, pulls the chair out, walks round it, turns, sits down (the real sit-down capture) and rides in.
The server walks him at 1.3 m/s with nothing after, so its walk ends 5–10 s before his.

**In real time, the page's own loop at the frame rate a headless check gets (software GL):**
- 0.24 fps at 1280 px, 0.75 fps at 390 px on a 4× slower CPU.
- The page advanced him at most 0.1 s per frame. At 0.24 fps his time ran at 1/40 of real time: the walk alone took
  166 s. A check that looks after the server's tick sees the caption flip while he still stands by the chair.
- On a device at 10 fps or more nothing was wrong: his time ran at real time.

## Causes and fixes (`web/room.html`)
1. **His time followed the frame rate.**
   - A late frame is now caught up in steps of at most 0.1 s, up to 8 s at once. A tab coming back jumps at most 8 s.
   - A step costs ~30 ms of the 100 ms it covers, so even a frame every 4 s keeps up.
   - At 10 fps or more nothing changes (one step per frame).
2. **The caption followed the server.** A desk caption now says "is going to the desk: …" until the page has him
   seated, then "is at the computer: …". It is re-checked every step, so it flips when he sits, not at the next tick.

## After (real time, headless software GL, the page's own loop)

| arrival from | fps | the server's walk ends | he is seated |
|---|---|---|---|
| the door (1280) | 0.23 | 8.1 s | 8.1 s |
| the door (390) | 0.21 | 9.6 s | 9.6 s |
| the bed | 0.19 | 12.2 s | 12.6 s |
| the window (1280) | 0.12 | 6.1 s | 16.0 s |
| the window, no walk in the server | 0.13 | 0 s | 15.5 s |

Before, under the same conditions, he was not seated within 60 s; the walk alone took 166 s. In the window rows the
caption says "is going to the desk" until he sits.

## Tests (`tests/visual/test_arrival.py`)
Both fail on main and pass here:
- **The caption.** From the door, the server sends the computer scene (`scenes.py` "computer": research with a page on
  the screen). The caption must say "going to the desk" every step until the page has him seated, then "at the
  computer". On main it said "at the computer" while he was still walking.
- **Real time.** The page's own loop under headless software GL, which draws the room at a fraction of a frame a
  second. He must be seated within 45 s of the tick (here ~16 s at 0.11 fps). On main he was not seated within 60 s.
  - The test does not throttle the CPU: that slows his steps as much as the drawing, so no catch-up can keep real time,
    and a slow device draws slowly, it does not step slowly.
  - With the hands from the owner's takes merged in, a 10× throttle took 48 s.

## The empty chair, live 2026-10-08 08:02 (17:04–17:07 Tokyo)
**The report.**
- For 3 minutes the API said "is at the computer: Highsnobiety / Time Out", but the chair was empty in the frames (1280 and 390).
- The camera framed the desk he had not reached.
- A minute before, while it said "lying on the bed listening to music", he stood by the bed.

**The live room is an old build.** The live boy_mh.js has md5 99b73f02. That file is main's from 0eaf73a to 8d159d2, before bb6cbbf, so neither this fix nor the one above (db6eb20) is live.

**What it does** (live_rt3.py in the session scratchpad):
- Each build runs alone on 2 cores, headless software GL, with the page's own loop.
- The server's ticks go: at the desk, then music in bed, then research at the desk.

| | music: lying on the bed after | browsing: seated after | his time per real second |
|---|---|---|---|
| live build (8d159d2) | not within 240 s | not within 240 s | 1.9 s of his time in 220 s (0.1 s a frame, ~0.09 fps) |
| main (f5f43cb) | 36–51 s | 21–50 s | ~0.5× (a frame takes 8–16 s; it caught up 8 s at most) |
| this fix | 59 s (his own 43 s) | 35 s | 0.73× in bed, 0.93× walking to the desk |

- **On the live build:** two minutes after the music tick he was still getting up from the chair. The camera had already turned to the bed (it frames where he is going), and the caption followed the server. This is the live frames exactly.
- **On main:** the caption says "is going to the desk" until he sits, and he gets there in under a minute.

**The fix (`web/room.html`)**
- **A slow frame:** caught up whole, up to 30 s (was 8 s).
- **A tab coming back:** still catches up at most 8 s.
- **A frozen page (?debug):** its time is dropped, not caught up.

**Tests**
- `test_a_slow_frame_is_caught_up_whole`: one 20 s frame gives 20 s of his time, and a tab coming back gives 8 s.
- `test_he_sits_in_real_time_on_a_slow_frame_rate`, alone on 2 cores:

  | build | seated after |
  |---|---|
  | main | 33.7 s, 34.0 s |
  | this fix | 33.8 s, 24.0 s |

**What actually fixes the live site:** deploying main. Railway has not deployed since before bb6cbbf.
