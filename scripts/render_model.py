#!/usr/bin/env python3
"""Headless render of hitos_sensors.urdf.xacro to separate PNGs (no display/X needed).
Outputs to src/hitos_setup/media/: solid (Lambertian-shaded), translucent+frames,
frames-only, FOV-overlap. The IP55 box is a white semi-transparent rounded solid; the
Ouster uses the real STL (FOV cone trimmed). View: cameras to the left, GPS back-right."""
import subprocess, struct, os
import xml.dom.minidom as MD
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection

WS = '/home/arvc/ros2_ws'
XACRO = f'{WS}/install/hitos_setup/share/hitos_setup/urdf/hitos_sensors.urdf.xacro'
PKG = {'hitos_setup': f'{WS}/src/hitos_setup'}
MEDIA = f'{WS}/src/hitos_setup/media'
CAP = 15000
ELEV, AZIM = 22, 32           # 90 deg from the original -58: cameras (+X) to the left, GPS back-right
FRAMES = {'ip55_box': 'box', 'multiespectral_base': 'm_base', 'multiespectral_focal_base': 'focal',
          'os_sensor': 'os_sensor', 'visible_camera_optical_frame': 'vis_opt',
          'lwir_camera_optical_frame': 'lwir_opt', 'gps_link': 'gps'}
BASLER_FOV, FLIR_FOV = (25.1, 18.9), (24.2, 18.4)
OUSTER_CROP = (-13.5, 14.0, -16.0, 7.0)
WHITE = (0.93, 0.93, 0.95)

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

def load_stl(path, scale, clip_r=None, decimate=True):
    d = open(path, 'rb').read(); n = struct.unpack('<I', d[80:84])[0]
    if 84 + n * 50 == len(d):
        dt = np.dtype([('n', '<3f4'), ('v', '<3,3f4'), ('a', '<u2')])
        tris = np.frombuffer(d, dtype=dt, count=n, offset=84)['v'].astype(float)
    else:
        verts = [list(map(float, ln.split()[1:4])) for ln in d.decode('latin1').splitlines()
                 if ln.strip().startswith('vertex')]
        tris = np.array(verts).reshape(-1, 3, 3)
    tris = tris * scale
    if clip_r is not None:
        tris = tris[(np.hypot(tris[:, :, 0], tris[:, :, 2]) < clip_r).all(1)]
    if decimate and len(tris) > CAP:
        tris = tris[np.linspace(0, len(tris) - 1, CAP).astype(int)]
    return tris

def box_tris(size):
    sx, sy, sz = np.array(size) / 2
    c = np.array([[x, y, z] for x in (-sx, sx) for y in (-sy, sy) for z in (-sz, sz)])
    f = [(0,1,3),(0,3,2),(4,6,7),(4,7,5),(0,4,5),(0,5,1),(2,3,7),(2,7,6),(0,2,6),(0,6,4),(1,5,7),(1,7,3)]
    return np.array([[c[i] for i in t] for t in f], float)

def rounded_box(size, r=0.012, nc=5):    # white IP55 box: rounded vertical edges, centred at origin
    sx, sy, sz = size; hx, hy = sx/2 - r, sy/2 - r; z0, z1 = -sz/2, sz/2
    pts = []
    for cx, cy, a0 in [(hx, hy, 0), (-hx, hy, 90), (-hx, -hy, 180), (hx, -hy, 270)]:
        for t in np.linspace(0, 90, nc):
            ang = np.radians(a0 + t); pts.append([cx + r*np.cos(ang), cy + r*np.sin(ang)])
    pts = np.array(pts); n = len(pts); T = []
    for i in range(n):
        j = (i + 1) % n; p, q = pts[i], pts[j]
        T += [[[p[0],p[1],z0],[q[0],q[1],z0],[q[0],q[1],z1]], [[p[0],p[1],z0],[q[0],q[1],z1],[p[0],p[1],z1]],
              [[0,0,z0],[q[0],q[1],z0],[p[0],p[1],z0]], [[0,0,z1],[p[0],p[1],z1],[q[0],q[1],z1]]]
    return np.array(T, float)

def xform(T, a):
    return ((T[:3, :3] @ a.reshape(-1, 3).T).T + T[:3, 3]).reshape(a.shape)

def shaded(tris, base):
    nrm = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(nrm, axis=1, keepdims=True); ln[ln == 0] = 1
    Lt = np.array([0.35, 0.25, 0.9]); Lt /= np.linalg.norm(Lt)
    inten = 0.4 + 0.6 * np.abs((nrm / ln) @ Lt)
    return np.clip(np.array(base[:3])[None, :] * inten[:, None], 0, 1)

dom = MD.parseString(subprocess.run(['xacro', XACRO], capture_output=True, text=True).stdout)
mat = {m.getAttribute('name'): vec(m.getElementsByTagName('color')[0].getAttribute('rgba'), (.5,.5,.5,1))
       for m in dom.getElementsByTagName('material')
       if m.parentNode.nodeName == 'robot' and m.getElementsByTagName('color')}
joints = []
for j in dom.getElementsByTagName('joint'):
    o = j.getElementsByTagName('origin')
    joints.append((j.getElementsByTagName('parent')[0].getAttribute('link'),
                   j.getElementsByTagName('child')[0].getAttribute('link'),
                   Tf(vec(o[0].getAttribute('xyz')) if o else [0,0,0],
                      vec(o[0].getAttribute('rpy')) if o else [0,0,0])))
world = {'base_link': np.eye(4)}
for _ in range(len(joints) + 1):
    for p, c, M in joints:
        if p in world and c not in world:
            world[c] = world[p] @ M

faces, boxfaces = [], []     # (tris,rgba) meshes ; (tris,) white box
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
            me = g.getElementsByTagName('mesh')[0]
            fn = me.getAttribute('filename'); sc = vec(me.getAttribute('scale'), (1,1,1))[0]
            tris = load_stl(resolve(fn), sc, clip_r=0.05, decimate=False) if 'os0' in fn else load_stl(resolve(fn), sc)
            faces.append((xform(Tv, tris), col))
        elif name == 'ip55_box':
            boxfaces.append(xform(Tv, rounded_box(vec(g.getElementsByTagName('box')[0].getAttribute('size')))))
        else:
            faces.append((xform(Tv, box_tris(vec(g.getElementsByTagName('box')[0].getAttribute('size')))), col))

allv = np.vstack([t.reshape(-1, 3) for t, _ in faces] + [b.reshape(-1, 3) for b in boxfaces])
ctr = (allv.max(0) + allv.min(0)) / 2; rng = (allv.max(0) - allv.min(0)).max() / 2 * 1.05
L3 = 0.035

def new_ax(rad=rng, center=ctr):
    fig = plt.figure(figsize=(10, 10)); ax = fig.add_subplot(111, projection='3d')
    ax.set_xlim(center[0]-rad, center[0]+rad); ax.set_ylim(center[1]-rad, center[1]+rad); ax.set_zlim(center[2]-rad, center[2]+rad)
    ax.set_box_aspect((1, 1, 1)); ax.view_init(elev=ELEV, azim=AZIM)
    ax.set_xlabel('X fwd'); ax.set_ylabel('Y left'); ax.set_zlabel('Z up')
    return fig, ax

def add_box(ax, alpha):
    for b in boxfaces:
        ax.add_collection3d(Poly3DCollection(b, facecolor=WHITE, edgecolor='none', alpha=alpha))

def add_frames(ax, length=L3):
    for f, lab in FRAMES.items():
        if f not in world:
            continue
        o = world[f][:3, 3]
        for c, a in zip('rgb', world[f][:3, :3].T):
            ax.quiver(*o, *(a * length), color=c, linewidth=2.4)
        ax.text(*o, ' ' + lab, fontsize=9, color='k')

def save(fig, name):
    fig.tight_layout(); fig.savefig(f'{MEDIA}/{name}', dpi=150); plt.close(fig); print('wrote', name)

# 1) solid
fig, ax = new_ax()
for tris, col in faces:
    ax.add_collection3d(Poly3DCollection(tris, facecolors=shaded(tris, col), edgecolor='none'))
add_box(ax, 0.38); ax.set_title('HITOS rig - solid', fontsize=13)
save(fig, 'sensor_solid.png')

# 2) translucent + frames
fig, ax = new_ax()
for tris, col in faces:
    ax.add_collection3d(Poly3DCollection(tris, facecolor=col[:3], edgecolor='none', alpha=0.2))
add_box(ax, 0.10); add_frames(ax)
ax.set_title('HITOS rig - translucent + frames (X=red fwd, Y=green left, Z=blue up)', fontsize=11)
save(fig, 'sensor_translucent_frames.png')

# 3) frames only
fig, ax = new_ax()
add_box(ax, 0.07); add_frames(ax)
ax.set_title('HITOS rig - frames only', fontsize=13)
save(fig, 'sensor_frames_only.png')

# 4) FOV overlap
D = 1.2
def cam_corners(h, v):
    th, tv = np.tan(np.radians(h)/2), np.tan(np.radians(v)/2)
    return np.array([[th, tv, 1], [-th, tv, 1], [-th, -tv, 1], [th, -tv, 1]])
def oust_corners(h0, h1, v0, v1):
    out = []
    for h, v in [(h1, v1), (h0, v1), (h0, v0), (h1, v0)]:
        hr, vr = np.radians(h), np.radians(v)
        out.append([np.cos(vr)*np.cos(hr), np.cos(vr)*np.sin(hr), np.sin(vr)])
    return np.array(out)
fovset = [('Basler', world.get('visible_camera_optical_frame'), cam_corners(*BASLER_FOV), (0, 0, 1)),
          ('FLIR', world.get('lwir_camera_optical_frame'), cam_corners(*FLIR_FOV), (.85, 0, 0)),
          ('Ouster crop', world.get('os_sensor'), oust_corners(*OUSTER_CROP), (0, .55, 0))]
fv = [(T[:3, :3] @ (c*D).T).T + T[:3, 3] for _, T, c, _ in fovset if T is not None]
av = np.vstack([allv] + fv); c2 = (av.max(0)+av.min(0))/2; r2 = (av.max(0)-av.min(0)).max()/2*1.05
fig, ax = new_ax(r2, c2)
add_box(ax, 0.10)
for name, T, corners, col in fovset:
    if T is None:
        continue
    apex = T[:3, 3]; far = (T[:3, :3] @ (corners*D).T).T + apex
    polys = [[apex, far[i], far[(i+1) % 4]] for i in range(4)] + [list(far)]
    ax.add_collection3d(Poly3DCollection(polys, facecolor=col, edgecolor=col, alpha=0.10, linewidths=0.9))
    ax.text(*far.mean(0), ' ' + name, color=col, fontsize=10)
for f in ('visible_camera_optical_frame', 'lwir_camera_optical_frame', 'os_sensor'):
    o = world[f][:3, 3]
    for c, a in zip('rgb', world[f][:3, :3].T):
        ax.quiver(*o, *(a*0.04), color=c, linewidth=1.8)
ax.set_title('FOV overlap - Basler(blue) FLIR(red) Ouster-crop(green), 1.2 m', fontsize=12)
save(fig, 'sensor_fov.png')
print('done')
