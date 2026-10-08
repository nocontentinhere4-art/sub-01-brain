"""The room's soft goods at game quality (#98 G4): socks and a towel on the pinch hanger, the hand towel in terry cloth,
the duvet (cloth-simulated, turned back at the head end, box-quilted), the pillow (a sewn case with its seam and a head
dent), the mattress with its fitted sheet, the curtains (pencil pleats, hems), the rug and its binding, the floor cushion
(tufted, piped), the hoodie and the tote on the door hooks, the backpack, and two clothes: jeans dropped by the bed's
foot and a T-shirt thrown on the bed (cloth-simulated).

Called from build_room.py:  `import props_soft as PS; PS.bind(globals())` right after the materials, then one call per
item where its old code was. Everything here is geometry built from code (CC0) with Poly Haven CC0 fabric textures
prepared by tex_prep.py (credits: web/room/CREDITS.md). Coordinates in the builders are glTF/three.js world units like the
rest of the build (x right, y up, z towards the viewer); `Bv` converts a glTF Vector into Blender's.

Names, origins and node structure that web/room.html relies on are untouched: the hoodie's and the tote's parts join the
"hangers" node (origin at the door hinge), the pillow and the mattress keep their names (the duvet's cloth sim collides
with them), the curtains are "curtain_a" / "curtain_b" and the rug is "rug" for the prop sweep.
"""
import bpy, bmesh, math, random
from mathutils import Vector, Matrix, noise

G = None            # build_room.py's globals (live: names defined later in the build are read when a builder runs)


def bind(ns):
    global G, B, mat, MATS, new_obj, project_uv, box, cyl, transform, set_vcol, STATIC, SC, srgb
    G = ns
    B, mat, MATS, new_obj, project_uv, box, cyl = ns["B"], ns["mat"], ns["MATS"], ns["new_obj"], ns["project_uv"], ns["box"], ns["cyl"]
    transform, set_vcol, STATIC, SC, srgb = ns["transform"], ns["set_vcol"], ns["STATIC"], ns["SC"], ns["srgb"]
    materials()


def Bv(v): return B(v.x, v.y, v.z)
def gl(v): return Vector((v.x, v.z, -v.y))          # Blender -> glTF


# ---------------------------------------------------------------- materials (fabrics; all textures from tex_prep.py)
def fab(name, sheen=0.0, **kw):
    """a fabric: build_room's mat() plus a sheen (KHR_materials_sheen: the soft rim light of fibres)"""
    m = mat(name, **kw)
    if sheen:
        P = m.node_tree.nodes["Principled BSDF"]
        P.inputs["Sheen Weight"].default_value = sheen; P.inputs["Sheen Roughness"].default_value = 0.6
    return m


def materials():
    fab("sheet", diff="sheet_diff.jpg", nor="sheet_nor.jpg", nstr=0.7, rough=0.9, uv=0.26)                      # cotton jersey (white)
    fab("duvet", diff="duvet_diff.jpg", nor="duvet_nor.jpg", nstr=0.9, rough=0.95, uv=0.28, sheen=0.25)         # waffle pique, slate
    fab("curtain", diff="curtain_diff.jpg", nor="curtain_nor.jpg", nstr=0.8, rough=0.95, uv=0.27, sheen=0.45)   # rough linen, light
    fab("rug", diff="rug_diff.jpg", nor="rug_nor.jpg", rough=1.0, uv=0.32, sheen=0.3)                           # wool herringbone
    fab("hoodie", diff="hoodie_diff.jpg", nor="hoodie_nor.jpg", nstr=0.9, rough=0.95, uv=0.27, sheen=0.3)       # jogging melange
    fab("rib", color=srgb("#4f5560"), rough=0.95, nor="rib_nor.jpg", nstr=1.0, uv=0.045, sheen=0.3)             # ribbed cuffs and hem
    fab("bag", color=srgb("#2b3440"), rough=0.7, nor="bag_nor.jpg", nstr=0.8, uv=0.09)                          # polyester weave
    fab("cushion", diff="cushion_diff.jpg", nor="sheet_nor.jpg", nstr=0.8, rough=0.95, uv=0.26, sheen=0.25)     # cotton, mustard
    fab("knit", vcol=True, rough=0.95, nor="knit_nor.jpg", nstr=1.0, uv=0.075, sheen=0.4)                       # socks (colour per vertex)
    fab("terry", diff="terry_diff.jpg", nor="terry_nor.jpg", nstr=1.0, rough=1.0, uv=0.18, sheen=0.5)           # the towel
    fab("canvas", diff="canvas_diff.jpg", nor="curtain_nor.jpg", nstr=0.7, rough=0.9, uv=0.27)                  # the tote
    fab("denim", diff="denim_diff.jpg", nor="denim_nor.jpg", nstr=0.9, rough=0.9, uv=0.27)                      # jeans
    fab("jersey", vcol=True, rough=0.92, nor="sheet_nor.jpg", nstr=0.7, uv=0.26, sheen=0.25)                    # T-shirt, mattress ticking


# ---------------------------------------------------------------- builders (glTF coordinates in, Blender meshes out)
def smooth01(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a))) if b != a else float(x >= b)
    return t * t * (3 - 2 * t)


def bump(x, c, w):
    """1 at c, 0 beyond c +- w (smooth)"""
    return max(0.0, 1 - ((x - c) / w) ** 2) ** 2


def nz(p, scale=1.0, seed=0.0):
    """smooth noise in -1..1 at a glTF point"""
    return noise.noise(Vector((p.x * scale + seed * 7.1, p.y * scale + seed * 3.3, p.z * scale - seed * 5.7)))


def grid_obj(nm, material, grid, static=True, flip=False):
    """a sheet from rows of glTF points: face (j,i)-(j,i+1)-(j+1,i+1)-(j+1,i); its normal is (along i) x (along j)"""
    bm = bmesh.new(); V = [[bm.verts.new(Bv(p)) for p in row] for row in grid]
    for j in range(len(V) - 1):
        for i in range(len(V[j]) - 1):
            q = [V[j][i], V[j][i + 1], V[j + 1][i + 1], V[j + 1][i]]
            f = bm.faces.new(q[::-1] if flip else q); f.smooth = True
    return new_obj(nm, bm, material, static)


def tube_obj(nm, material, rings, static=True, cap=(False, False), closed=False):
    """a tube through rings of glTF points (same count each); cap: a face on the first / last ring; closed: a loop (the
    last ring joins the first). Collapsed rings (a tiny radius) become a pole."""
    bm = bmesh.new(); R = [[bm.verts.new(Bv(p)) for p in ring] for ring in rings]; n = len(rings[0])
    if closed: R.append(R[0])
    for k in range(len(R) - 1):
        for i in range(n):
            j = (i + 1) % n
            f = bm.faces.new([R[k][i], R[k][j], R[k + 1][j], R[k + 1][i]]); f.smooth = True
    if cap[0]: bm.faces.new(list(reversed(R[0]))).smooth = True
    if cap[1]: bm.faces.new(R[-1]).smooth = True
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=5e-4)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return new_obj(nm, bm, material, static)


def frames(pts, ref):
    """per point of a glTF polyline: (tangent, width axis, the third axis). ref: a Vector made perpendicular to the
    tangent, or "h": the width axis horizontal (up x tangent; the third axis then points up for a path lying flat)"""
    out = []; up = Vector((0, 1, 0))
    for k in range(len(pts)):
        t = (pts[min(k + 1, len(pts) - 1)] - pts[max(k - 1, 0)]).normalized()
        w = up.cross(t) if ref == "h" else ref - ref.dot(t) * t
        w = w.normalized() if w.length > 1e-6 else t.orthogonal().normalized()
        out.append((t, w, t.cross(w).normalized()))
    return out


def ring(c, ax_a, ax_b, a, b, n, fn=None, p=2.0):
    """an ellipse (or a superellipse, p > 2: squarer) of half-axes a along ax_a and b along ax_b; fn(theta) scales"""
    pts = []
    for i in range(n):
        th = 2 * math.pi * i / n; ct, st = math.cos(th), math.sin(th)
        if p != 2.0: ct, st = math.copysign(abs(ct) ** (2 / p), ct), math.copysign(abs(st) ** (2 / p), st)
        r = 1.0 if fn is None else fn(th)
        pts.append(c + ax_a * (a * r * ct) + ax_b * (b * r * st))
    return pts


def tube_along(nm, material, path, a, b, n=12, ref=Vector((0, 1, 0)), taper=None, fn=None, static=True, cap=(False, False), p=2.0):
    """a tube of elliptical section (a along ref's projection, b across) along a glTF polyline; taper(k, N) scales"""
    F = frames(path, ref); rings = []
    for k, (c, (t, w, nn)) in enumerate(zip(path, F)):
        s = 1.0 if taper is None else taper(k / max(1, len(path) - 1))
        aa, bb = (a * s, b * s) if not isinstance(s, tuple) else (a * s[0], b * s[1])
        rings.append(ring(c, w, nn, aa, bb, n, fn=(lambda th, k=k: fn(th, k / max(1, len(path) - 1))) if fn else None, p=p))
    return tube_obj(nm, material, rings, static=static, cap=cap)


def paint(o, fn, by_index=False):
    """per-vertex colour: fn(glTF position) -> linear rgb (or fn(vertex index) with by_index)"""
    me = o.data; a = me.color_attributes.get("Col") or me.color_attributes.new("Col", 'FLOAT_COLOR', 'CORNER')
    for pg in me.polygons:
        for li in pg.loop_indices:
            vi = me.loops[li].vertex_index
            a.data[li].color = (*(fn(vi) if by_index else fn(gl(me.vertices[vi].co))), 1)


def displace(o, fn):
    """move every vertex along its normal by fn(glTF position, glTF normal)"""
    me = o.data; me.update()
    for v in me.vertices:
        d = fn(gl(v.co), gl(v.normal))
        if d: v.co += v.normal * d


def unspike(o, tol=0.05, rounds=4):
    """after a cloth simulation: a vertex the solver shot away (pinched between colliders) is put back among its
    neighbours; repeated, so a stray cluster collapses onto the cloth"""
    bm = bmesh.new(); bm.from_mesh(o.data); bm.verts.ensure_lookup_table(); total = 0
    for _ in range(rounds):
        moves = []
        for v in bm.verts:
            nb = [e.other_vert(v).co for e in v.link_edges]
            if not nb: continue
            mean = sum(nb, Vector()) / len(nb)
            if (v.co - mean).length > tol: moves.append((v, mean))
        for v, mean in moves: v.co = mean
        total += len(moves)
        if not moves: break
    bm.to_mesh(o.data); bm.free(); o.data.update()
    if total: print(o.name + ": put back", total, "stray vertices")


def smooth_mesh(o, factor=0.4, repeat=1):
    bm = bmesh.new(); bm.from_mesh(o.data)
    for _ in range(repeat): bmesh.ops.smooth_vert(bm, verts=bm.verts[:], factor=factor, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    bm.to_mesh(o.data); bm.free(); o.data.update()


def thin(o):
    """a thin thing (piping, a cord, a strap): its AO islands would get no texel, so the bake gives it the white corner"""
    o["ao_small"] = 1; return o


def sheet(o, thickness):
    """a thin cloth sheet: thickened symmetrically, without rim faces (their islands get no AO texel and render black)"""
    md = o.modifiers.new("solid", "SOLIDIFY"); md.thickness = thickness; md.offset = 0; md.use_even_offset = True; md.use_rim = False
    return md


def rounded_rect(y0, y1, z0, z1, r, ins, levels, n_top=10, n_bot=4, n_arc=5):
    """points (y, z) around a rounded rectangle shrunk by `ins` (corner radius r - ins), counter-clockwise seen from +x,
    with the same count for every `ins`: the sides keep the given y levels (constant: y0 + r .. y1 - r)"""
    rc = max(1e-4, r - ins); Y0, Y1, Z0, Z1 = y0 + ins, y1 - ins, z0 + ins, z1 - ins; pts = []
    def arc(cy, cz, a0, a1, k0, k1):
        for k in range(k0, k1):
            a = math.radians(a0 + (a1 - a0) * k / n_arc); pts.append((cy + rc * math.sin(a), cz + rc * math.cos(a)))
    for k in range(n_top + 1): pts.append((Y1, (Z1 - rc) + ((Z0 + rc) - (Z1 - rc)) * k / n_top))      # top, front to back
    arc(Y1 - rc, Z0 + rc, 90, 180, 1, n_arc + 1)                                                        # top-back corner
    for y in reversed(levels): pts.append((y, Z0))                                                      # back side, down (interior levels)
    arc(Y0 + rc, Z0 + rc, 180, 270, 0, n_arc + 1)
    for k in range(1, n_bot + 1): pts.append((Y0, (Z0 + rc) + ((Z1 - rc) - (Z0 + rc)) * k / n_bot))   # bottom, back to front
    arc(Y0 + rc, Z1 - rc, 270, 360, 1, n_arc + 1)
    for y in levels: pts.append((y, Z1))                                                                # front side, up
    arc(Y1 - rc, Z1 - rc, 0, 90, 0, n_arc)
    return pts


# ================================================================ curtains: pencil-pleat heading, hems, a linen that lets light in
def curtain(nm, za, zb, side):
    """a gathered linen panel between za..zb (z), hanging from the rod to just above the sill. The heading is gathered
    into ten pencil pleats that merge into four soft folds towards the hem; the hem, the heading and the side hems are
    double (thicker), the hem edge waves a little with the folds, and the panel flares slightly at the bottom."""
    ROD_Y, IX, WY0 = G["ROD_Y"], G["IX"], G["WY0"]
    nz_, ny = 64, 26; top = ROD_Y - 0.012; bot = WY0 + 0.0012; W = zb - za; x0 = IX + 0.07; grid = []
    for j in range(ny + 1):
        t = j / ny; y = top + (bot - top) * t; row = []
        k = min(1.0, t / 0.75) ** 0.8                                   # 0 at the heading (pleats) -> 1 lower down (folds)
        for i in range(nz_ + 1):
            s = i / nz_; z = za + W * s; ph = 2 * math.pi * 8 * s
            f_top = math.sin(ph) + 0.10 * math.sin(3 * ph)                                       # pencil pleats (soft enough for the shell)
            f_low = math.sin(2 * math.pi * 4.0 * s + 0.6 + 0.5 * side) + 0.3 * math.sin(2 * math.pi * 1.5 * s + 2.0)
            x = x0 + (1 - k) * 0.017 * f_top + k * 0.036 * f_low + 0.004 * nz(Vector((s * 5, t * 3, side)))
            zz = z + side * 0.03 * t * t * (s - 0.5) + 0.003 * math.sin(ph) * (1 - k)            # flare; the pleats gather z too
            yy = y + (0.004 * (0.5 + 0.5 * math.sin(2 * math.pi * 4.0 * s + 0.6 + 0.5 * side + 1.0)) if j == ny else 0)
            row.append(Vector((x, yy, zz)))
        grid.append(row)
    o = grid_obj(nm, "curtain", grid)
    vg = o.vertex_groups.new(name="hem")
    for v in o.data.vertices:
        p = gl(v.co); hem = p.y < bot + 0.06 or p.y > top - 0.07 or abs(p.z - za) < 0.025 or abs(p.z - zb) < 0.025
        vg.add([v.index], 1.0 if hem else 0.0, 'REPLACE')
    md = sheet(o, 0.010); md.vertex_group = "hem"; md.thickness_vertex_group = 0.5          # double hems and heading: 10 mm, the panel 5 mm
    return o


def curtains():
    WZ0, WZ1 = G["WZ0"], G["WZ1"]
    curtain("curtain_a", WZ0 - 0.30, WZ0 + 0.05, -1)
    curtain("curtain_b", WZ1 - 0.05, WZ1 + 0.34, 1)


# ================================================================ the bed's soft parts: mattress + fitted sheet, pillow, duvet
def mattress():
    """the mattress as a soft rounded slab (rings along its length): the fitted sheet covers the top and the sides down
    to its elastic hem, 7 cm above the base, with a 3 mm step at the hem; below it the mattress ticking shows. The
    sheet's top is faintly wrinkled."""
    BX0, BX1, BZ0, BZ1, BASE_Y, MAT_Y = (G[k] for k in ("BX0", "BX1", "BZ0", "BZ1", "BASE_Y", "MAT_Y"))
    x0, x1, z0, z1, y0, y1, r = BX0 + 0.045, BX1 - 0.01, BZ0 + 0.01, BZ1 - 0.01, BASE_Y, MAT_Y, 0.05
    band = y0 + 0.07
    levels = [band - 0.004, band, band + 0.004, (band + y1 - r) / 2]              # the sides' interior points (y0 + r .. y1 - r are the arcs')
    ends = [r * (1 - math.cos(math.radians(a))) for a in (0, 12, 25, 40, 56, 73, 90)]           # ring spacing around the ends
    xs = [x0 + d for d in ends] + [x0 + r + (x1 - x0 - 2 * r) * k / 34 for k in range(1, 34)] + [x1 - d for d in reversed(ends)]
    rings = []
    for x in xs:
        d = min(x - x0, x1 - x); ins = r - math.sqrt(max(0.0, r * r - (r - d) ** 2)) if d < r else 0.0
        rings.append([Vector((x, y, z)) for (y, z) in rounded_rect(y0, y1, z0, z1, r, ins, levels)])
    o = tube_obj("mattress", ["sheet", "jersey"], rings, cap=(True, True))
    me = o.data
    for pg in me.polygons:                                        # the ticking below the sheet's hem
        pg.material_index = 1 if gl(pg.center).y < band - 0.001 else 0
    paint(o, lambda p: srgb("#aeb3bd"))
    random.seed(31)
    displace(o, lambda p, n: 0.003 * smooth01(band - 0.004, band + 0.004, p.y) +                   # the sheet's own thickness
             (0.005 * nz(p, 6.0, 1) + 0.0025 * nz(p, 16.0, 2) if n.y > 0.7 and y0 + 0.2 < p.y else 0.0))   # wrinkles on top
    return o


def pillow():
    """a pillow in its case: a soft superellipse body (flatter underneath), the side seam as a thin piped ridge, the
    case's envelope flap at one end (a step), a head dent and small wrinkles"""
    MAT_Y = G["MAT_Y"]
    PW, PL, PT = 0.42, 0.64, 0.15; nv, nth = 40, 44; rings = []               # lofted: a filled pillow, 15 cm at the middle
    for j in range(nv + 1):
        v = j / nv * 2 - 1; e = max(0.0, 1 - abs(v) ** 4)
        a = PW / 2 * (0.06 + 0.94 * e ** 0.35); h = PT / 2 * (0.02 + 0.98 * e ** 0.5); zc = v * PL / 2 * (1 - 0.03 * e)
        pts = []
        for i in range(nth):
            th = 2 * math.pi * i / nth; c, s = math.cos(th), math.sin(th)
            x = a * math.copysign(abs(c) ** (2 / 2.0), c); y = h * math.copysign(abs(s) ** (2 / 2.0), s)
            if y < 0: y *= 0.7                                                   # a little flatter underneath
            pts.append(Vector((x, y, zc)))
        rings.append(pts)
    o = tube_obj("pillow", "sheet", rings, cap=(True, True))
    random.seed(32)
    def d(p, n):
        out = 0.0
        if n.y > 0.3: out += 0.002 * smooth01(0.17, 0.21, p.z)                   # the envelope flap of the case (a soft step)
        if abs(n.y) < 0.6: out += 0.003 * bump(abs(p.x), PW / 2, 0.03)            # the side seam's piping
        return out + 0.0035 * nz(p, 9.0, 3) + 0.0015 * nz(p, 24.0, 4)
    displace(o, d)
    for v in o.data.vertices:                                                     # the dent where his head rests: straight down, so the top never crosses itself
        p = gl(v.co)
        if p.y > 0.005: v.co.z -= 0.018 * math.exp(-(p.x * p.x * 0.7 + (p.z + 0.06) ** 2) / 0.05) * smooth01(0.0, 0.03, p.y)
    o.data.transform(Matrix.Translation(B(-1.58, MAT_Y + 0.006 + 0.7 * PT / 2 + 0.004, 0.87)) @ Matrix.Rotation(0.06, 4, 'Z') @ Matrix.Rotation(-0.05, 4, 'Y'))
    o.data.update(); return o


def duvet(mattress_o, pillow_o):
    """the duvet: a cloth simulation dropped flat onto the bed gives its lower face; the slab is then built explicitly
    (a lower face, an upper face 3 cm above it along the normal, a rim), with its head end turned back over itself:
    the lower face continues round the outside of the fold (radius 4 cm) and becomes the flap's top, the upper face
    round the inside (radius 1 cm) and becomes the flap's underside, laid back over the main part. Subtle box quilting
    (5 x 6 channels, stitch lines 2 mm down, puffs 6 mm up) and small wrinkles on the faces that show.
    web/room.html lifts this duvet over him (#108) by vertex height: on the mattress the lower face lies at ~0.838 m and
    the upper at ~0.868 m (its REF); the parts hanging over the bed's sides are below 0.80 m."""
    BZ0, BZ1, MAT_Y = G["BZ0"], G["BZ1"], G["MAT_Y"]
    NX, NY = 68, 70; L, W = 1.30, 1.54; TH = 0.03; R_IN = 0.010; R_OUT = R_IN + TH; R_MID = R_IN + TH / 2
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=NX, y_subdivisions=NY, size=1.0, location=(0, 0, 0))
    d = bpy.context.active_object; d.name = "duvet_sim"
    d.scale = (L, W, 1); bpy.ops.object.transform_apply(scale=True)
    me = d.data
    uv0 = [(v.co.x / L + 0.5, v.co.y / W + 0.5) for v in me.vertices]          # the flat duvet's own coordinates
    nc = len({round(u, 5) for u, _ in uv0}); nr = len({round(w, 5) for _, w in uv0})
    ij = [(round(u * (nc - 1)), round(w * (nr - 1))) for u, w in uv0]; at = {k: n for n, k in enumerate(ij)}
    xf = -L / 2 + 0.24; i_f = round((xf + L / 2) / L * (nc - 1))               # the fold line, on a grid column
    d.location = B(-0.85, MAT_Y + 0.13, (BZ0 + BZ1) / 2 + 0.01); bpy.ops.object.transform_apply(location=True)
    colliders = [mattress_o, pillow_o, bpy.data.objects["bed_base"], bpy.data.objects["bed_head"], bpy.data.objects["floor"]]
    for o in colliders:
        o.modifiers.new("col", "COLLISION"); o.collision.thickness_outer = 0.004; o.collision.cloth_friction = 10
    cl = d.modifiers.new("cloth", "CLOTH"); s = cl.settings
    s.quality = 8; s.mass = 0.4; s.tension_stiffness = 20; s.compression_stiffness = 20; s.shear_stiffness = 8; s.bending_stiffness = 1.0
    s.air_damping = 2.0; cl.collision_settings.distance_min = 0.008; cl.collision_settings.use_self_collision = False
    cl.point_cache.frame_start = 1; cl.point_cache.frame_end = 60
    for f in range(1, 48): SC.frame_set(f)
    bpy.context.view_layer.objects.active = d; bpy.ops.object.modifier_apply(modifier="cloth")
    for o in colliders:
        for m in list(o.modifiers):
            if m.type == 'COLLISION': o.modifiers.remove(m)
    SC.frame_set(1)
    unspike(d, 0.06); smooth_mesh(d, 0.35, 1); me = d.data
    pos = [v.co.copy() for v in me.vertices]; nrm = [v.normal.copy() for v in me.vertices]   # Blender coords; normals point up / outward
    P = lambda i, j: pos[at[(i, j)]]; N = lambda i, j: nrm[at[(i, j)]]
    def row_avg(fn, i, j, k=2):                                                     # smoothed along the rows: no sawtooth at the fold
        js = range(max(0, j - k), min(nr - 1, j + k) + 1); return sum((fn(i, jj) for jj in js), Vector()) / len(js)
    dx = L / (nc - 1); lower, upper = {}, {}                                        # the two faces of the slab, per grid point
    rows = {}
    for j in range(nr):
        Pm = [P(i, j) for i in range(i_f, nc)]; S = [0.0]
        for a_, b_ in zip(Pm, Pm[1:]): S.append(S[-1] + (b_ - a_).length)
        rows[j] = (Pm, S)
    random.seed(46); cu, cw = L / 5, W / 6
    def puff(u, w):
        fu, fw = (u * L / cu) % 1.0, (w * W / cw) % 1.0; border = min(1.0, min(u, 1 - u) * L / 0.07, min(w, 1 - w) * W / 0.07)
        return border * (0.008 * math.sin(math.pi * fu) * math.sin(math.pi * fw) - 0.002) + (1 - border) * 0.004
    for n, (i, j) in enumerate(ij):
        u, w = uv0[n]
        if i >= i_f:                                                                 # the main part: lies on the bed
            lo = P(i, j); nn = N(i, j)
            lower[(i, j)] = lo; upper[(i, j)] = lo + nn * (TH + puff(u, w) + 0.003 * nz(gl(lo), 7.0, 4))
        else:                                                                        # the flap: round the fold, then back over the top
            P0 = row_avg(P, i_f, j); nn = row_avg(N, i_f, j).normalized(); T = (row_avg(P, i_f + 1, j) - P0).normalized()
            dist = (i_f - i) * dx; C = P0 + nn * (TH + R_IN)                       # the fold's centre (above the upper face at the fold line)
            if dist < math.pi * R_MID:
                th = dist / R_MID
                upper[(i, j)] = C - nn * (R_IN * math.cos(th)) + T * (R_IN * math.sin(th))      # inside of the fold
                lower[(i, j)] = C - nn * (R_OUT * math.cos(th)) + T * (R_OUT * math.sin(th))    # outside of the fold (what shows)
            else:
                Pm, S = rows[j]; s_ = dist - math.pi * R_MID
                m = max(0, min(len(S) - 2, next((k for k in range(len(S) - 1) if S[k + 1] > s_), len(S) - 2)))
                t = (s_ - S[m]) / max(1e-6, S[m + 1] - S[m]); base = Pm[m].lerp(Pm[m + 1], t)
                nb = (row_avg(N, i_f + m, j) * (1 - t) + row_avg(N, min(nc - 1, i_f + m + 1), j) * t).normalized()
                upper[(i, j)] = base + nb * (TH + 2 * R_IN)                                       # the flap's underside, 2 cm over the main part
                lower[(i, j)] = base + nb * (2 * TH + 2 * R_IN + puff(u, w) + 0.003 * nz(gl(base), 7.0, 5))   # the flap's top (the old lower face)
    bpy.data.objects.remove(d)
    bm = bmesh.new(); VL = {k: bm.verts.new(v) for k, v in lower.items()}; VU = {k: bm.verts.new(v) for k, v in upper.items()}
    for i in range(nc - 1):
        for j in range(nr - 1):
            bm.faces.new([VL[(i, j)], VL[(i + 1, j)], VL[(i + 1, j + 1)], VL[(i, j + 1)]]).smooth = True
            bm.faces.new([VU[(i, j)], VU[(i, j + 1)], VU[(i + 1, j + 1)], VU[(i + 1, j)]]).smooth = True
    rim = [(0, j) for j in range(nr)] + [(i, nr - 1) for i in range(1, nc)] + [(nc - 1, j) for j in range(nr - 2, -1, -1)] + [(i, 0) for i in range(nc - 2, 0, -1)]
    for k in range(len(rim)):
        a_, b_ = rim[k], rim[(k + 1) % len(rim)]
        bm.faces.new([VL[a_], VU[a_], VU[b_], VL[b_]]).smooth = True
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    o = new_obj("duvet", bm, "duvet")
    return o


# ================================================================ rug: a thick pile with a bound edge, a little uneven
def rug():
    FY = G["FY"]; x0, x1, z0, z1 = -0.50, 0.95, -0.62, 0.85; tp, bw = 0.013, 0.025
    n = 22; grid = []
    random.seed(33)
    for j in range(n + 1):
        row = []
        for i in range(n + 1):
            x = x0 + bw + (x1 - x0 - 2 * bw) * i / n; z = z0 + bw + (z1 - z0 - 2 * bw) * j / n
            row.append(Vector((x, FY + tp + 0.0025 * nz(Vector((x, 0, z)), 4.0, 5) + 0.001 * nz(Vector((x, 0, z)), 17.0, 6), z)))
        grid.append(row)
    bm = bmesh.new(); V = [[bm.verts.new(Bv(p)) for p in row] for row in grid]
    for j in range(n):
        for i in range(n): bm.faces.new([V[j][i], V[j + 1][i], V[j + 1][i + 1], V[j][i + 1]]).smooth = True
    rim = [V[0][i] for i in range(n)] + [V[j][n] for j in range(n)] + [V[n][i] for i in range(n, 0, -1)] + [V[j][0] for j in range(n, 0, -1)]
    low = [bm.verts.new(Vector((v.co.x, v.co.y, Bv(Vector((0, FY, 0))).z))) for v in rim]
    for k in range(len(rim)):
        k2 = (k + 1) % len(rim); bm.faces.new([rim[k], low[k], low[k2], rim[k2]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    pile = new_obj("rug", bm, "rug")
    # the binding: a cotton tape sewn around the edge, a touch lower than the pile
    tb = tp - 0.002
    for (xa, xb, za, zb) in ((x0, x1, z0, z0 + bw), (x0, x1, z1 - bw, z1), (x0, x0 + bw, z0 + bw, z1 - bw), (x1 - bw, x1, z0 + bw, z1 - bw)):
        b = box("rug", "painted", (xa, xb), (FY, FY + tb), (za, zb), bevel=0.003, seg=2); set_vcol(b, srgb("#4a4440"))
    return pile


# ================================================================ floor cushion (zabuton): tufted at five points, piped edge
def cushion():
    FY = G["FY"]; W, L, T = 0.55, 0.58, 0.09; nu = nv = 20
    tufts = [(0, 0), (0.17, 0.17), (-0.17, 0.17), (0.17, -0.17), (-0.17, -0.17)]
    def h_of(x, z, top):
        u, v = x / (W / 2), z / (L / 2); h = T / 2 * ((1 - u ** 4) * (1 - v ** 4)) ** 0.5 + 0.004
        h *= 1.0 if top else 0.55
        for (tx, tz) in tufts:
            dd = math.hypot(x - tx, z - tz); ph = math.atan2(z - tz, x - tx)
            h *= 1 - 0.7 * math.exp(-dd * dd / (2 * 0.026 ** 2))                           # the tuft pulls the cover in
            h += 0.004 * math.cos(5 * ph + tx * 9) * math.exp(-dd / 0.07) * smooth01(0.02, 0.05, dd)   # gathers around it
        return h + 0.0015 * nz(Vector((x, 0, z)), 12.0, 7)
    top, bot = [], []
    for j in range(nv + 1):
        rt, rb = [], []
        for i in range(nu + 1):
            u = i / nu * 2 - 1; v = j / nv * 2 - 1
            x = u * W / 2 * (1 - 0.04 * (1 - v * v)); z = v * L / 2 * (1 - 0.04 * (1 - u * u))
            rt.append(Vector((x, h_of(x, z, True), z))); rb.append(Vector((x, -h_of(x, z, False), z)))
        top.append(rt); bot.append(rb)
    bm = bmesh.new(); Tv = [[bm.verts.new(Bv(p)) for p in r] for r in top]; Bb = [[bm.verts.new(Bv(p)) for p in r] for r in bot]
    for j in range(nv):
        for i in range(nu):
            bm.faces.new([Tv[j][i], Tv[j][i + 1], Tv[j + 1][i + 1], Tv[j + 1][i]]).smooth = True
            bm.faces.new([Bb[j][i], Bb[j + 1][i], Bb[j + 1][i + 1], Bb[j][i + 1]]).smooth = True
    edge = [(0, i) for i in range(nu)] + [(j, nu) for j in range(nv)] + [(nv, i) for i in range(nu, 0, -1)] + [(j, 0) for j in range(nv, 0, -1)]
    for k in range(len(edge)):
        (j0, i0), (j1, i1) = edge[k], edge[(k + 1) % len(edge)]
        bm.faces.new([Tv[j0][i0], Bb[j0][i0], Bb[j1][i1], Tv[j1][i1]]).smooth = True
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    body = new_obj("cushion", bm, "cushion")
    path = [(top[j][i] + bot[j][i]) / 2 for (j, i) in edge]                                  # the piping along the side seam
    pipe = thin(tube_along("cushion_pipe", "cushion", path + path[:1], 0.0045, 0.0045, n=8, ref="h"))
    parts = [body, pipe]
    for o in parts: transform(o, loc=(1.32, 0, 0.98), ry=0.28)
    G["settle"](parts, FY); [project_uv(o) for o in parts]
    return parts


# ================================================================ the laundry pinch hanger: socks with heels and toes, a terry towel
def sock(nm, clip, y_top, ry, colour, heel, stripes=()):
    """a sock pinched at the cuff by a clip at (x, z) = clip, hanging from y_top: the cuff gathers to the clip and its
    edges droop, ribbing round the cuff, a flat leg, the heel bulging at the bend, the foot dangling forward (+x, turned
    by ry) and a rounded toe. heel: the heel-and-toe colour; stripes: (from, to, colour) along the length (m)."""
    n = 32; L_leg, R_b, phi, L_foot = 0.150, 0.03, 0.55, 0.095
    L_bend = R_b * phi; Ltot = L_leg + L_bend + L_foot
    def centre(dist):
        if dist < L_leg: return Vector((0, -dist, 0))
        if dist < L_leg + L_bend:
            a = (dist - L_leg) / R_b; return Vector((R_b * (1 - math.cos(a)), -L_leg - R_b * math.sin(a), 0))
        e = dist - L_leg - L_bend
        return Vector((R_b * (1 - math.cos(phi)), -L_leg - R_b * math.sin(phi), 0)) + Vector((math.sin(phi), -math.cos(phi), 0)) * e
    N = 30; dists = [Ltot * (k / N) ** 0.85 for k in range(N + 1)]                   # denser rings near the cuff
    path = [centre(dd) for dd in dists]
    F = frames(path, Vector((1, 0, 0)))
    rings = []; ring_col = []
    for k, (dd, c, (t, w, nn)) in enumerate(zip(dists, path, F)):
        col = colour
        for (d0, d1, sc) in stripes:
            if d0 <= dd <= d1: col = sc
        if heel and (abs(dd - (L_leg + L_bend * 0.5)) < 0.03 or dd > Ltot - 0.045): col = heel
        ring_col.append(srgb(col))
        pinch = smooth01(0.0, 0.032, dd)
        a = 0.006 + 0.034 * pinch; b = 0.0035 + 0.0085 * pinch
        a *= 1 - 0.09 * bump(dd, 0.064, 0.012)                                       # the cuff's elastic edge
        full = smooth01(L_leg - 0.02, L_leg + L_bend, dd); a += 0.004 * full; b += 0.004 * full
        toe = (dd - (Ltot - 0.036)) / 0.036
        k_toe = math.sqrt(max(1e-6, 1 - toe * toe)) if toe > 0 else 1.0
        if k == N: k_toe = 0.01
        a *= k_toe; b *= k_toe
        ribw = smooth01(0.008, 0.016, dd) * (1 - smooth01(0.050, 0.060, dd))
        heel_amp = 0.55 * bump(dd, L_leg + L_bend * 0.5, 0.05)
        droop = 0.016 * (1 - smooth01(0.0, 0.05, dd))
        pts = []
        for i in range(n):
            th = 2 * math.pi * i / n; ct, st = math.cos(th), math.sin(th)
            r = 1 + 0.11 * math.cos(8 * th) * ribw + heel_amp * max(0.0, -ct) ** 1.5
            p = c + w * (a * r * ct) + nn * (b * (1 + 0.5 * heel_amp * max(0.0, -ct)) * st)
            p.y -= droop * abs(ct) ** 1.5                                                # the cuff's edges hang below the clip
            pts.append(p)
        rings.append(pts)
    o = tube_obj(nm, "knit", rings, cap=(True, False))
    displace(o, lambda p, nrm: 0.0012 * nz(p, 40.0, 8))
    paint(o, lambda vi: ring_col[min(N, vi // n)], by_index=True)          # (the toe's collapsed ring is the last vertex)
    o.data.transform(Matrix.Translation(B(clip[0], y_top, clip[1])) @ Matrix.Rotation(ry, 4, 'Z')); o.data.update()
    return o


def towel(c0, c1, y_top):
    """a hand towel in terry cloth, pinched by two clips (c0, c1) near the middle of its top edge: it hangs flat between
    them with a slight sag, the corners outside the clips droop and fold forward, soft vertical folds grow towards the
    wavy bottom edge, and the dobby border shows as a low ridge near the hem"""
    W, Lh = 0.30, 0.36; nu, nv = 26, 22
    chord = math.hypot(c1[0] - c0[0], c1[1] - c0[1]); h = chord / 2; out = W / 2 - h
    grid = []
    for j in range(nv + 1):
        t = j / nv; row = []
        for i in range(nu + 1):
            s = i / nu; z = -W / 2 + W * s; dz = max(0.0, abs(z) - h) / out
            droop = 0.055 * dz ** 1.6; sag = 0.008 * (1 - (z / h) ** 2) if abs(z) < h else 0.0
            y = y_top - droop - sag - t * (Lh - 0.3 * droop)
            x = (0.010 * math.sin(2 * math.pi * 2.3 * s + 1.1 * t) * (0.25 + 0.75 * t) + 0.004 * nz(Vector((s * 4, t * 3, 0)), 1.0, 9)
                 + 0.014 * dz ** 1.5 * (1 - t))                                                     # the drooping corners fold forward (+x: into the room)
            zz = z - math.copysign(0.03 * dz ** 1.5 * (1 - 0.5 * t), z)
            if j == nv: y += 0.004 * (0.5 + 0.5 * math.sin(2 * math.pi * 2.3 * s + 1.1))            # a wavy hem
            if 0.84 < t < 0.92: x += 0.0015                                                          # the dobby border
            row.append(Vector((x, y, zz)))
        grid.append(row)
    o = grid_obj("towel", "terry", grid); sheet(o, 0.006)
    ry = math.atan2(c1[0] - c0[0], c1[1] - c0[1])
    if math.cos(ry) < 0: ry += math.pi                                   # its folds and corners come forward into the room, never into the window wall
    transform(o, loc=((c0[0] + c1[0]) / 2, 0, (c0[1] + c1[1]) / 2), ry=ry)
    return o


def socks_and_towel(clips, PH):
    """clips: the pinch clips' (x, z) round the hanger ring (8); PH: the ring's centre (x, y, z). Two pairs of socks on
    clips 1, 2, 5, 6 (their feet point away from the ring's centre, clear of the window wall and of each other) and the
    towel between clips 3 and 4."""
    y_top = PH[1] - 0.045 + 0.012
    pairs = [(1, "#2d2f36", "#8d9099", ((0.012, 0.018, "#c9c6bd"), (0.024, 0.030, "#c9c6bd"))),
             (2, "#2d2f36", "#8d9099", ((0.012, 0.018, "#c9c6bd"), (0.024, 0.030, "#c9c6bd"))),
             (5, "#d9d3c6", "#8e8a84", ()), (6, "#d9d3c6", "#8e8a84", ())]
    for k, col, heel, stripes in pairs:
        cx, cz = clips[k]; a = math.atan2(cz - PH[2], max(0.25, abs(cx - PH[0])) if cx < PH[0] else cx - PH[0])   # never towards the window wall
        sock("sock", (cx, cz), y_top, -a + random.uniform(-0.15, 0.15), col, heel, stripes)
    towel(clips[3], clips[4], y_top)


# ================================================================ the door hooks: a hoodie, a canvas tote
def tube_pts(pts, n=10):
    """a smooth polyline through control points (Catmull-Rom), n samples per span"""
    P = [pts[0]] + list(pts) + [pts[-1]]; out = []
    for k in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[k - 1], P[k], P[k + 1], P[k + 2]
        for i in range(n):
            t = i / n
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(P[-2]); return out


def hoodie(HX):
    """a hoodie hanging by its hood from the door's left hook (HX): the hood bunched round the hook, the shoulders
    dropping into a body that hangs in soft vertical folds, a kangaroo pocket, ribbed hem, sleeves hanging at the sides
    with ribbed cuffs, two drawstrings. Returns its parts (they join the "hangers" node)."""
    IZ = G["IZ"]; random.seed(41); parts = []
    zb = IZ + 0.128                                                            # the body's mid plane (in front of the tote)
    # the hood: a bunched bag with the hook's tip inside it
    bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=28, v_segments=16, radius=1.0)
    for v in bm.verts:
        p = Vector((v.co.x * 0.10, v.co.z * 0.066, -v.co.y * 0.055))
        ang = math.atan2(p.z, p.x); up = (p.y + 0.066) / 0.132
        g = 1 + 0.13 * nz(p, 16.0, 10) + 0.10 * math.sin(9 * ang + 2 * up) * (1 - up) ** 0.5 * 0.5   # gathered: the fabric bunches round the hook
        p.x *= g; p.z *= g
        if p.y < -0.02: p.x *= 1 + 1.6 * (-p.y - 0.02)                                 # opens out onto the shoulders
        v.co = B(HX + p.x, 1.70 + p.y, IZ + 0.125 + p.z)
    hood = new_obj("hoodie_hood", bm, "hoodie"); [setattr(f, "use_smooth", True) for f in hood.data.polygons]; parts.append(hood)
    # the body
    nx, ny = 24, 36; y_top, y_hem = 1.665, 1.09; grid = []
    for j in range(ny + 1):
        t = j / ny; y = y_top + (y_hem - y_top) * t; row = []
        hw = 0.06 + 0.115 * smooth01(0.0, 0.16, t) - 0.012 * smooth01(0.5, 1.0, t)
        if t > 0.92: hw *= 0.95                                                   # the ribbed hem hugs
        for i in range(nx + 1):
            s = i / nx * 2 - 1; x = HX + s * hw
            z = (zb + 0.018 * (1 - s * s) * math.sin(math.pi * min(1.0, t * 1.1)) ** 0.7
                 + 0.02 * (math.sin(2 * math.pi * 2.5 * s + 1.2 * t) + 0.5 * math.sin(2 * math.pi * 1.2 * s + 3.0)) * smooth01(0.1, 0.45, t)
                 + 0.018 * smooth01(0.60, 0.66, t) * (1 - smooth01(0.86, 0.90, t)) * (1 - smooth01(0.62, 0.74, abs(s)))   # the pocket
                 + 0.005 * nz(Vector((s, t, 0)), 6.0, 11))
            row.append(Vector((x, y, z)))
        grid.append(row)
    body = grid_obj("hoodie", ["hoodie", "rib"], grid)
    for pg in body.data.polygons: pg.material_index = 1 if gl(pg.center).y < y_hem + 0.045 else 0
    sheet(body, 0.012)
    parts.append(body)
    # sleeves: hanging at the sides, flattened, a ribbed cuff
    for sgn in (-1, 1):
        path = tube_pts([Vector((HX + sgn * 0.13, 1.60, zb)), Vector((HX + sgn * 0.185, 1.50, zb + 0.022)), Vector((HX + sgn * 0.19, 1.36, zb + 0.03)),
                         Vector((HX + sgn * 0.165, 1.24, zb + 0.024)), Vector((HX + sgn * 0.155, 1.19, zb + 0.02)), Vector((HX + sgn * 0.152, 1.145, zb + 0.018))], 6)
        n_ = len(path)
        def taper(u, n_=n_):
            return (0.5 + 0.5 * smooth01(0.0, 0.12, u)) * (1 - 0.22 * smooth01(0.3, 0.84, u)) * (0.78 if u > 0.87 else 1.0)
        sl = tube_along("hoodie_sleeve", ["hoodie", "rib"], path, 0.042, 0.018, n=16, ref=Vector((1, 0, 0)), taper=taper,
                        fn=lambda th, u: 1 + 0.07 * math.sin(3 * th + 9 * u) * smooth01(0.15, 0.4, u) + 0.03 * nz(Vector((th, u * 4, 0)), 1.0, 15), cap=(False, True))
        for pg in sl.data.polygons: pg.material_index = 1 if gl(pg.center).y < 1.19 else 0
        parts.append(sl)
    # drawstrings
    for sgn in (-1, 1):
        path = tube_pts([Vector((HX + sgn * 0.022, 1.655, IZ + 0.17)), Vector((HX + sgn * 0.03, 1.60, IZ + 0.168)), Vector((HX + sgn * 0.045, 1.52, IZ + 0.165))], 6)
        st = thin(tube_along("hoodie_string", "painted", path, 0.0028, 0.0028, n=6, cap=(False, True))); set_vcol(st, srgb("#ece8e0")); parts.append(st)
    return parts


def tote(xc):
    """a canvas tote on the right hook: the bag hangs by its two handles looped over the hook's tip, the top edge
    peaks at the handles and droops between them, the sides crease where the bag is nearly empty, the bottom gusset
    gives it depth. Parts are named "tote" / "tote_strap" (they join the "hangers" node)."""
    IZ = G["IZ"]; zd = IZ + 0.06; random.seed(42)
    rings = []; n = 36; nr = 22
    for k in range(nr + 1):
        t = k / nr; y = 1.62 - 0.38 * t
        a = 0.17 - 0.012 * (1 - t) ** 2; b = 0.012 + 0.04 * t ** 1.3
        c = Vector((xc, y, zd + b + 0.002))
        pts = []
        for i in range(n):
            th = 2 * math.pi * i / n; ct, st = math.cos(th), math.sin(th)
            x = math.copysign(abs(ct) ** (2 / 3.6), ct); z = math.copysign(abs(st) ** (2 / 3.6), st)
            r = 1 + 0.07 * math.sin(3 * th + 5 * t) * (1 - t) ** 0.5 * (1 - abs(z)) + 0.025 * nz(Vector((th, t * 3, 0)), 2.0, 12)   # creases
            p = c + Vector((a * x * r, 0, b * z * r))
            if k == 0: p.y = 1.60 + 0.016 * math.exp(-((abs(p.x - xc) - 0.09) / 0.05) ** 2)           # peaks at the handles
            pts.append(p)
        rings.append(pts)
    body = tube_obj("tote", "canvas", rings, cap=(False, True)); sheet(body, 0.004)
    for zz in (zd + 0.004, zd + 0.004 + 0.026):                                   # the two handles, over the hook's tip
        pts = []
        for k in range(13):
            u = k / 12; ang = math.pi * u
            x = xc - 0.088 * math.cos(ang) * (0.55 + 0.45 * abs(math.cos(ang)) ** 0.6)
            y = 1.60 + 0.165 * math.sin(ang) ** 0.7
            z = zz + (IZ + 0.102 - zz) * math.sin(ang) ** 2
            pts.append(Vector((x, y, z)))
        thin(tube_along("tote_strap", "canvas", pts, 0.0017, 0.013, n=8, ref=Vector((0, 0, 1)), cap=(True, True)))
    return body


# ================================================================ the backpack by the bed's foot
def backpack():
    """a day pack leaning on the bed's foot end: a soft body with a rounded top, a zipped lid, a front zip pocket, a
    stretch bottle pocket on its side, a grab handle, and a shoulder strap's end lying on the floor beside it"""
    FY, BX1 = G["FY"], G["BX1"]; n0 = len(STATIC); random.seed(43)
    bb = box("bag_body", "bag", (0, 0.13), (0, 0.42), (-0.15, 0.15), bevel=0.045, seg=5)
    for v in bb.data.vertices:
        g = gl(v.co); u = g.z / 0.15; h = min(1.0, g.y / 0.42)
        g.x += 0.035 * (1 - u * u) * math.sin(math.pi * h) ** 0.8 * (g.x / 0.13)               # a fuller front
        g.y += 0.01 * (1 - u * u) * (g.y > 0.3)                                                  # a rounded top
        v.co = B(*g)
    displace(bb, lambda p, nrm: 0.002 * nz(p, 16.0, 13))
    box("bag_pocket", "bag", (0.13, 0.172), (0.05, 0.23), (-0.11, 0.11), bevel=0.02, seg=3)
    # zips: the lid's round the top, the pocket's across it; a pull on each
    for (nm, x, y, z) in (("bag_zip", (0.125, 0.14), (0.325, 0.332), (-0.14, 0.14)), ("bag_zip", (0.168, 0.176), (0.21, 0.217), (-0.09, 0.09))):
        box(nm, "plastic_black", x, y, z, bevel=0.0015, seg=1)
    for (x, z) in ((0.138, 0.14), (0.172, 0.08)):
        box("bag_zip", "plastic_black", (x - 0.012, x + 0.012), (0.302, 0.33) if z > 0.1 else (0.195, 0.222), (z - 0.004, z + 0.004), bevel=0.002, seg=1)
    for (nm, x, y, z) in (("bag_zip", (0.0, 0.13), (0.325, 0.332), (0.148, 0.156)), ("bag_zip", (0.0, 0.13), (0.325, 0.332), (-0.156, -0.148))):
        box(nm, "plastic_black", x, y, z, bevel=0.0015, seg=1)
    # a stretch pocket on the side (a half tube, closed at the bottom)
    grid = []
    for j in range(9):
        t = j / 8; y = 0.045 + 0.17 * t; rr = (0.3 + 0.7 * smooth01(0.0, 0.3, t)) * (1 - 0.25 * smooth01(0.7, 1.0, t)); row = []
        for i in range(11):
            th = math.pi * i / 10; row.append(Vector((0.065 + 0.058 * math.cos(th) * rr ** 0.3, y, 0.15 + 0.034 * math.sin(th) * rr)))
        grid.append(row)
    sp = grid_obj("bag_side_pocket", "bag", grid); sheet(sp, 0.004)
    # a grab handle, and a strap's end on the floor
    thin(tube_along("bag_loop", "bag", tube_pts([Vector((0.045, 0.42, -0.04)), Vector((0.055, 0.455, 0)), Vector((0.045, 0.42, 0.04))], 6), 0.0065, 0.0065, n=8))
    thin(tube_along("bag_strap", "bag", tube_pts([Vector((0.02, 0.012, 0.16)), Vector((0.06, 0.012, 0.205)), Vector((0.11, 0.013, 0.225)), Vector((0.15, 0.014, 0.215))], 6),
                    0.013, 0.0025, n=8, ref="h", cap=(False, True)))
    box("bag_buckle", "plastic_black", (0.12, 0.155), (0.008, 0.02), (0.20, 0.232), bevel=0.003, seg=1)
    parts = [o for o in STATIC[n0:]]
    for o in parts: o.data.transform(Matrix.Translation(B(BX1 + 0.049, 0, 1.24)) @ Matrix.Rotation(-0.11, 4, 'Y')); o.data.update()
    G["settle"](parts, FY); [project_uv(o) for o in parts]
    return parts


# ================================================================ clothes: jeans dropped by the bed's foot, a T-shirt on the bed
def jeans():
    """a pair of jeans in a heap on the floor: the seat lying flat with the waistband, one leg folded back on itself,
    the other crossing over it"""
    FY = G["FY"]; n0 = len(STATIC); random.seed(44)
    # the seat: a flat superellipse tube along x, its waist opening at -x with the waistband (a thin tube round it)
    tube_along("jeans", "denim", [Vector((-0.14 + 0.16 * k / 7, 0.045, 0)) for k in range(8)], 0.17, 0.042, n=32, ref="h",
               taper=lambda u: (1 - 0.06 * (1 - u), 1 - 0.2 * (1 - u) ** 2), fn=lambda th, u: 1 + 0.03 * math.sin(4 * th + 3 * u), cap=(True, True), p=2.8)
    Z, Y = Vector((0, 0, 1)), Vector((0, 1, 0))
    thin(tube_obj("jeans", "denim", [ring(c, Z, Y, 0.16 + dr, 0.034 + dr, 32, p=2.8) for c, dr in
                                     ((Vector((-0.146, 0.045, 0)), 0.0), (Vector((-0.146, 0.045, 0)), 0.006), (Vector((-0.136, 0.045, 0)), 0.006), (Vector((-0.136, 0.045, 0)), 0.0))]))
    # the legs: flat tubes (wide axis horizontal) along two curves, one folded back, the other crossing over it
    for k, ctrl in enumerate(([(0.0, 0.03, -0.07), (0.12, 0.03, -0.10), (0.20, 0.034, -0.03), (0.16, 0.038, 0.07), (0.04, 0.042, 0.09)],
                              [(0.0, 0.045, 0.06), (0.10, 0.085, 0.08), (0.19, 0.09, 0.0), (0.14, 0.08, -0.09), (0.02, 0.068, -0.11)])):
        path = tube_pts([Vector(p) for p in ctrl], 5)
        tube_along("jeans", "denim", path, 0.08, 0.027, n=20, ref="h",
                   taper=lambda u: (1 + 0.06 * smooth01(0.85, 1.0, u), 1 - 0.1 * u), fn=lambda th, u, k=k: 1 + 0.035 * math.sin(3 * th + 7 * u + k), cap=(False, True))
    parts = [o for o in STATIC[n0:]]
    for o in parts:
        displace(o, lambda p, nrm: 0.004 * nz(p, 14.0, 14) + 0.0015 * nz(p, 40.0, 16))
        transform(o, loc=(0.45, 0, 1.38), ry=0.5)
    G["settle"](parts, FY); [project_uv(o) for o in parts]
    return parts


def tee(cushion_parts):
    """a T-shirt dropped on the floor cushion: a flat tee cut from a grid (body, sleeves, a round neck), dropped as
    cloth onto the cushion, where it crumples and hangs over its sides (off the bed: web/room.html reshapes the duvet
    over him when he sleeps, #108, and a tee lying on it would be buried)"""
    FY = G["FY"]; random.seed(45)
    nx, nzz = 40, 40; hw, hl, sw = 0.22, 0.28, 0.29
    def inside(x, z):
        if x * x + (z - hl) ** 2 < 0.07 ** 2: return False                                  # the neck
        if abs(x) <= hw and -hl <= z <= hl: return True
        return abs(x) <= sw and 0.09 + 0.05 * (abs(x) - hw) / (sw - hw) <= z <= hl - 0.03   # sleeves
    bm = bmesh.new(); V = {}
    for j in range(nzz + 1):
        for i in range(nx + 1):
            V[(j, i)] = bm.verts.new(Bv(Vector((-sw + 2 * sw * i / nx, 0, -hl + 2 * hl * j / nzz))))
    for j in range(nzz):
        for i in range(nx):
            c = sum((gl(V[(j + dj, i + di)].co) for dj in (0, 1) for di in (0, 1)), Vector()) / 4
            if inside(c.x, c.z): bm.faces.new([V[(j, i)], V[(j, i + 1)], V[(j + 1, i + 1)], V[(j + 1, i)]]).smooth = True
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    edge = [v for v in bm.verts if v.is_boundary]
    for _ in range(4): bmesh.ops.smooth_vert(bm, verts=edge, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)   # a smooth outline, not grid steps
    for v in bm.verts: v.co.z += 0.03 * nz(gl(v.co), 6.0, 17)                                # dropped crumpled, not flat
    o = new_obj("tee", bm, "jersey")
    o.data.transform(Matrix.Translation(B(1.30, FY + 0.20, 0.98)) @ Matrix.Rotation(0.75, 4, 'Z') @ Matrix.Rotation(0.12, 4, 'X')); o.data.update()
    colliders = [cushion_parts[0], bpy.data.objects["floor"]]                   # the cushion's body (not its thin piping: the solver snags on it)
    for c in colliders:
        c.modifiers.new("col", "COLLISION"); c.collision.thickness_outer = 0.004; c.collision.cloth_friction = 12
    cl = o.modifiers.new("cloth", "CLOTH"); s = cl.settings
    s.quality = 8; s.mass = 0.2; s.tension_stiffness = 12; s.compression_stiffness = 12; s.shear_stiffness = 4; s.bending_stiffness = 0.2
    s.air_damping = 1.0; cl.collision_settings.distance_min = 0.006; cl.collision_settings.use_self_collision = False   # (self-collision blew it up)
    cl.point_cache.frame_start = 1; cl.point_cache.frame_end = 60
    for f in range(1, 46): SC.frame_set(f)
    bpy.context.view_layer.objects.active = o; o.select_set(True); bpy.ops.object.modifier_apply(modifier="cloth")
    assert not any(m.type == 'CLOTH' for m in o.modifiers), "the tee's cloth simulation was not applied"
    for c in colliders:
        for m in list(c.modifiers):
            if m.type == 'COLLISION': c.modifiers.remove(m)
    SC.frame_set(1)
    unspike(o, 0.04); smooth_mesh(o, 0.3, 1)
    for v in o.data.vertices:                                                      # nothing through the floor (the solver lets a fast corner slip)
        if v.co.z < FY + 0.004: v.co.z = FY + 0.004
    o.data.update()
    paint(o, lambda p: srgb("#7d93a6"))
    sheet(o, 0.005)
    return o


def clothes(cushion_parts):
    """jeans on the floor by the bed's foot and a T-shirt on the floor cushion, each registered with the prop sweep"""
    FY = G["FY"]
    G["check"]("jeans", jeans(), ("y", FY))
    G["check"]("tee", [tee(cushion_parts)], None)
