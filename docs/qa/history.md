# Scorecard history (issue #98, G8)

One row per re-score. Scores: face · body · motion · soft goods · hard surfaces · lighting · window · overall, on the
photorealism scale of `scorecard.md` (1 obviously CG … 5 passes as a photo in the close-ups).

| date (UTC) | main / branch | face | body | motion | soft | hard | light | window | overall | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-02 | main 00af116 | 1 | 1 | 2 | 2 | 3 | 2 | 1 | 1.7 | baseline; 22 defects routed (`defects.md`); scale re-based to photorealism on the owner's brief (first draft of the day used a "game look" scale: 2/2/3/2/4/3/2) |
| 2026-10-03 | main 9353bda | 1 | 1 | 3 | 2 | 3 | 2 | 1 | 1.9 | after #104 (path/path_to: camera waits for him), #105, #108 (asleep under the duvet, side poses), #109; defects 9 and 21 fixed; no regressions; 58 shots, 0 hard failures |
| 2026-10-03 | main 5d9a934 | 1 | 1 | 3 | 3 | 4 | 2 | 3 | 2.4 | after #107 (soft goods), #113 (window), #110 (hard surfaces), #80 (motion: typing clip); defects 7, 11, 13, 19, 20 fixed, 12 and 14 largely; new 23–27; draw calls 52 → 64, triangles 168k → 226k; 0 hard failures |
