# char-fix: the collar (hood lining) on v5

v5's head is a separate bust grafted on the body. Between the neck and the hood there was nothing: the hood is one thin
shell standing 6-9 cm off the neck at the sides and back, so looking down the collar you saw the shell's back faces and
into the body. The owner's one-piece Tripo character (`docs/design/char-owner-tripo/`) is the reference: its lining
runs from the hood's rim down into a groove that meets the neck 1.5-3 cm below it (0.7-2.5 cm off the neck at the rim,
a fold about 2 cm thick).

`hood_lining` is that inner surface on v5, a part of its own on the same skeleton: for each 3 deg round the neck, from
the hood's top rim down the inside of its wall (3 mm inside it, facing the neck) to the wall's innermost lip, then a
sagging groove down to the neck 2.5 cm below the lip. Where the neck's skin ends in its cut lower edge (the open edges of
the head's mesh: a ring at 1.454 m at the throat, a saw-toothed cut up to 1.478 m at the sides and back), the lining
meets the neck 4 mm over that edge's highest tooth (smoothed round the neck), 1 mm out of the skin, and runs on under
the skin, 4 mm into it, to 1 cm under the edge: the skin's cut edge always sits on lining, never on air (G23's review:
a ragged throat edge with a black sliver and a pinhole of light under it). Its top rim is smoothed round the neck (a
5-point average, three times: it showed as flat shards round the nape). Skinned from the hood's nearest vertices at the
top and the neck's at the bottom. Its fabric is a 7.6 cm patch of the hood's own texture (base colour and normal map),
mirrored-tiled at real scale. The face, the neck and the hood's outer shape are untouched.

`hood_patches` fills the hood's own holes round the collar: every open-edge loop of its mesh there (9 of them; the loop
along the hood's top rim, behind the lining, stays open), a domed fan about each loop's centre (a middle ring, the
centre 4 mm out), skinned from the nearest hood vertices (`patches.py`). A hole whose edge lies in one texture chart of
the hood is in the hood's own material and UVs (a copy of it, two-sided: the same fabric, colour and grain as round it);
the three a seam crosses are in the lining's tiled fabric (`hood_patches_tiled`). The hoodie's own neck opening (the big
loop round the neck) is closed by `hood_neck_fill`, a band from the neckline up and in to the neck's skin, 4 mm over its
cut edge and 2 mm inside it, round the front (+-70 deg; at the sides and back the lining closes it), in the lining's
fabric a shade darker. Before, a flat fan across that opening caught the light as a lighter plate under the chin (G23).
Every fill is wound to face the way it is seen from: the page draws the back faces of his parts black, as his inside.

Rebuild (the dumps under `charfix/v5` are made by `dump.mjs` from main's v5 before the collar, `git show
3e91006:web/room/char_v5.glb`; the fabric patch by hand from its texture as described in `lining.py`; then the feet,
`feet.mjs`, on the result):

    cd room_build && node charfix/dump.mjs <v5 before the collar> charfix/v5
    cd charfix && python3 lining.py && python3 patches.py && cd ..     # -> p_lining, p_patches, p_patches_tiled, p_neck_fill
    node charfix/add_parts.mjs <v5 before the collar> <collar.glb> charfix/spec_collar.json
    node charfix/feet.mjs <collar.glb> ../web/room/char_v5.glb
