# Tastes learn faster (issue #36)

Tastes (`tastes.py`) are a running average of the brain model's simulated responses to pages, per topic. They are not
feelings. This change makes the average settle faster in two ways:

1. **A Kalman gain per topic** replaces the fixed rate `ALPHA = 0.2`. Each topic keeps an uncertainty `var`.
   - The model is the one the rule already assumed. A stay's response is the mean of its topics' values plus noise
     (`NOISE_VAR = 0.1`). Each value fades toward 0 with the existing 7-day decay, which is an Ornstein-Uhlenbeck
     process with spread `PRIOR_VAR = 0.25`.
   - A stay with m topics has predicted variance `S = sum(var)/m² + NOISE_VAR`. Topic t moves by `var_t / (m S) × error`.
   - So the error goes mostly to uncertain topics: new ones, or ones not seen for days, whose `var` grows back with
     the decay. A topic seen 40 times moves less than 0.05 on one contrary stay.
   - **Why not `1 / (1 + n_seen)`?** I tried it first. It is the gain for a topic seen *alone*, but a stay carries about
     6 topics. In the simulation below it was *worse* than the old fixed rate at ranking the top 5: 3.1 vs 4.1 of the
     true top 5 found in the last 5 days, at noise 0.1, with the older 60-topic world. On a stay with several new
     topics, each takes the whole error, so the prediction overshoots. The gain also falls as 1/n, although one stay
     tells only about 1/m about each of its m topics.
2. **Overnight replay, prioritised.**
   - Each stay `(topics, response, prediction error)` is also logged in `tastes.json`. The log keeps at most 200
     stays and is written atomically with `state_io.save_json`, as before.
   - At each sleep onset, one line in `live_server.sleep_tick` calls `Tastes.replay()`. It re-applies the 60 logged
     stays with the largest *current* |prediction error| at 0.5 × their gain, without lowering their uncertainty
     (a replay is not new evidence), then clears the log.
   - The last replay is reported as `last_replay` in `/api/tastes` (stays, replayed, mean |error| before and after).
     The page is unchanged.

Old state files load unchanged. Topics without a stored `var` start at `LEGACY_VAR`, the variance at which a stay on
that topic alone has gain 0.2, the old fixed rate. The interface (`topics` / `predict` / `learn`) is unchanged.

## How much faster (simulated)

`tests/test_tastes_faster.py` (run it with `PYTHONPATH=. python tests/test_tastes_faster.py`) sets up this world:

- Hidden values for 40 topics: 7 networks and 33 words. 5 of them have a clear lead (0.5–0.9); the rest are ≤ 0.3.
- 120 stays per 16-hour day, each with 1–3 networks and 3–5 words. Words follow a skewed popularity.
- Response = tanh(mean of the stay's true values + Gaussian noise).
- A night (replay) follows each day's last stay.

The measure is **stays until the learned top 5 is the true top 5 and holds for half a day (60 stays in a row)**,
over 16 seeds and 3000 stays (25 days). "Never" counts the runs that did not get there.

| noise sd | fixed 0.2 (before) | fixed + replay | Kalman gain | Kalman + replay (after) |
|---|---|---|---|---|
| 0.1 | median 1004, mean 1085, never 0 | 711 / 876 / 0 | 436 / 534 / 0 | **405 / 470 / 0** |
| 0.2 | median 3000, mean 2364, never 9 | 3000 / 2282 / 9 | 2525 / 2279 / 6 | **2274 / 2077 / 4** |

- At noise 0.1 the top 5 is right about **2.5× sooner**: median 1004 → 405 stays, about 8.4 → 3.4 simulated days.
- At noise 0.2 most runs need more than the 25 days, before and after. Fewer runs fail (9 → 4 of 16).
- Replay is the smaller effect. With the fixed rate it helps clearly (1004 → 711). On top of the Kalman gain it
  gains 5–15 %. Other settings (15–60 replays, rate 0.5–1.0) were within the seed-to-seed noise.
- The noise level of the real stay response is not known. These numbers compare rules on one simulated world; they do
  not predict days on the live site.

## Cost

- `replay()` with a full log (200 stays, 400 topics) takes 3.8 ms, once per sleep onset. Most of that is the same
  fsync'd save that `learn()` already does after every stay (2.6 ms).
- The 50 ms brain tick is unchanged. `tests/smoke_demo.py` on one shared core gave main 64.2 / 61.2 ms and this
  branch 64.8 / 61.6 ms CPU per tick (alternating runs; this machine is saturated, so CI's figure is the absolute one).
