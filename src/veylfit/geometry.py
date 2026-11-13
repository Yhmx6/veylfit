import math

import numpy as np
from PIL import Image, ImageDraw


def render(vertices, faces, path):
    canvas = Image.new('RGB', (1140, 720), '#242a33')
    draw = ImageDraw.Draw(canvas)
    scale = min(3.13, 340 / max(np.ptp(vertices[:,0]), np.ptp(vertices[:,2])))
    for i, (angle, label) in enumerate([(0, 'FRONT'), (34, 'THREE-QUARTER'), (90, 'SIDE')]):
        a = math.radians(angle)
        v = vertices @ np.array([[math.cos(a), 0, -math.sin(a)], [0, 1, 0], [math.sin(a), 0, math.cos(a)]])
        if i == 1:
            tilt = math.radians(6)
            v[:, 1:] = v[:, 1:] @ np.array([[math.cos(tilt), -math.sin(tilt)], [math.sin(tilt), math.cos(tilt)]])
        tri = v[faces]
        normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        vertex_normals = np.zeros_like(v)
        for corner in range(3):
            np.add.at(vertex_normals, faces[:, corner], normals)
        vertex_normals /= np.maximum(np.linalg.norm(vertex_normals, axis=1, keepdims=True), 1e-10)
        n = vertex_normals[faces].mean(axis=1)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-10)
        light = np.clip(n @ np.array([-.35, .5, .79]), 0, 1)
        x_offset = 190 + i * 380 - scale * ((v[:, 0].max() + v[:, 0].min()) / 2)
        pos = np.column_stack((v[:, 0] * scale + x_offset, 650 - v[:, 1] * scale))
        for face in np.argsort(tri[:, :, 2].mean(axis=1)):
            color = int(127 + 118 * light[face])
            draw.polygon([tuple(pt) for pt in pos[faces[face]]], fill=(color, color, color))
        draw.text((i * 380 + 25, 30), label, fill='#cfd8e3')
        draw.line((i * 380 + 40, 652, i * 380 + 340, 652), fill='#526172', width=1)
    canvas.save(path, format='PNG')
    return scale
