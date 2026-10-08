# blender -b -P build_room.py -- [--nobake]
# Builds SUB-01's room from clean primitives + a few CC0 Poly Haven props, bakes ambient occlusion into a shared
# lightmap atlas, and exports out/room_raw.glb (+ out/ao.png).  Coordinates in the helpers are glTF/three.js world units:
# x right, y up, z towards the viewer; the room spans x -2..2, z -1.6..1.6, floor top at y = FY (= the page's F).
import bpy, bmesh, math, random, sys, os
from mathutils import Vector, Matrix, Euler
R = os.path.dirname(os.path.abspath(__file__)); TX = f"{R}/tex_final"; AS = f"{R}/assets"; OUT = f"{R}/out"; os.makedirs(OUT, exist_ok=True)
NOBAKE = "--nobake" in sys.argv
FY = 0.16
random.seed(11)
bpy.ops.wm.read_factory_settings(use_empty=True)
SC = bpy.context.scene

def B(x, y, z): return Vector((x, -z, y))           # glTF -> Blender

# ---------------------------------------------------------------- materials
MATS = {}
def img(name, colour=True):
    im = bpy.data.images.load(f"{TX}/{name}", check_existing=True)
    if not colour: im.colorspace_settings.name = "Non-Color"
    return im
def mat(name, color=(0.8, 0.8, 0.8), rough=0.6, metal=0.0, diff=None, nor=None, nstr=1.0, mr=None, uv=1.0, vcol=False, emit=None, grain=0):
    """uv: metres covered by one texture tile (used by the UV projection); grain: 0 = along x/z as projected, 1 = swap u/v"""
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; P = nt.nodes["Principled BSDF"]
    P.inputs["Base Color"].default_value = (*color, 1); P.inputs["Roughness"].default_value = rough; P.inputs["Metallic"].default_value = metal
    if diff:
        t = nt.nodes.new("ShaderNodeTexImage"); t.image = img(diff); nt.links.new(t.outputs["Color"], P.inputs["Base Color"])
    if vcol:
        a = nt.nodes.new("ShaderNodeVertexColor"); a.layer_name = "Col"; nt.links.new(a.outputs["Color"], P.inputs["Base Color"])
    if nor:
        t = nt.nodes.new("ShaderNodeTexImage"); t.image = img(nor, False); n = nt.nodes.new("ShaderNodeNormalMap"); n.inputs["Strength"].default_value = nstr
        nt.links.new(t.outputs["Color"], n.inputs["Color"]); nt.links.new(n.outputs["Normal"], P.inputs["Normal"])
    if mr:
        t = nt.nodes.new("ShaderNodeTexImage"); t.image = img(mr, False); s = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(t.outputs["Color"], s.inputs["Color"]); nt.links.new(s.outputs["Green"], P.inputs["Roughness"]); nt.links.new(s.outputs["Blue"], P.inputs["Metallic"])
    if emit:
        P.inputs["Emission Color"].default_value = (*emit[0], 1); P.inputs["Emission Strength"].default_value = emit[1]
    m["uv"] = uv; m["grain"] = grain; MATS[name] = m; return m

def srgb(h):
    h = h.lstrip("#"); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c)

mat("floor", diff="floor_diff.jpg", nor="floor_nor.jpg", mr="floor_mr.jpg", uv=1.7)
mat("wall", diff="wall_diff.jpg", nor="wall_nor.jpg", nstr=0.6, rough=0.9, uv=1.4)
mat("cut", color=srgb("#2b2927"), rough=0.95)
mat("oak", diff="oak_diff.jpg", nor="oak_nor.jpg", nstr=0.6, mr="oak_mr.jpg", uv=1.2)
mat("door", diff="door_diff.jpg", nor="oak_nor.jpg", nstr=0.5, mr="oak_mr.jpg", uv=1.2, grain=1)
mat("white", color=srgb("#ece9e2"), rough=0.42)
mat("plastic_black", color=srgb("#19191b"), rough=0.42)
mat("fabric_black", color=srgb("#151517"), rough=0.92, nor="fabric_nor.jpg", nstr=0.8, uv=0.12)
mat("metal_dark", color=srgb("#2a2a2d"), rough=0.38, metal=1.0)
mat("steel", color=srgb("#c3c5c8"), rough=0.28, metal=1.0)
mat("screen", color=srgb("#060708"), rough=0.12)
mat("painted", color=(1, 1, 1), rough=0.65, vcol=True)
mat("posters", diff="posters.png", rough=0.55)
sys.path.insert(0, R); import props_hard; props_hard.materials(globals())   # #98 G5: the hard surfaces (room_build/props_hard.py) take over floor, wall, oak, door, white, plastic, metal, screen

# ---------------------------------------------------------------- mesh helpers
STATIC = []          # objects joined into the one static mesh (baked AO)
def new_obj(name, bm, material, static=True):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); SC.collection.objects.link(o)
    if isinstance(material, (list, tuple)):
        for m in material: me.materials.append(MATS[m])
    else: me.materials.append(MATS[material])
    if static: STATIC.append(o)
    return o

def project_uv(o, layer="UVMap"):
    """box projection in world space: 1 texture tile = material['uv'] metres"""
    me = o.data; uvl = me.uv_layers.get(layer) or me.uv_layers.new(name=layer)
    M = o.matrix_world; N = M.to_3x3().inverted_safe().transposed()
    for p in me.polygons:
        m = me.materials[p.material_index] if me.materials else None
        if m and m.get("nouv"): continue           # atlases (keycaps, spines, decals, posters) keep their own UVs (#98 G5)
        s = m.get("uv", 1.0) if m else 1.0; g = m.get("grain", 0) if m else 0
        n = (N @ p.normal); ax = max(range(3), key=lambda i: abs(n[i]))
        for li in p.loop_indices:
            w = M @ me.vertices[me.loops[li].vertex_index].co          # Blender world: x, y(-z gl), z(up)
            gx, gy, gz = w.x, w.z, -w.y
            if ax == 2: u, v = gx, gz              # horizontal face (Blender z = up)
            elif ax == 0: u, v = gz, gy            # facing +-x
            else: u, v = gx, gy                    # facing +-z (glTF)
            if g: u, v = v, u
            uvl.data[li].uv = (u / s, v / s)

def cuboid(bm, x0, x1, y0, y1, z0, z1):
    """a box in glTF coords into bmesh; returns its faces"""
    r = bmesh.ops.create_cube(bm, size=1.0)
    vs = r["verts"]
    for v in vs:
        gx = x0 if v.co.x < 0 else x1; gy = y0 if v.co.z < 0 else y1; gz = z0 if v.co.y > 0 else z1
        v.co = B(gx, gy, gz)
    return list({f for v in vs for f in v.link_faces})

def box(name, material, x, y, z, bevel=0.0, seg=2, static=True, mat_by_face=None, smooth=True):
    """x, y, z: (min, max) in glTF coords.  mat_by_face: {'top':i,'bottom':i,'side':i} with material list"""
    bm = bmesh.new(); faces = cuboid(bm, x[0], x[1], y[0], y[1], z[0], z[1])
    if mat_by_face:
        for f in faces:
            f.normal_update(); nz = f.normal.z
            f.material_index = mat_by_face.get("top" if nz > 0.5 else "bottom" if nz < -0.5 else "side", 0)
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=bevel, segments=seg, profile=0.5, affect='EDGES', clamp_overlap=True)
    o = new_obj(name, bm, material, static)
    if smooth and bevel > 0:
        for p in o.data.polygons: p.use_smooth = True
    project_uv(o); return o

def cyl(name, material, c, r, y0, y1, n=24, r1=None, axis="y", static=True, cap=True, smooth=True):
    """cylinder (or cone with r1) along glTF y (or x/z) from y0 to y1 centred at c=(x,z) (or (y,z)/(x,y))"""
    bm = bmesh.new(); r1 = r if r1 is None else r1
    ring0, ring1 = [], []
    for i in range(n):
        a = 2 * math.pi * i / n; ca, sa = math.cos(a), math.sin(a)
        if axis == "y": p0 = B(c[0] + r * ca, y0, c[1] + r * sa); p1 = B(c[0] + r1 * ca, y1, c[1] + r1 * sa)
        elif axis == "x": p0 = B(y0, c[0] + r * ca, c[1] + r * sa); p1 = B(y1, c[0] + r1 * ca, c[1] + r1 * sa)
        else: p0 = B(c[0] + r * ca, c[1] + r * sa, y0); p1 = B(c[0] + r1 * ca, c[1] + r1 * sa, y1)
        ring0.append(bm.verts.new(p0)); ring1.append(bm.verts.new(p1))
    for i in range(n):
        j = (i + 1) % n; f = bm.faces.new([ring0[i], ring0[j], ring1[j], ring1[i]]); f.smooth = smooth
    if cap: bm.faces.new(ring1); bm.faces.new(list(reversed(ring0)))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    o = new_obj(name, bm, material, static); project_uv(o); return o

def lathe(name, material, prof, c, y0, n=32, static=True, close_top=False):
    """profile [(r, h), ...] revolved around the vertical axis at c=(x,z), from y0"""
    bm = bmesh.new(); rings = []
    for (r, h) in prof:
        ring = []
        for i in range(n):
            a = 2 * math.pi * i / n; ring.append(bm.verts.new(B(c[0] + r * math.cos(a), y0 + h, c[1] + r * math.sin(a))))
        rings.append(ring)
    for k in range(len(rings) - 1):
        for i in range(n):
            j = (i + 1) % n
            if prof[k][0] == 0 and prof[k + 1][0] == 0: continue
            f = bm.faces.new([rings[k][i], rings[k][j], rings[k + 1][j], rings[k + 1][i]]); f.smooth = True
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    o = new_obj(name, bm, material, static); project_uv(o); return o

def set_vcol(o, rgb):
    me = o.data; a = me.color_attributes.get("Col") or me.color_attributes.new("Col", 'FLOAT_COLOR', 'CORNER')
    for d in a.data: d.color = (*rgb, 1)

def transform(o, loc=(0, 0, 0), ry=0.0, pivot=(0, 0, 0)):
    """rotate about glTF y through pivot, then translate by loc (glTF)"""
    M = Matrix.Translation(B(*loc)) @ Matrix.Translation(B(*pivot)) @ Matrix.Rotation(ry, 4, 'Z') @ Matrix.Translation(-B(*pivot))
    o.data.transform(M); o.data.update()

def join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs: o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]; bpy.ops.object.join(); objs[0].name = name; return objs[0]

def marker(name, pos, rot=(0, 0, 0), **props):
    e = bpy.data.objects.new(name, None); SC.collection.objects.link(e); e.location = B(*pos)
    e.rotation_mode = 'YXZ'
    # glTF Euler (rx, ry, rz) order YXZ -> Blender: rotation about gl y = Blender z, gl x = Blender x, gl z = Blender -y
    q = (Matrix.Rotation(rot[1], 4, 'Z') @ Matrix.Rotation(rot[0], 4, 'X') @ Matrix.Rotation(-rot[2], 4, 'Y')).to_quaternion()
    e.rotation_mode = 'QUATERNION'; e.rotation_quaternion = q
    for k, v in props.items(): e[k] = v
    return e

# the soft goods (#98 G4: fabrics, cloth simulations, the clothes) live in props_soft.py and use these helpers
sys.path.insert(0, R); import props_soft as PS; PS.bind(globals())

# ================================================================ the room shell
X0, X1, Z0, Z1 = -2.0, 2.0, -1.6, 1.6
WALL_T, H = 0.15, 2.39
IX, IZ = -1.9, -1.45                          # inner faces of the left (window) and back walls
box("floor", ["floor", "cut"], (X0, X1), (0, FY), (Z0, Z1), mat_by_face={"top": 0, "side": 1, "bottom": 1})
# walls: interior face = plaster, the cut ends and tops = dark
def wall_box(name, x, y, z):
    o = box(name, ["wall", "cut"], x, y, z)
    for p in o.data.polygons:
        n = p.normal; c = p.center
        interior = (n.x > 0.5 and abs(c.x - IX) < 1e-3) or (n.y < -0.5 and abs(-c.y - IZ) < 1e-3)   # +x face at IX, +z(gl) face at IZ
        p.material_index = 0 if interior else 1
    project_uv(o); return o
WZ0, WZ1, WY0, WY1 = -0.62, 0.90, 1.27, 2.10   # window opening (z range, y range)
wall_box("wall_back", (X0, X1), (0, H), (Z0, IZ))
wall_box("wall_l_below", (X0, IX), (0, WY0), (IZ, Z1))
wall_box("wall_l_above", (X0, IX), (WY1, H), (IZ, Z1))
wall_box("wall_l_a", (X0, IX), (WY0, WY1), (IZ, WZ0))
wall_box("wall_l_b", (X0, IX), (WY0, WY1), (WZ1, Z1))
# the window reveals (inside the opening) are plaster too
for o in [bpy.data.objects[n] for n in ("wall_l_below", "wall_l_above", "wall_l_a", "wall_l_b")]:
    for p in o.data.polygons:
        c = p.center; n = p.normal
        if (abs(c.z - WY0) < 1e-3 and n.z > 0.5 and WZ0 < -c.y < WZ1) or (abs(c.z - WY1) < 1e-3 and n.z < -0.5 and WZ0 < -c.y < WZ1) \
           or (abs(-c.y - WZ0) < 1e-3 and n.y > 0.5) or (abs(-c.y - WZ1) < 1e-3 and n.y < -0.5): p.material_index = 0
    project_uv(o)
# skirting boards
DOOR_X0, DOOR_X1 = 1.05, 1.85                 # door casing span on the back wall
props_hard.skirting(globals())

# ================================================================ window
props_hard.window(globals())
# curtain rod and two gathered linen curtains (pleats from a sine, wider at the hem)
ROD_Y = WY1 + 0.11
cyl("curtain_rod", "metal_dark", (ROD_Y, IX + 0.07), 0.009, WZ0 - 0.32, WZ1 + 0.36, n=12, axis="z")
for zc in (WZ0 - 0.32, WZ1 + 0.36):
    cyl("rod_end", "metal_dark", (ROD_Y, IX + 0.07), 0.016, zc - 0.012, zc + 0.012, n=12, axis="z")
    box("rod_bracket", "metal_dark", (IX, IX + 0.075), (ROD_Y - 0.006, ROD_Y + 0.006), (zc + (0.04 if zc < 0 else -0.04) - 0.006, zc + (0.04 if zc < 0 else -0.04) + 0.006), bevel=0.002, seg=1)
PS.curtains()                                    # two linen panels with pencil pleats and hems (props_soft.py)

# ================================================================ desk
props_hard.desk(globals())

# ================================================================ office chair (black fabric + black plastic)
props_hard.chair(globals())

# ================================================================ bed (storage bed, mattress, sheet, pillow, duvet)
props_hard.bed_frame(globals())
# the mattress with its fitted sheet, the pillow in its case and the duvet (a cloth simulation, turned back at the head
# end, box-quilted): props_soft.py
mattress = PS.mattress(); pillow = PS.pillow(); DUVET = PS.duvet(mattress, pillow)

# ================================================================ bookshelf with books
props_hard.bookshelf(globals())

# ================================================================ small fridge (two doors) with things on top
props_hard.fridge(globals())
# a photo strip stuck on the freezer door (poster atlas, region D)
def poster_quad(nm, x0, x1, y0, y1, zf, uv0, uv1, ry=0.0, pivot=None):
    bm = bmesh.new(); vs = [bm.verts.new(B(x, y, zf)) for (x, y) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    f = bm.faces.new(vs); o = new_obj(nm, bm, "posters"); uvl = o.data.uv_layers.new(name="UVMap")
    (u0, v0), (u1, v1) = uv0, uv1
    for li, (u, v) in zip(o.data.polygons[0].loop_indices, ((u0, v0), (u1, v0), (u1, v1), (u0, v1))): uvl.data[li].uv = (u, v)
    return o
poster_quad("photostrip", 0.60, 0.80, 1.06, 1.16, FZ1 + 0.0015, (683 / 1024, 1 - 512 / 512), (1.0, 1 - 341 / 512))

# ================================================================ door, casing, handle, hooks, switch, mat
props_hard.door(globals())
# hook rail on the door with a tote bag and a cap
box("hook_rail", "oak", (LX0 + 0.16, LX0 + 0.52), (1.70, 1.76), (IZ + 0.041, IZ + 0.056), bevel=0.003, seg=1)
for hx in (LX0 + 0.22, LX0 + 0.34, LX0 + 0.46):
    hk = cyl("hook", "metal_dark", (hx, 1.735), 0.006, IZ + 0.056, IZ + 0.10, n=10, axis="z")
    cyl("hook_tip", "metal_dark", (hx, IZ + 0.10), 0.006, 1.735, 1.765, n=10)
PS.tote(LX0 + 0.46)                                # a canvas tote by its handles on the right hook (the hoodie hangs on the left one)
# light switch by the door, doormat in front of it
box("switch_plate", "white", (0.93, 1.00), (1.17, 1.29), (IZ, IZ + 0.008), bevel=0.003, seg=2)
box("switch_rocker", "white", (0.945, 0.985), (1.19, 1.27), (IZ + 0.008, IZ + 0.013), bevel=0.002, seg=1)
dm = box("doormat", "painted", (1.08, 1.82), (FY, FY + 0.012), (-1.40, -0.98), bevel=0.004, seg=2); set_vcol(dm, srgb("#45403a"))

# ================================================================ rug, posters, air conditioner
rug = PS.rug()                                      # a wool pile with a bound edge
def framed(nm, xc, yc, w, h, uv0, uv1):
    F_ = 0.016
    box(nm + "_frame", "plastic_black", (xc - w / 2 - F_, xc + w / 2 + F_), (yc - h / 2 - F_, yc + h / 2 + F_), (IZ, IZ + 0.018), bevel=0.002, seg=1)
    poster_quad(nm, xc - w / 2, xc + w / 2, yc - h / 2, yc + h / 2, IZ + 0.0185, uv0, uv1)
framed("poster_a", -1.06, 1.97, 0.32, 0.48, (0, 0), (341 / 1024, 1))
framed("poster_b", -0.56, 1.86, 0.26, 0.39, (341 / 1024, 0), (682 / 1024, 1))
framed("poster_c", -1.60, 1.97, 0.24, 0.24, (683 / 1024, 1 - 341 / 512), (1.0, 1.0))
props_hard.aircon(globals())

# ================================================================ the prop sweep (#75): nothing inside a wall, nothing floating
# Every prop is registered with check(); sweep() measures its real (evaluated) vertices and reports each offender.
def world_box(objs):
    """world AABB of the evaluated meshes, in glTF coords: ([x0, y0, z0], [x1, y1, z1])"""
    dg = bpy.context.evaluated_depsgraph_get(); lo = [1e9] * 3; hi = [-1e9] * 3
    for o in objs:
        if o.type != 'MESH': continue
        ev = o.evaluated_get(dg); me = ev.to_mesh(); M = ev.matrix_world
        for v in me.vertices:
            w = M @ v.co
            for i, c in enumerate((w.x, w.z, -w.y)): lo[i] = min(lo[i], c); hi[i] = max(hi[i], c)
        ev.to_mesh_clear()
    return lo, hi
SWEEP = []
# room.html's hard-coded places (#63) that no prop may enter: (x, y, z) ranges, glTF
KEEP = {"his place at the window": ((-1.93, -1.30), (1.0, 1.95), (-0.24, 0.20)),       # he stands at (-1.56, -0.02), leaning on the sill
        "the delivery bag's spot": ((-0.70, -0.42), (DTOP + 0.004, DTOP + 0.40), (-0.93, -0.80)),  # BAG_AT (-0.56, -0.855)
        "the tea bottle's old spot": ((-1.43, -1.33), (DTOP + 0.004, DTOP + 0.30), (-0.95, -0.85)),
        # #87 (food): the dish left of the keyboard, the tea bottle in front of the mouse, and where he crouches at the bin
        # under the desk (-0.55, -1.22) to throw the empty dish away
        "the dish's spot": ((-1.48, -1.26), (DTOP + 0.004, DTOP + 0.25), (-1.02, -0.84)),       # DISH_AT, a pizza 4 cm further left
        "the tea bottle's spot": ((-0.87, -0.79), (DTOP + 0.004, DTOP + 0.30), (-0.89, -0.81)),  # BOTTLE_AT (-0.83, -0.85) r 3.2 cm, in front of the mouse
        "his crouch at the bin": ((-0.85, -0.25), (FY + 0.02, DTOP - 0.04), (-1.08, -0.55))}      # (under the desk top)
DOOR_SWING = (0.71, 0.9 + 0.15)                  # the leaf opens into the room (#82): 0.68 m plus 3 cm, up to 0.9 rad plus a margin
# room.html's walking graph (#82: NODES, LINKS and the standing anchors): every prop up to his height keeps WALK_R off
# each link (his shoulders and some air); flat things he walks over (rug, mats) and the plant (anchored by #63, its
# leaves above the sill path's knees) are left out
WALK_NODES = {"bs": (-0.36, -0.18), "ds": (-0.62, -0.35), "w": (0.15, -0.12), "c": (0.45, -0.35), "m": (0.35, 0.05), "d": (1.22, -0.92),
              "f": (0.15, 0.75), "sl": (-1.10, -0.06), "g": (-0.62, -0.08),
              "sill": (-1.56, -0.02), "doorway": (1.76, -0.98), "deskside": (-0.30, -0.40), "deskstand": (-0.68, -0.55)}
WALK_LINKS = [("bs", "ds"), ("bs", "w"), ("ds", "w"), ("w", "m"), ("w", "c"), ("m", "c"), ("c", "d"), ("m", "d"), ("w", "f"), ("m", "f"),
              ("bs", "g"), ("g", "sl"), ("w", "g"), ("sl", "sill"), ("d", "doorway"), ("ds", "deskstand"), ("bs", "deskside"), ("ds", "deskside")]
WALK_R, WALK_H = 0.22, 1.9
def walk_hit(lo, hi):
    """the first walking link whose capsule (radius WALK_R) meets the box's floor plan, or None"""
    for a, b in WALK_LINKS:
        (ax, az), (bx, bz) = WALK_NODES[a], WALK_NODES[b]; n = max(1, int(math.hypot(bx - ax, bz - az) / 0.02))
        for i in range(n + 1):
            x, z = ax + (bx - ax) * i / n, az + (bz - az) * i / n
            if math.hypot(x - min(max(x, lo[0]), hi[0]), z - min(max(z, lo[2]), hi[2])) < WALK_R: return f"{a}-{b}"
    return None
def check(name, objs, support, clear=0.0, minx=None, on_door=False, walk=True):
    """support: ("y", h) rests on a surface at height h (its lowest vertex within 2 mm of it); ("wall", None) hangs flat on
    the back wall (its rear within 2 mm of it); None: hangs from something (no support test). clear: the least distance
    from the window wall and the back wall. minx: the window wall's face where the prop stands (the sill reaches past it).
    Every prop also stays out of KEEP, off his walking graph (unless walk=False) and, unless on_door (it hangs on the
    leaf and swings with it), out of the door's swing"""
    SWEEP.append(dict(name=name, objs=[o for o in objs if o.type == 'MESH'], support=support, clear=clear, minx=IX if minx is None else minx, on_door=on_door, walk=walk))
def settle(objs, y):
    """drop modelled parts as one, so that their lowest vertex rests on y"""
    bpy.context.view_layer.update(); lo, _ = world_box(objs)
    for o in objs: o.data.transform(Matrix.Translation(B(0, y - lo[1], 0))); o.data.update()
def named(*names):
    return [o for o in STATIC if o.name in bpy.data.objects and o.name.split(".")[0] in names]
def sweep():
    bad, rows = 0, []
    for e in SWEEP:
        lo, hi = world_box(e["objs"]); cl = e["clear"]; tol = 0.0005; why = []
        if lo[0] < e["minx"] + cl - tol: why.append(f"{(e['minx'] + cl - lo[0]) * 1000:.1f} mm into the window wall" + (f" (keep {cl * 100:.0f} cm)" if cl else ""))
        if lo[2] < IZ + cl - tol: why.append(f"{(IZ + cl - lo[2]) * 1000:.1f} mm into the back wall" + (f" (keep {cl * 100:.0f} cm)" if cl else ""))
        if hi[0] > X1 or hi[2] > Z1: why.append("outside the floor")
        if lo[1] < FY - tol: why.append(f"{(FY - lo[1]) * 1000:.1f} mm under the floor")
        if hi[1] > H: why.append("through the ceiling")
        s = e["support"]; gap = None
        if s and s[0] == "y": gap = lo[1] - s[1]
        if s and s[0] == "wall": gap = lo[2] - IZ
        if gap is not None and abs(gap) > 0.002:
            why.append(f"{'floats' if gap > 0 else 'sinks'} {abs(gap) * 1000:.1f} mm {'above' if gap > 0 else 'into'} its support" if s[0] == "y"
                       else f"{'stands off' if gap > 0 else 'sinks into'} the wall by {abs(gap) * 1000:.1f} mm")
        for kn, (kx, ky, kz) in KEEP.items():                    # room.html's hard-coded spots (#63)
            if lo[0] < kx[1] and hi[0] > kx[0] and lo[1] < ky[1] and hi[1] > ky[0] and lo[2] < kz[1] and hi[2] > kz[0]: why.append(f"in {kn}")
        if not e["on_door"] and hi[1] > FY + 0.015 and lo[1] < LY1 and hi[2] > IZ and hi[0] > LX0:   # the door leaf's swing (a sector on the floor plan)
            for i in range(41):
                for j in range(1, 36):
                    a_ = DOOR_SWING[1] * i / 40; r_ = DOOR_SWING[0] * j / 35; x_, z_ = LX0 + r_ * math.cos(a_), IZ + r_ * math.sin(a_)
                    if lo[0] <= x_ <= hi[0] and lo[2] <= z_ <= hi[2]: break
                else: continue
                why.append("in the door's swing"); break
        if e["walk"] and hi[1] > FY + 0.02 and lo[1] < WALK_H:
            hit = walk_hit(lo, hi)
            if hit: why.append(f"on his way {hit}")
        sup = "-" if not s else f"y={s[1]:.3f}" if s[0] == "y" else "back wall"
        rows.append(f"{'ok ' if not why else 'BAD'} {e['name']:<20} x {lo[0]:+.3f}..{hi[0]:+.3f}  y {lo[1]:.3f}..{hi[1]:.3f}  z {lo[2]:+.3f}..{hi[2]:+.3f}"
                    f"  support {sup:<10} gap {'-' if gap is None else f'{gap * 1000:+.1f} mm':<9} {'; '.join(why)}")
        bad += bool(why)
    rep = "\n".join(rows) + f"\nSWEEP {len(SWEEP)} props, {bad} offenders"
    print(rep); open(f"{OUT}/sweep.txt", "w").write(rep + "\n"); return bad

# ================================================================ Poly Haven props (kept as their own meshes)
PROPS = []
def import_asset(k, loc, ry=0.0, scale=1.0, keep=None, drop=(), rest="bottom", centre=False):
    """rest: "bottom" puts the lowest vertex on loc's y (its support), "back" the rear face on loc's z (a wall), None
    leaves it as authored; centre: the kept meshes' footprint centred on loc's x, z (a file's origin can be far away)"""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=f"{AS}/{k}/{k}.gltf")
    new = [o for o in bpy.data.objects if o not in before]
    for o in list(new):
        if o.type == 'MESH' and (any(d in o.name for d in drop) or (keep and not any(kk in o.name for kk in keep))):
            bpy.data.objects.remove(o); new.remove(o)
    root = bpy.data.objects.new(k, None); SC.collection.objects.link(root)
    for o in new:
        if o.parent is None: o.parent = root
    root.location = B(*loc); root.rotation_euler = (0, 0, ry); root.scale = (scale,) * 3
    meshes = [o for o in new if o.type == 'MESH']
    bpy.context.view_layer.update(); lo, hi = world_box(meshes); d = [0.0, 0.0, 0.0]
    if centre: d[0] = loc[0] - (lo[0] + hi[0]) / 2; d[2] = loc[2] - (lo[2] + hi[2]) / 2
    if rest == "bottom": d[1] = loc[1] - lo[1]
    elif rest == "back": d[2] = loc[2] - lo[2]
    root.location = root.location + B(*d); bpy.context.view_layer.update()
    PROPS.extend(meshes); return root, new
# desk lamp: base at the back-left corner, its head reaching over towards the keyboard
lamp_root, lamp_objs = import_asset("desk_lamp_arm_01", (-1.74, DTOP, -1.30), ry=0.0, scale=0.8)
lm = [o for o in lamp_objs if o.type == 'MESH'][0]
def head_centre():
    me = lm.data; idx = [i for i, m in enumerate(me.materials) if m and m.name.endswith("_light")]
    ps = [lm.matrix_world @ p.center for p in me.polygons if p.material_index in idx]
    return sum(ps, Vector()) / len(ps) if ps else None
# turn the lamp so its head points at the keyboard
hc = head_centre(); base = lamp_root.location.copy()
d0 = Vector((hc.x - base.x, hc.y - base.y)); want = Vector((-1.25 - (-1.74), -(-1.05) - (1.30)))   # Blender xy towards (x=-1.25, z=-1.05)
ang = math.atan2(want.y, want.x) - math.atan2(d0.y, d0.x)
lamp_root.rotation_euler = (0, 0, ang); bpy.context.view_layer.update()
def off_walls(root, meshes, clear):
    """slide an imported prop out of the window wall and the back wall until every vertex keeps `clear` off them"""
    lo, _ = world_box(meshes); dx = max(0.0, IX + clear - lo[0]); dz = max(0.0, IZ + clear - lo[2])
    root.location = root.location + B(dx, 0, dz); bpy.context.view_layer.update(); return dx, dz
# its arm swings back behind the base: slide the lamp out until base and arm keep 1.5 cm off both walls
ldx, ldz = off_walls(lamp_root, [lm], 0.015)
LAMP_LO, LAMP_HI = world_box([lm])
print("LAMP moved by", round(ldx, 3), round(ldz, 3), "box", [round(v, 3) for v in LAMP_LO], [round(v, 3) for v in LAMP_HI])
hc = head_centre(); print("LAMP HEAD (blender)", tuple(round(v, 3) for v in hc))
marker("SURF_lamp", (hc.x, hc.z - 0.02, -hc.y))          # the page's lamp light: under the moved head
check("desk_lamp", [lm], ("y", DTOP), clear=0.01)
# plants: a philodendron on the floor by the window wall, a succulent on the desk
# (room.html anchors the plant at (-1.66, -0.36): it stays there, turned so that its leaves clear the window wall,
# which they reached 10 cm into at ry 0.8, and lean towards the desk, away from where he stands at the window)
pr, po = import_asset("potted_plant_02", (-1.66, FY, -0.36), ry=3 * math.pi / 2, scale=0.85, drop=("dirt",))
assert abs(pr.location.x + 1.66) < 1e-6 and abs(-pr.location.y + 0.36) < 1e-6, "the plant left its anchor"
check("floor_plant", po, ("y", FY), walk=False)
PLANT = (pr.location.x, -pr.location.y)
d = cyl("plant_soil", "painted", PLANT, 0.172, FY + 0.27, FY + 0.272, n=28); set_vcol(d, srgb("#2a2018"))
check("desk_succulent", import_asset("potted_plant_04", (-0.48, DTOP, -1.14), ry=0.3, scale=0.9)[1], ("y", DTOP))
check("wall_clock", import_asset("wall_clock", (0.68, 1.70, IZ), ry=0.0, scale=0.85, rest="back")[1], ("wall", None))
SILL_X = -1.912                                  # the window sill, in front of the sash track
check("alarm_clock", import_asset("alarm_clock_01", (-1.865, WY0, 0.62), ry=-math.pi / 2 + 0.35, scale=0.8)[1], ("y", WY0), minx=SILL_X)
check("shelf_carton", import_asset("cardboard_box_01", (0.10, STOP, -1.30), ry=0.1, scale=0.62)[1], ("y", STOP))
# the sticky notes: the file keeps them 0.45 m from its origin, so centre the stack itself; on top of the left speaker
# (the desk's free spots near its front edge belong to room.html's delivery bag and tea bottle)
SPK_TOP = DTOP + 0.20
check("sticky_notes", import_asset("office_notepads", (-1.52, SPK_TOP, -1.30), ry=0.37, keep=("sticky_stack",), centre=True)[1], ("y", SPK_TOP))

# ================================================================ lived-in things (#75): all modelled here (CC0), off his routes
# The free floor (room.html NODES/LINKS) runs from the desk and the bed edge to the window, the middle and the door; these
# stand in the corners it never reaches: the gap between desk and shelf, the bed's foot end, the front right, the doormat.
mat("pinboard", diff="pinboard.png", rough=0.8)
mat("cable", color=srgb("#1d1d20"), rough=0.5)

def blob(nm, material, c, r, n=16, static=True):
    """an ellipsoid centred at c with radii r (glTF axes)"""
    bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=n, v_segments=max(6, n // 2 + 2), radius=1.0)
    for v in bm.verts: v.co = B(c[0] + v.co.x * r[0], c[1] + v.co.z * r[1], c[2] - v.co.y * r[2])
    o = new_obj(nm, bm, material, static); [setattr(p, "use_smooth", True) for p in o.data.polygons]; project_uv(o); return o
def rod(nm, material, p0, p1, r, n=8, static=True):
    """a cylinder between two points (glTF)"""
    a, b = B(*p0), B(*p1); d = b - a
    o = cyl(nm, material, (0, 0), r, 0, d.length, n=n, static=static)
    o.data.transform(Matrix.Translation(a) @ d.to_track_quat('Z', 'Y').to_matrix().to_4x4()); o.data.update(); project_uv(o); return o
def torus(nm, material, c, R, r, axis="y", half=None, static=True, nmaj=28, nmin=8):
    """a ring around the glTF axis through c; half="up"/"down" keeps one half"""
    rot = {"y": (0, 0, 0), "z": (math.pi / 2, 0, 0), "x": (0, math.pi / 2, 0)}[axis]
    bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=r, major_segments=nmaj, minor_segments=nmin, location=B(*c), rotation=rot)
    o = bpy.context.active_object; o.name = nm; o.data.materials.append(MATS[material]); bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if half:
        bm = bmesh.new(); bm.from_mesh(o.data); cz = B(*c).z
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if (v.co.z < cz - 1e-4 if half == "up" else v.co.z > cz + 1e-4)], context='VERTS'); bm.to_mesh(o.data); bm.free()
    for p in o.data.polygons: p.use_smooth = True
    if static: STATIC.append(o)
    project_uv(o); return o
def cable(nm, pts, r=0.0028):
    """a smooth cable along the points (glTF), as a mesh: a NURBS curve stays inside its points' hull (never into a wall)"""
    cu = bpy.data.curves.new(nm, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = r; cu.bevel_resolution = 1; cu.resolution_u = 8
    sp = cu.splines.new('NURBS'); sp.points.add(len(pts) - 1); sp.order_u = 3; sp.use_endpoint_u = True
    for pt, p in zip(sp.points, pts): pt.co = (*B(*p), 1.0)
    co = bpy.data.objects.new(nm + "_curve", cu); SC.collection.objects.link(co); bpy.context.view_layer.update()
    me = bpy.data.meshes.new_from_object(co.evaluated_get(bpy.context.evaluated_depsgraph_get())); bpy.data.objects.remove(co)
    o = bpy.data.objects.new(nm, me); SC.collection.objects.link(o); me.materials.clear(); me.materials.append(MATS["cable"])
    for p in me.polygons: p.use_smooth = True
    STATIC.append(o); project_uv(o); return o
def puffy(nm, material, W, L, T_, nu=14, nv=14):
    bm = bmesh.new(); top, bot = [], []
    for j in range(nv + 1):
        rt, rb = [], []
        for i in range(nu + 1):
            u = i / nu * 2 - 1; v = j / nv * 2 - 1; h = T_ / 2 * ((1 - u ** 4) * (1 - v ** 4)) ** 0.5 + 0.004
            rt.append(bm.verts.new(Vector((u * W / 2, -v * L / 2, h)))); rb.append(bm.verts.new(Vector((u * W / 2, -v * L / 2, -h * 0.6))))
        top.append(rt); bot.append(rb)
    for j in range(nv):
        for i in range(nu):
            bm.faces.new([top[j][i], top[j][i + 1], top[j + 1][i + 1], top[j + 1][i]]); bm.faces.new([bot[j][i], bot[j + 1][i], bot[j + 1][i + 1], bot[j][i + 1]])
    edge = [(0, i) for i in range(nu)] + [(j, nu) for j in range(nv)] + [(nv, i) for i in range(nu, 0, -1)] + [(j, 0) for j in range(nv, 0, -1)]
    for k in range(len(edge)):
        (j0, i0), (j1, i1) = edge[k], edge[(k + 1) % len(edge)]
        try: bm.faces.new([top[j0][i0], bot[j0][i0], bot[j1][i1], top[j1][i1]])
        except ValueError: pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5); bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    o = new_obj(nm, bm, material); [setattr(p, "use_smooth", True) for p in o.data.polygons]; return o
def group(): return len(STATIC)
def since(n): return [o for o in STATIC[n:] if o.name in bpy.data.objects]
def vc(objs, h):
    for o in objs: set_vcol(o, srgb(h))

# --- a cork pinboard on the window wall above the desk (original drawing: a calendar page, notes, doodles); clear of the lamp
PB_Z0, PB_Z1 = -1.40, -1.04; PB_Y0 = max(1.72, LAMP_HI[1] + 0.03); PB_Y1 = PB_Y0 + (PB_Z1 - PB_Z0)
n0 = group()
box("pinboard_frame", "oak", (IX, IX + 0.02), (PB_Y0 - 0.015, PB_Y1 + 0.015), (PB_Z0 - 0.015, PB_Z1 + 0.015), bevel=0.003, seg=1)
bm = bmesh.new(); xf = IX + 0.022                      # 2 mm off the frame: no z-fighting from afar
vs = [bm.verts.new(B(xf, y, z)) for (z, y) in ((PB_Z1, PB_Y0), (PB_Z0, PB_Y0), (PB_Z0, PB_Y1), (PB_Z1, PB_Y1))]
bm.faces.new(vs); pbq = new_obj("pinboard", bm, "pinboard"); uvl = pbq.data.uv_layers.new(name="UVMap")
for li, uv in zip(pbq.data.polygons[0].loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1))): uvl.data[li].uv = uv
check("pinboard", since(n0), None)
assert PB_Y1 < WY1 + 0.05 or PB_Z1 < WZ0 - 0.06, "the pinboard runs into the window casing"

# --- a game controller behind the keyboard, between the monitor's foot and the right speaker
props_hard.controller(globals())

# --- manga on the floor in the gap between the desk and the bookshelf
props_hard.manga(globals())

# --- a wall hook above them; the headphones on it are their own node ("headphones", not in the static mesh or its AO),
# so a later change can take them off the hook and put them on his head (#68)
HP = (-0.24, 1.43)
n0 = group()
cyl("hp_hook", "metal_dark", HP, 0.006, IZ, IZ + 0.07, n=10, axis="z"); cyl("hp_hook_tip", "metal_dark", (HP[0], IZ + 0.07), 0.006, HP[1], HP[1] + 0.025, n=10)
cyl("hp_hook_plate", "metal_dark", HP, 0.016, IZ, IZ + 0.004, n=16, axis="z")
check("headphone_hook", since(n0), ("wall", None))
props_hard.headphones(globals())

# --- a hoodie on the door's left hook (the tote moved to the right one), hanging in front of the tote
HX = LX0 + 0.22
HOODIE = PS.hoodie(HX); check("hoodie", HOODIE, None, on_door=True)   # (it hangs on the leaf: it swings with it, see "hangers")

# --- a backpack on the floor, leaning on the bed's foot end
check("backpack", PS.backpack(), ("y", FY))

# --- the front right: a floor cushion (zabuton) and a small fan
CUSHION = PS.cushion(); check("cushion", CUSHION, ("y", FY))
props_hard.fan(globals())

# --- slippers by the floor cushion (the door's side is his place at the doorway and the leaf's swing, #82)
def slipper(x, z, ry):
    n0 = group(); L, W = 0.255, 0.095
    sole = cyl("slipper_sole", "painted", (0, 0), 1.0, 0.0, 0.016, n=24)
    sole.data.transform(Matrix.Diagonal((W / 2, L / 2, 1, 1))); sole.data.update()
    bm = bmesh.new(); na, nl = 10, 6; grid = []                  # the upper: a half tube over the front
    for j in range(nl + 1):
        t = j / nl; zz = -L * 0.48 + t * L * 0.42; ww = W / 2 * (0.62 + 0.38 * math.sin(math.pi * min(1, 0.25 + t * 0.75)))
        grid.append([bm.verts.new(B(ww * math.cos(math.pi * i / na), 0.012 + 0.04 * math.sin(math.pi * i / na) * (0.6 + 0.4 * t), zz)) for i in range(na + 1)])
    for j in range(nl):
        for i in range(na): bm.faces.new([grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]])
    up = new_obj("slipper_upper", bm, "painted"); m = up.modifiers.new("solid", "SOLIDIFY"); m.thickness = 0.006
    for p in up.data.polygons: p.use_smooth = True
    set_vcol(sole, srgb("#3c3c40")); set_vcol(up, srgb("#8d98a6"))
    parts = since(n0)
    for o in parts: transform(o, loc=(x, 0, z), ry=ry)
    settle(parts, FY); [project_uv(o) for o in parts]; return parts
check("slippers", slipper(0.80, 0.95, -math.pi / 2 + 0.05) + slipper(0.80, 1.06, -math.pi / 2 - 0.04), ("y", FY))   # toes towards the cushion

# --- a laundry pinch hanger on the curtain rod (socks and a hand towel), in front of the glass, above the bed's head end
n0 = group(); PH = (-1.745, 1.98, 0.45); PH_R = 0.15                # clear of his head at the window (#63)
torus("hanger_ring", "white", PH, PH_R, 0.004, axis="y", nmaj=36, nmin=6)
rod("hanger_hook", "white", (PH[0], PH[1], PH[2]), (IX + 0.07, ROD_Y - 0.008, PH[2]), 0.003)
torus("hanger_hook_tip", "white", (IX + 0.07, ROD_Y, PH[2]), 0.012, 0.0025, axis="z", half="up", nmaj=12, nmin=6)
for k in range(4): rod("hanger_spoke", "white", PH, (PH[0] + PH_R * math.cos(k * math.pi / 2 + 0.4), PH[1], PH[2] + PH_R * math.sin(k * math.pi / 2 + 0.4)), 0.0025)
clips = []
for k in range(8):
    a = k * math.pi / 4 + 0.2; cx, cz = PH[0] + PH_R * math.cos(a), PH[2] + PH_R * math.sin(a)
    clips.append((cx, cz)); c = box("hanger_clip", "painted", (cx - 0.006, cx + 0.006), (PH[1] - 0.045, PH[1] - 0.002), (cz - 0.004, cz + 0.004)); set_vcol(c, srgb("#7fb8d9"))
PS.socks_and_towel(clips, PH)                                    # two pairs of knitted socks and a terry hand towel on the clips
check("laundry_hanger", since(n0), None, minx=SILL_X)

# --- clothes (#98): jeans in a heap by the bed's foot, a T-shirt dropped on the floor cushion (a cloth simulation)
PS.clothes(CUSHION)

# --- a small cat figure on the window sill
n0 = group(); CAT = (-1.872, 0.40)                            # away from his hands on the sill (#63)
blob("cat_body", "painted", (0, 0.016, 0), (0.017, 0.016, 0.022), n=14); blob("cat_head", "painted", (0, 0.044, 0.012), (0.015, 0.014, 0.014), n=14)
for s in (-1, 1): cyl("cat_ear", "painted", (s * 0.008, 0.012), 0.005, 0.054, 0.064, r1=0.0005, n=8)
cyl("cat_tail", "painted", (0, -0.022), 0.004, 0.0, 0.03, n=8)
parts = since(n0); vc(parts, "#f4f0e8")
for o in parts: transform(o, loc=(CAT[0], 0, CAT[1]), ry=-math.pi / 2 - 0.4)
settle(parts, WY0); [project_uv(o) for o in parts]; check("cat_figure", parts, ("y", WY0), minx=SILL_X)

# --- under the desk: a wall socket, a power strip on the floor, cables up the back edge to the monitor and the lamp
n0 = group()
box("socket_plate", "white", (-1.47, -1.39), (0.34, 0.46), (IZ, IZ + 0.008), bevel=0.003, seg=1)
box("socket_plug", "white", (-1.445, -1.415), (0.38, 0.42), (IZ + 0.008, IZ + 0.03), bevel=0.004, seg=1)
check("socket", since(n0), ("wall", None))
n0 = group()
box("power_strip", "white", (-1.32, -1.02), (FY, FY + 0.038), (IZ + 0.012, IZ + 0.062), bevel=0.006, seg=2)
for i, px in enumerate((-1.27, -1.20, -1.13)): box("strip_plug", "plastic_black" if i else "white", (px - 0.016, px + 0.016), (FY + 0.038, FY + 0.06), (IZ + 0.022, IZ + 0.052), bevel=0.004, seg=1)
settle(since(n0), FY); check("power_strip", since(n0), ("y", FY))
n0 = group()
cable("cable_socket", [(-1.43, 0.40, IZ + 0.03), (-1.42, 0.30, IZ + 0.05), (-1.37, FY + 0.006, IZ + 0.05), (-1.32, FY + 0.018, IZ + 0.037)])
MB = (MON_C[0] - 0.02, MON_C[1] - 0.06, MON_C[2] - 0.07)                     # behind the monitor
cable("cable_monitor", [(-1.20, FY + 0.06, IZ + 0.037), (-1.18, 0.40, IZ + 0.006), (-1.14, DTOP - 0.06, IZ + 0.005), (-1.12, DTOP + 0.004, IZ + 0.012),
                         (-1.09, DTOP + 0.004, MB[2] - 0.08), (MB[0], DTOP + 0.06, MB[2] - 0.02), MB])
LB = (lamp_root.location.x, DTOP + 0.004, -lamp_root.location.y)
cable("cable_lamp", [(-1.13, FY + 0.06, IZ + 0.037), (-1.30, 0.42, IZ + 0.006), (-1.55, DTOP - 0.07, IZ + 0.005), (-1.60, DTOP + 0.004, IZ + 0.012), (LB[0] + 0.02, LB[1], LB[2] - 0.03)])
check("cables", since(n0), None)

props_hard.decals(globals())                       # #98 G5: dust, scuffs, scratches, stickers (their own node, no AO)

# ================================================================ the sweep (before anything is joined; `-- --sweep` stops here)
for nm, sup in (("mug", DTOP), ("pencup", DTOP), ("desk_book", DTOP), ("deskmat", DTOP), ("kb_body", DTOP + 0.003), ("mouse", DTOP + 0.003),
                ("mon_base", DTOP), ("spk_l_box", DTOP), ("spk_r_box", DTOP), ("bin", FY), ("cupnoodle", FTOP), ("tissues", FTOP),
                ("shelf_box", LEVELS[0] + T), ("doormat", FY), ("rug", FY)):
    check(nm, named(nm), ("y", sup))
for nm in ("curtain_a", "curtain_b"):
    check(nm, named(nm), ("y", WY0), minx=SILL_X)                # hanging just above the sill, not through it
for nm in ("poster_a_frame", "poster_b_frame", "poster_c_frame", "switch_plate", "ac_body"):
    check(nm, named(nm), ("wall", None))
bpy.context.view_layer.update()
if sweep():
    print("SWEEP FAILED: see the offenders above"); sys.exit(1)
if "--sweep" in sys.argv: sys.exit(0)

# ================================================================ finish: modifiers applied, static parts joined
bpy.context.view_layer.update()
for o in STATIC:
    bpy.context.view_layer.objects.active = o
    for m in list(o.modifiers): bpy.ops.object.modifier_apply(modifier=m.name)
for o in STATIC: project_uv(o)
props_hard.finish(globals())                       # #98 G5: every joined mesh carries the vertex-colour layer (edge wear)
# the things hanging on the door (hook rail, hooks, tote, hoodie) are one node of their own, "hangers", whose origin is
# the door's hinge as room.html builds its opening leaf (#82): the page turns it with the leaf
HANG = named("hook_rail", "hook", "hook_tip", "tote", "tote_strap") + [o for o in HOODIE if o.name in bpy.data.objects]
for o in HANG: STATIC.remove(o)
STATIC_OBJS = [o for o in STATIC if o.name in bpy.data.objects]
# tiny parts (keycaps, pens, wheels...) get no AO texels: flag them, so the atlas spends its pixels on big surfaces
for o in STATIC_OBJS:
    area = sum(p.area for p in o.data.polygons) * (o.matrix_world.to_scale()[0] ** 2)
    a = o.data.attributes.new("small", 'INT', 'FACE')
    for d in a.data: d.value = 1 if (area < 0.006 or o.get("ao_small")) else 0   # ao_small: thin things (piping, cords, straps) whose islands get no texel
room = join(STATIC_OBJS, "room_static"); room.data.name = "room_static"
# the headphones: one node of their own (origin where the band rests on the hook), like the chair
for o in hp:
    bpy.context.view_layer.objects.active = o
    for m in list(o.modifiers): bpy.ops.object.modifier_apply(modifier=m.name)
HPN = join(hp, "headphones"); HPN.data.name = "headphones"
HP_M = Matrix.Translation(B(HP[0], HP[1] + 0.006, HB_C[2]))
HPN.data.transform(HP_M.inverted()); HPN.matrix_world = HP_M
HANGN = join(HANG, "hangers"); HANGN.data.name = "hangers"
HANG_M = Matrix.Translation(B(LX0, FY + 0.008, IZ))
HANGN.data.transform(HANG_M.inverted()); HANGN.matrix_world = HANG_M
for i, m in enumerate(HANGN.data.materials):     # own copies (they move with the leaf); never named "door*": the page finds the leaf's by that
    c = m.copy(); c.name = "hang_" + m.name; HANGN.data.materials[i] = c
# lightmap UVs for the ambient occlusion bake
uv2 = room.data.uv_layers.new(name="AO")
room.data.uv_layers.active = uv2
small = [d.value for d in room.data.attributes["small"].data]
for p in room.data.polygons:                     # faces nobody looks at: undersides, the outside of the two walls
    n, c = p.normal, p.center
    if (n.z < -0.9 and c.z < FY + 0.06) or (n.x < -0.9 and c.x < X0 + 1e-3) or (n.y > 0.9 and c.y > -Z0 - 1e-3): small[p.index] = 1
for p in room.data.polygons: p.select = not small[p.index]
bpy.ops.object.select_all(action='DESELECT'); room.select_set(True); bpy.context.view_layer.objects.active = room
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.002, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
bpy.ops.uv.pack_islands(margin=0.002, rotate=True)
bpy.ops.object.mode_set(mode='OBJECT')
uv2 = room.data.uv_layers["AO"]                  # (re-fetched: edit mode rebuilt the mesh data)
for p in room.data.polygons:                     # keep a white corner (u, v > 0.988) for the tiny parts
    for li in p.loop_indices:
        uv2.data[li].uv = (0.995, 0.995) if small[p.index] else (uv2.data[li].uv[0] * 0.985, uv2.data[li].uv[1] * 0.985)
room.data.attributes.remove(room.data.attributes["small"])
room.data.uv_layers.active = room.data.uv_layers["AO"]       # (removing an attribute can move the active UV map)
print("bake UV", room.data.uv_layers.active.name, [u.name for u in room.data.uv_layers])
print("small faces", sum(small), "of", len(small))
print("STATIC tris", sum(len(p.vertices) - 2 for p in room.data.polygons), "materials", [m.name for m in room.data.materials])

# the chair's own AO atlas (small: one object)
cuv = CHAIR.data.uv_layers.new(name="AO")
bpy.ops.object.select_all(action='DESELECT'); CHAIR.select_set(True); bpy.context.view_layer.objects.active = CHAIR
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
CHAIR.data.uv_layers.active = CHAIR.data.uv_layers["AO"]
bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.004, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
bpy.ops.uv.pack_islands(margin=0.004, rotate=True)
bpy.ops.object.mode_set(mode='OBJECT')
CHAIR.data.uv_layers.active = CHAIR.data.uv_layers["AO"]
print("CHAIR tris", sum(len(p.vertices) - 2 for p in CHAIR.data.polygons), "materials", [m.name for m in CHAIR.data.materials],
      "pivot", tuple(round(v, 4) for v in CHAIR.location), "rot z", round(CHAIR.rotation_euler.z, 4))

def bake_ao(obj, size, path, hide):
    """AO of `obj` into its "AO" UV set, with the objects in `hide` left out of the render"""
    for o in hide: o.hide_render = True
    img = bpy.data.images.new(obj.name + "_ao", size, size, alpha=False, float_buffer=False); img.colorspace_settings.name = "Non-Color"
    for m in obj.data.materials:
        nt = m.node_tree; t = nt.nodes.new("ShaderNodeTexImage"); t.image = img; t.name = "BAKE"
        for n in nt.nodes: n.select = False
        t.select = True; nt.nodes.active = t
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True); bpy.context.view_layer.objects.active = obj
    obj.data.uv_layers.active = obj.data.uv_layers["AO"]
    bpy.ops.object.bake(type='AO', margin=6, uv_layer="AO")
    img.filepath_raw = path; img.file_format = 'PNG'; img.save()
    for m in obj.data.materials: m.node_tree.nodes.remove(m.node_tree.nodes["BAKE"])
    for o in hide: o.hide_render = False

if not NOBAKE:
    SC.render.engine = 'CYCLES'; SC.cycles.device = 'CPU'; SC.cycles.samples = int(os.environ.get("AO_SAMPLES", "128"))
    w = bpy.data.worlds.new("w"); SC.world = w; w.light_settings.distance = 0.35
    SC.render.bake.margin = 6; SC.render.bake.use_selected_to_active = False
    # the room without the chair (it moves: no chair-shaped AO footprint may stay behind on the floor; the real-time
    # shadows ground it), the props occlude; then the chair on its own (self-occlusion only, true wherever it stands)
    bake_ao(room, 2048, f"{OUT}/ao_raw.png", [CHAIR, HPN])        # (the headphones come off the hook: no footprint either)
    bake_ao(CHAIR, 512, f"{OUT}/ao_chair.png", [o for o in SC.objects if o is not CHAIR and o.type == 'MESH'])
for o in (room, CHAIR):
    o.data.uv_layers.active = o.data.uv_layers["UVMap"]; o.data.uv_layers["UVMap"].active_render = True
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=f"{OUT}/room_raw.glb", export_format='GLB', use_selection=False, export_extras=True, export_yup=True,
                          export_apply=True, export_texcoords=True, export_normals=True, export_tangents=False, export_materials='EXPORT',
                          export_image_format='AUTO', export_cameras=False, export_lights=False, export_vertex_color='MATERIAL')
bpy.ops.wm.save_as_mainfile(filepath=f"{OUT}/room.blend")
print("DONE")
