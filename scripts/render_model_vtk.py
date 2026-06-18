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
        else:
            size = vec(g.getElementsByTagName('box')[0].getAttribute('size'))
            if name == 'gps_link':            # draw VK-162 domed puck + cable (not the URDF box)
                tris, Tg = gps_shape_local(), world[name]
            elif name == 'ip55_box':
                tris, Tg = rounded_box(size, 0.012), Tv
            else:
                tris, Tg = box_tris(size), Tv
            tw = ((Tg[:3, :3] @ tris.reshape(-1, 3).T).T + Tg[:3, 3]).reshape(tris.shape)
            boxprim.append((tw, col, name))

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

def render(name, mesh_op, box_op, gps_op, frames=False, fov=False, fov_len=0.7):
    ren = vtk.vtkRenderer(); ren.SetBackground(1, 1, 1)
    if mesh_op > 0:
        for path, M, col in stls:
            if 'ouster' in path:
                for a in ouster_actors(path, M, mesh_op):
                    ren.AddActor(a)
            else:
                ren.AddActor(stl_actor(path, M, col, mesh_op))
    for tw, col, nm in boxprim:               # box solid/translucent/absent per box_op; gps per gps_op
        op = box_op if nm == 'ip55_box' else gps_op
        if op > 0:
            ren.AddActor(poly_actor(tw, (0.93, 0.93, 0.95) if nm == 'ip55_box' else col, op))
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
    d = VIEWDIR/np.linalg.norm(VIEWDIR)
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
# same three ideas, with the FOV frustums
render('sensor_fov_solid.png', 1.0, 1.0, 1.0, fov=True)
render('sensor_fov_translucent_frames.png', 0.28, 0.14, 0.5, frames=True, fov=True)
render('sensor_fov_frames_only.png', 0.0, 0.0, 0.0, frames=True, fov=True)
print('done')
