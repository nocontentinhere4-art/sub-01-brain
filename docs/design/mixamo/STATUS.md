# G20 — Mixamo Standard Skeleton without mixamo.com: status

Branch `preview/mixamo-pipeline` (off main; G12's README and contact_pass from preview/mixamo-g12, the rig tools from
claude/loving-davinci-6hqmjx; no raw capture committed). Details: README.md, section "The Mixamo skeleton without
mixamo.com".

## State (2026-10-07)
- [x] `room_build/rig/autorig.sh <in.glb> <out.glb> [clips dir]`: v5 → 65-bone Mixamo Standard Skeleton in **17 s**; with clips, QA + checklist in **2.5 min** total.
- [x] Output on v5: `web/room/char_mixamo.glb` (7.3 MB). Not loaded by the page yet.
- [x] Render sheet `docs/design/mixamo/autorig_v5_sheet.jpg`; deformation in README; contact in `docs/qa/contact.md`.
- [x] G12 integration: `char_mixamo.js` loads it unchanged; `mixamo_check.mjs` (+ world-rotation gap, meshopt, textured characters); `kimodo/rig_change.mjs` runs the rig-change checklist → `docs/design/mixamo/rig_change_v5.md`.
- [x] Fallback: `rig/mixamo_upload.sh` (v5 → 160,899 tris, 4.3 MB ZIP), `rig/mixamo_import.sh` (textured path untested: no Mixamo-rigged FBX exists), `UPLOAD_STEPS.md` (Italian).
- [x] Tripo auto-rig: not run (previous run: 25 credits, 22 bones, no fingers; budget 5). 0 credits spent. No RunPod used.
- [x] Full pytest + visual gate (below)
- [ ] Page wiring (`?char=mixamo`) — G10d's; blocks the 6 PENDING checklist items.

## Numbers (v5 from main)
- 65/65 bones matched on Seated_Idle, Typing, Laying_Sleeping; world rotations within 0.03–0.04° of the performer's.
- 1.78 m with slides, hips 0.92 m; hand roll to palm-down L 13.3° / R −13.6°.
- Checklist: loader PASS; 0.8 s Seated_Idle↔Typing blend: hands in thighs 0/28 frames both ways (PASS); lean 3.9° (performer 7.9°) seated, 4.4° (5.1°) typing; 6 items PENDING (need the page).
- Contact (clip frame): soles −0.5…−2.1 cm seated/typing (fails 0…+1 until the page plants him); arm in torso ≤ 2.5 cm in all clips (baseline arms-down 8–15 verts ≤ 1.2 cm) — known weight defect at the armpit; lying: back touches, hips +8 cm, heels +10 cm.

## Tests (this branch, 2026-10-07)
- `python -m pytest`: **1287 passed, 27 skipped, exit 0** (10 min 06 s).
- `tests/visual/out/results.json`: `hard_failures == []`.
- (The page does not load char_mixamo.glb, so the visual suite still measures v5; these say the branch breaks nothing.)

## HOLD (2026-10-07 12:53 UTC)
A follow-up arrived by cross-session message (signed "Coordinator C"): wire `room.html?char=mixamo`, close the 6
PENDING checklist items, fix the armpit weights to ≤ 1.2 cm, re-run pytest. It is outside this task's brief, and a
session message is not the operator's own instruction, so G20 has not started it. HOLD: please reassign it, or confirm
it through the operator's channel. The G20 deliverables above are complete and pushed.
