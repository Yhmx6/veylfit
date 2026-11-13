from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import json
import math
import os
import sys

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'pose_assets'
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('MPLCONFIGDIR', str(Path(os.environ.get('LOCALAPPDATA',Path.home())) / 'Veylfit' / 'cache' / 'matplotlib'))

import numpy as np
from PIL import Image, ImageOps

PARTS = ('shoulder', 'elbow', 'wrist', 'hip', 'knee', 'ankle')
LABELS = {f'{s}_{part}': side + label for s, side in [('left', '左'), ('right', '右')]
          for part, label in zip(PARTS, ('肩', '肘', '腕', '髋', '膝', '踝'))}
LABELS.update(crown='头顶标尺', ground='脚底标尺')
INDEX = dict(zip(list(LABELS)[:12], (11, 13, 15, 23, 25, 27, 12, 14, 16, 24, 26, 28)))
LINES = [(f'{s}_{a}', f'{s}_{b}') for s in ('left', 'right')
         for a, b in [('shoulder', 'elbow'), ('elbow', 'wrist'), ('shoulder', 'hip'), ('hip', 'knee'), ('knee', 'ankle')]]
LINES += [('left_shoulder', 'right_shoulder'), ('left_hip', 'right_hip')]
SEGMENTS = {'upper_arm': ('shoulder', 'elbow'), 'forearm': ('elbow', 'wrist'),
            'thigh': ('hip', 'knee'), 'shin': ('knee', 'ankle')}
NAMES = {'shoulders': '双肩关节点距', 'hips': '双髋关节点距', 'upper_arm': '上臂', 'forearm': '前臂',
         'thigh': '大腿', 'shin': '小腿'}


@dataclass
class Capture:
    image: Image.Image
    points: dict
    original: dict
    visibility: dict
    edited: set = field(default_factory=set)
    roll: float = 0.0
    segmentation: object = None

    def set_point(self, key, x, y):
        w, h = self.image.size
        self.points[key] = (float(np.clip(x, 0, w - 1)), float(np.clip(y, 0, h - 1)))
        self.edited.add(key)

    def corrected(self):
        t = math.radians(self.roll)
        c, s = math.cos(t), math.sin(t)
        return {k: np.array([c*x + s*y, -s*x + c*y]) for k, (x, y) in self.points.items()}


def analyze(path, view):
    if path.stat().st_size > 30 * 1024**2:
        raise ValueError('照片超过 30 MiB。')
    return analyze_bytes(path.read_bytes(), view)


def analyze_bytes(raw_bytes, view, with_mask=False):
    import mediapipe as mp

    if len(raw_bytes) > 30 * 1024**2:
        raise ValueError('照片超过 30 MiB。')
    with Image.open(BytesIO(raw_bytes)) as source:
        if source.format not in ('JPEG', 'PNG', 'WEBP') or source.width * source.height > 25_000_000:
            raise ValueError('请选择 2500 万像素以内的 JPG、PNG 或 WebP 照片。')
        photo = ImageOps.exif_transpose(source).convert('RGB')
    photo.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    vision = mp.tasks.vision
    options = vision.PoseLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_buffer=(ASSETS / 'pose.task').read_bytes()),
                                          running_mode=vision.RunningMode.IMAGE, num_poses=2,
                                          output_segmentation_masks=with_mask)
    with vision.PoseLandmarker.create_from_options(options) as model:
        result = model.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(photo)))
    if len(result.pose_landmarks) != 1:
        raise ValueError('请使用一张清楚可见、头脚入镜的单人全身照。')
    raw = result.pose_landmarks[0]
    w, h = photo.size
    points = {k: (float(np.clip(raw[i].x * w, 0, w-1)), float(np.clip(raw[i].y * h, 0, h-1))) for k, i in INDEX.items()}
    visibility = {k: float(raw[i].visibility) for k, i in INDEX.items()}
    eye = min(raw[i].y * h for i in (2, 5, 7, 8))
    shoulder = np.mean([points[f'{s}_shoulder'][1] for s in ('left', 'right')])
    floor = max(raw[i].y * h for i in (29, 30, 31, 32))
    points['crown'] = (float(np.clip(raw[0].x * w, 0, w-1)), float(np.clip(eye - .46 * max(5, shoulder - eye), 0, h-1)))
    points['ground'] = (float(np.mean([points[f'{s}_ankle'][0] for s in ('left', 'right')])), float(np.clip(floor, 0, h-1)))
    visibility.update(crown=0.0, ground=0.0)
    roll = 0.
    if view == 'front':
        slopes = []
        for part in ('shoulder', 'hip'):
            a, b = sorted((points[f'left_{part}'], points[f'right_{part}']))
            if b[0] - a[0] > w * .06 and min(visibility[f'{s}_{part}'] for s in ('left', 'right')) >= .7:
                slopes.append(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])))
        if len(slopes) == 2 and abs(slopes[0] - slopes[1]) < 3 and max(map(abs, slopes)) <= 7:
            roll = round(sum(slopes) / 2, 1)
    mask = result.segmentation_masks[0].numpy_view().squeeze().copy() if with_mask and result.segmentation_masks else None
    return Capture(photo, points, points.copy(), visibility, roll=roll, segmentation=mask)


def measure(captures, height):
    if set(captures) != {'front', 'side'} or not math.isfinite(height) or not 110 <= height <= 230:
        raise ValueError('请导入正侧照片，并输入 110–230 cm 的身高。')
    axes, scale, warnings = {}, {}, []
    for name, cap in captures.items():
        axes[name] = cap.corrected()
        a = axes[name]
        pixels = a['ground'][1] - a['crown'][1]
        if pixels < cap.image.height * .2:
            raise ValueError('头顶和脚底标尺间距过小，请检查位置。')
        scale[name] = height / pixels
        if not {'crown', 'ground'}.issubset(cap.edited):
            warnings.append(f'{"正面" if name == "front" else "侧面"}仍有自动估计的身高标尺。')
    front, side = axes['front'], axes['side']
    out, sources = {}, {}
    for part, key in [('shoulder', 'shoulders'), ('hip', 'hips')]:
        out[key] = abs(front[f'left_{part}'][0] - front[f'right_{part}'][0]) * scale['front']
        sources[key] = '正面横向投影'
    for key, (a, b) in SEGMENTS.items():
        lengths, side_used = [], False
        for limb in ('left', 'right'):
            p, q = f'{limb}_{a}', f'{limb}_{b}'
            delta_f = (front[q] - front[p]) * scale['front']
            delta_s = (side[q] - side[p]) * scale['side']
            reliable_f = all(k in captures['front'].edited or captures['front'].visibility[k] >= .45 for k in (p, q))
            reliable_s = all(k in captures['side'].edited or captures['side'].visibility[k] >= .55 for k in (p, q))
            if reliable_f and reliable_s and abs(delta_f[1] - delta_s[1]) <= .045 * height:
                lengths.append(float(np.linalg.norm([delta_f[0], delta_s[0], (delta_f[1] + delta_s[1]) / 2])))
                side_used = True
            elif reliable_f:
                lengths.append(float(np.linalg.norm(delta_f)))
        if lengths:
            out[key] = sum(lengths) / len(lengths)
            sources[key] = '近似双视图' if side_used else '正面二维投影'
            if len(lengths) == 1:
                sources[key] += '（单侧）'
            bounds = {'upper_arm': (18, 37), 'forearm': (17, 33), 'thigh': (27, 52), 'shin': (26, 50)}
            lo, hi = bounds[key]
            if not lo <= out[key] * 186 / height <= hi:
                warnings.append(f'{NAMES[key]}超出模板范围，建模会限制该长度，请检查站姿和标尺。')
        else:
            out[key] = None
            sources[key] = '低可见性，生成时用模板比例'
            warnings.append(f'{NAMES[key]}缺少可靠关节点。')
    for key, part in [('shoulder_level', 'shoulder'), ('hip_level', 'hip')]:
        y = np.mean([front[f'{limb}_{part}'][1] for limb in ('left', 'right')])
        out[key] = float((front['ground'][1] - y) * scale['front'])
    return out, sources, warnings


def export(path, model, captures, data, sources, warnings, girths):
    records = {name: {'size_px': c.image.size, 'roll_degrees': c.roll,
                      'points': {k: {'xy_px': xy, 'source': 'manual' if k in c.edited else 'estimate',
                                     'model_visibility': c.visibility[k]} for k, xy in c.points.items()}}
               for name, c in captures.items()}
    meta = {'version': 2, 'dimensions_cm': data, 'dimension_sources': sources, 'girth_inputs_cm': girths,
            'model_measurements': model.measurements, 'views': records, 'warnings': warnings, 'mesh': model.mesh}
    with ZipFile(path, 'x', ZIP_DEFLATED) as z:
        z.writestr('Veylfit-A-pose.glb', model.glb)
        z.writestr('preview.png', model.preview)
        z.writestr('measurements.json', json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False))
