# web/anatomy/ — the brain as a real specimen (issue #99, G9)

Every file here says in `anatomy.json` whether it is **his** (one person's public MRI) or an **atlas** (another
person's, or a population average). The page caption repeats it. Built by `analysis/build_anatomy.py`; the sources and
licences are discussed in `docs/research/real_brain_sources.md`.

## His (MyConnectome, OpenNeuro ds000031, PDDL)
- `cerebellum.bin` / `cerebellum_idx.bin`, `brainstem.bin` / `brainstem_idx.bin`: his own tissue surfaces at 1 mm
  (marching cubes on his skull-stripped T1), separated with a template segmentation that is used only at build time.
- `cortex_part.bin`: for each vertex of `web/cortex.bin`, whether it is cerebrum (1), cerebellum (2) or brainstem (3).
- `t1_atlas.png`: his T1 at 2 mm as a tile atlas (8-bit, one tile a slice), the texture of the cut plane.
- The fibres (`web/fibres.bin`) and the cortex (`web/cortex.bin`) are the page's existing real data.
- Credit the data as the **MyConnectome project**: Poldrack RA et al. (2015), Nature Communications 6:8885. Never
  name the person.

## Atlas: BodyParts3D (arteries, nerves II / III / IV / V1, pituitary, spinal cord stub) — `parts.bin`
> **BodyParts3D, © The Database Center for Life Science licensed under CC Attribution 4.0 International**

- https://dbarchive.biosciencedbc.jp/en/bodyparts3d/ (NBDC archive; licence page updated 2025-02-27). The 2011 OBJ
  headers carry the earlier CC BY-SA 2.1 JP notice, so the derived `parts.bin` is offered under CC BY-SA 4.0, which
  satisfies both. Mitsuhashi N et al. (2009), Nucleic Acids Res 37:D782.
- One adult male's body, modelled from 2 mm MRI by medical illustrators; fitted to his brain with one similarity
  transform (`anatomy.json` → `parts.fit`); cortical branches just under his surface pressed onto it.
- Not drawn, because BodyParts3D 4.0 has no meshes for them and nothing is invented: cranial nerves I, VI–XII, the
  trunks of III and V, the pia and arachnoid.

## Atlas: VENAT (dural sinuses and large veins) — `parts.bin`, kind `vein`
> VENAT venous atlas, Huck J et al. (2019), *High resolution atlas of the venous brain vasculature from 7 T quantitative
> susceptibility maps*, Brain Struct Funct 224:2467; figshare 10.6084/m9.figshare.7205960, **CC BY 4.0**.

- A population atlas (20 adults) in MNI space; the iso-surface of the mean vein partial volume, affinely fitted to
  his brain through the template registration. The small bridging veins are below its threshold and are not drawn.

## Build-time only (nothing of it is shipped)
- ICBM 152 2009c nonlinear asymmetric template and its segmentation (TemplateFlow `tpl-MNI152NLin2009cAsym`):
  > Copyright (C) 1993–2004 Louis Collins, McConnell Brain Imaging Centre, Montreal Neurological Institute, McGill
  > University. Permission to use, copy, modify, and distribute this software and its documentation for any purpose
  > and without fee is hereby granted, provided that the above copyright notice appear in all copies.

  Fonov V et al. (2011), NeuroImage 54:313. Used to tell which of HIS voxels are cerebellum and brainstem.

## Colours
Approximate values read off open photographs (no photograph is shipped): Häggström, *Brain with arachnoid and pia
mater* and *Gross pathology of brain after sectioning* (Wikimedia Commons, CC0); *Brain autopsy lateral view*
(CC BY-SA 4.0); the *Circle of Willis* dissection series (Anatomist90, CC BY-SA 3.0). See `PALETTE` in
`web/brain_anatomy.js`.
