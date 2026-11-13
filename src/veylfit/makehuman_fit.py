from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image, ImageDraw
from geometry import render

TEMPLATES = Path(__file__).resolve().parent / 'templates'
SECTIONS = {'chest': .724, 'waist': .66, 'hips': .522}
LABELS = {'height': '身高', 'chest': '胸围', 'waist': '腰围', 'hips': '臀围'}
TOLERANCE_CM = .05


@dataclass
class FittedBody:
    glb: bytes
    preview: bytes
    measurements: dict
    mesh: dict


class Template:
    def __init__(self, gender):
        if gender not in ('male', 'female'):
            raise ValueError('请选择男性或女性模板。')
        raw = (TEMPLATES / f'{gender}.glb').read_bytes()
        magic, version, total, size, kind = struct.unpack_from('<4sIII4s', raw)
        if (magic, version, total, kind) != (b'glTF', 2, len(raw), b'JSON'):
            raise ValueError('MakeHuman 模板文件损坏。')
        self.doc = json.loads(raw[20:20+size])
        self.binary = bytearray(raw[28+size:])
        self.nodes = self.doc['nodes']
        self.skin = self.doc['skins'][0]
        self.attrs = self.doc['meshes'][0]['primitives'][0]['attributes']
        self.faces = self.array(self.doc['meshes'][0]['primitives'][0]['indices']).reshape(-1, 3)
        self.parents = {child:i for i,node in enumerate(self.nodes) for child in node.get('children', [])}
        self.world = {}
        for root in self.doc['scenes'][0]['nodes']:
            self.read_world(root, np.eye(4))
        self.arm_nodes = set()
        for i, node in enumerate(self.nodes):
            if node.get('name') in ('upperarm01.L', 'upperarm01.R'):
                stack = [i]
                while stack:
                    joint = stack.pop()
                    self.arm_nodes.add(joint)
                    stack.extend(self.nodes[joint].get('children', []))
        arm = np.isin(self.skin['joints'], list(self.arm_nodes))
        influence = np.zeros(len(self.array(self.attrs['POSITION'])))
        for key in self.attrs:
            if key.startswith('JOINTS_'):
                joints = self.array(self.attrs[key])
                weights = self.array(self.attrs[key.replace('JOINTS_', 'WEIGHTS_')])
                influence += np.sum(weights * arm[joints], axis=1)
        # Keep arms and hands out of the torso adjustment while allowing a soft shoulder transition.
        self.torso_influence = np.clip(1-influence, 0., 1.) ** 2

    def read_world(self, index, parent):
        node = self.nodes[index]
        local = np.array(node.get('matrix', np.eye(4).flatten())).reshape(4,4).T
        self.world[index] = parent @ local
        for child in node.get('children', []):
            self.read_world(child, self.world[index])

    def array(self, index):
        acc = self.doc['accessors'][index]
        view = self.doc['bufferViews'][acc['bufferView']]
        dtype = {5123:'<u2', 5125:'<u4', 5126:'<f4'}[acc['componentType']]
        cols = {'SCALAR':1, 'VEC3':3, 'VEC4':4, 'MAT4':16}[acc['type']]
        offset = view.get('byteOffset',0) + acc.get('byteOffset',0)
        return np.frombuffer(self.binary, dtype=dtype, offset=offset, count=acc['count']*cols).reshape(-1, cols)

    def encode(self, vertices, worlds):
        faces = self.faces
        tri = vertices[faces]
        normals = np.zeros_like(vertices)
        face_normals = np.cross(tri[:,1]-tri[:,0], tri[:,2]-tri[:,0])
        if np.min(np.linalg.norm(face_normals,axis=1)) <= 1e-12:
            raise ValueError('形体调整生成退化面，请检查输入围度。')
        for i in range(3):
            np.add.at(normals, faces[:,i], face_normals)
        norms = np.linalg.norm(normals, axis=1, keepdims=True)
        if np.any(norms < 1e-12):
            raise ValueError('形体调整后法线异常，请检查输入围度。')
        self.array(self.attrs['NORMAL'])[:] = normals / norms
        position = self.array(self.attrs['POSITION'])
        position[:] = vertices
        acc = self.doc['accessors'][self.attrs['POSITION']]
        acc.update(min=position.min(axis=0).tolist(),max=position.max(axis=0).tolist())
        for index in self.skin['joints']:
            parent = self.parents.get(index)
            local = np.linalg.solve(worlds[parent],worlds[index]) if parent is not None else worlds[index]
            self.nodes[index]['matrix'] = local.T.flatten().tolist()
        bind = np.linalg.inv(np.stack([worlds[i] for i in self.skin['joints']]))
        self.array(self.skin['inverseBindMatrices'])[:] = bind.transpose(0,2,1).reshape(-1,16)
        text = json.dumps(self.doc,separators=(',',':'),allow_nan=False).encode()
        text += b' ' * ((-len(text)) % 4)
        return (struct.pack('<4sII',b'glTF',2,28+len(text)+len(self.binary)) +
                struct.pack('<I4s',len(text),b'JSON') + text +
                struct.pack('<I4s',len(self.binary),b'BIN\0') + self.binary)


class Section:
    def __init__(self, vertices, faces, y):
        # Index intersections by the original mesh edge, so shared points match exactly.
        if np.any(np.abs(vertices[:,1]-y) < 1e-8):
            y += 1e-7
        self.y = y
        tri = vertices[faces,1] > y
        crossed = faces[tri.any(axis=1) & ~tri.all(axis=1)]
        graph = {}
        for face in crossed:
            edges = [tuple(sorted((int(a),int(b)))) for a,b in zip(face,np.roll(face,-1))
                     if (vertices[a,1]>y) != (vertices[b,1]>y)]
            if len(edges) == 2:
                a,b = edges
                graph.setdefault(a, set()).add(b)
                graph.setdefault(b, set()).add(a)
        components = []
        while graph:
            stack = [next(iter(graph))]
            parts = {}
            while stack:
                edge = stack.pop()
                if edge in graph:
                    parts[edge] = graph.pop(edge)
                    stack.extend(parts[edge])
            edges = list(parts)
            if not all(len(part)==2 for part in parts.values()):
                continue
            ids = {edge:i for i,edge in enumerate(edges)}
            links = [(ids[a],ids[b]) for a,neighbors in parts.items() for b in neighbors if ids[a]<ids[b]]
            ends = np.asarray(edges)
            a,b = vertices[ends[:,0]],vertices[ends[:,1]]
            t = (y-a[:,1])/(b[:,1]-a[:,1])
            points = a + t[:,None]*(b-a)
            components.append((ends,t,np.array(links),points))
        self.components = components
        center = [c for c in components if c[3][:,0].min()<0<c[3][:,0].max()]
        if center:
            self.torso = max(center,key=lambda c:len(c[0]))
        else:
            self.torso = None

    def girth(self, vertices):
        if self.torso is None:
            raise ValueError('无法识别闭合的躯干测量截面。')
        ends,t,links,_ = self.torso
        points = vertices[ends[:,0]] + t[:,None]*(vertices[ends[:,1]]-vertices[ends[:,0]])
        return float(np.linalg.norm(points[links[:,0]]-points[links[:,1]],axis=1).sum()*100)

    def has_gaps(self, minimum_loops):
        intervals = sorted((p[:,0].min(),p[:,0].max()) for _,_,_,p in self.components if np.ptp(p[:,0])>.015)
        return len(intervals)==minimum_loops and all(b[0]-a[1]>.003 for a,b in zip(intervals,intervals[1:]))


def profile(y, levels, height):
    distance = np.abs(y[:,None]-levels[None,:])/(.14*height)
    return np.where(distance<1.,.5*(1+np.cos(np.pi*distance)),0.)


def warp(points, influence, levels, height, params):
    moved = points.copy()
    factor = np.exp((profile(points[:,1], levels, height) @ params) * influence)
    moved[:,[0,2]] *= factor[:,None]
    return moved


def fit(gender, height_cm, girths):
    if not np.isfinite(height_cm) or not 110 <= height_cm <= 230:
        raise ValueError('身高请填写 110–230 cm。')
    if any(k not in SECTIONS or not np.isfinite(v) or not 45<=v<=190 for k,v in girths.items()):
        raise ValueError('实测胸腰臀围请填写 45–190 cm，或留空。')
    source = Template(gender)
    initial = source.array(source.attrs['POSITION']).astype(float)
    h = height_cm/100
    scale = h / np.ptp(initial[:,1])
    initial *= scale
    keys = [key for key in SECTIONS if key in girths]
    planes = {k:Section(initial,source.faces,p*h) for k,p in SECTIONS.items()}
    levels = np.array([planes[k].y for k in keys])
    target = np.array([girths[k] for k in keys])
    params = np.zeros(len(keys))
    def evaluate(p):
        v = warp(initial, source.torso_influence, levels, h, p)
        return v,np.array([planes[k].girth(v) for k in keys])
    if keys:
        for _ in range(15):
            _, current = evaluate(params)
            residual = target-current
            if np.max(np.abs(residual)) <= TOLERANCE_CM/2:
                break
            perturbations = .001*np.eye(len(keys))
            jac = np.column_stack([(evaluate(params+delta)[1]-current)/.001 for delta in perturbations])
            step = np.linalg.lstsq(jac,residual,rcond=None)[0]
            params = np.clip(params+np.clip(step,-.18,.18),np.log(.58),np.log(1.65))
    vertices,_ = evaluate(params)
    # Validate separations on the fitted mesh, rather than assuming the template pose survived.
    arms = [Section(vertices,source.faces,p*h).has_gaps(3) for p in (.61,.65)]
    legs = [Section(vertices,source.faces,p*h).has_gaps(2) for p in (.29,.36)]
    if not all(arms+legs):
        raise ValueError('调整后的网格没有通过臂躯或腿部间隙检查。请复查围度，或选更接近体型的模板。')
    world = {i:m.copy() for i,m in source.world.items()}
    ids = source.skin['joints']
    joints = np.array([world[i][:3,3]*scale for i in ids])
    moved_joints = warp(joints, np.array([i not in source.arm_nodes for i in ids]), levels, h, params)
    for i,j in zip(ids,moved_joints):
        world[i][:3,3] = j
    glb = source.encode(vertices, world)
    # Read back the packed float32 coordinates used by the exported GLB.
    exported = source.array(source.attrs['POSITION']).astype(float)
    measurements = {}
    for key in LABELS:
        if key=='height':
            actual, desired, level = float(np.ptp(exported[:,1])*100),height_cm,None
        else:
            actual = Section(exported,source.faces,planes[key].y).girth(exported)
            desired,level = girths.get(key),planes[key].y*100
        measurements[key] = {'input_cm':desired,'model_cm':round(actual,4),
                             'difference_cm':None if desired is None else round(actual-desired,4)+0.,
                             'section_height_cm':None if level is None else round(level,4)}
    matched = all(row['difference_cm'] is None or abs(row['difference_cm'])<=TOLERANCE_CM for row in measurements.values())
    preview = BytesIO()
    preview_scale = render(exported*(186/h), source.faces, preview)
    with Image.open(preview) as image:
        display = image.copy()
    draw = ImageDraw.Draw(display)
    for key,plane in planes.items():
        y = round(650 - (plane.y/h*186)*preview_scale)
        color = {'chest':'#6adac7','waist':'#f3c37e','hips':'#a5baff'}[key]
        for left in (0,760):
            draw.line((left+82,y,left+298,y),fill=color,width=2)
    result_image = BytesIO()
    display.save(result_image,format='PNG')
    return FittedBody(glb, result_image.getvalue(), measurements,
                      {'template':gender,'height_cm':height_cm,'joints':len(ids),'vertices':len(vertices),
                       'triangles':len(source.faces),'arm_angle_degrees':35,'arm_sections_clear':sum(arms),
                       'leg_sections_clear':sum(legs),'fit_within_0_05_cm':matched,
                       'mesh_length_unit':'m','pose':'A'})
