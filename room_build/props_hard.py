"""The room's hard surfaces at game quality (#98 G5): materials with roughness micro-variation, edge wear in the vertex
colours, bevels that catch the light, real keycaps with legends, books with spines, decals (dust, scuffs, stickers), and
the furniture rebuilt with more detail: desk, monitor, keyboard, mouse, speakers, mug, pen cup, office chair (node
"chair", same origin), storage bed frame, bookshelf, fridge, door with handle and hinges, window frame and sashes, air
conditioner, fan, headphones (node "headphones") and the controller.

Called from build_room.py, which hands over its namespace (`bind(globals())`): the helpers (box, cyl, lathe, new_obj,
project_uv, ...), the constants (IX, IZ, FY, ...) and the lists it keeps (STATIC, MATS, SWEEP). Every entry point binds
that namespace first, so names defined later in build_room.py are visible to later calls, and writes the constants the
rest of build_room.py reads back into it (G.update(...)). Coordinates are glTF (x right, y up, z towards the viewer),
as in build_room.py; B() converts to Blender."""
import bpy, bmesh, math, random, os, sys
from mathutils import Vector, Matrix
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hard_layout as L

G = None
WHITE = (1.0, 1.0, 1.0)
C_GL = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))     # glTF -> Blender axes


def bind(g):
    """take build_room.py's namespace (helpers, constants, lists) into this module"""
    global G
    G = g; globals().update({k: v for k, v in g.items() if not k.startswith("__") and k not in _MINE})


def export(**kw): G.update(kw); globals().update(kw)


# ---------------------------------------------------------------- materials
def hmat(name, color=(0.8, 0.8, 0.8), rough=0.6, metal=0.0, diff=None, nor=None, nstr=1.0, mr=None, uv=1.0, grain=0, wear=None, emit=None,
         blend=False, nouv=False, alpha_from=None):
    """a Principled material: textures from tex_final/; `wear`: an (r, g, b) tint for worn edges (the vertex colour "Col"
    multiplies the base colour: white = untouched); `nouv`: the mesh's own UVs are kept (atlases); `blend`: alpha blended"""
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; P = nt.nodes["Principled BSDF"]
    # a worn edge lighter than its surface needs the base lifted by `gain` (vertex colours never exceed 1): a plain colour is
    # multiplied here, a texture comes as a brighter copy from tex_hard (hard_layout.GAIN); the vertex colour is 1 / gain by default
    gain = max(1.0, max(wear)) if wear else 1.0
    if wear and not diff: color = tuple(min(1.0, c * gain) for c in color)
    P.inputs["Base Color"].default_value = (*color, 1); P.inputs["Roughness"].default_value = rough; P.inputs["Metallic"].default_value = metal
    base_out = None
    if diff:
        t = nt.nodes.new("ShaderNodeTexImage"); t.image = img(diff); base_out = t.outputs["Color"]
        if blend or alpha_from:
            nt.links.new(t.outputs["Alpha"], P.inputs["Alpha"])
    if wear:
        a = nt.nodes.new("ShaderNodeVertexColor"); a.layer_name = "Col"
        if base_out is not None:
            mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = 'RGBA'; mix.blend_type = 'MULTIPLY'; mix.inputs["Factor"].default_value = 1.0
            nt.links.new(base_out, mix.inputs[6]); nt.links.new(a.outputs["Color"], mix.inputs[7]); base_out = mix.outputs[2]
        else:
            mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = 'RGBA'; mix.blend_type = 'MULTIPLY'; mix.inputs["Factor"].default_value = 1.0
            mix.inputs[6].default_value = (*color, 1); nt.links.new(a.outputs["Color"], mix.inputs[7]); base_out = mix.outputs[2]
    if base_out is not None: nt.links.new(base_out, P.inputs["Base Color"])
    if nor:
        t = nt.nodes.new("ShaderNodeTexImage"); t.image = img(nor, False); n = nt.nodes.new("ShaderNodeNormalMap"); n.inputs["Strength"].default_value = nstr
        nt.links.new(t.outputs["Color"], n.inputs["Color"]); nt.links.new(n.outputs["Normal"], P.inputs["Normal"])
    if mr:
        t = nt.nodes.new("ShaderNodeTexImage"); t.image = img(mr, False); s = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(t.outputs["Color"], s.inputs["Color"]); nt.links.new(s.outputs["Green"], P.inputs["Roughness"]); nt.links.new(s.outputs["Blue"], P.inputs["Metallic"])
    if emit:
        P.inputs["Emission Color"].default_value = (*emit[0], 1); P.inputs["Emission Strength"].default_value = emit[1]
    if blend:
        m.blend_method = 'BLEND'; m.use_backface_culling = True
    m["uv"] = uv; m["grain"] = grain; m["nouv"] = 1 if nouv else 0
    if wear: m["wear_tint"] = [t / gain for t in wear]; m["col_default"] = 1.0 / gain
    MATS[name] = m; return m


def materials(g):
    """the hard surfaces' materials (replacing build_room.py's floor, wall, oak, door, white, plastic, metal, screen) and
    the new ones: alu, keycap, book, decal, rubber, tea, led"""
    bind(g)
    for k in ("floor", "wall", "oak", "door", "white", "plastic_black", "metal_dark", "steel", "screen"):
        if k in MATS: bpy.data.materials.remove(MATS.pop(k))
    hmat("floor", diff="floor_diff.jpg", nor="floor_nor.jpg", mr="floor_mr.jpg", uv=1.99)
    hmat("wall", diff="wall_diff.jpg", nor="wall_nor.jpg", nstr=0.55, mr="wall_mr.jpg", uv=1.4)
    hmat("oak", diff="oak_diff_hard.jpg", nor="oak_nor.jpg", nstr=0.6, mr="oak_mr.jpg", uv=1.2, wear=(L.GAIN["oak"], 1.12, 1.05))
    hmat("door", diff="door_diff_hard.jpg", nor="oak_nor.jpg", nstr=0.5, mr="oak_mr.jpg", uv=1.2, grain=1, wear=(L.GAIN["door"], 1.16, 1.06))
    hmat("white", color=srgb("#ece9e2"), nor="white_nor.jpg", nstr=0.3, mr="white_mr.jpg", uv=0.45, wear=(0.86, 0.85, 0.83))
    hmat("plastic_black", color=srgb("#19191b"), nor="plastic_nor.jpg", nstr=0.12, mr="plastic_mr.jpg", uv=0.30, wear=(2.6, 2.6, 2.7))
    hmat("metal_dark", color=srgb("#2a2a2d"), metal=1.0, nor="metal_nor.jpg", nstr=0.4, mr="metal_mr.jpg", uv=0.22, wear=(2.2, 2.2, 2.2))
    hmat("steel", color=srgb("#c3c5c8"), metal=1.0, nor="metal_nor.jpg", nstr=0.5, mr="metal_mr.jpg", uv=0.22)
    hmat("alu", color=srgb("#b9bcc0"), metal=1.0, nor="metal_nor.jpg", nstr=0.4, mr="metal_mr.jpg", uv=0.3, wear=(0.8, 0.8, 0.8))
    hmat("screen", color=srgb("#060708"), rough=0.12)
    hmat("rubber", color=srgb("#141416"), rough=0.88)                          # (gaskets, feet, tyres, the mouse's wheel: also used for cables)
    hmat("keycap", diff="keycaps.png", rough=0.58, nouv=True)
    hmat("book", diff="spines.png", rough=0.72, nouv=True)
    hmat("decal", diff="decals.png", rough=0.7, blend=True, nouv=True)
    hmat("led", color=(0.1, 0.6, 0.3), rough=0.4, emit=((0.2, 1.0, 0.5), 2.0))
    # the posters, the pinboard and the photo strip carry their own UVs: the final projection pass must leave them alone
    for k in ("posters", "pinboard"):
        if k in MATS: MATS[k]["nouv"] = 1


# ---------------------------------------------------------------- helpers
def glm(rot=None, loc=(0, 0, 0), scale=None):
    """a Blender matrix for a glTF-space transform: rotate about a glTF axis ('x'|'y'|'z', angle), scale, then translate"""
    M = Matrix.Translation(Vector(loc))
    if rot: M = M @ Matrix.Rotation(rot[1], 4, rot[0].upper())
    if scale: M = M @ Matrix.Diagonal((*scale, 1.0))
    return C_GL @ M @ C_GL.inverted()


def gl4(rows, loc=(0, 0, 0)):
    """a Blender matrix for a glTF-space linear map given as 3 rows, then a translation"""
    M = Matrix(((*rows[0], loc[0]), (*rows[1], loc[1]), (*rows[2], loc[2]), (0, 0, 0, 1)))
    return C_GL @ M @ C_GL.inverted()


def xf(o, M):
    o.data.transform(M); o.data.update(); project_uv_keep(o); return o


def project_uv_keep(o):
    """project_uv unless the material keeps its own UVs"""
    me = o.data
    if me.materials and all(m and m.get("nouv") for m in me.materials): return
    project_uv(o)


def set_col_fn(o, fn):
    """the vertex colour "Col" per loop from fn(vertex position in glTF) -> (r, g, b)"""
    me = o.data; a = me.color_attributes.get("Col") or me.color_attributes.new("Col", 'FLOAT_COLOR', 'CORNER')
    for p in me.polygons:
        for li in p.loop_indices:
            v = me.vertices[me.loops[li].vertex_index].co
            a.data[li].color = (*fn((v.x, v.z, -v.y)), 1)


def edge_wear(o, bounds, bevel, amount=1.0, tint=None):
    """worn edges: the vertex colour tints the vertices on the box's bevels (within `bevel` of two of its planes)"""
    m = o.data.materials[0] if o.data.materials else None
    tint = tint or (m.get("wear_tint") if m else None) or (1.0, 1.0, 1.0); d0 = (m.get("col_default") if m else None) or 1.0
    (x0, x1), (y0, y1), (z0, z1) = bounds; eps = 1e-5
    def fn(p):
        d = sorted([abs(p[0] - x0), abs(p[0] - x1), abs(p[1] - y0), abs(p[1] - y1), abs(p[2] - z0), abs(p[2] - z1)])
        if d[1] > bevel + eps or bevel <= 0: return (d0, d0, d0)
        w = (1 - d[1] / bevel) * amount
        return tuple(d0 + (t - d0) * w for t in tint)
    set_col_fn(o, fn)


GREY = 2.3            # "plastic_grey": black plastic with its vertex colour lifted (the material carries a gain of 2.7)


def grey(o):
    """a lighter grey plastic part: the black plastic's vertex colour lifted (one material, one draw call)"""
    m = o.data.materials[0]; d0 = (m.get("col_default") or 1.0) * GREY
    a = o.data.color_attributes.get("Col") or o.data.color_attributes.new("Col", 'FLOAT_COLOR', 'CORNER')
    for d in a.data: d.color = (min(1.0, d0), min(1.0, d0), min(1.0, d0 * 1.03), 1)
    return o


def hbox(name, material, x, y, z, bevel=0.0, seg=2, wear=0.0, static=True, smooth=True, taper=None, mat_by_face=None):
    """build_room's box with worn edges (`wear` 0..1) and an optional taper: top face scaled by `taper` about its centre"""
    if material == "plastic_grey":
        return grey(hbox(name, "plastic_black", x, y, z, bevel=bevel, seg=seg, wear=0.0, static=static, smooth=smooth, taper=taper, mat_by_face=mat_by_face))
    o = box(name, material, x, y, z, bevel=bevel, seg=seg, static=static, mat_by_face=mat_by_face, smooth=smooth)
    if taper:
        cx, cz = (x[0] + x[1]) / 2, (z[0] + z[1]) / 2; h = y[1] - y[0]
        for v in o.data.vertices:
            t = max(0.0, min(1.0, (v.co.z - y[0]) / h)); k = 1 - (1 - taper) * t
            v.co.x = cx + (v.co.x - cx) * k; v.co.y = -cz + (v.co.y + cz) * k
        o.data.update(); project_uv_keep(o)
    if wear > 0 and bevel > 0: edge_wear(o, (x, y, z), bevel, wear)
    return o


def hcyl(name, material, c, r, y0, y1, n=24, r1=None, axis="y", static=True, cap=True, smooth=True):
    if material == "plastic_grey":
        return grey(cyl(name, "plastic_black", c, r, y0, y1, n=n, r1=r1, axis=axis, static=static, cap=cap, smooth=smooth))
    return cyl(name, material, c, r, y0, y1, n=n, r1=r1, axis=axis, static=static, cap=cap, smooth=smooth)


def hrod(name, material, p0, p1, r, n=8, static=True):
    """a cylinder between two glTF points"""
    a, b = B(*p0), B(*p1); d = b - a
    o = cyl(name, material, (0, 0), r, 0, d.length, n=n, static=static)
    o.data.transform(Matrix.Translation(a) @ d.to_track_quat('Z', 'Y').to_matrix().to_4x4()); o.data.update(); project_uv_keep(o); return o


def hsphere(name, material, c, r, n=16, static=True):
    """an ellipsoid at c with radii r (glTF)"""
    bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=n, v_segments=max(6, n // 2 + 2), radius=1.0)
    for v in bm.verts: v.co = B(c[0] + v.co.x * r[0], c[1] + v.co.z * r[1], c[2] - v.co.y * r[2])
    o = new_obj(name, bm, material, static); [setattr(p, "use_smooth", True) for p in o.data.polygons]; project_uv_keep(o); return o


def htorus(name, material, c, R, r, axis="y", half=None, nmaj=28, nmin=8, static=True, arc=None):
    """a ring (bmesh) about a glTF axis through c; half "up"/"down" keeps the half above/below c; arc (a0, a1) keeps a sector"""
    bm = bmesh.new(); rings = []
    a0, a1 = arc if arc else (0, 2 * math.pi); closed = arc is None
    nseg = nmaj if closed else nmaj
    for i in range(nseg if closed else nseg + 1):
        a = a0 + (a1 - a0) * i / nseg; ring = []
        for j in range(nmin):
            b = 2 * math.pi * j / nmin
            # local: ring in the plane perpendicular to the axis; (u, v) the plane's axes, w the axis
            rr = R + r * math.cos(b); hh = r * math.sin(b)
            u, v = rr * math.cos(a), rr * math.sin(a)
            if axis == "y": p = (c[0] + u, c[1] + hh, c[2] + v)
            elif axis == "z": p = (c[0] + u, c[1] + v, c[2] + hh)
            else: p = (c[0] + hh, c[1] + v, c[2] + u)
            ring.append(bm.verts.new(B(*p)))
        rings.append(ring)
    n_r = len(rings)
    for i in range(n_r if closed else n_r - 1):
        k = (i + 1) % n_r
        for j in range(nmin):
            jj = (j + 1) % nmin
            try: f = bm.faces.new([rings[i][j], rings[i][jj], rings[k][jj], rings[k][j]]); f.smooth = True
            except ValueError: pass
    if half:
        up = {"y": 1, "z": 1, "x": 1}
        keep_sign = 1 if half == "up" else -1
        cy = c[1]
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if (v.co.z - cy) * keep_sign < -1e-4], context='VERTS')
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    o = new_obj(name, bm, material, static); project_uv_keep(o); return o


def hlathe(name, material, prof, c, y0, n=32, static=True):
    if material == "plastic_grey":
        return grey(lathe(name, "plastic_black", prof, c, y0, n=n, static=static))
    return lathe(name, material, prof, c, y0, n=n, static=static)


def ribbed(name, material, c, r, ribs, depth, y0, y1, n=48, static=True):
    """a cup with vertical ribs: radius r + depth * cos(ribs * angle)"""
    bm = bmesh.new(); ring0, ring1 = [], []
    for i in range(n):
        a = 2 * math.pi * i / n; rr = r + depth * math.cos(ribs * a)
        ring0.append(bm.verts.new(B(c[0] + rr * math.cos(a), y0, c[1] + rr * math.sin(a)))); ring1.append(bm.verts.new(B(c[0] + rr * math.cos(a), y1, c[1] + rr * math.sin(a))))
    for i in range(n):
        j = (i + 1) % n; f = bm.faces.new([ring0[i], ring0[j], ring1[j], ring1[i]]); f.smooth = True
    bm.faces.new(list(reversed(ring0)))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    o = new_obj(name, bm, material, static); project_uv_keep(o); return o


def quad(name, material, pts, uvs, static=True):
    """a single face through four glTF points (seen from the front: top-left, top-right, bottom-right, bottom-left) with
    explicit UVs (glTF-style, v down the image) at those corners"""
    bm = bmesh.new(); vs = [bm.verts.new(B(*p)) for p in pts]; bm.faces.new(vs)
    o = new_obj(name, bm, material, static); uvl = o.data.uv_layers.get("UVMap") or o.data.uv_layers.new(name="UVMap")
    for li, (u, v) in zip(o.data.polygons[0].loop_indices, uvs): uvl.data[li].uv = (u, 1 - v)
    return o


def decal(name, cell, centre, size, facing, up=None, static=False, rot=0.0):
    """an alpha-blended quad of the decal atlas cell `cell` (size w x h, metres) at centre, its face pointing along
    `facing` (a unit glTF vector), its image top along `up`; rot turns it in its plane"""
    u0, v0, u1, v1 = L.decal_uv(cell); w, h = size
    f = Vector(facing).normalized()
    if up is None: up = Vector((0, 1, 0)) if abs(f.y) < 0.9 else Vector((0, 0, -1))
    up = Vector(up); right = up.cross(f).normalized(); up = f.cross(right).normalized()
    if rot:
        ca, sa = math.cos(rot), math.sin(rot); right, up = right * ca + up * sa, up * ca - right * sa
    c = Vector(centre); R, U = right * (w / 2), up * (h / 2)
    pts = [c - R + U, c + R + U, c + R - U, c - R - U]
    o = quad(name, "decal", [tuple(p) for p in pts], [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], static=static)
    # the face must look along `facing`
    me = o.data; nrm = Vector(me.polygons[0].normal); nrm_gl = Vector((nrm.x, nrm.z, -nrm.y))
    if nrm_gl.dot(f) < 0:
        bm = bmesh.new(); bm.from_mesh(me); bmesh.ops.reverse_faces(bm, faces=bm.faces[:]); bm.to_mesh(me); bm.free()
    return o


def face_uv(o, classify, cells, axes):
    """explicit UVs per face class: classify(normal glTF) -> class name; cells[class] = (u0, v0, u1, v1) glTF-style;
    axes[class] = ((axis, lo, hi) for u, (axis, lo, hi) for v) with axis 0/1/2 = glTF x/y/z, v growing with the axis
    towards the image's TOP"""
    me = o.data; uvl = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    for p in me.polygons:
        n = p.normal; k = classify((n.x, n.z, -n.y)); u0, v0, u1, v1 = cells[k]; (ua, ulo, uhi), (va, vlo, vhi) = axes[k]
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co; g = (co.x, co.z, -co.y)
            tu = max(0.0, min(1.0, (g[ua] - ulo) / (uhi - ulo))); tv = max(0.0, min(1.0, (g[va] - vlo) / (vhi - vlo)))
            uvl.data[li].uv = (u0 + (u1 - u0) * tu, 1 - (v1 + (v0 - v1) * tv))


def book(name, th, hh, dd, design, manga=False, static=True):
    """an upright book at the origin: thickness along x (0..th), height along y (0..hh), depth along z (-dd..0), the
    spine facing +z; textured from the spine atlas (spine, covers, page block)"""
    o = box(name, "book", (0, th), (0, hh), (-dd, 0), bevel=min(0.0012, th * 0.3), seg=1, static=static)
    if manga: sp = L.manga_uv(design); cv = (sp[0], sp[1] + 0.02, sp[2], sp[1] + 0.06)
    else: sp = L.spine_uv(design); cv = L.cover_uv(design)
    pg = L.PAGES_UV
    def cls(n):
        if n[2] > 0.6: return "spine"
        if abs(n[0]) > 0.5: return "cover"
        return "pages"
    face_uv(o, cls, {"spine": sp, "cover": cv, "pages": pg},
            {"spine": ((0, 0, th), (1, 0, hh)), "cover": ((2, -dd, 0), (1, 0, hh)), "pages": ((2, -dd, 0), (0, 0, th))})
    return o


def ensure_col(objs):
    """every mesh that will be joined with vertex-coloured ones carries "Col" (white: no tint)"""
    for o in objs:
        if o.type == 'MESH' and not o.data.color_attributes.get("Col"):
            m = o.data.materials[0] if o.data.materials else None; d0 = (m.get("col_default") if m else None) or 1.0
            a = o.data.color_attributes.new("Col", 'FLOAT_COLOR', 'CORNER')
            for d in a.data: d.color = (d0, d0, d0, 1)


# ================================================================ walls: skirting with a profile
def skirting(g):
    bind(g)
    for nm, x, z in (("skirt_back_a", (IX, DOOR_X0), (IZ, IZ + 0.014)), ("skirt_back_b", (DOOR_X1, X1), (IZ, IZ + 0.014)), ("skirt_left", (IX, IX + 0.014), (IZ + 0.014, Z1))):
        hbox(nm, "white", x, (FY, FY + 0.062), z, bevel=0.003, seg=1, wear=0.6)
        # a rounded cap on top of the board
        xx = (x[0], x[1]) if nm != "skirt_left" else (IX, IX + 0.018); zz = (IZ, IZ + 0.018) if nm != "skirt_left" else (IZ + 0.018, Z1)
        hbox(nm + "_cap", "white", xx, (FY + 0.062, FY + 0.074), zz, bevel=0.005, seg=2, wear=0.3)


# ================================================================ window: oak casing, aluminium sliding sashes, a crescent lock
def window(g):
    bind(g)
    for nm, x, y, z in [("win_casing_t", (IX, IX + 0.016), (WY1, WY1 + 0.055), (WZ0 - 0.055, WZ1 + 0.055)),
                        ("win_casing_a", (IX, IX + 0.016), (WY0, WY1), (WZ0 - 0.055, WZ0)),
                        ("win_casing_b", (IX, IX + 0.016), (WY0, WY1), (WZ1, WZ1 + 0.055))]:
        hbox(nm, "oak", x, y, z, bevel=0.003, seg=2, wear=0.5)
    # the inner lip of the casing stands a little proud (an architrave step)
    hbox("win_casing_t_lip", "oak", (IX, IX + 0.024), (WY1 + 0.03, WY1 + 0.055), (WZ0 - 0.055, WZ1 + 0.055), bevel=0.003, seg=1, wear=0.4)
    hbox("win_sill", "oak", (IX - 0.03, IX + 0.075), (WY0 - 0.028, WY0), (WZ0 - 0.08, WZ1 + 0.08), bevel=0.009, seg=3, wear=0.8)
    hbox("win_sill_apron", "oak", (IX, IX + 0.014), (WY0 - 0.082, WY0 - 0.028), (WZ0 - 0.06, WZ1 + 0.06), bevel=0.002, seg=1, wear=0.3)
    # the fixed aluminium frame in the reveal: head, jambs, and the bottom track with two rails
    hbox("win_frame_t", "alu", (-1.99, -1.905), (WY1 - 0.012, WY1), (WZ0, WZ1), bevel=0.002, seg=1)
    hbox("win_frame_a", "alu", (-1.99, -1.905), (WY0, WY1), (WZ0, WZ0 + 0.012), bevel=0.002, seg=1)
    hbox("win_frame_b", "alu", (-1.99, -1.905), (WY0, WY1), (WZ1 - 0.012, WZ1), bevel=0.002, seg=1)
    hbox("sash_track", "alu", (-1.99, -1.905), (WY0 - 0.004, WY0 + 0.008), (WZ0, WZ1), bevel=0.001, seg=1)
    for xr in (-1.9625, -1.9325):
        hbox("sash_rail", "alu", (xr - 0.003, xr + 0.003), (WY0 + 0.008, WY0 + 0.016), (WZ0 + 0.02, WZ1 - 0.02))
    SASH = 0.034
    def sash(nm, x, z0, z1):
        """an aluminium sash: four members, a glazing bead inside them, a rubber gasket, no glass (the page's sky plane)"""
        hbox(nm + "_t", "alu", x, (WY1 - SASH, WY1 - 0.014), (z0, z1), bevel=0.002, seg=2, wear=0.3)
        hbox(nm + "_b", "alu", x, (WY0 + 0.016, WY0 + SASH + 0.016), (z0, z1), bevel=0.002, seg=2, wear=0.3)
        hbox(nm + "_l", "alu", x, (WY0 + 0.016, WY1 - 0.014), (z0, z0 + SASH), bevel=0.002, seg=2, wear=0.3)
        hbox(nm + "_r", "alu", x, (WY0 + 0.016, WY1 - 0.014), (z1 - SASH, z1), bevel=0.002, seg=2, wear=0.3)
        bx = ((x[0] + x[1]) / 2 - 0.004, (x[0] + x[1]) / 2 + 0.004); bw = 0.009
        hbox(nm + "_bead_t", "alu", bx, (WY1 - SASH - bw, WY1 - SASH), (z0 + SASH - 0.002, z1 - SASH + 0.002), bevel=0.001, seg=1)
        hbox(nm + "_bead_b", "alu", bx, (WY0 + SASH + 0.016, WY0 + SASH + 0.016 + bw), (z0 + SASH - 0.002, z1 - SASH + 0.002), bevel=0.001, seg=1)
        hbox(nm + "_bead_l", "alu", bx, (WY0 + SASH + 0.016, WY1 - SASH), (z0 + SASH - 0.002, z0 + SASH + bw), bevel=0.001, seg=1)
        hbox(nm + "_bead_r", "alu", bx, (WY0 + SASH + 0.016, WY1 - SASH), (z1 - SASH - bw, z1 - SASH + 0.002), bevel=0.001, seg=1)
        gx = ((x[0] + x[1]) / 2 - 0.0015, (x[0] + x[1]) / 2 + 0.0015)
        hbox(nm + "_gasket", "rubber", gx, (WY0 + SASH + 0.016 + bw, WY0 + SASH + 0.016 + bw + 0.004), (z0 + SASH + bw, z1 - SASH - bw))
        hbox(nm + "_gasket_t", "rubber", gx, (WY1 - SASH - bw - 0.004, WY1 - SASH - bw), (z0 + SASH + bw, z1 - SASH - bw))
    sash("sash_a", (-1.978, -1.947), WZ0 + 0.012, 0.17)
    sash("sash_b", (-1.948, -1.917), 0.11, WZ1 - 0.012)
    # the crescent lock on the inner sash's meeting stile, and a pull on each sash
    hbox("sash_lock_base", "alu", (-1.917, -1.906), (1.62, 1.70), (0.118, 0.145), bevel=0.002, seg=2)
    hcyl("sash_lock_pivot", "alu", (1.66, 0.1315), 0.006, -1.906, -1.898, n=12, axis="x")
    hbox("sash_lock_lever", "alu", (-1.906, -1.899), (1.655, 1.665), (0.125, 0.185), bevel=0.002, seg=2)
    hsphere("sash_lock_knob", "alu", (-1.9025, 1.66, 0.185), (0.006, 0.006, 0.006), n=10)
    hbox("sash_pull_a", "alu", (-1.947, -1.943), (1.60, 1.72), (0.125, 0.14), bevel=0.0015, seg=1)
    hbox("sash_pull_b", "alu", (-1.917, -1.913), (1.60, 1.72), (0.14, 0.155), bevel=0.0015, seg=1)
    marker("SURF_window", (-2.012, (WY0 + WY1) / 2, (WZ0 + WZ1) / 2), (0, math.pi / 2, 0), w=WZ1 - WZ0 + 0.06, h=WY1 - WY0 + 0.06, mullion=-1.0)


# ================================================================ desk: top, steel frame, monitor, keyboard, mouse, speakers, mug, pens, books, bin
def desk(g):
    bind(g)
    DX0, DX1, DZ0, DZ1, DTOP = -1.86, -0.36, IZ + 0.01, -0.80, 0.97
    export(DX0=DX0, DX1=DX1, DZ0=DZ0, DZ1=DZ1, DTOP=DTOP)
    hbox("desk_top", "oak", (DX0, DX1), (DTOP - 0.03, DTOP), (DZ0, DZ1), bevel=0.005, seg=3, wear=0.9)
    for lx in (DX0 + 0.04, DX1 - 0.04):           # black steel side frames: two legs, a foot and a top rail
        for lz in (DZ0 + 0.05, DZ1 - 0.05):
            hbox("desk_leg", "metal_dark", (lx - 0.02, lx + 0.02), (FY + 0.02, DTOP - 0.03), (lz - 0.012, lz + 0.012), bevel=0.003, seg=2, wear=0.5)
        hbox("desk_foot", "metal_dark", (lx - 0.02, lx + 0.02), (FY, FY + 0.025), (DZ0 + 0.02, DZ1 - 0.02), bevel=0.003, seg=2, wear=0.5)
        hbox("desk_rail", "metal_dark", (lx - 0.02, lx + 0.02), (DTOP - 0.06, DTOP - 0.03), (DZ0 + 0.03, DZ1 - 0.03), bevel=0.002, seg=1)
        for lz in (DZ0 + 0.05, DZ1 - 0.05):      # levelling feet
            hcyl("desk_glide", "rubber", (lx, lz), 0.012, FY, FY + 0.004, n=10)
    hbox("desk_back_rail", "metal_dark", (DX0 + 0.06, DX1 - 0.06), (DTOP - 0.09, DTOP - 0.03), (DZ0 + 0.04, DZ0 + 0.055), bevel=0.002, seg=1)
    hbox("desk_tray", "metal_dark", (-1.30, -0.80), (DTOP - 0.12, DTOP - 0.03), (DZ0 + 0.06, DZ0 + 0.16), bevel=0.003, seg=1)   # a cable tray under the back
    hcyl("desk_grommet", "rubber", (DX1 - 0.10, DZ0 + 0.06), 0.03, DTOP, DTOP + 0.0015, n=20)                                    # a cable grommet in the top

    # ---- monitor: thin bezels, a chin with a power LED, a hump with ports at the back, a flat neck on an oval foot
    MON_C = (-1.06, 1.33, -1.19); MON_RY = 0.10; MON_RX = -0.06; SW, SH = 0.64, 0.37
    export(MON_C=MON_C, MON_RY=MON_RY, MON_RX=MON_RX, SW=SW, SH=SH)
    def mon_part(o):
        M = Matrix.Translation(B(*MON_C)) @ Matrix.Rotation(MON_RY, 4, 'Z') @ Matrix.Rotation(MON_RX, 4, 'X')
        o.data.transform(M); o.data.update(); project_uv_keep(o); return o
    bz = 0.007                                                                                            # the bezel
    mon_part(hbox("mon_body", "plastic_black", (-SW / 2 - bz, SW / 2 + bz), (-SH / 2 - 0.001, SH / 2 + bz), (-0.018, 0.0), bevel=0.003, seg=2, wear=0.4))
    mon_part(box("mon_screen", "screen", (-SW / 2, SW / 2), (-SH / 2, SH / 2), (0.0, 0.0008)))
    # the chin: a grey band under the glass over the body's full depth, 3.5 mm proud of the glass. Its top is 1 mm under the
    # glass's bottom edge, so the page's screen plane (SURF_monitor + 1 mm, tilted) rests on it for the QA harness's prop check
    mon_part(hbox("mon_chin", "plastic_grey", (-SW / 2 - bz, SW / 2 + bz), (-SH / 2 - 0.018, -SH / 2 - 0.001), (-0.018, 0.0035), bevel=0.001, seg=1))
    mon_part(box("mon_led", "led", (SW / 2 - 0.028, SW / 2 - 0.022), (-SH / 2 - 0.012, -SH / 2 - 0.009), (0.0012, 0.0022)))
    mon_part(hbox("mon_back", "plastic_black", (-0.17, 0.17), (-0.13, 0.11), (-0.052, -0.018), bevel=0.014, seg=3, wear=0.3))
    mon_part(hbox("mon_ports", "rubber", (-0.08, 0.06), (-0.11, -0.085), (-0.055, -0.045), bevel=0.002, seg=1))
    mon_part(hbox("mon_vesa", "plastic_grey", (-0.05, 0.05), (-0.05, 0.05), (-0.056, -0.052), bevel=0.002, seg=1))
    mon_part(hcyl("mon_joy", "plastic_black", (0.12, -0.10), 0.004, -0.058, -0.052, n=8, axis="z"))
    nb = hbox("mon_neck", "plastic_black", (MON_C[0] - 0.035, MON_C[0] + 0.035), (DTOP + 0.01, MON_C[1] - 0.03), (MON_C[2] - 0.072, MON_C[2] - 0.056), bevel=0.005, seg=2, wear=0.3)
    transform(nb, ry=MON_RY, pivot=(MON_C[0], 0, MON_C[2])); project_uv_keep(nb)
    nh = hcyl("mon_neck_hole", "rubber", (MON_C[0], MON_C[1] - 0.12), 0.012, MON_C[2] - 0.073, MON_C[2] - 0.071, n=14, axis="z")
    transform(nh, ry=MON_RY, pivot=(MON_C[0], 0, MON_C[2])); project_uv_keep(nh)
    bp = hlathe("mon_base", "plastic_black", [(0.0, 0.0), (0.112, 0.0), (0.115, 0.004), (0.112, 0.010), (0.095, 0.013), (0.0, 0.013)], (MON_C[0], MON_C[2] - 0.035), DTOP, n=40)
    bp.data.transform(Matrix.Translation(B(MON_C[0], 0, MON_C[2] - 0.035)) @ Matrix.Diagonal((1.0, 0.62, 1.0, 1.0)) @ Matrix.Translation(-B(MON_C[0], 0, MON_C[2] - 0.035)))
    transform(bp, ry=MON_RY, pivot=(MON_C[0], 0, MON_C[2])); project_uv_keep(bp)
    marker("SURF_monitor", tuple(Vector(MON_C) + Vector((math.sin(MON_RY) * 0.002, 0, math.cos(MON_RY) * 0.002))), (MON_RX, MON_RY, 0), w=SW, h=SH)

    # ---- felt desk mat, a tenkeyless keyboard with real keycaps (legends from the atlas), a mouse with a wheel
    KB_C = (-1.07, -0.97); KB_RY = 0.06
    export(KB_C=KB_C, KB_RY=KB_RY)
    box("deskmat", "fabric_black", (-1.47, -0.67), (DTOP, DTOP + 0.003), (-1.12, -0.84), bevel=0.0015, seg=1)
    kb = hbox("kb_body", "plastic_black", (-0.182, 0.182), (DTOP + 0.003, DTOP + 0.0205), (-0.070, 0.070), bevel=0.004, seg=2, wear=0.5)
    transform(kb, loc=(KB_C[0], 0, KB_C[1]), ry=KB_RY); project_uv_keep(kb)
    lip = hbox("kb_lip", "plastic_grey", (-0.179, 0.179), (DTOP + 0.0205, DTOP + 0.0225), (-0.067, 0.067), bevel=0.0015, seg=1)
    transform(lip, loc=(KB_C[0], 0, KB_C[1]), ry=KB_RY); project_uv_keep(lip)
    for s in (-1, 1):                                                                            # rubber feet (seen from the side)
        ft = hbox("kb_foot", "rubber", (s * 0.16 - 0.012, s * 0.16 + 0.012), (DTOP + 0.003, DTOP + 0.0045), (-0.06, -0.05))
        transform(ft, loc=(KB_C[0], 0, KB_C[1]), ry=KB_RY)
    kled = box("kb_led", "led", (0.130, 0.134), (DTOP + 0.0225, DTOP + 0.0235), (-0.0675, -0.0655))
    transform(kled, loc=(KB_C[0], 0, KB_C[1]), ry=KB_RY)
    cells, sides = L.keycap_cells(); P = L.U; x_left = -18.5 * P / 2
    CAP_H = 0.0085; GAP = 0.0011
    for r, xu, legend, wu, kind, uvc in cells:
        zc = -0.0545 if r == 0 else -0.034 + (r - 1) * P
        x0 = x_left + xu * P + GAP; x1 = x_left + (xu + wu) * P - GAP; z0, z1 = zc - P / 2 + GAP, zc + P / 2 - GAP
        k = hbox("key", "keycap", (x0, x1), (DTOP + 0.0225, DTOP + 0.0225 + CAP_H), (z0, z1), bevel=0.0009, seg=1, taper=0.84)
        side = sides[kind]; sc = ((side[0] + side[2]) / 2, (side[1] + side[3]) / 2)
        me = k.data; uvl = me.uv_layers["UVMap"]
        for p in me.polygons:
            top = p.normal.z > 0.6
            for li in p.loop_indices:
                if top:
                    co = me.vertices[me.loops[li].vertex_index].co; g = (co.x, co.z, -co.y)
                    tu = max(0.0, min(1.0, (g[0] - x0) / (x1 - x0))); tv = max(0.0, min(1.0, (g[2] - z0) / (z1 - z0)))
                    uvl.data[li].uv = (uvc[0] + (uvc[2] - uvc[0]) * tu, 1 - (uvc[1] + (uvc[3] - uvc[1]) * tv))
                else: uvl.data[li].uv = (sc[0], 1 - sc[1])
        transform(k, loc=(KB_C[0], 0, KB_C[1]), ry=KB_RY)
    # the keyboard's cable: out of the back, behind the monitor's foot
    hrod("kb_cable", "rubber", (KB_C[0] + 0.05, DTOP + 0.012, KB_C[1] - 0.07), (KB_C[0] + 0.03, DTOP + 0.006, KB_C[1] - 0.16), 0.0022, n=6)
    hrod("kb_cable", "rubber", (KB_C[0] + 0.03, DTOP + 0.006, KB_C[1] - 0.16), (MON_C[0] - 0.06, DTOP + 0.004, MON_C[2] - 0.06), 0.0022, n=6)
    # the mouse: a smooth shell, a split front, a scroll wheel
    MC = (-0.755, -0.95)
    bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=28, v_segments=16, radius=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * 0.031, v.co.y * 0.058, max(v.co.z, -0.2) * 0.02))
        if v.co.y < 0: v.co.z *= 0.90
        if v.co.y > 0.02: v.co.z *= 1 - 0.25 * (v.co.y - 0.02) / 0.038
    bm.transform(Matrix.Translation(B(MC[0], DTOP + 0.004 + 0.004, MC[1])))
    mouse = new_obj("mouse", bm, "plastic_black"); [setattr(p, "use_smooth", True) for p in mouse.data.polygons]; project_uv_keep(mouse)
    box("mouse_split", "rubber", (MC[0] - 0.0006, MC[0] + 0.0006), (DTOP + 0.012, DTOP + 0.030), (MC[1] - 0.060, MC[1] - 0.012))
    hbox("mouse_slot", "rubber", (MC[0] - 0.004, MC[0] + 0.004), (DTOP + 0.018, DTOP + 0.030), (MC[1] - 0.045, MC[1] - 0.028))
    hcyl("mouse_wheel", "rubber", (DTOP + 0.0235, MC[1] - 0.0365), 0.0065, MC[0] - 0.003, MC[0] + 0.003, n=16, axis="x")
    hbox("mouse_side_btn", "plastic_grey", (MC[0] - 0.0325, MC[0] - 0.029), (DTOP + 0.012, DTOP + 0.016), (MC[1] - 0.030, MC[1] - 0.005), bevel=0.001, seg=1)

    # ---- speakers: oak boxes, a black baffle with a woofer in its surround, a tweeter dome, a bass port, a knob on the right
    def speaker(nm, x, z, ry, knob=False):
        parts = [hbox(nm + "_box", "oak", (-0.065, 0.065), (0, 0.20), (-0.075, 0.075), bevel=0.005, seg=2, wear=0.6),
                 hbox(nm + "_front", "plastic_black", (-0.058, 0.058), (0.007, 0.193), (0.075, 0.080), bevel=0.003, seg=2, wear=0.3)]
        w = hlathe(nm + "_woofer", "plastic_black", [(0.047, 0), (0.049, 0.004), (0.045, 0.007), (0.040, 0.004), (0.028, -0.001), (0.013, -0.010), (0.0, -0.007)], (0, 0), 0, n=32)
        w.data.transform(Matrix.Translation(B(0, 0.072, 0.080)) @ Matrix.Rotation(-math.pi / 2, 4, 'X')); parts.append(w)
        cap = hlathe(nm + "_dustcap", "plastic_grey", [(0.012, 0), (0.010, 0.004), (0.005, 0.006), (0.0, 0.0065)], (0, 0), 0, n=16)
        cap.data.transform(Matrix.Translation(B(0, 0.072, 0.0705)) @ Matrix.Rotation(-math.pi / 2, 4, 'X')); parts.append(cap)
        t = hlathe(nm + "_tweet", "steel", [(0.018, 0), (0.016, 0.002), (0.012, 0.003), (0.0, 0.008)], (0, 0), 0, n=20)
        t.data.transform(Matrix.Translation(B(0, 0.158, 0.080)) @ Matrix.Rotation(-math.pi / 2, 4, 'X')); parts.append(t)
        parts.append(hcyl(nm + "_port", "rubber", (0.035, 0.030), 0.010, 0.0795, 0.0825, n=14, axis="z"))
        if knob:
            parts.append(hcyl(nm + "_knob", "steel", (-0.035, 0.030), 0.009, 0.080, 0.090, n=16, axis="z"))
            parts.append(box(nm + "_knob_mark", "rubber", (-0.0355, -0.0345), (0.033, 0.039), (0.0895, 0.0905)))
            parts.append(box(nm + "_led", "led", (-0.015, -0.011), (0.027, 0.031), (0.080, 0.0812)))
        for o in parts: transform(o, loc=(x, DTOP, z), ry=ry); project_uv_keep(o)
    speaker("spk_l", -1.52, -1.30, 0.22)
    speaker("spk_r", -0.58, -1.30, -0.18, knob=True)

    # ---- mug with tea in it, a ribbed pen cup with capped pens
    MUG = (-0.50, -0.98)
    hlathe("mug", "white", [(0.0, 0.0), (0.034, 0.0), (0.038, 0.003), (0.040, 0.010), (0.041, 0.090), (0.0415, 0.096), (0.0395, 0.097), (0.037, 0.094), (0.036, 0.016), (0.0, 0.016)], MUG, DTOP, n=32)
    hcyl("mug_tea", "screen", MUG, 0.0365, DTOP + 0.074, DTOP + 0.075, n=28)
    htorus("mug_handle", "white", (MUG[0] + 0.046, DTOP + 0.052, MUG[1]), 0.027, 0.0065, axis="z", arc=(-math.pi / 2, math.pi / 2), nmaj=16, nmin=8)
    PC = (-0.47, -1.33)
    ribbed("pencup", "plastic_black", PC, 0.033, 12, 0.0015, DTOP, DTOP + 0.10, n=36)
    hcyl("pencup_rim", "plastic_black", PC, 0.0355, DTOP + 0.098, DTOP + 0.102, n=32)
    hcyl("pencup_floor", "plastic_black", PC, 0.031, DTOP + 0.006, DTOP + 0.007, n=24)
    for i, (col, cap, tilt) in enumerate([("#2f6fd6", "#1b3f80", 0.10), ("#d63b2f", "#8c241b", -0.12), ("#f2c12e", "#2a2a2e", 0.05), ("#222222", "#9a9a9e", -0.04), ("#3aa860", "#1d6a3a", 0.14), ("#f4f0e8", "#d63b2f", 0.08)]):
        a = 2 * math.pi * i / 6; M = Matrix.Translation(B(PC[0] + 0.014 * math.cos(a), DTOP + 0.010, PC[1] + 0.014 * math.sin(a))) @ Matrix.Rotation(tilt, 4, 'X') @ Matrix.Rotation(tilt * 0.7, 4, 'Y')
        hl = 0.15 if i != 2 else 0.17
        body = cyl("pen", "painted", (0, 0), 0.0042, 0.0, hl - 0.03, n=8); set_vcol(body, srgb(col)); body.data.transform(M); body.data.update()
        cp = cyl("pen_cap", "painted", (0, 0), 0.0046, hl - 0.03, hl, n=8); set_vcol(cp, srgb(cap)); cp.data.transform(M); cp.data.update()
        clip = box("pen_clip", "painted", (0.004, 0.0055), (hl - 0.028, hl - 0.004), (-0.0012, 0.0012)); set_vcol(clip, srgb(cap)); clip.data.transform(M); clip.data.update()

    # ---- a couple of books lying on the desk (the spine atlas), a bin under it with a bag folded over its rim
    yb = DTOP; random.seed(31)
    for i, (hh, dd, th, des) in enumerate([(0.28, 0.21, 0.028, 0), (0.25, 0.19, 0.022, 9), (0.23, 0.17, 0.018, 3)]):
        bk = book("desk_book", th, hh, dd, des)
        # upright -> lying flat, cover up (thickness x -> y), height along z, the spine (+z) towards +x
        xf(bk, gl4(((0, 0, 1), (1, 0, 0), (0, 1, 0)), loc=(dd / 2, yb, -hh / 2)))
        transform(bk, loc=(-1.70, 0, -1.02), ry=0.25 + 0.12 * i); project_uv_keep(bk); yb += th
    hlathe("bin", "plastic_black", [(0, 0), (0.105, 0), (0.119, 0.29), (0.122, 0.30), (0.115, 0.30), (0.10, 0.008), (0, 0.008)], (-0.55, -1.22), FY, n=32)
    bag = hlathe("bin_bag", "painted", [(0.108, 0.255), (0.126, 0.30), (0.118, 0.305), (0.114, 0.30)], (-0.55, -1.22), FY, n=32); set_vcol(bag, srgb("#f2f2ee"))
    hcyl("bin_bag_top", "painted", (-0.55, -1.22), 0.113, FY + 0.27, FY + 0.272, n=28); set_vcol(bpy.data.objects["bin_bag_top"], srgb("#e8e8e4"))


# ================================================================ office chair (node "chair": origin on the floor under the gas lift, as before)
def chair(g):
    bind(g)
    CH_C = (-1.13, -0.585); CH_RY = 0.54; SEAT_TOP = 0.665
    chair = []
    def cpart(o): chair.append(o); return o
    for i in range(5):                                             # five-star base, casters with hubs and forks
        a = 2 * math.pi * i / 5
        bm = bmesh.new(); cuboid(bm, 0.0, 0.29, -0.022, 0.012, -0.022, 0.022)
        for v in bm.verts:
            gg = Vector((v.co.x, v.co.z, -v.co.y)); t = gg.x / 0.29
            gg.y += 0.05 - 0.03 * t; gg.z *= (1.0 - 0.35 * t); v.co = B(gg.x, gg.y, gg.z)
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=0.006, segments=2, affect='EDGES', clamp_overlap=True)
        leg = new_obj("ch_leg", bm, "plastic_black"); [setattr(p, "use_smooth", True) for p in leg.data.polygons]
        leg.data.transform(Matrix.Rotation(a, 4, 'Z')); project_uv_keep(leg); cpart(leg)
        cx, cz = 0.29 * math.cos(a), -0.29 * math.sin(a)
        cpart(hbox("ch_fork", "plastic_black", (cx - 0.012, cx + 0.012), (0.03, 0.068), (cz - 0.017, cz + 0.017), bevel=0.004, seg=2, wear=0.4))
        cpart(hcyl("ch_axle", "steel", (0.03, cz), 0.004, cx - 0.026, cx + 0.026, n=8, axis="x"))
        for s in (-1, 1):
            cpart(hcyl("ch_wheel", "rubber", (0.03, cz + s * 0.015), 0.027, cx - 0.0075, cx + 0.0075, n=16, axis="x"))
            cpart(hcyl("ch_hubcap", "plastic_grey", (0.03, cz + s * 0.0225), 0.012, cx - 0.003, cx + 0.003, n=8, axis="x"))
    cpart(hcyl("ch_hub", "plastic_black", (0, 0), 0.052, 0.03, 0.095, n=28, r1=0.040))
    cpart(hcyl("ch_gas_sleeve", "plastic_black", (0, 0), 0.034, 0.08, 0.26, n=24, r1=0.031))
    for k in range(3): cpart(htorus("ch_sleeve_ring", "plastic_black", (0, 0.13 + 0.05 * k, 0), 0.031, 0.004, axis="y", nmaj=18, nmin=4))
    cpart(hcyl("ch_gas", "steel", (0, 0), 0.021, 0.25, 0.37, n=20))
    cpart(hbox("ch_mech", "plastic_black", (-0.12, 0.12), (0.35, 0.41), (-0.13, 0.12), bevel=0.01, seg=2, wear=0.3))
    cpart(hbox("ch_lever", "steel", (0.12, 0.21), (0.375, 0.385), (-0.06, -0.05), bevel=0.003, seg=1))
    cpart(hsphere("ch_lever_tip", "plastic_black", (0.215, 0.38, -0.055), (0.009, 0.009, 0.009), n=10))
    cpart(hcyl("ch_tilt_knob", "plastic_black", (0.38, -0.10), 0.016, -0.09, -0.05, n=14, axis="x"))
    # seat cushion: a soft rounded slab (dished top, rolled front edge), as before
    seat = box("ch_seat", "fabric_black", (-0.25, 0.25), (0.41, 0.505), (-0.25, 0.23), bevel=0.035, seg=4)
    for v in seat.data.vertices:
        gg = Vector((v.co.x, v.co.z, -v.co.y))
        if gg.y > 0.47: gg.y -= 0.012 * (1 - (gg.x / 0.25) ** 2) * (1 - ((gg.z + 0.01) / 0.24) ** 2)
        v.co = B(*gg)
    cpart(seat)
    cpart(hbox("ch_seat_pan", "plastic_black", (-0.23, 0.23), (0.395, 0.415), (-0.23, 0.21), bevel=0.008, seg=2, wear=0.3))
    # backrest: a curved, padded panel on a plastic spine (as before), with a plastic back shell
    bm = bmesh.new(); nx, ny = 14, 16; grid = []
    for j in range(ny + 1):
        t = j / ny; y = 0.60 + 0.56 * t; row = []
        hw = 0.215 + 0.03 * math.sin(math.pi * min(1, t * 1.2)) - 0.04 * max(0, t - 0.8) / 0.2
        for i in range(nx + 1):
            s = i / nx * 2 - 1; x = s * hw
            z = 0.26 + 0.06 * s * s - 0.025 * math.sin(math.pi * t) * (1 - s * s) + 0.03 * t
            row.append(bm.verts.new(B(x, y, z)))
        grid.append(row)
    for j in range(ny):
        for i in range(nx): bm.faces.new([grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]])
    back = new_obj("ch_back", bm, "fabric_black")
    for p in back.data.polygons: p.use_smooth = True
    md = back.modifiers.new("solid", "SOLIDIFY"); md.thickness = 0.045; md.offset = 1.0
    md2 = back.modifiers.new("bev", "BEVEL"); md2.width = 0.012; md2.segments = 3; md2.limit_method = 'ANGLE'
    cpart(back)
    spine = hbox("ch_spine", "plastic_black", (-0.035, 0.035), (0.38, 0.84), (0.24, 0.27), bevel=0.01, seg=2, wear=0.3)
    for v in spine.data.vertices:
        gg = Vector((v.co.x, v.co.z, -v.co.y)); t = (gg.y - 0.38) / 0.46
        gg.z += 0.08 * t * t + 0.05 * t; v.co = B(*gg)
    spine.data.update(); project_uv_keep(spine); cpart(spine)
    cpart(hbox("ch_spine_foot", "plastic_black", (-0.04, 0.04), (0.37, 0.41), (0.08, 0.27), bevel=0.01, seg=2, wear=0.3))
    cpart(hcyl("ch_back_knob", "plastic_black", (0.62, 0.345), 0.018, -0.052, -0.035, n=14, axis="x"))
    for s in (-1, 1):                                              # armrests: posts, bars, pads (the pads stay where the page rests his hands)
        cpart(hbox("ch_arm_post", "plastic_black", (s * 0.255 - 0.018, s * 0.255 + 0.018), (0.38, 0.68), (-0.02, 0.06), bevel=0.008, seg=2, wear=0.4))
        cpart(hbox("ch_arm_bar", "plastic_black", (s * 0.15 - 0.02, s * 0.27) if s > 0 else (s * 0.27, s * 0.15 + 0.02), (0.375, 0.41), (0.0, 0.05), bevel=0.008, seg=2, wear=0.3))
        cpart(hbox("ch_arm_pad", "plastic_black", (s * 0.255 - 0.04, s * 0.255 + 0.04), (0.68, 0.71), (-0.13, 0.11), bevel=0.012, seg=3, wear=0.6))
        cpart(hbox("ch_arm_btn", "plastic_grey", (s * 0.255 + s * 0.018, s * 0.255 + s * 0.024) if s > 0 else (s * 0.255 - 0.024, s * 0.255 - 0.018), (0.60, 0.62), (0.005, 0.03), bevel=0.002, seg=1))
    CH_M = Matrix.Translation(B(CH_C[0], FY, CH_C[1])) @ Matrix.Rotation(CH_RY, 4, 'Z')
    for o in chair:
        o.data.transform(CH_M); o.data.update(); project_uv_keep(o)
        STATIC.remove(o)
        bpy.context.view_layer.objects.active = o
        for m in list(o.modifiers): bpy.ops.object.modifier_apply(modifier=m.name)
    ensure_col(chair)
    CHAIR = join(chair, "chair"); CHAIR.data.name = "chair"
    CHAIR.data.transform(CH_M.inverted()); CHAIR.matrix_world = CH_M
    for i, m in enumerate(CHAIR.data.materials):
        c = m.copy(); c.name = "chair_" + m.name; CHAIR.data.materials[i] = c
    export(CH_C=CH_C, CH_RY=CH_RY, SEAT_TOP=SEAT_TOP, CHAIR=CHAIR, CH_M=CH_M)


# ================================================================ storage bed frame (the mattress, pillow and duvet stay in build_room / props_soft)
def bed_frame(g):
    bind(g)
    BX0, BX1, BZ0, BZ1 = -1.90, -0.20, 0.25, 1.50
    BASE_Y, MAT_Y = 0.55, 0.82
    export(BX0=BX0, BX1=BX1, BZ0=BZ0, BZ1=BZ1, BASE_Y=BASE_Y, MAT_Y=MAT_Y)
    hbox("bed_base", "oak", (BX0 + 0.04, BX1), (FY + 0.03, BASE_Y), (BZ0, BZ1), bevel=0.007, seg=3, wear=0.8)
    hbox("bed_plinth", "plastic_black", (BX0 + 0.08, BX1 - 0.04), (FY, FY + 0.035), (BZ0 + 0.04, BZ1 - 0.04), wear=0.0)
    for (x0, x1) in ((-1.80, -1.04), (-1.00, -0.25)):            # drawer fronts with a routed finger pull and a bar grip
        hbox("bed_drawer", "oak", (x0, x1), (FY + 0.06, BASE_Y - 0.05), (BZ0 - 0.014, BZ0), bevel=0.004, seg=2, wear=0.7)
        hbox("bed_drawer_gap", "cut", (x0 - 0.004, x1 + 0.004), (FY + 0.056, BASE_Y - 0.046), (BZ0 - 0.002, BZ0 + 0.001))
        hbox("bed_drawer_pull", "cut", ((x0 + x1) / 2 - 0.08, (x0 + x1) / 2 + 0.08), (BASE_Y - 0.11, BASE_Y - 0.085), (BZ0 - 0.015, BZ0 - 0.011))
        hbox("bed_drawer_grip", "metal_dark", ((x0 + x1) / 2 - 0.08, (x0 + x1) / 2 + 0.08), (BASE_Y - 0.10, BASE_Y - 0.088), (BZ0 - 0.024, BZ0 - 0.014), bevel=0.003, seg=2, wear=0.4)
    hbox("bed_head", "oak", (BX0, BX0 + 0.04), (FY + 0.03, 1.10), (BZ0, BZ1), bevel=0.008, seg=3, wear=0.8)
    hbox("bed_head_cap", "oak", (BX0, BX0 + 0.07), (1.10, 1.13), (BZ0 - 0.005, BZ1 + 0.005), bevel=0.006, seg=3, wear=0.9)
    hbox("bed_head_groove", "cut", (BX0 + 0.04, BX0 + 0.043), (0.86, 0.872), (BZ0 + 0.04, BZ1 - 0.04))
    hbox("bed_head_groove", "cut", (BX0 + 0.04, BX0 + 0.043), (0.96, 0.972), (BZ0 + 0.04, BZ1 - 0.04))
    hbox("bed_rail", "oak", (BX0 + 0.04, BX1), (BASE_Y, BASE_Y + 0.012), (BZ0 - 0.006, BZ0 + 0.03), bevel=0.004, seg=2, wear=0.8)    # the front lip under the mattress edge


# ================================================================ bookshelf with books from the spine atlas
def bookshelf(g):
    bind(g)
    SX0, SX1, SZ0, SZ1, STOP = -0.12, 0.32, IZ + 0.005, -1.17, 2.12
    T = 0.018
    export(SX0=SX0, SX1=SX1, SZ0=SZ0, SZ1=SZ1, STOP=STOP, T=T)
    hbox("shelf_side_l", "oak", (SX0, SX0 + T), (FY, STOP), (SZ0, SZ1), bevel=0.0025, seg=2, wear=0.7)
    hbox("shelf_side_r", "oak", (SX1 - T, SX1), (FY, STOP), (SZ0, SZ1), bevel=0.0025, seg=2, wear=0.7)
    hbox("shelf_top", "oak", (SX0, SX1), (STOP - T, STOP), (SZ0, SZ1), bevel=0.0025, seg=2, wear=0.7)
    box("shelf_back", "oak", (SX0 + T, SX1 - T), (FY + 0.05, STOP - T), (SZ0, SZ0 + 0.006))
    hbox("shelf_plinth", "oak", (SX0 + T, SX1 - T), (FY, FY + 0.06), (SZ1 - 0.03, SZ1 - 0.012), bevel=0.002, seg=1, wear=0.5)
    LEVELS = [FY + 0.06, 0.56, 0.94, 1.32, 1.70]
    export(LEVELS=LEVELS)
    for y in LEVELS:
        hbox("shelf_board", "oak", (SX0 + T, SX1 - T), (y, y + T), (SZ0 + 0.006, SZ1), bevel=0.002, seg=2, wear=0.6)
        for sx in (SX0 + T, SX1 - T - 0.012):                    # shelf pins
            hcyl("shelf_pin", "steel", (y - 0.004, SZ1 - 0.04), 0.0025, sx, sx + 0.012, n=8, axis="x")
    random.seed(11)
    def place_upright(b, x, y, zfront, lean=0.0):
        if lean: xf(b, glm(rot=("z", lean)))
        xf(b, glm(loc=(x, y, zfront)))
    def books_row(x0, x1, y, depth_max=0.21, lean_end=True, fill=0.9):
        x = x0 + 0.004; n = 0
        while x < x1 - 0.03 and (x - x0) / (x1 - x0) < fill:
            th = random.uniform(0.016, 0.042); hh = random.uniform(0.17, 0.27); dd = random.uniform(0.15, depth_max)
            if hh > 0.30: hh = 0.30
            b = book("book", th, hh, dd, random.randrange(L.N_SPINES))
            place_upright(b, x, y + T, SZ1 - 0.010 - random.uniform(0.0, 0.012)); x += th + 0.0012; n += 1
        if lean_end and x < x1 - 0.13:
            b = book("book", 0.024, 0.22, 0.17, random.randrange(L.N_SPINES))
            xf(b, glm(rot=("z", 0.42))); xf(b, glm(loc=(x + 0.003 + 0.22 * math.sin(0.42), y + T, SZ1 - 0.012)))
    def books_stack(xc, y, n):
        yy = y + T
        for i in range(n):
            hh, dd, th = random.uniform(0.17, 0.22), random.uniform(0.13, 0.18), random.uniform(0.02, 0.04)
            b = book("book", th, hh, dd, random.randrange(L.N_SPINES))
            xf(b, glm(rot=("z", math.pi / 2))); xf(b, glm(loc=(hh / 2, yy, dd / 2)))
            transform(b, loc=(xc, 0, SZ1 - 0.11), ry=random.uniform(-0.15, 0.15)); project_uv_keep(b); yy += th
    books_row(SX0 + T, SX1 - T, LEVELS[1], fill=0.95)
    books_row(SX0 + T, SX1 - T - 0.13, LEVELS[2], fill=0.9); books_stack(SX1 - T - 0.085, LEVELS[2], 3)
    books_row(SX0 + T + 0.12, SX1 - T, LEVELS[3], fill=1.0, lean_end=False); books_stack(SX0 + T + 0.07, LEVELS[3], 2)
    books_row(SX0 + T, SX1 - T, LEVELS[0], depth_max=0.24, fill=0.6)
    # a steel bookend by the row on level 3, and a few magazines leaning on the top level
    hbox("bookend", "steel", (SX0 + T + 0.10, SX0 + T + 0.102), (LEVELS[3] + T, LEVELS[3] + T + 0.14), (SZ1 - 0.20, SZ1 - 0.04), bevel=0.0008, seg=1)
    hbox("bookend", "steel", (SX0 + T + 0.10, SX0 + T + 0.10 + 0.09), (LEVELS[3] + T, LEVELS[3] + T + 0.002), (SZ1 - 0.20, SZ1 - 0.04))
    xm = SX1 - T - 0.004
    for i in range(5):
        b = book("book", 0.006, 0.28, 0.21, (i * 5) % L.N_SPINES)
        xf(b, glm(rot=("z", -0.16 - 0.02 * i))); xf(b, glm(loc=(xm - 0.012 * i - 0.04, LEVELS[4] + T, SZ1 - 0.015)))
    b = box("shelf_box", "painted", (SX1 - T - 0.16, SX1 - T - 0.005), (LEVELS[0] + T, LEVELS[0] + T + 0.2), (SZ1 - 0.25, SZ1 - 0.01), bevel=0.003, seg=1); set_vcol(b, srgb("#cfc4ae"))


# ================================================================ small fridge: rounded body, two doors with gaskets, grips, hinges, a badge, magnets
def fridge(g):
    bind(g)
    FX0, FX1, FZ0, FZ1, FTOP = 0.45, 0.93, IZ + 0.02, -0.97, 1.27
    export(FX0=FX0, FX1=FX1, FZ0=FZ0, FZ1=FZ1, FTOP=FTOP)
    hbox("fridge_body", "white", (FX0, FX1), (FY + 0.012, FTOP), (FZ0, FZ1 - 0.03), bevel=0.012, seg=3, wear=0.35)
    for nm, (y0, y1) in (("fridge_door_lo", (FY + 0.02, 0.905)), ("fridge_door_hi", (0.915, FTOP - 0.008))):
        hbox(nm, "white", (FX0 + 0.004, FX1 - 0.004), (y0, y1), (FZ1 - 0.031, FZ1), bevel=0.010, seg=3, wear=0.45)
        hbox(nm + "_gasket", "rubber", (FX0 + 0.010, FX1 - 0.010), (y0 + 0.006, y1 - 0.006), (FZ1 - 0.036, FZ1 - 0.030))
        for hy in (y0 + 0.01, y1 - 0.03):                      # hinges on the right
            hbox(nm + "_hinge", "steel", (FX1 - 0.012, FX1 + 0.006), (hy, hy + 0.02), (FZ1 - 0.034, FZ1 - 0.006), bevel=0.002, seg=1)
    hbox("fridge_grip_lo", "steel", (FX0 + 0.03, FX0 + 0.045), (0.62, 0.86), (FZ1, FZ1 + 0.022), bevel=0.004, seg=2)
    hbox("fridge_grip_hi", "steel", (FX0 + 0.03, FX0 + 0.045), (0.95, 1.10), (FZ1, FZ1 + 0.022), bevel=0.004, seg=2)
    hbox("fridge_badge", "alu", (FX1 - 0.12, FX1 - 0.06), (FTOP - 0.07, FTOP - 0.055), (FZ1, FZ1 + 0.0015), bevel=0.001, seg=1)
    for fx in (FX0 + 0.04, FX1 - 0.04):
        for fz in (FZ0 + 0.05, FZ1 - 0.06): hcyl("fridge_foot", "plastic_black", (fx, fz), 0.015, FY, FY + 0.013, n=10)
    # a note held by two round magnets on the freezer door, a sticker on the lower door (decals)
    for mx, col in ((0.66, "#d9472b"), (0.76, "#2d3b5c")):
        mg = hcyl("fridge_magnet", "painted", (mx, 1.042), 0.011, FZ1 + 0.001, FZ1 + 0.006, n=16, axis="z"); set_vcol(mg, srgb(col))
    # cup noodles stacked on top + a tissue box, as before (vertex coloured)
    for i in range(2):
        cn = hlathe("cupnoodle", "painted", [(0.0, 0.0), (0.038, 0.0), (0.047, 0.10), (0.050, 0.103), (0.048, 0.106), (0.0, 0.106)], (0.58, -1.18), FTOP + i * 0.105, n=20)
        set_vcol(cn, srgb("#f2efe8" if i else "#d9442f"))
        band = hcyl("cupnoodle_band", "painted", (0.58, -1.18), 0.0445, FTOP + i * 0.105 + 0.06, FTOP + i * 0.105 + 0.075, n=20, r1=0.0460); set_vcol(band, srgb("#d9442f" if i else "#f2efe8"))
    tb = hbox("tissues", "painted", (0.70, 0.88), (FTOP, FTOP + 0.075), (-1.33, -1.22), bevel=0.003, seg=1); set_vcol(tb, srgb("#9fc2c9"))
    hbox("tissue_top", "white", (0.76, 0.82), (FTOP + 0.075, FTOP + 0.095), (-1.29, -1.26), bevel=0.008, seg=2)


# ================================================================ door: leaf with moulded panels, lever handle on a rose, lock, three hinges, architrave
def door(g):
    bind(g)
    LX0, LX1, LY1 = 1.11, 1.79, 2.10
    export(LX0=LX0, LX1=LX1, LY1=LY1)
    hbox("door_leaf", "door", (LX0, LX1), (FY + 0.008, LY1), (IZ, IZ + 0.035), bevel=0.004, seg=2, wear=0.6)
    for (y0, y1) in ((0.30, 1.05), (1.20, 1.96)):                # two panels: a moulding ring and a raised field
        px0, px1 = LX0 + 0.09, LX1 - 0.09; mw = 0.028
        for nm, x, y in (("door_mould", (px0, px0 + mw), (y0, y1)), ("door_mould", (px1 - mw, px1), (y0, y1)), ("door_mould", (px0, px1), (y0, y0 + mw)), ("door_mould", (px0, px1), (y1 - mw, y1))):
            hbox(nm, "door", x, y, (IZ + 0.035, IZ + 0.043), bevel=0.0035, seg=2, wear=0.4)
        hbox("door_panel", "door", (px0 + mw, px1 - mw), (y0 + mw, y1 - mw), (IZ + 0.034, IZ + 0.039), bevel=0.0025, seg=1, wear=0.2)
    for nm, x, y in (("door_casing_l", (DOOR_X0, LX0), (FY, LY1 + 0.06)), ("door_casing_r", (LX1, DOOR_X1), (FY, LY1 + 0.06)), ("door_casing_t", (DOOR_X0, DOOR_X1), (LY1, LY1 + 0.06))):
        hbox(nm, "white", x, y, (IZ, IZ + 0.022), bevel=0.003, seg=2, wear=0.5)
    hbox("door_casing_t_lip", "white", (DOOR_X0, DOOR_X1), (LY1 + 0.035, LY1 + 0.06), (IZ, IZ + 0.03), bevel=0.003, seg=1, wear=0.3)
    hbox("door_stop_l", "white", (LX0 - 0.012, LX0), (FY, LY1), (IZ + 0.022, IZ + 0.034), bevel=0.002, seg=1)
    hbox("door_stop_r", "white", (LX1, LX1 + 0.012), (FY, LY1), (IZ + 0.022, IZ + 0.034), bevel=0.002, seg=1)
    # the handle: a rose, a neck, a lever that curves down to a rounded end; the lock cylinder below; the strike plate on the casing
    HX, HY = LX1 - 0.07, 1.02
    hlathe("door_rose", "steel", [(0.0, 0.0), (0.027, 0.0), (0.029, 0.004), (0.026, 0.010), (0.0, 0.010)], (0, 0), 0, n=28).data.transform(Matrix.Translation(B(HX, HY, IZ + 0.035)) @ Matrix.Rotation(-math.pi / 2, 4, 'X'))
    hcyl("door_lever_neck", "steel", (HX, HY), 0.010, IZ + 0.044, IZ + 0.068, n=16, axis="z")
    hrod("door_lever", "steel", (HX, HY, IZ + 0.062), (HX - 0.10, HY - 0.006, IZ + 0.064), 0.0085, n=14)
    hrod("door_lever", "steel", (HX - 0.10, HY - 0.006, IZ + 0.064), (HX - 0.125, HY - 0.016, IZ + 0.062), 0.008, n=12)
    hsphere("door_lever_end", "steel", (HX - 0.125, HY - 0.016, IZ + 0.062), (0.008, 0.008, 0.008), n=12)
    hcyl("door_lock", "steel", (HX, HY - 0.07), 0.012, IZ + 0.035, IZ + 0.040, n=16, axis="z")
    box("door_keyhole", "rubber", (HX - 0.0015, HX + 0.0015), (HY - 0.078, HY - 0.064), (IZ + 0.040, IZ + 0.0405))
    hbox("door_strike", "steel", (LX1 + 0.001, LX1 + 0.011), (HY - 0.05, HY + 0.02), (IZ + 0.012, IZ + 0.0215), bevel=0.001, seg=1)
    for hy in (0.30, 1.05, 1.80):                                 # three hinges: two leaves and a knuckle
        hbox("door_hinge", "steel", (LX0 - 0.012, LX0 + 0.002), (hy, hy + 0.09), (IZ + 0.012, IZ + 0.022), bevel=0.001, seg=1)
        hbox("door_hinge", "steel", (LX0 + 0.002, LX0 + 0.03), (hy, hy + 0.09), (IZ + 0.033, IZ + 0.036), bevel=0.001, seg=1)
        hcyl("door_knuckle", "steel", (LX0 - 0.001, IZ + 0.028), 0.0065, hy - 0.002, hy + 0.092, n=12)


# ================================================================ air conditioner on the back wall
def aircon(g):
    bind(g)
    hbox("ac_body", "white", (0.36, 1.00), (2.02, 2.29), (IZ, IZ + 0.21), bevel=0.03, seg=3, wear=0.25)
    box("ac_seam", "cut", (0.385, 0.975), (2.195, 2.197), (IZ + 0.205, IZ + 0.212))
    hbox("ac_vent", "rubber", (0.40, 0.96), (2.030, 2.064), (IZ + 0.165, IZ + 0.205), bevel=0.004, seg=2)
    for k, (yy, tilt) in enumerate(((2.036, 0.0), (2.052, 0.0))):
        hbox("ac_louvre", "white", (0.405, 0.955), (yy, yy + 0.004), (IZ + 0.17, IZ + 0.205), bevel=0.001, seg=1)
    hbox("ac_flap", "white", (0.40, 0.96), (2.062, 2.080), (IZ + 0.185, IZ + 0.218), bevel=0.006, seg=2, wear=0.2)
    box("ac_display", "screen", (0.86, 0.94), (2.095, 2.115), (IZ + 0.211, IZ + 0.2125))
    box("ac_led", "led", (0.93, 0.94), (2.10, 2.11), (IZ + 0.2125, IZ + 0.2135))
    for i in range(16):                                           # the intake grille on top
        xx = 0.41 + i * 0.035
        box("ac_grille", "white", (xx, xx + 0.012), (2.288, 2.292), (IZ + 0.04, IZ + 0.17))
    box("ac_grille_slot", "cut", (0.40, 0.96), (2.287, 2.288), (IZ + 0.035, IZ + 0.175))
    hbox("ac_pipe", "white", (1.00, 1.044), (2.08, 2.22), (IZ, IZ + 0.07), bevel=0.012, seg=3, wear=0.2)     # the pipe cover to the outside


# ================================================================ the game controller on the desk (generic shape)
def controller(g):
    bind(g)
    n0 = group(); pad = []
    pad.append(hbox("pad_body", "painted", (-0.052, 0.052), (0.0, 0.024), (-0.028, 0.02), bevel=0.01, seg=3))
    for s in (-1, 1):
        gr = blob("pad_grip", "painted", (s * 0.046, 0.011, 0.022), (0.022, 0.012, 0.036), n=14); gr.data.transform(Matrix.Rotation(s * 0.35, 4, 'Z')); pad.append(gr)
    vc(pad, "#e4e2dc")
    plate = hbox("pad_plate", "painted", (-0.024, 0.024), (0.024, 0.0255), (-0.026, -0.002), bevel=0.0015, seg=1); set_vcol(plate, srgb("#2a2a2e"))
    sticks = []
    for c in ((-0.022, 0.006), (0.016, 0.006)):
        st = hlathe("pad_stick", "painted", [(0.0, 0.0), (0.006, 0.0), (0.006, 0.006), (0.0088, 0.009), (0.0082, 0.0115), (0.0, 0.010)], c, 0.024, n=14); sticks.append(st)
    dpad = [box("pad_dpad", "painted", (-0.042, -0.026), (0.024, 0.027), (-0.012, -0.006), bevel=0.0008, seg=1), box("pad_dpad", "painted", (-0.037, -0.031), (0.024, 0.027), (-0.017, -0.001), bevel=0.0008, seg=1)]
    vc(sticks + dpad, "#2a2a2e")
    for (dx, dz), col in (((0.009, 0), "#d64a4a"), ((-0.009, 0), "#4aa8d6"), ((0, 0.009), "#e8c84a"), ((0, -0.009), "#4ad67a")):
        bt = hcyl("pad_btn", "painted", (0.034 + dx, -0.009 + dz), 0.0042, 0.023, 0.0275, n=12); set_vcol(bt, srgb(col))
    for s in (-1, 1):
        bp = hbox("pad_bumper", "painted", (s * 0.032 - 0.014, s * 0.032 + 0.014), (0.016, 0.022), (-0.034, -0.027), bevel=0.002, seg=1); set_vcol(bp, srgb("#d8d6d0"))
    box("pad_light", "led", (-0.012, 0.012), (0.012, 0.015), (-0.0285, -0.028))
    parts = since(n0)
    for o in parts: transform(o, loc=(-0.80, DTOP, -1.20), ry=-0.35)
    settle(parts, DTOP); [project_uv_keep(o) for o in parts]; check("game_pad", parts, ("y", DTOP))


# ================================================================ headphones on the wall hook (node "headphones", origin where the band rests on the hook)
def headphones(g):
    bind(g)
    hmat("hp_shell", color=srgb("#26272c"), rough=0.4, nor="plastic_nor.jpg", nstr=0.12, mr="plastic_mr.jpg", uv=0.20)
    hmat("hp_pad", color=srgb("#141416"), rough=0.9, nor="fabric_nor.jpg", nstr=0.8, uv=0.10)
    HB_R = 0.078; HB_C = (HP[0], HP[1] + 0.006 - HB_R + 0.008, IZ + 0.05)
    export(HB_R=HB_R, HB_C=HB_C)
    hp = [htorus("hp_band", "hp_shell", HB_C, HB_R, 0.0075, axis="z", half="up", nmaj=36, nmin=10, static=False),
          htorus("hp_band_pad", "hp_pad", (HB_C[0], HB_C[1], HB_C[2]), HB_R - 0.006, 0.0085, axis="z", arc=(math.pi * 0.3, math.pi * 0.7), nmaj=14, nmin=10, static=False)]
    for s in (-1, 1):
        cx = HB_C[0] + s * HB_R; cy = HB_C[1] - 0.04
        hp.append(hbox("hp_yoke", "hp_shell", (cx - 0.004, cx + 0.004), (cy + 0.02, HB_C[1] + 0.004), (HB_C[2] - 0.009, HB_C[2] + 0.009), bevel=0.002, seg=2, static=False))
        hp.append(hcyl("hp_hinge", "hp_shell", (cy + 0.025, HB_C[2]), 0.005, cx - 0.008, cx + 0.008, n=10, axis="x", static=False))
        # the cup: a shell with a rounded back, a slim steel rim, the pad; built around the vertical axis then laid along x
        shell = hlathe("hp_cup", "hp_shell", [(0.0, 0.0), (0.026, 0.0), (0.034, 0.004), (0.038, 0.012), (0.039, 0.022), (0.038, 0.026), (0.0, 0.026)], (0, 0), 0, n=28, static=False)
        rim = hlathe("hp_rim", "hp_shell", [(0.0375, 0.024), (0.0395, 0.026), (0.0375, 0.028), (0.0355, 0.027)], (0, 0), 0, n=28, static=False)
        pad = hlathe("hp_pad", "hp_pad", [(0.021, 0.026), (0.034, 0.027), (0.037, 0.034), (0.034, 0.041), (0.025, 0.043), (0.021, 0.040)], (0, 0), 0, n=28, static=False)
        for o in (shell, rim, pad):
            # local up (y) -> towards the band's centre (-s x): lay the cup along x, the pad inwards
            xf(o, glm(rot=("z", s * math.pi / 2), loc=(0, 0, 0))); xf(o, glm(loc=(cx + s * 0.021, cy, HB_C[2])))
            hp.append(o)
    check("headphones", hp, None)
    export(hp=hp)


# ================================================================ the small fan in the front right
def fan(g):
    bind(g)
    n0 = group(); FAN = (1.70, 0.30); FAN_RY = -2.2
    hlathe("fan_base", "white", [(0, 0), (0.115, 0), (0.119, 0.008), (0.117, 0.014), (0.10, 0.03), (0.02, 0.034), (0, 0.034)], (0, 0), 0, n=32)
    for i, col in enumerate(("#3a3b40", "#3a3b40", "#d9472b")):
        bt = hcyl("fan_btn", "painted", (0.05 + 0.025 * i - 0.025, 0.07), 0.006, 0.03, 0.037, n=10); set_vcol(bt, srgb(col))
    hcyl("fan_stem", "white", (0, 0), 0.014, 0.03, 0.36, n=14)
    hcyl("fan_collar", "plastic_grey", (0, 0), 0.018, 0.20, 0.23, n=14)
    hcyl("fan_motor", "white", (0, 0.36), 0.045, -0.09, -0.01, n=24, axis="z")
    hcyl("fan_motor_back", "plastic_grey", (0, 0.36), 0.030, -0.10, -0.09, n=18, axis="z")
    hcyl("fan_tilt", "plastic_grey", (0.36, -0.05), 0.012, -0.05, 0.05, n=12, axis="x")
    FC = (0, 0.36, -0.005)
    htorus("fan_rim", "white", FC, 0.13, 0.007, axis="z", nmaj=36, nmin=6)
    for rr, dz in ((0.105, 0.028), (0.075, 0.042), (0.045, 0.050), (0.02, 0.054)): htorus("fan_ring", "white", (0, FC[1], FC[2] + dz), rr, 0.002, axis="z", nmaj=24, nmin=4)
    for k in range(12):
        a = k * math.pi / 6; hrod("fan_spoke", "white", (0, FC[1], FC[2] + 0.055), (0.128 * math.cos(a), FC[1] + 0.128 * math.sin(a), FC[2] + 0.004), 0.0018, n=4)
    hcyl("fan_badge", "white", (0, FC[1]), 0.024, FC[2] + 0.052, FC[2] + 0.062, n=18, axis="z")
    fb = hlathe("fan_back", "white", [(0.0, 0.0), (0.06, 0.004), (0.12, 0.03), (0.13, 0.05)], (0, 0), 0, n=36)
    fb.data.transform(Matrix.Translation(B(0, 0.36, -0.055)) @ Matrix.Rotation(math.pi / 2, 4, 'X')); fb.data.update()
    for rr in (0.09, 0.05): htorus("fan_back_ring", "white", (0, FC[1], FC[2] - 0.04), rr, 0.002, axis="z", nmaj=20, nmin=4)
    hcyl("fan_hub", "plastic_grey", (0, FC[1]), 0.02, FC[2] - 0.01, FC[2] + 0.012, n=16, axis="z")
    for i in range(3):
        bl = blob("fan_blade", "painted", (0.062, 0, 0), (0.055, 0.026, 0.004), n=12); set_vcol(bl, srgb("#c9d3dc"))
        bl.data.transform(Matrix.Translation(B(0, 0.36, -0.005)) @ Matrix.Rotation(i * 2 * math.pi / 3, 4, 'Y') @ Matrix.Rotation(0.35, 4, 'X')); bl.data.update()
    parts = since(n0)
    for o in parts: transform(o, loc=(FAN[0], FY, FAN[1]), ry=FAN_RY)
    settle(parts, FY); [project_uv_keep(o) for o in parts]; check("fan", parts, ("y", FY))


# ================================================================ decals: dust, scuffs, scratches, a coffee ring, stickers (one node "decals", no AO)
def decals(g):
    bind(g)
    ds = []
    def D(name, cell, centre, size, facing, **kw): ds.append(decal(name, cell, centre, size, facing, **kw))
    UP, FWD, LEFT_IN, BACK_IN = (0, 1, 0), (0, 0, 1), (1, 0, 0), (0, 0, 1)
    e = 0.0012
    # the floor: worn lacquer where the chair rolls, scratches by the door, scuffs off the rug
    D("dc_floor_wear", "floor_wear", (-0.95, FY + e, -0.50), (1.1, 1.0), UP, rot=0.3)
    D("dc_floor_scr", "scratches", (1.30, FY + e, -0.75), (0.55, 0.55), UP, rot=1.1)
    D("dc_floor_scuff", "scuff_a", (-0.70, FY + e, -0.92), (0.35, 0.35), UP, rot=0.6)
    D("dc_floor_scuff2", "scuff_b", (1.55, FY + e, 1.25), (0.45, 0.45), UP, rot=2.2)
    D("dc_floor_scuff3", "scuff_b", (0.05, FY + e, 1.25), (0.4, 0.4), UP, rot=-0.4)
    # walls: rubs above the skirting and where things lean
    D("dc_wall_rub", "wall_scuff", (-0.24, 0.78, IZ + e), (0.24, 0.12), FWD)
    D("dc_wall_rub2", "scuff_b", (0.39, 0.95, IZ + e), (0.10, 0.18), FWD)
    D("dc_wall_rub3", "wall_scuff", (IX + e, 1.21, 1.42), (0.26, 0.10), LEFT_IN, up=(0, 1, 0))
    D("dc_wall_rub4", "wall_scuff", (1.90, 0.32, IZ + e), (0.16, 0.08), FWD)
    # the door: scuffed at the bottom where feet push it
    D("dc_door_scuff", "scuff_a", (1.33, 0.235, IZ + 0.035 + e), (0.26, 0.10), FWD)
    # the desk: a coffee ring near the mug, dust along the back edge
    D("dc_ring", "ring", (-0.60, DTOP + e, -0.92), (0.085, 0.085), UP, rot=0.4)
    D("dc_desk_dust", "dust_edge", (-1.10, DTOP + e, DZ0 + 0.04), (0.60, 0.07), UP)
    D("dc_desk_dust2", "dust", (-1.76, DTOP + e, DZ0 + 0.06), (0.14, 0.14), UP)
    # the fridge: a note and two stickers, dust on top
    D("dc_fridge_note", "label", (0.71, 1.015, FZ1 + e), (0.13, 0.065), FWD)
    D("dc_fridge_cat", "sticker_cat", (0.80, 0.56, FZ1 + e), (0.075, 0.075), FWD, rot=-0.15)
    D("dc_fridge_wave", "sticker_wave", (0.62, 0.42, FZ1 + e), (0.065, 0.065), FWD, rot=0.1)
    D("dc_fridge_dust", "dust", (0.62, FTOP + e, FZ0 + 0.10), (0.26, 0.16), UP)
    # the bin, the bed base, a speaker, the shelf top, the air conditioner, the window sill
    D("dc_bin_sticker", "sticker_tokyo", (-0.55, FY + 0.17, -1.22 + 0.112 + e), (0.045, 0.045), FWD)
    D("dc_bed_sticker", "sticker_record", (-0.42, 0.44, BZ0 - 0.014 - e), (0.05, 0.05), (0, 0, -1), rot=0.2)
    D("dc_bed_scuff", "scuff_a", (-1.40, 0.27, BZ0 - 0.014 - e), (0.30, 0.09), (0, 0, -1))
    D("dc_bin_sticker2", "sticker_onigiri", (-0.55 + 0.113 + e, FY + 0.21, -1.22), (0.045, 0.045), (1, 0, 0), rot=0.25)
    D("dc_shelf_dust", "dust", (0.10, STOP + e, -1.30), (0.30, 0.20), UP)
    D("dc_ac_dust", "dust_edge", (0.68, 2.29 + e, IZ + 0.10), (0.5, 0.08), UP)
    D("dc_sill_dust", "dust_edge", (-1.90, WY0 + e, -0.42), (0.07, 0.30), UP, up=(1, 0, 0))
    for k in ("posters", "pinboard"):                     # their own UVs too (see materials())
        if k in MATS: MATS[k]["nouv"] = 1
    DEC = join(ds, "decals"); DEC.data.name = "decals"; DEC.hide_render = True              # not in the AO bake (it would shadow its own surface)
    export(DECALS_OBJ=DEC)


# ================================================================ the manga stack on the floor between the desk and the shelf
def manga(g):
    bind(g)
    n0 = group(); random.seed(5); yy = FY
    for i in range(9):
        th = random.uniform(0.014, 0.019)
        b = book("manga", th, 0.176, 0.114, i % 4, manga=True)
        xf(b, glm(rot=("z", math.pi / 2))); xf(b, glm(loc=(0.088, yy, 0.057)))                     # lying flat, the spine towards the room
        transform(b, loc=(-0.24 + random.uniform(-0.006, 0.006), 0, -1.32), ry=random.uniform(-0.18, 0.18)); project_uv_keep(b); yy += th
    check("manga_stack", since(n0), ("y", FY))


def finish(g):
    """before the static parts are joined: every mesh carries the vertex colour layer (white where no wear was set)"""
    bind(g)
    ensure_col([o for o in STATIC if o.name in bpy.data.objects] + list(hp) + [CHAIR])


# this module's own names never get overwritten by build_room's (it has a float `xf`, a list `chair`, ...)
_MINE = {k for k, v in globals().items() if callable(v) and getattr(v, "__module__", None) == __name__} | {"G", "L", "WHITE", "C_GL", "_MINE"}
