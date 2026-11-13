"""Local, pixel-preserving face reference preparation. No network or generative edits."""
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json
import math

import engine  # Loads the bundled local runtime before numpy/Pillow/MediaPipe.
import numpy as np
from PIL import Image, ImageOps

MODEL = Path(__file__).parent / 'face_assets' / 'blaze_face_short_range.tflite'
MODEL_SHA256 = 'b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f'
SCHEMA = 'fitlogic.face-reference.v1'


@dataclass
class FacePhoto:
    image: Image.Image
    candidates: list
    notice: str = ''


def clean_rgb(image):
    # Construct a new image so source EXIF, comments and ICC data cannot propagate.
    rgb = image.convert('RGB')
    return Image.frombytes('RGB', rgb.size, rgb.tobytes())


def load_photo(path):
    path = Path(path)
    if path.stat().st_size > 30 * 1024**2:
        raise ValueError('照片超过 30 MiB，请先选择较小的版本。')
    with Image.open(path) as src:
        if src.format not in ('JPEG', 'PNG', 'WEBP') or src.width * src.height > 25_000_000:
            raise ValueError('请选择 2500 万像素以内的 JPG、PNG 或 WebP。')
        photo = clean_rgb(ImageOps.exif_transpose(src))
    if min(photo.size) < 32:
        raise ValueError('照片太小，请选择清楚的原照。')
    try:
        candidates = detect(photo)
        notice = '' if candidates else '未检测到脸部。侧脸可能漏检，请在原图上手动画框。'
    except Exception:
        # A missing/broken model must not prevent truthful manual preparation.
        candidates, notice = [], '本地自动检测不可用，请手动画框；本次不标记为自动识别。'
    return FacePhoto(photo, candidates, notice)


def intersection_over_union(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1-x0) * max(0, y1-y0)
    return inter / max(1, (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter)


def detect(photo):
    import mediapipe as mp
    blob = MODEL.read_bytes()
    if hashlib.sha256(blob).hexdigest() != MODEL_SHA256:
        raise ValueError('Face detector model checksum mismatch')
    options = mp.tasks.vision.FaceDetectorOptions(
        base_options=mp.tasks.BaseOptions(model_asset_buffer=blob),
        running_mode=mp.tasks.vision.RunningMode.IMAGE, min_detection_confidence=.60)
    boxes = []
    with mp.tasks.vision.FaceDetector.create_from_options(options) as detector:
        def scan(region):
            tile = photo.crop(region)
            native_w, native_h = tile.size
            tile.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(tile)))
            sx, sy = native_w/tile.width, native_h/tile.height
            for item in result.detections:
                b = item.bounding_box
                try:
                    bounds = clamp_box((region[0]+b.origin_x*sx, region[1]+b.origin_y*sy,
                                        region[0]+(b.origin_x+b.width)*sx,
                                        region[1]+(b.origin_y+b.height)*sy), photo.size, 1)
                except ValueError:
                    continue
                boxes.append({'box': bounds, 'confidence': float(item.categories[0].score)})
        w, h = photo.size
        scan((0, 0, w, h))
        # Overlapping tiles improve small-face detection in large photos and groups.
        if max(w, h) > 800:
            tw, th = round(w*.65), round(h*.65)
            for x, y in ((0,0), (w-tw,0), (0,h-th), (w-tw,h-th)):
                scan((x,y,x+tw,y+th))
        if not boxes and min(w,h) >= 128:
            # A full-body image can have a face too small for the full-frame model.
            tw,th=round(w*.35),round(h*.35)
            for iy in range(4):
                for ix in range(4):
                    x,y=round(ix*(w-tw)/3),round(iy*(h-th)/3)
                    scan((x,y,x+tw,y+th))
    unique = []
    for item in sorted(boxes, key=lambda c: -c['confidence']):
        if not any(intersection_over_union(item['box'], other['box']) > .25 for other in unique):
            unique.append(item)
    return sorted(unique, key=lambda c: (c['box'][0], c['box'][1]))


def clamp_box(box, size, minimum=16):
    if len(box) != 4 or not all(math.isfinite(float(v)) for v in box):
        raise ValueError('裁切坐标无效。')
    w, h = size
    x0, x1 = sorted((max(0, min(w, round(box[0]))), max(0, min(w, round(box[2])))))
    y0, y1 = sorted((max(0, min(h, round(box[1]))), max(0, min(h, round(box[3])))))
    if x1-x0 < minimum or y1-y0 < minimum:
        raise ValueError('裁切框太小，请框住完整头部。')
    return (x0, y0, x1, y1)


def suggested_crop(face, size):
    x0,y0,x1,y1 = face
    w,h = x1-x0,y1-y0
    return clamp_box((x0-.38*w, y0-.65*h, x1+.38*w, y1+.30*h), size)


def crop(photo, box):
    return clean_rgb(photo.image.crop(clamp_box(box, photo.image.size)))


def warnings(photo, box, selected=None):
    bounds = clamp_box(box, photo.image.size)
    result = []
    image = crop(photo, bounds)
    if min(image.size) < 256:
        result.append('裁切图短边不足 256 像素，建议补拍近距离照片；放大不能补回细节。')
    if bounds[0] == 0 or bounds[1] == 0 or bounds[2] == photo.image.width or bounds[3] == photo.image.height:
        result.append('裁切框触及原图边缘，请检查头发、鼻尖和下巴是否完整。')
    small = image.copy()
    small.thumbnail((256,256))
    gray = np.asarray(small.convert('L'), dtype=float)
    if gray.mean() < 40 or gray.mean() > 225:
        result.append('画面可能过暗或过亮，请检查面部细节。')
    for i, item in enumerate(photo.candidates):
        a,b,c,d = item['box']
        if i != selected and bounds[0] < (a+c)/2 < bounds[2] and bounds[1] < (b+d)/2 < bounds[3]:
            result.append('框内还有其他检测到的人脸，请检查并缩小范围。')
            break
    return result


def export(path, entries, same_person):
    if not same_person:
        raise ValueError('请确认正面和侧面参考来自同一人。')
    if set(entries) != {'front','side'}:
        raise ValueError('需要正面和侧面两张参考图。')
    records, images = {}, {}
    for role, entry in entries.items():
        photo, box = entry['photo'], entry['box']
        if not entry.get('confirmed') or box is None:
            raise ValueError('请分别检查并确认两张裁切预览。')
        if role == 'side' and entry.get('direction') not in ('image_left','image_right'):
            raise ValueError('请标注侧脸鼻尖朝向画面左侧还是右侧。')
        if role == 'side' and entry.get('view_angle') not in ('oblique','profile'):
            raise ValueError('请标注斜侧脸或接近 90° 的纯侧脸。')
        box = clamp_box(box, photo.image.size)
        image = crop(photo, box)
        native_size = image.size
        image.thumbnail((1024,1024), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        clean_rgb(image).save(buffer, format='PNG')
        filename = f'face_{role}.png'
        images[filename] = buffer.getvalue()
        selected = entry.get('selected')
        candidate = photo.candidates[selected] if selected is not None else None
        records[role] = dict(file=filename, source_size=list(photo.image.size),
            crop_box=list(box), native_crop_size=list(native_size), output_size=list(image.size),
            crop_source=entry['method'], detected_face_box=candidate['box'] if candidate else None,
            detection_confidence=candidate['confidence'] if candidate else None,
            direction=entry.get('direction') if role == 'side' else 'front_user_confirmed',
            view_angle=entry.get('view_angle') if role == 'side' else 'front',
            warnings=warnings(photo,box,selected), confirmed=True,
            sha256=hashlib.sha256(images[filename]).hexdigest())
    metadata = dict(schema=SCHEMA, views=records, same_person='user_confirmed_not_biometric_verified',
                    coordinates='EXIF-oriented original pixels, x0/y0 inclusive x1/y1 exclusive',
                    detector='MediaPipe BlazeFace short range', model_sha256=MODEL_SHA256,
                    processing='local crop and downscale only; no retouch, synthesis or mirroring',
                    originals_included=False, source_paths_included=False)
    instructions = ('映衣间 · Veylfit 面部参考包\n\nface_front.png：本人正面身份参考。\n'
        'face_side.png：同一人的斜侧/侧面身份参考，角度类别与方向见 manifest.json。\n'
        '这些是原照裁切，未经生图补全、美颜或镜像。侧面不是由正面推测生成。\n'
        '与白模渲染图和衣物图一起使用；白模负责体型，面部图负责身份，衣物图负责服装。\n'
        '本程序只导出，不自动上传或调用聊天内置生图。需要在后续聊天中使用这些图片。\n'
        '导出含真实人脸及框内背景；请选择合适保存位置，检查云同步设置。\n')
    # Build completely in memory; an invalid entry cannot partially overwrite a file.
    output = BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as z:
        for name, blob in images.items():
            z.writestr(name,blob)
        z.writestr('manifest.json', json.dumps(metadata,ensure_ascii=False,indent=2))
        z.writestr('使用说明.txt', instructions)
    Path(path).write_bytes(output.getvalue())
    return metadata
