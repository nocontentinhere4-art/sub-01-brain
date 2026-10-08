# Body (twin/body.py)

A minimal body for a digital twin model of one real person's brain structure and recorded activity; not a mind, not
conscious, not the person. It gives the brain model a heart rate, breathing, blood glucose and hunger so that the
simulated life has a physiological reason to eat. The parameters are generic textbook adult values; nothing is fitted
to the recorded person and no body data from the dataset is used.

## Equations

**Autonomic balance and heart rate.** Sympathetic tone S and vagal tone V (both 0..1) relax to targets with time
constants 20 s (sympathetic, slow) and 5 s (vagal, fast) (Berger et al. 1989, Am J Physiol):

    S* = clip(S_stage + 0.30 (NE - 1) + 0.30 amygdala + 0.35 exertion + 0.3 hypo, 0, 1)
    V* = clip(V_stage - 0.6 (S* - S_stage), 0, 1)
    HR = HR_int - 45 V + 70 S + noise,     HR_int = 95 bpm

The additive sympatho-vagal form follows Berntson et al. (1991, Psychol Rev; 1993, Psychophysiology); the intrinsic rate
118.1 - 0.57 age (Jose and Collison 1970, Cardiovasc Res) gives ~95 bpm at 40 y. `hypo = max(0, (70-G)/20)` is a small
sympathoadrenal counter-regulation. Stage tone (S, V): awake (0.15, 0.75), NREM (0.04, 0.88), REM (0.10, 0.85)
(qualitative pattern: Somers et al. 1993 NEJM; Trinder et al. 2001 J Sleep Res). "Awake" is daytime wake, not supine
rest, so it sits above the sleep values. Resulting means: awake 71.5, NREM 58.0, REM 63.1 bpm (sd over 30 s samples
1.4 / 0.8 / 3.4); NE 1.5 -> 86; NE 1.6 plus amygdala 1.0 -> 118. `NE` is the neuromodulator level
(1.0 = resting wake) and `amygdala` the activity excess over rest (0 = baseline), both supplied by the caller.
`noise` is an Ornstein-Uhlenbeck process (tau 30 s) with sd 1.5 (awake), 0.8 (NREM), 3.5 (REM) bpm.

**Breathing.** rate = base(stage) + 9 (S - S_stage) + noise; base 14.5 (awake), 14.0 (NREM), 15.0 (REM) per min, sd
1.0 / 0.35 / 2.2, clipped 6-35. In NREM minute ventilation falls by roughly 13-15 % almost entirely through tidal volume,
with the breathing rate nearly unchanged and very regular; REM breathing is faster and irregular, more so with dense
eye movements (Douglas et al. 1982 Thorax; Gould et al. 1988 Am Rev Respir Dis). Only the rate is modelled, so the
NREM ventilation drop is not visible here.

**Glucose.** Bergman minimal model (Bergman et al. 1979, Am J Physiol) with a two-compartment gut (stomach -> gut ->
plasma, Dalla Man et al. 2006, IEEE Trans Biomed Eng):

    dQsto/dt = -kgri Qsto;   dQgut/dt = kgri Qsto - kabs Qgut        (kgri 0.056, kabs 0.057 /min)
    Ra = F kabs Qgut / (BW Vg)                                         (mg/dl/min; BW 70 kg, Vg 1.88 dl/kg)
    dG/dt = -p1 (G - Gset) - X G - kex * exertion * G + Ra             (p1 0.03 /min)
    dX/dt = -p2 X + p3 (I - Ib)                                        (p2 0.02 /min, p3 2e-5)
    dI/dt = -n (I - Ib) + gamma max(G - Gset, 0)                       (n 0.27 /min, gamma 0.03, Ib 8 uU/ml)

Euler steps of <= 60 s. `F = 0.45` is the net fraction reaching plasma (0.9 absorbed minus first-pass splanchnic
uptake) and `p3`, `gamma` were tuned by hand to give a realistic mixed-meal curve; they are not literature values.
`Gset`, the fasting set-point, drifts from 92 toward 70 mg/dl with a 30 h time constant after the last meal: ~88 at
6 h, ~85 after an overnight fast (12 h), ~80 at 24 h, ~72 at 72 h, roughly the slow fall seen in prolonged fasting
(Cahill 1970 NEJM). It is a phenomenological stand-in for hepatic glycogen depletion and gluconeogenesis, not a liver
model.

Results (default parameters, from 3 h after the previous meal): 30 g carbohydrate -> peak 131 mg/dl at 40 min (+39
over fasting, close to what ~30 g of white bread does in healthy adults), 94 at 2 h, 89 at 3 h; 60 g -> peak 170 (+78);
75 g -> peak 189 (+97, too high: a healthy 75 g OGTT peaks around 140-160 mg/dl, because absorption here is linear
in the load). Life eats 30 g at a time, where the curve is reasonable. The result is the same with Euler steps of 1 s
or 180 s (peak 168 vs 170 for 60 g; value at 4 h identical to 0.01 mg/dl), so the live server's large ticks are safe.
A 24 h loop with three meals stays between ~70 and ~190 mg/dl (asserted); the 2-day Life loop below stays at 84-165,
mean ~100 mg/dl.

**Hunger (0..1).** `0.6 * ghrelin_proxy + 0.4 * clip((100 - G)/30, 0, 1)`. The proxy relaxes toward 1 with tau 5 h and
is multiplied by exp(-carbs/35 g) at each meal (pre-meal rise and post-meal fall of ghrelin: Cummings et al. 2001,
Diabetes). Real hunger is mostly hormonal, habitual and cue-driven, not a glucose threshold; glucose only contributes
the smaller term here, and the proxy is a stand-in for the whole gut/hormone signal.

**Interoceptive drive.** `intero_drive()` returns `{"insula": amount}` (empty when fed and calm) =
2.0 * low-glucose (G < 85) + 1.0 * high HR (> 80 bpm) + 0.5 * hunger above 0.4, in `brain.stimulate` units. The group
`insula` (new in `brain_sim.GROUPS`) is the 8 `SalVentAttn_FrOperIns` Schaefer parcels, a frontal operculum / anterior
insula proxy (Craig 2002, Nat Rev Neurosci). The atlas (Schaefer-200 + 14 Harvard-Oxford subcortical) has no
hypothalamus, so there is no hypothalamic input; the amounts are choices, not fitted.

## Life integration
`Life(state, rng, body=None)`: `hunger` is now a read-only property of the body (the old +1/5 h rule and the -0.6 per
meal rule are removed). Eating one piece of bread calls `body.eat(30)` (`CARBS_PER_BREAD_G`: a ~60 g roll at ~50 % carbohydrate, USDA FoodData
Central). The eat / buy-bread decision was re-scaled to the body's hunger (`SATED = 0.35`: no eating below it;
`EAT_AT = 0.55`: meal-time bonus above it; the old constant +0.2 for eating whenever bread was at home is gone). With
the old thresholds the body-driven Life ate about every hour (11-16 breads a day, glucose up to ~210 mg/dl). Now a
2-day Life + Body + SleepEngine run (real time and x60) eats 5-6 times per waking day (one or two breads at
breakfast, then about every 2-2.5 h); hunger stays in 0.1-0.8 (asserted in `tests/test_body.py`). Over that run the
glucose term is about a quarter of the mean hunger (0.11 of 0.46) and moves with it (r = 0.94). At `--time-scale
3600` Life eats only 1-2 times a day because indoor walking still takes real seconds (= sim hours); that is a Life
limitation that predates the body. Exertion: walking 0.3, sitting on the park bench 0.1. With an external `body`, its owner (live_server) must step it with
`body.update(dt_sim, levels, amygdala, stage, exertion=life.exertion())`; without one, Life makes its own body, steps it,
and saves it in `to_dict()["body"]` (a legacy save with only `hunger` seeds the ghrelin proxy). Snapshot keys are
unchanged. `update(..., levels=None, amygdala=0.0)` pass the neuromodulators to an owned body.

Interface additions to the contract: `Body.update(..., exertion=0.0)`, `Body(state, rng=None)`, `Body.from_dict`,
`brain_sim.GROUPS["insula"]`, `Life(body=)`. `Dockerfile` now copies `twin/` (life.py imports it).
Wiring in `live_server.py` (done): one `Body` is created (state in `data/twin_state.json`), stepped with the
accumulated sim time whenever at least 1 sim second has passed (one call can cover ~180 s at `--time-scale 3600`) with the
neuromodulator levels, `amygdala = max(0, rel["fear"] - 1)` of the previous tick, the sleep stage and `life.exertion()`;
`intero_drive()` is applied every tick as `brain.stimulate("insula", v * stimulus_gain * TICK / 2 s)`, i.e. a continuous
input whose steady-state stimulus level equals `v` (stimuli decay with a 2 s time constant) and which the sleep engine's
stimulus gain scales down while asleep. Life uses the body for hunger and calls `body.eat`.

## Not realistic
- No hormones (insulin is a single lumped state; no glucagon, cortisol, leptin, real ghrelin), no liver/kidney, no fat
  or protein digestion; every meal is pure carbohydrate with the same absorption.
- No diabetes, no glucose-lowering drugs, no exercise beyond a crude uptake term; one fixed 70 kg body.
- Heart rate: no baroreflex, no respiratory sinus arrhythmia or beat-level HRV, no circadian HR, no blood pressure;
  the variability is generic coloured noise. REM surges are only larger noise, not discrete bursts.
- Breathing is a rate only (no depth, apnoea, CO2 chemoreflex).
- The brain feedback (insula drive) and every gain are design choices.
- Data and licences: no external data. All numbers are from the cited papers or hand-tuned.

## References
Bergman et al. 1979 Am J Physiol 236:E667; Dalla Man et al. 2006 IEEE Trans Biomed Eng 53:2472 and 2007 54:1740;
Cahill 1970 NEJM 282:668;
Berntson et al. 1991 Psychol Rev 98:459; Berntson et al. 1993 Psychophysiology 30:183; Berger et al. 1989 Am J Physiol
256:H142; Jose and Collison 1970 Cardiovasc Res 4:160; Somers et al. 1993 NEJM 328:303; Trinder et al. 2001
J Sleep Res 10:253 (autonomic activity across sleep); Douglas et al. 1982 Thorax 37:840; Gould et al. 1988 Am Rev
Respir Dis 138:874; Cummings et al. 2001 Diabetes 50:1714; Craig 2002 Nat Rev Neurosci 3:655.
