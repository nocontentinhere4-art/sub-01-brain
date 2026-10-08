# Receptor data: sources and licences (component: neurochem)

Part of a digital twin model of one real person's brain structure and recorded activity; not a mind, not conscious,
not the person. All receptor data here are **group data from other people** (post-mortem brains), not this person's.
Checked on 2026-09-30. This project is public and linked to a crypto token, so every source was treated as
potentially commercial use: only sources with a permissive licence (CC0 / CC BY / MIT-style) are used.

## Used

| File | Content | Source | Licence |
|---|---|---|---|
| `twin/data/zilles2017_all_layers.csv` | 15 receptors x 44 cortical areas, mean density over all layers (fmol/mg protein), extracted unchanged from Supplementary Table 2; plus our **approximate** MNI centroid per area (hand-set, see `twin/build_receptors.py`) | Zilles K, Palomero-Gallagher N (2017) Multiple transmitter receptors in regions and layers of the human cerebral cortex. *Frontiers in Neuroanatomy* 11:78. doi:10.3389/fnana.2017.00078. File taken from the mirror `AlGoulas/receptor_principles` (`recept_data/ReceptData.xlsx`, commit `1a8b8714271d99ffe62f81f93ac42f3e57c952f1`) | Article and supplement: **CC BY 4.0** (Frontiers publishes all articles under the Creative Commons Attribution licence, https://creativecommons.org/licenses/by/4.0/). The mirror repository is **MIT** (Copyright (c) 2020 AlGoulas). Its README says "The receptor data are freely available from the following publication: Zilles K, Palomero-Gallagher N (2018) ...". |
| `twin/data/receptors_214.csv` | 7 of those receptors (D1, 5-HT1A, 5-HT2, alpha1, alpha2, M1, alpha4beta2) mapped to the 200 Schaefer parcels by inverse-distance weighting; subcortical rows left **blank** (no data) | Derived from the row above (adaptation, CC BY 4.0, attribution: Zilles & Palomero-Gallagher 2017) + Schaefer MNI centroids | **CC BY 4.0** (adapted; changes: parcel interpolation, subset of receptors) |
| (build input, not committed) Schaefer-200 7-network MNI centroids + label order | `Schaefer2018_200Parcels_7Networks_order_FSLMNI152_1mm.Centroid_RAS.csv` | Schaefer A et al. (2018) *Cerebral Cortex* 28:3095-3114; ThomasYeoLab/CBIG commit `35b5664bec8822e2f77da5e090e96f91d0095be6` | **MIT** (Copyright (c) 2016 CBIG). Centroid coordinates are copied into `receptors_214.csv` (columns mni_x/y/z). |

Parcel order check: the 200 names in the CBIG centroid file equal `out/atlas_names.json[0:200]` exactly (also
asserted by `twin/build_receptors.py` and `tests/test_neurochem.py`).

Licence caveat: frontiersin.org, Crossref, PubMed Central and Europe PMC are blocked from this sandbox, so the
CC BY statement on the article page could not be re-read today. It rests on Frontiers' journal-wide CC BY policy
and on the MIT-licensed mirror. Please confirm it before a commercial release.

## Looked at and NOT used (non-commercial or unclear licence)

| Source | Why not |
|---|---|
| `netneurolab/hansen_receptors` (Hansen et al. 2022 *Nat Neurosci* 25:1569) - the ready Schaefer-parcellated PET maps (D1, D2, DAT, 5-HT1A/1B/2A/4/6, 5-HTT, NET, alpha4beta2, M1, VAChT, ...) | README: "This work is licensed under a Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License" (http://creativecommons.org/licenses/by-nc-sa/4.0/), commit `f8b41da92a733f99368c1f39d4959731aa1316c1`. There is no separate LICENSE file (404). **NC: no data or derived values used.** |
| `netneurolab/neuromaps` (Markello et al. 2022 *Nat Methods* 19:1472) - toolbox + annotation registry | Repository `LICENSE`: "Attribution-NonCommercial-ShareAlike 4.0 International" (commit `ffcc2e0f657943ce00a1b6a968396f32250e495c`). Per-annotation licences in `neuromaps/datasets/data/meta.json`: beliveau2017 (5-HT1A cumi101, 5-HT1B az10419369, 5-HT2A cimbi36, 5-HT4 sb207145, 5-HTT dasb) and norgaard2021 (flumazenil) are **CC BY-NC-SA 4.0**. Most others (kaller2017 D1, sandiego2015/smith2017 D2 flb457, alarkurtti2015 raclopride, jaworska2020 fallypride, dukart2018 fpcit DAT, savli2012 5-HT maps, hesse2017/ding2010 NET, hillmer2016 flubatine alpha4beta2, naganawa2020 M1, aghourian2017/bedard2019/tuominen/spreng FEOBV VAChT) have **no licence stated = unclear**, so they are not used. |
| neuromaps `malen2022` raclopride D2 (Malén T et al. 2022 *NeuroImage* 255:119149) | Licence **CC0** (usable), but the file is hosted only on OSF (osf.io blocked from here: "CONNECT tunnel failed, response 403"); GitHub code search found no mirror of the file. **Not used: D2 has no map.** |
| neuromaps CC0/CC BY/MIT maps that are not neuromodulator receptors (lukow2022 GABAA-alpha5 CC BY 4.0, kim2020 COX-1 CC0, wey2016 HDAC CC0, lois2018 TSPO MIT) | Permissive but not relevant to DA/5-HT/NE/ACh gain. |
| Zenodo, NeuroVault, figshare, OpenNeuro, Allen brain-map API | Blocked from this sandbox (proxy 403). |

## Consequences (documented fallbacks)

- **Subcortical regions (14 Harvard-Oxford nuclei): no receptor data.** The autoradiography table covers cortex
  only. `receptors_214.csv` leaves these rows blank. At runtime `twin/neurochem.py` gives them the **cortical
  mean** density (flag `RECEPTOR_SOURCE == "fallback_cortical_mean"`): no regional specificity, and certainly not
  the real striatal D1/D2 or thalamic density, which are much higher in reality.
- **No D2, DAT, 5-HTT or NET map.** Dopamine gain uses D1 only. Noradrenaline uses alpha1/alpha2 receptor density
  instead of NET (transporter) density.
