# Real brains online: sources, licences and what `/brain` uses (issue #99, G9)

The owner's ask: *"cerca cervelli reali online, e fai che il nostro sia più reale possibile, neuroni, nervi etc."*
This note records every candidate source checked on 2026-10-02, its licence as read on the live page (quoted, not
paraphrased), whether a public, possibly commercial website may use it, and what the brain page finally draws. Not legal
advice. The full research log with URLs is condensed here; the verbatim licence sentences are kept.

## The rule for this site
The brain itself is **his** (one person's public MRI, MyConnectome / OpenNeuro ds000031, PDDL): cortex, cerebellum,
brainstem, the cut surface and the fibres. Anything that is not in his scans comes from an **atlas** and is labelled as
such in the page caption, part by part. Nothing is invented: a structure with no licensed source is **not drawn**, and
the caption lists what is missing. Only sources that allow commercial public use are shipped.

## Verdicts

| source | what it is | licence (verified) | public commercial site? | used |
|---|---|---|---|---|
| **BodyParts3D 4.0** (DBCLS, NBDC archive) | polygon atlas of one adult male body from 2 mm MRI, hand-refined by medical illustrators (Mitsuhashi et al. 2009, NAR 37:D782) | **CC BY 4.0** since 2025-02-27: *"The license for this database is specified in the Creative Commons Attribution 4.0 International. If you use data from this database, please be sure attribute this database as follows: "BodyParts3D, © The Database Center for Life Science licensed under CC Attribution 4.0 International"."* (dbarchive.biosciencedbc.jp/en/bodyparts3d/lic.html). The 2011 OBJ headers still say CC BY-SA 2.1 JP. | yes | **yes**: arteries, nerves II / III (orbital branches) / IV / V1, chiasm, pituitary, cord stub; its brain only to fit the atlas to his |
| **MNI ICBM152 2009c** nonlinear asym (McConnell BIC; TemplateFlow mirror) | population-average template (152 young adults) | *"Copyright (C) 1993-2004 Louis Collins, McConnell Brain Imaging Centre, Montreal Neurological Institute, McGill University. Permission to use, copy, modify, and distribute this software and its documentation for any purpose and without fee is hereby granted, provided that the above copyright notice appear in all copies."* | yes | **build time only**: its FreeSurfer-style segmentation (`desc-carpet_dseg`) is warped onto his T1 to tell which of HIS voxels are cerebellum / brainstem; nothing of the template is shipped |
| **VENAT** venous atlas (Huck et al. 2019, 7 T QSM, n = 20; figshare 10.6084/m9.figshare.7205960) | probabilistic map of cerebral veins and dural sinuses in MNI space | **CC BY 4.0** (figshare record) | yes | **yes**: the superior sagittal, straight and transverse sinuses and the large superficial veins as an atlas layer (`analysis/venat_veins.py`), fitted with the template's affine |
| Mouches & Forkert 2019 artery atlas (Sci Data 6:29) | TOF-MRA average of 544 subjects, MNI 0.5 mm | **CC0** (figshare) | yes | no: BodyParts3D's arteries are one real person's named vessels, which read better than a blurred average; kept as the fallback |
| Harvard Ascending Arousal Network atlas v2 (Edlow et al.) | brainstem nuclei | **CC0** (Dryad) | yes | no: his own brainstem is drawn |
| Z-Anatomy (Z-Anatomy/Models-of-human-anatomy, LluisV/Z-Anatomy) | BodyParts3D rebuilt in Blender, with added parts | CC BY-SA 4.0; but its README says the "Brainder" and "White matter" brain models (University of Washington) carry **no stated licence**, and two included models are **non-commercial** | only the BodyParts3D-derived parts, share-alike | no (the licence mix is not clean; BodyParts3D itself is CC BY) |
| **BigBrain** (Amunts et al. 2013) | one post-mortem brain at 20 µm | *"BigBrain is licensed under: Creative Commons Attribution-NonCommercial-ShareAlike 4.0"*; the FTP welcome file: *"For research purposes only, no commercial use without written consent."* | **no** | no |
| **Allen Human Brain Atlas** | microarray + MRI of 6 donors | terms of use: *"must be for research or other noncommercial purposes unless ... agreed to in writing by the Allen Institute"* | **no** (without written permission) | no |
| **Julich-Brain** (Amunts et al. 2020) | probabilistic cytoarchitectonic maps | CC BY-NC-SA 4.0 on every release v1.13–v3.1 (DataCite) | **no** | no |
| **HCP** open-access data | 1200 young adults' MRI | the Open Access Data Use Terms forbid nothing commercial, require the acknowledgement sentence, and derived data may only be redistributed under the same terms | unclear for redistribution | no: our fibres are his own tractography |
| SUIT / Diedrichsen cerebellum | cerebellar template and lobules | `tpl-SUIT/LICENSE`: CC BY-NC 3.0 (the repo README says CC BY unless noted: a conflict) | **no** | no |
| Umeå Brain Arteries (Dunås 2017) | 4D-flow artery atlas | CC BY-NC-SA | **no** | no |
| Braincharter vasculature (Bernier 2018) | TOF + SWI atlas, 41 subjects | no licence file in the repository | treat as all rights reserved | no |
| AAL | Colin27-drawn parcellation | GPL ("copyright freeware under the terms of the GNU General Public Licence") | yes, copyleft | no |
| Sketchfab | — | downloads need a login; candidates: Science Museum "Model of a human brain" (CC0, a 19th-century papier-mâché model, not a brain), RISD Nature Lab "Human Brain" (CC BY, a structured-light scan), dgallichan "Brain" (CC BY, FreeSurfer from an MRI), haimezer "Normal cerebral arteries N001" (CC BY), Z-Anatomy "Neurology" (CC BY-SA). One "CC BY" model derives from a CC BY-NC original (avoid). | per model | no: none adds anything his MRI and BodyParts3D do not have, and none is downloadable without an account |

## What the page draws, and where each piece comes from

| piece | source | file | how |
|---|---|---|---|
| cortex with gyri and sulci | **his MRI** | `web/cortex.bin` (existing) | `build_cortex.py`; the sulcal shading is computed in the browser from the mesh itself (depth under a smoothed copy) |
| cerebellum (folia), brainstem | **his MRI** | `web/anatomy/cerebellum.bin`, `brainstem.bin` | `analysis/build_anatomy.py`: the template segmentation is warped onto his T1 (dipy affine + SyN) only to pick which of his voxels belong to each; marching cubes on his own tissue at 1 mm, light simplification |
| the cut surface (dissected view) | **his MRI** | `web/anatomy/t1_atlas.png` | his skull-stripped T1 at 2 mm as a tile atlas; the shader colours it grey / white / CSF from the landmarks of his own intensity histogram |
| white-matter bundles | **his MRI** | `web/fibres.bin` (existing) | the same real tractography, drawn with normal blending and muted direction colours instead of additive glow |
| arteries (circle of Willis, carotid, vertebral, basilar, ACA / MCA / PCA with their cortical branches, cerebellar arteries) | atlas: BodyParts3D | `web/anatomy/parts.bin` | `analysis/bp3d_parts.py`: one similarity transform (scale, rotation, translation) fitted by trimmed ICP of the atlas brain onto his cortex; cortical branches just under his surface are pressed onto it; the fit residual is written to `anatomy.json` and quoted in the caption |
| cranial nerves II (optic nerve, chiasm, tract), III (orbital branches), IV, V1; pituitary; spinal cord stub | atlas: BodyParts3D | `web/anatomy/parts.bin` | same transform |
| dural sinuses and large veins | atlas: VENAT | `web/anatomy/parts.bin` | `analysis/venat_veins.py`: iso-surface of the density map, the template affine into his T1 frame |
| **not drawn** | — | — | cranial nerves I, III (trunk), V (trunk), VI–XII, the small bridging veins, pia / arachnoid as surfaces: no source with a licence that allows a public site. The caption says so whenever nerves or vessels are on. |

## Colour values
No paper gives calibrated sRGB values of fresh grey vs white matter. The spectral measurements (Eggert & Blazek 1987,
Neurosurgery 21:459; Yaroslavsky et al. 2002, Phys Med Biol 47:2059; Ali 2022, Optics 4:1, CC BY) say grey matter
reflects about half of what white matter does at 650–800 nm, and below 600 nm haemoglobin dominates: living cortex is
pink-grey, white matter cream. The values in `web/brain_anatomy.js` (`PALETTE`) were read off open photographs:
- fresh: Häggström, *Brain with arachnoid and pia mater* (Wikimedia Commons, **CC0**): glistening arachnoid, surface
  vessels, pinkish-grey gyri; the unfixed pink tissue in *Gross pathology of brain after sectioning* (CC0);
- fixed: the tan fixed tissue in the same sectioning photo, *Brain autopsy lateral view* (CC BY-SA 4.0), and the
  *Circle of Willis* dissection series (Anatomist90, CC BY-SA 3.0) for the base of the brain and the arteries.
No photograph is shipped. Vessel courses follow Rhoton 2002 (*The Supratentorial Arteries*, *The Cerebral Veins*,
Neurosurgery 51 Suppl) only as reading; the geometry is the atlases'.

## Download and provenance log (2026-10-02)
- BodyParts3D: `https://dbarchive.biosciencedbc.jp/data/bodyparts3d/LATEST/isa_BP3D_4.0_obj_99.zip` (142,903,898 B;
  2,233 OBJ files) + `isa_element_parts.txt`, `isa_parts_list_e.txt`, `partof_element_parts.txt`,
  `partof_parts_list_e.txt`. The is-a tree names the vessels and nerves; the part-of tree names the hemispheres,
  brainstem and spinal cord (same element files). Present in the brain: 59 brain elements, cerebellum (2), brainstem
  (11), optic chiasm / nerves / tracts, spinal cord (1), the whole circle of Willis with the proximal cortical MCA
  branches, tentorium. Absent: CN I, VI–XII, the trunks of III and V, every dural sinus and cerebral vein, falx, pia.
- ICBM 2009c: `https://templateflow.s3.amazonaws.com/tpl-MNI152NLin2009cAsym/` (`res-01_desc-brain_T1w`,
  `desc-brain_mask`, `desc-carpet_dseg`, `LICENSE`).
- VENAT: `https://ndownloader.figshare.com/files/15347951` (`VENAT_DensityMap.nii.gz`).
- Everything was fetched once at build time (`out/anatomy_work/`, git-ignored). The page hot-links nothing.

## Budget
`web/anatomy/` ships ≈ 1.2 MB (see `anatomy.json` → sizes), lazy-loaded on the first click of a realistic view or
layer; the page without them is unchanged.
