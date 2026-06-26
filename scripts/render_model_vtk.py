#!/usr/bin/env python3
"""Proper off-screen render of hitos_sensors.urdf.xacro with VTK (run via xvfb-run).
Real z-buffer + Phong lighting + depth-peeled transparency. 4 PNGs to media/:
solid, translucent+frames, frames-only, FOV overlap."""
import subprocess, os, struct
import xml.dom.minidom as MD
import numpy as np
import vtk
from vtk.util import numpy_support

WS = '/home/arvc/ros2_ws'
XACRO = f'{WS}/install/hitos_setup/share/hitos_setup/urdf/hitos_sensors.urdf.xacro'
PKG = {'hitos_setup': f'{WS}/src/hitos_setup'}
MEDIA = f'{WS}/src/hitos_setup/media'
SIZE = 2000
VIEWDIR = np.array([0.786, 0.491, 0.375])   # iso: cameras (+X) to the left, GPS back-right
BASLER_FOV, FLIR_FOV = (25.1, 18.9), (24.2, 18.4)
OUSTER_CROP = (-13.5, 14.0, -16.0, 7.0)
FRAMES = {'ip55_box': 'box', 'multiespectral_base': 'm_base', 'multiespectral_focal_base': 'focal',
          'os_sensor': 'os_sensor', 'visible_camera_optical_frame': 'vis_opt',
          'lwir_camera_optical_frame': 'lwir_opt', 'gps_link': 'gps'}

def vec(s, d=(0, 0, 0)):
    return np.array([float(x) for x in s.split()], float) if s else np.array(d, float)

def rpy_R(r, p, y):
    cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(y), np.sin(y)
    return (np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]]) @
            np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]]) @
            np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]]))

def Tf(xyz, rpy):
    M = np.eye(4); M[:3, :3] = rpy_R(*rpy); M[:3, 3] = xyz; return M

def resolve(fn):
    p = fn.replace('package://', '').split('/', 1); return os.path.join(PKG[p[0]], p[1])

def vmat(M):
    m = vtk.vtkMatrix4x4()
    for i in range(4):
        for j in range(4):
            m.SetElement(i, j, M[i, j])
    return m

def rounded_box(size, r=0.012, nc=7):
    sx, sy, sz = size; hx, hy = sx/2-r, sy/2-r; z0, z1 = -sz/2, sz/2
    pts = []
    for cx, cy, a0 in [(hx, hy, 0), (-hx, hy, 90), (-hx, -hy, 180), (hx, -hy, 270)]:
        for t in np.linspace(0, 90, nc):
            a = np.radians(a0+t); pts.append([cx+r*np.cos(a), cy+r*np.sin(a)])
    pts = np.array(pts); n = len(pts); T = []
    for i in range(n):
        j = (i+1) % n; p, q = pts[i], pts[j]
        T += [[[p[0],p[1],z0],[q[0],q[1],z0],[q[0],q[1],z1]], [[p[0],p[1],z0],[q[0],q[1],z1],[p[0],p[1],z1]],
              [[0,0,z0],[q[0],q[1],z0],[p[0],p[1],z0]], [[0,0,z1],[p[0],p[1],z1],[q[0],q[1],z1]]]
    return np.array(T, float)

def box_tris(size):
    sx, sy, sz = np.array(size)/2
    c = np.array([[x, y, z] for x in (-sx, sx) for y in (-sy, sy) for z in (-sz, sz)])
    f = [(0,1,3),(0,3,2),(4,6,7),(4,7,5),(0,4,5),(0,5,1),(2,3,7),(2,7,6),(0,2,6),(0,6,4),(1,5,7),(1,7,3)]
    return np.array([[c[i] for i in t] for t in f], float)

def cylinder_tris(radius, length, n=20):  # URDF <cylinder>: axis +Z, centred at origin
    z0, z1 = -length/2, length/2
    ring = [[radius*np.cos(a), radius*np.sin(a)] for a in np.linspace(0, 2*np.pi, n, endpoint=False)]
    T = []
    for i in range(n):
        j = (i+1) % n; p, q = ring[i], ring[j]
        T += [[[p[0],p[1],z0],[q[0],q[1],z0],[q[0],q[1],z1]], [[p[0],p[1],z0],[q[0],q[1],z1],[p[0],p[1],z1]],
              [[0,0,z0],[q[0],q[1],z0],[p[0],p[1],z0]], [[0,0,z1],[p[0],p[1],z1],[q[0],q[1],z1]]]
    return np.array(T, float)

def frustum(p0, p1, r0, r1, n=22, caps=True):   # tapered cylinder (cone if r1!=r0) between two pts
    p0 = np.array(p0, float); p1 = np.array(p1, float); ax = p1 - p0; ax = ax/np.linalg.norm(ax)
    ref = np.array([1., 0, 0]) if abs(ax[0]) < 0.9 else np.array([0, 1., 0])
    u = np.cross(ax, ref); u /= np.linalg.norm(u); v = np.cross(ax, u)
    R0 = [p0 + r0*(np.cos(t)*u + np.sin(t)*v) for t in np.linspace(0, 2*np.pi, n, endpoint=False)]
    R1 = [p1 + r1*(np.cos(t)*u + np.sin(t)*v) for t in np.linspace(0, 2*np.pi, n, endpoint=False)]
    T = []
    for i in range(n):
        j = (i+1) % n
        T += [[R0[i], R0[j], R1[j]], [R0[i], R1[j], R1[i]]]
        if caps: T += [[p0, R0[j], R0[i]], [p1, R1[i], R1[j]]]
    return np.array(T, float)

# Ricoh FL-CC1614-2M on the visible camera: barrel O29.5 x 33.2 mm + C-mount base + dark AR front
# element. Built in the visible_camera_frame (optical axis +X), in metres.
LENS_GREY = (0.20, 0.20, 0.22, 1); LENS_GLASS = (0.06, 0.09, 0.16, 1)
def lens_segments():
    return [
        (frustum([0, 0, 0],      [0.004, 0, 0],  0.0127,  0.0127),  LENS_GREY),    # C-mount base O25.4
        (frustum([0.004, 0, 0],  [0.030, 0, 0],  0.01475, 0.01475), LENS_GREY),    # barrel O29.5
        (frustum([0.030, 0, 0],  [0.0332, 0, 0], 0.01475, 0.01475), LENS_GREY),    # filter rim O29.5
        (frustum([0.0312, 0, 0], [0.0332, 0, 0], 0.0118,  0.0118),  LENS_GLASS),   # recessed front glass
    ]

# FLIR A68 (20 deg, integrated optics): gold germanium LWIR element + dark bezel. lwir_camera_frame, +X.
FLIR_BEZEL = (0.10, 0.10, 0.11, 1); FLIR_GE = (0.60, 0.46, 0.18, 1)
def flir_lens_segments():
    return [
        (frustum([0, 0, 0], [0.004, 0, 0],  0.013, 0.013), FLIR_BEZEL),   # bezel ring O26
        (frustum([0, 0, 0], [0.0055, 0, 0], 0.010, 0.010), FLIR_GE),      # germanium element O20 (slightly proud)
    ]

# Famatel 3012 "caja estanca IP55 con conos" — fully procedural box (replaces the plain URDF box
# visual in the render): inset base body + 10 domed conical cable entries + a faithful lid
# (overhanging slab, 4 countersunk corner screw bosses, IP55/IEC/logo embossing) + 2 mounting ears.
# Built in the ip55_box frame (origin=box bottom-centre, total height 0.095). Lid+ears authored by
# the lid-design multi-agent workflow against the real product photo. Dims 232x182x95 are FIXED.
def _cone_entry(c, nout, base_r=0.017, h=0.012, steps=5):   # large DOMED entry w/ concentric ring ridges
    c = np.array(c, float); nout = np.array(nout, float)/np.linalg.norm(nout); seg = h/steps
    return [frustum(c + nout*seg*k, c + nout*seg*(k+1),
                    base_r*(1-(k/steps)**2)**0.5, base_r*(1-(k/steps)**2)**0.5)
            for k in range(steps)]
def box_vents():     # 10 conos, TWO sizes. front/back: outer two LARGE + centre small. laterals: one LARGE + one small.
    z = 0.040; bx = 0.089; by = 0.114; SM = 0.018; LG = 0.024; out = []
    for nx in (1, -1):                         # front (+X) & back (-X): 3 each, pulled in (margin to edge + between)
        out += _cone_entry([nx*bx,  0.062, z], [nx, 0, 0], base_r=LG)
        out += _cone_entry([nx*bx,  0.000, z], [nx, 0, 0], base_r=SM)
        out += _cone_entry([nx*bx, -0.062, z], [nx, 0, 0], base_r=LG)
    for ny in (1, -1):                         # laterals (+-Y): big + small, pulled toward centre (margin to edge)
        out += _cone_entry([-0.032, ny*by, z], [0, ny, 0], base_r=LG)
        out += _cone_entry([ 0.036, ny*by, z], [0, ny, 0], base_r=SM)
    return out
def box_body():      # inset base body 0..0.075 (the thick lid overhangs it -> visible seam/lip)
    body = rounded_box([0.178, 0.228, 0.075], 0.011); body[:, :, 2] += 0.0375
    return [(body, (0.72, 0.72, 0.74, 1))]

def _shift(tris, dx=0.0, dy=0.0, dz=0.0):
    return np.asarray(tris, float) + np.array([dx, dy, dz])
def _rounded_tab(length, width, thick, r, nc=6):     # flat tab, outer end rounded, inner squared at X=0
    hw = width / 2.0; rr = min(r, hw)
    pts = [[0.0, hw], [0.0, -hw], [-(length - rr), -hw]]
    for t in np.linspace(-90, 90, nc):
        a = np.radians(t); pts.append([-(length - rr) - rr * np.cos(a), -rr * np.sin(a)])
    pts.append([-(length - rr), hw])
    pts = np.array(pts, float); n = len(pts); z0, z1 = -thick / 2, thick / 2; cx = -length / 2.0
    T = []
    for i in range(n):
        j = (i + 1) % n; p, q = pts[i], pts[j]
        T += [[[p[0],p[1],z0],[q[0],q[1],z0],[q[0],q[1],z1]], [[p[0],p[1],z0],[q[0],q[1],z1],[p[0],p[1],z1]],
              [[cx,0,z0],[q[0],q[1],z0],[p[0],p[1],z0]], [[cx,0,z1],[p[0],p[1],z1],[q[0],q[1],z1]]]
    return np.array(T, float)
def box_lid():       # SIMPLE thick lid: one overhang slab + 4 plain corner screws (just reads as "a lid")
    GREY_LID2 = (0.745, 0.745, 0.765, 1)
    z_bot = 0.075; h = 0.020                                                  # thick lid: 0.075..0.095
    lid = rounded_box([0.182, 0.232, h], 0.014); lid[:, :, 2] += z_bot + h / 2
    parts = [(lid, GREY_LID2)]
    z_surf = z_bot + h                                                        # 0.095 top face
    for sx in (-1, 1):                                                        # 4 plain recessed corner screws
        for sy in (-1, 1):
            scr = cylinder_tris(0.0055, 0.0020, n=28) + np.array([sx*0.081, sy*0.106, z_surf - 0.0008])
            parts.append((scr, (0.40, 0.40, 0.43, 1)))
    return parts
def box_ears():      # 2 flat mounting tabs at diagonal corners, each with a through-hole
    parts = []; EAR = (0.76, 0.76, 0.78, 1); HOLE = (0.34, 0.34, 0.37, 1)
    length = 0.019; width = 0.020; thick = 0.0050; body_x = 0.089; z_mid = 0.070
    def tab(sign_x, y):
        t = _rounded_tab(length, width, thick, r=width / 2 * 0.9)
        if sign_x > 0:
            t = t.copy(); t[:, :, 0] = -t[:, :, 0]
        t = _shift(t, sign_x * body_x, y, z_mid)
        hole_x = sign_x * (body_x + length - width / 2 * 0.85)
        hole = cylinder_tris(0.0042, thick + 0.0010, n=22); hole = _shift(hole, hole_x, y, z_mid)
        return [(t, EAR), (hole, HOLE)]
    parts += tab(+1, 0.072); parts += tab(-1, -0.072)
    return parts

def dome_tris(rx, ry, h, n=44, m=12):    # half-ellipsoid: base ellipse (rx,ry) at z=0, apex at z=h
    def P(phi, th):
        return [rx*np.cos(phi)*np.cos(th), ry*np.cos(phi)*np.sin(th), h*np.sin(phi)]
    T = []
    for i in range(m):
        ph0, ph1 = np.pi/2*i/m, np.pi/2*(i+1)/m
        for j in range(n):
            th0, th1 = 2*np.pi*j/n, 2*np.pi*(j+1)/n
            a, b, c, d = P(ph0, th0), P(ph0, th1), P(ph1, th1), P(ph1, th0)
            T += [[a, b, c], [a, c, d]]
    return np.array(T, float)

def tube(p0, p1, r, n=12):               # thin cylinder between two points (the GPS cable)
    p0, p1 = np.array(p0, float), np.array(p1, float); ax = p1 - p0; ax /= np.linalg.norm(ax)
    ref = np.array([1., 0, 0]) if abs(ax[0]) < 0.9 else np.array([0, 1., 0])
    u = np.cross(ax, ref); u /= np.linalg.norm(u); v = np.cross(ax, u)
    r0 = [p0 + r*(np.cos(t)*u + np.sin(t)*v) for t in np.linspace(0, 2*np.pi, n, endpoint=False)]
    r1 = [p1 + r*(np.cos(t)*u + np.sin(t)*v) for t in np.linspace(0, 2*np.pi, n, endpoint=False)]
    T = []
    for i in range(n):
        j = (i+1) % n; T += [[r0[i], r0[j], r1[j]], [r0[i], r1[j], r1[i]]]
    return np.array(T, float)

def gps_shape_local():                   # VK-162 G-Mouse: rounded-corner puck + gently domed top
    h1, hdome = 0.012, 0.004                                        # body 12 mm + 4 mm gentle crown
    body = rounded_box([0.038, 0.049, h1], 0.007); body[:, :, 2] += h1/2   # -> z[0,h1]
    dome = dome_tris(0.019, 0.0245, hdome); dome[:, :, 2] += h1            # -> z[h1, h1+hdome]
    return np.vstack([body, dome])

def pd_from_tris(tris):
    ntri = len(tris)
    verts = np.ascontiguousarray(tris.reshape(-1, 3), np.float64)
    pts = vtk.vtkPoints(); pts.SetData(numpy_support.numpy_to_vtk(verts, deep=1))
    offsets = np.arange(0, 3 * ntri + 1, 3, dtype=np.int64)         # VTK 9 cellarray: offsets + connectivity
    conn = np.arange(3 * ntri, dtype=np.int64)
    ca = vtk.vtkCellArray()
    ca.SetData(numpy_support.numpy_to_vtkIdTypeArray(offsets, deep=1),
               numpy_support.numpy_to_vtkIdTypeArray(conn, deep=1))
    pd = vtk.vtkPolyData(); pd.SetPoints(pts); pd.SetPolys(ca); return pd

def read_tris(path):
    d = open(path, 'rb').read(); n = struct.unpack('<I', d[80:84])[0]
    dt = np.dtype([('nrm', '<3f4'), ('v', '<3,3f4'), ('a', '<u2')])
    return np.frombuffer(d, dtype=dt, count=n, offset=84)['v'].astype(float)

def smooth(pd_or_port, is_port=False):
    nrm = vtk.vtkPolyDataNormals()
    nrm.SetInputConnection(pd_or_port) if is_port else nrm.SetInputData(pd_or_port)
    # Split normals at sharp edges so flat mechanical faces shade flat (SplittingOff smeared
    # the boxy mount into "collapsed" gradients).
    nrm.SetFeatureAngle(30); nrm.SplittingOn(); nrm.ConsistencyOn()
    nrm.ComputePointNormalsOn(); return nrm

# ---- parse URDF ----
dom = MD.parseString(subprocess.run(['xacro', XACRO], capture_output=True, text=True).stdout)
mat = {m.getAttribute('name'): vec(m.getElementsByTagName('color')[0].getAttribute('rgba'), (.5,.5,.5,1))
       for m in dom.getElementsByTagName('material')
       if m.parentNode.nodeName == 'robot' and m.getElementsByTagName('color')}
joints = []
for j in dom.getElementsByTagName('joint'):
    o = j.getElementsByTagName('origin')
    joints.append((j.getElementsByTagName('parent')[0].getAttribute('link'),
                   j.getElementsByTagName('child')[0].getAttribute('link'),
                   Tf(vec(o[0].getAttribute('xyz')) if o else [0,0,0], vec(o[0].getAttribute('rpy')) if o else [0,0,0])))
world = {'base_link': np.eye(4)}
for _ in range(len(joints)+1):
    for p, c, M in joints:
        if p in world and c not in world:
            world[c] = world[p] @ M

# visuals: stl meshes, the ip55 box, the gps box
stls, boxprim = [], []   # (path, Mfull, color) ; (tris_world, color, name)
for link in dom.getElementsByTagName('link'):
    name = link.getAttribute('name')
    if name not in world:
        continue
    for vis in link.getElementsByTagName('visual'):
        o = vis.getElementsByTagName('origin')
        Tv = world[name] @ (Tf(vec(o[0].getAttribute('xyz')), vec(o[0].getAttribute('rpy'))) if o else np.eye(4))
        g = vis.getElementsByTagName('geometry')[0]
        mn = vis.getElementsByTagName('material')
        col = mat.get(mn[0].getAttribute('name'), (.6,.6,.6,1)) if mn else (.6,.6,.6,1)
        if g.getElementsByTagName('mesh'):
            me = g.getElementsByTagName('mesh')[0]; sc = vec(me.getAttribute('scale'), (1,1,1))[0]
            stls.append((resolve(me.getAttribute('filename')), Tv @ np.diag([sc, sc, sc, 1.0]), col))
            continue
        if g.getElementsByTagName('cylinder'):     # e.g. the Ouster ventilation standoffs
            cy = g.getElementsByTagName('cylinder')[0]
            tris, Tg = cylinder_tris(float(cy.getAttribute('radius')), float(cy.getAttribute('length'))), Tv
        else:
            size = vec(g.getElementsByTagName('box')[0].getAttribute('size'))
            if name == 'gps_link':            # draw VK-162 domed puck + cable (not the URDF box)
                tris, Tg = gps_shape_local(), world[name]
            elif name == 'ip55_box':
                continue                       # box is drawn procedurally below (Famatel-style)
            else:
                tris, Tg = box_tris(size), Tv
        tw = ((Tg[:3, :3] @ tris.reshape(-1, 3).T).T + Tg[:3, 3]).reshape(tris.shape)
        boxprim.append((tw, col, name))

# procedural cosmetics: Ricoh lens on the visible camera + the 10 IP55 vent cones
def _place(W, tris):
    return ((W[:3, :3] @ tris.reshape(-1, 3).T).T + W[:3, 3]).reshape(tris.shape)
if 'visible_camera_frame' in world:
    for seg, col in lens_segments():
        boxprim.append((_place(world['visible_camera_frame'], seg), col, 'lens_visible'))
if 'lwir_camera_frame' in world:
    for seg, col in flir_lens_segments():
        boxprim.append((_place(world['lwir_camera_frame'], seg), col, 'lens_flir'))
if 'ip55_box' in world:
    Wb = world['ip55_box']
    for seg, col in box_body():
        boxprim.append((_place(Wb, seg), col, 'box_body'))
    for seg in box_vents():
        boxprim.append((_place(Wb, seg), (0.80, 0.80, 0.82, 1), 'box_vent'))
    for seg, col in box_lid():
        boxprim.append((_place(Wb, seg), col, 'box_lid'))
    # mounting ears removed (Enrique: "lengüeta con agujero perdida" — not wanted)

# ---- actor builders ----
def stl_actor(path, M, col, op):
    r = vtk.vtkSTLReader(); r.SetFileName(path)
    nrm = smooth(r.GetOutputPort(), True)
    mp = vtk.vtkPolyDataMapper(); mp.SetInputConnection(nrm.GetOutputPort())
    a = vtk.vtkActor(); a.SetMapper(mp); a.SetUserMatrix(vmat(M))
    pr = a.GetProperty(); pr.SetColor(*col[:3]); pr.SetOpacity(op); pr.SetInterpolationToPhong()
    pr.SetAmbient(0.25); pr.SetDiffuse(0.8); pr.SetSpecular(0.15); return a

def poly_actor(tris, col, op):
    nrm = smooth(pd_from_tris(tris))
    mp = vtk.vtkPolyDataMapper(); mp.SetInputConnection(nrm.GetOutputPort())
    a = vtk.vtkActor(); a.SetMapper(mp)
    pr = a.GetProperty(); pr.SetColor(*col[:3]); pr.SetOpacity(op); pr.SetInterpolationToPhong(); return a

def ouster_actors(path, M, op):
    """Two-tone Ouster via a per-point scalar + 2-colour LUT (no mesh splitting): optical
    window band (native Y in [-2,24] mm) black, rest aluminium."""
    r = vtk.vtkSTLReader(); r.SetFileName(path)
    nrm = smooth(r.GetOutputPort(), True); nrm.Update()
    pd = nrm.GetOutput()
    pts = numpy_support.vtk_to_numpy(pd.GetPoints().GetData())
    ymin, ymax = float(pts[:, 1].min()), float(pts[:, 1].max())
    # scalar = native Y per point; the LUT is black only inside the window band [ylow,yhigh].
    # InterpolateScalarsBeforeMapping makes the LUT cut per-pixel -> crisp FULL-circumference band
    # regardless of how big/sparse the window triangles are (per-cell centroid was patchy).
    ylow, yhigh = 24.0, 49.0
    pd.GetPointData().SetScalars(numpy_support.numpy_to_vtk(np.ascontiguousarray(pts[:, 1].copy()), deep=1))
    N = 256
    lut = vtk.vtkLookupTable(); lut.SetNumberOfTableValues(N); lut.SetTableRange(ymin, ymax)
    for i in range(N):
        y = ymin + (ymax - ymin) * i / (N - 1)
        lut.SetTableValue(i, *(((0.06, 0.06, 0.07, 1)) if ylow <= y <= yhigh else (0.78, 0.78, 0.80, 1)))
    lut.Build()
    mp = vtk.vtkPolyDataMapper(); mp.SetInputData(pd)
    mp.SetScalarModeToUsePointData(); mp.SetColorModeToMapScalars(); mp.InterpolateScalarsBeforeMappingOn()
    mp.SetLookupTable(lut); mp.SetScalarRange(ymin, ymax)
    a = vtk.vtkActor(); a.SetMapper(mp); a.SetUserMatrix(vmat(M))
    pr = a.GetProperty(); pr.SetOpacity(op); pr.SetInterpolationToPhong()
    pr.SetAmbient(0.25); pr.SetDiffuse(0.8); pr.SetSpecular(0.2)
    return [a]

def axes_actor(M, L=0.04):
    ax = vtk.vtkAxesActor(); ax.SetTotalLength(L, L, L); ax.SetUserMatrix(vmat(M))
    ax.AxisLabelsOff(); ax.SetShaftTypeToCylinder(); ax.SetCylinderRadius(0.04); ax.SetConeRadius(0.3)
    return ax

def label_actor(text, pos):
    t = vtk.vtkBillboardTextActor3D(); t.SetInput(text); t.SetPosition(*pos)
    t.SetDisplayOffset(10, 8)                         # nudge off the triad origin
    tp = t.GetTextProperty()
    tp.SetFontSize(34); tp.SetBold(1); tp.SetColor(0, 0, 0); tp.SetJustificationToLeft()
    tp.SetBackgroundColor(1, 1, 1); tp.SetBackgroundOpacity(0.85)   # near-solid, clearly legible
    tp.SetFrame(1); tp.SetFrameColor(0.4, 0.4, 0.4)
    return t

def frustum_actor(M, corners, col, D=0.7):
    apex = M[:3, 3]; far = (M[:3, :3] @ (corners*D).T).T + apex
    tris = [[apex, far[i], far[(i+1) % 4]] for i in range(4)]
    a = poly_actor(np.array(tris), col, 0.16); a.GetProperty().SetInterpolationToFlat()
    return a

def cam_corners(h, v):
    th, tv = np.tan(np.radians(h)/2), np.tan(np.radians(v)/2)
    return np.array([[th, tv, 1], [-th, tv, 1], [-th, -tv, 1], [th, -tv, 1]])
def oust_corners(h0, h1, v0, v1):
    out = []
    for h, v in [(h1, v1), (h0, v1), (h0, v0), (h1, v0)]:
        hr, vr = np.radians(h), np.radians(v)
        out.append([np.cos(vr)*np.cos(hr), np.cos(vr)*np.sin(hr), np.sin(vr)])
    return np.array(out)
FOVSET = [('visible_camera_optical_frame', cam_corners(*BASLER_FOV), (0, 0, 1)),
          ('lwir_camera_optical_frame', cam_corners(*FLIR_FOV), (0.85, 0, 0)),
          ('os_sensor', oust_corners(*OUSTER_CROP), (0, 0.55, 0))]

# Fixed world bounds so every image shares the same orthographic framing (aligned).
def _rig_points():
    pts = []
    for path, M, _ in stls:
        t = read_tris(path).reshape(-1, 3); pts.append((M[:3, :3] @ t.T).T + M[:3, 3])
    for tw, _, _ in boxprim:
        pts.append(tw.reshape(-1, 3))
    return np.vstack(pts)
RIGPTS = _rig_points()
RIG_C = (RIGPTS.max(0) + RIGPTS.min(0)) / 2
RIG_R = (RIGPTS.max(0) - RIGPTS.min(0)).max() / 2

def _fov_frame(fov_len):
    pts = [RIGPTS]
    for fr, cor, _ in FOVSET:
        if fr in world:
            M = world[fr]; pts.append((M[:3, :3] @ (cor*fov_len).T).T + M[:3, 3])
    a = np.vstack(pts)
    return (a.max(0)+a.min(0))/2, (a.max(0)-a.min(0)).max()/2

def render(name, mesh_op, box_op, gps_op, frames=False, fov=False, fov_len=0.7, viewdir=None):
    ren = vtk.vtkRenderer(); ren.SetBackground(1, 1, 1)
    if mesh_op > 0:
        for path, M, col in stls:
            if 'ouster' in path:
                for a in ouster_actors(path, M, mesh_op):
                    ren.AddActor(a)
            else:
                ren.AddActor(stl_actor(path, M, col, mesh_op))
    for tw, col, nm in boxprim:               # lens follows mesh_op; box+vents box_op; gps gps_op
        op = mesh_op if nm.startswith('lens') else (gps_op if nm == 'gps_link' else box_op)
        if op > 0:
            ren.AddActor(poly_actor(tw, col, op))
    if frames:
        for f, lab in FRAMES.items():
            if f in world:
                ren.AddActor(axes_actor(world[f])); ren.AddActor(label_actor(lab, world[f][:3, 3]))
    if fov:
        for fr, cor, col in FOVSET:
            if fr in world:
                ren.AddActor(frustum_actor(world[fr], cor, col, fov_len))
                ren.AddActor(axes_actor(world[fr], 0.05))
    lk = vtk.vtkLightKit(); lk.AddLightsToRenderer(ren)
    transparent = (0 < mesh_op < 1) or (0 < box_op < 1) or (0 < gps_op < 1) or fov
    rw = vtk.vtkRenderWindow(); rw.SetOffScreenRendering(1); rw.AddRenderer(ren); rw.SetSize(SIZE, SIZE)
    rw.SetMultiSamples(0)                       # swrast (xvfb) crashes with MSAA enabled
    rw.SetAlphaBitPlanes(1)                      # for a transparent (RGBA) background
    if transparent:
        ren.SetUseDepthPeeling(1); ren.SetMaximumNumberOfPeels(6); ren.SetOcclusionRatio(0.05)
    center, scale = (_fov_frame(fov_len)[0], _fov_frame(fov_len)[1]*1.12) if fov else (RIG_C, RIG_R*1.45)
    cam = ren.GetActiveCamera(); cam.ParallelProjectionOn()
    d = np.array(viewdir, float) if viewdir is not None else VIEWDIR; d = d/np.linalg.norm(d)
    cam.SetFocalPoint(*center); cam.SetPosition(*(center + d*3.0)); cam.SetViewUp(0, 0, 1)
    cam.SetParallelScale(scale); cam.SetClippingRange(1.0, 6.0)
    rw.Render()
    w2i = vtk.vtkWindowToImageFilter(); w2i.SetInput(rw)
    w2i.SetInputBufferTypeToRGBA(); w2i.ReadFrontBufferOff(); w2i.Update()
    wr = vtk.vtkPNGWriter(); wr.SetFileName(f'{MEDIA}/{name}'); wr.SetInputConnection(w2i.GetOutputPort()); wr.Write()
    print('wrote', name)

# rig: solid / translucent+frames / frames-only
render('sensor_solid.png', 1.0, 1.0, 1.0)
render('sensor_translucent_frames.png', 0.32, 0.16, 0.55, frames=True)
render('sensor_frames_only.png', 0.0, 0.0, 0.0, frames=True)
# 100% frontal view (camera at +X looking back -X): lens faces, Ouster, standoff air gap
render('sensor_front_solid.png', 1.0, 1.0, 1.0, viewdir=[1, 0, 0])
render('sensor_front_translucent_frames.png', 0.32, 0.16, 0.55, frames=True, viewdir=[1, 0, 0])
render('sensor_front_frames_only.png', 0.0, 0.0, 0.0, frames=True, viewdir=[1, 0, 0])
# same three ideas, with the FOV frustums
render('sensor_fov_solid.png', 1.0, 1.0, 1.0, fov=True)
render('sensor_fov_translucent_frames.png', 0.28, 0.14, 0.5, frames=True, fov=True)
render('sensor_fov_frames_only.png', 0.0, 0.0, 0.0, frames=True, fov=True)
print('done')
