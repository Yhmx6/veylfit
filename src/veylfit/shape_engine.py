"""Local engineering shape presets. BMI is a heuristic prior, not measured anatomy."""
from dataclasses import dataclass, asdict
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from makehuman_fit import Template, Section

VERSION = 'male-four-region-v2'
FAMILIES = {'heavy':'偏胖', 'normal':'正常', 'lean':'偏瘦'}
GROUPS = {
    'arms': ('手臂', ('较纤细', '圆润饱满', '上臂较厚实')),
    'torso': ('胸腹', ('腰腹较平缓', '腹部向前', '胸背较宽厚')),
    'legs': ('臀腿', ('臀腿较纤细', '臀部较突出', '大腿较厚实')),
    'neck': ('肩颈', ('颈部较长细', '中间形态', '颈部较短厚')),
}
DISCLAIMER = '工程体型估计，未校准真实肌肉量或体脂；网格尺寸不是本人实测。'


@dataclass(frozen=True)
class Settings:
    height_cm: float = 175.
    weight_kg: float = 75.
    arms: int = 1
    torso: int = 1
    legs: int = 1
    neck: int = 1
    neck_length: float = 0.
    neck_width: float = 0.
    body_family: str = 'auto'

    def validated(self):
        if not all(math.isfinite(x) for x in (self.height_cm, self.weight_kg, self.neck_length, self.neck_width)):
            raise ValueError('请填写有限数值。')
        if not 150 <= self.height_cm <= 205 or not 40 <= self.weight_kg <= 150:
            raise ValueError('本轮测试范围：身高150–205 cm，体重40–150 kg。')
        if not 17 <= self.bmi <= 36:
            raise ValueError('本轮体量形变仅支持BMI 17–36，超出范围需另行验证。')
        if any(type(getattr(self, key)) is not int or getattr(self, key) not in (0, 1, 2) for key in GROUPS):
            raise ValueError('每组请选择一种外形。')
        if not -1 <= self.neck_length <= 1 or not -1 <= self.neck_width <= 1:
            raise ValueError('颈部微调超出范围。')
        if self.body_family not in ('auto',*FAMILIES):
            raise ValueError('请选择偏胖、正常或偏瘦。')
        return self

    @property
    def bmi(self):
        return self.weight_kg / (self.height_cm / 100)**2

    @property
    def illustration_family(self):
        if self.body_family != 'auto': return self.body_family
        # Gallery grouping only, not a clinical classification.
        return 'lean' if self.bmi<20.5 else 'heavy' if self.bmi>=27 else 'normal'


def smooth(x):
    x = np.clip(x, 0, 1)
    return x*x*(3-2*x)


def bell(y, center, radius):
    d = np.abs((y-center)/radius)
    return np.where(d < 1, .5*(1+np.cos(np.pi*np.minimum(d,1))), 0.)


@lru_cache(maxsize=1)
def base():
    t = Template('male')
    v = t.array(t.attrs['POSITION']).astype(float).copy()
    indices = t.skin['joints']
    js = np.concatenate([t.array(t.attrs[k]) for k in sorted(t.attrs) if k.startswith('JOINTS_')], axis=1)
    ws = np.concatenate([t.array(t.attrs[k]) for k in sorted(t.attrs) if k.startswith('WEIGHTS_')], axis=1)
    groups = []
    for names in [('upperarm01.L','upperarm01.R'), ('upperleg01.L','upperleg01.R'), ('neck01',), ('head',)]:
        nodes = set()
        for i,node in enumerate(t.nodes):
            if node.get('name') in names:
                stack = [i]
                while stack:
                    j = stack.pop(); nodes.add(j); stack.extend(t.nodes[j].get('children', []))
        mask = np.isin(indices, list(nodes))
        groups.append(((mask[js]*ws).sum(1), mask.astype(float)))
    p = np.array([t.world[i][:3,3] for i in indices])
    return v, t.faces.copy(), p, np.stack([g[0] for g in groups],1), np.stack([g[1] for g in groups],1)


def deform(points, weights, s):
    """Shared continuous field for surface and joint centers, in template meters."""
    x,y,z = points.T
    yn = y / 1.86
    arm,leg,neck,head = weights.T
    torso = np.clip(1-arm-leg-neck,0,1)
    b = (s.bmi-23.)/13.  # Explicit uncalibrated engineering prior; not kg or body-fat fitting.
    if s.body_family != 'auto':
        b = .72*b + .28*{'lean':-.3,'normal':0.,'heavy':.7}[s.body_family]
    out = points.copy()
    chest = bell(yn,.735,.115)
    abdomen = bell(yn,.625,.12)
    pelvis = bell(yn,.535,.095)
    grow = (.13*chest+.23*abdomen+.13*pelvis)*b
    out[:,0] += x*grow*torso
    out[:,2] += (z-.025)*(.20*chest+.35*abdomen+.18*pelvis)*b*torso
    front = smooth((z+.015)/.13)
    out[:,2] += .025*b*abdomen*front*torso

    # Arm cross-section around the actual A-pose bone line; hands stay almost unchanged.
    side = np.where(x>=0,1.,-1.)
    shoulder = np.c_[side*.200, np.full(len(x),1.483), np.full(len(x),.019)]
    elbow = np.c_[side*.356, np.full(len(x),1.261), np.full(len(x),.019)]
    axis = elbow-shoulder
    u = np.clip(((points-shoulder)*axis).sum(1)/(axis*axis).sum(1),0,1)
    center = shoulder+u[:,None]*axis
    radial = points-center
    radial -= ((radial*axis).sum(1)/(axis*axis).sum(1))[:,None]*axis
    upper = bell(yn,.735,.105)
    lower = bell(yn,.625,.085)
    preset = (-.15,.10,.23)[s.arms]
    amount = (.20*b+preset)*upper + (.12*b+(-.08,.06,.05)[s.arms])*lower
    out += radial*(amount*arm)[:,None]
    out[:,0] += side*.022*b*arm

    # Separate chest width, abdominal front and back fullness.
    tw,cf,af = ((-.045,0.,-.022),(.02,.003,.024),(.13,.022,-.012))[s.torso]
    out[:,0] += x*(tw*chest+(-.045,.025,-.015)[s.torso]*abdomen)*torso
    out[:,2] += (cf*chest*front+af*abdomen*front)*torso
    if s.torso == 2:
        out[:,2] -= .016*chest*(1-front)*torso

    # Leg radial growth about interpolated hip/knee centers, not the body midline.
    cx = side*np.interp(yn,[0,.292,.531,1],[.21,.163,.117,.117])
    cz = np.interp(yn,[0,.292,.531,1],[.02,.029,-.008,-.008])
    thigh = bell(yn,.43,.125)
    calf = bell(yn,.23,.13)
    thick = (.18*b+(-.13,.025,.23)[s.legs])*thigh + .10*b*calf
    out[:,0] += (x-cx)*thick*leg
    out[:,2] += (z-cz)*thick*leg
    out[:,0] += side*(.014*b+(-.003,.003,.009)[s.legs])*leg
    butt = bell(yn,.535,.075)
    out[:,0] += x*(-.045,.065,.005)[s.legs]*butt*torso
    out[:,2] -= (-.008,.024,.003)[s.legs]*butt*(1-front)*torso

    # Neck descendants include facial bones. Explicitly protect head-dominant vertices
    # and feather the neck/head junction using skin weights, not just vertex height.
    # The chin sits beside the upper neck at similar heights; a y-only cutoff fails.
    head_free = 1-smooth(head/.55)
    length = (.014,0.,-.012)[s.neck] + .008*s.neck_length
    out[:,1] -= length*(bell(yn,.837,.085)*(1-arm)+arm)*head_free
    neck_band = bell(yn,.88,.065)*neck*head_free
    width = (-.12,0.,.18)[s.neck]+.10*s.neck_width+.05*b
    out[:,0] += x*width*neck_band
    out[:,2] += (z-.025)*width*neck_band
    return out*(s.height_cm/186.)


@dataclass
class Body:
    settings: Settings
    vertices: np.ndarray
    faces: np.ndarray
    joints: np.ndarray
    report: dict

    def glb(self):
        t = Template('male')
        world = {i:m.copy() for i,m in t.world.items()}
        for i,p in zip(t.skin['joints'],self.joints):
            world[i][:3,3] = p
        return t.encode(self.vertices,world)


def build(s=Settings(), validate=True):
    s.validated()
    v,f,j,w,jw = base()
    v = deform(v,w,s)
    joints = deform(j,jw,s)
    if not np.isfinite(v).all():
        raise ValueError('生成了异常顶点。')
    height = float(np.ptp(v[:,1])*100)
    if abs(height-s.height_cm)>.05:
        raise ValueError('形变后身高未保持。')
    report = dict(engine=VERSION,settings=asdict(s),bmi=round(s.bmi,4),
                  source='MakeHuman male engineering presets',status='awaiting_user_confirmation',
                  body_family_requested=s.body_family,illustration_family=s.illustration_family,
                  note=DISCLAIMER,template_sha256=hashlib.sha256((Path(__file__).parent/'templates/male.glb').read_bytes()).hexdigest(),
                  dimensions_source='mesh_measured_at_fixed_height_fractions_not_anatomical_tape_measurements',
                  height_cm=round(height,4))
    if validate:
        rows = {}
        for key,level in [('chest',.724),('abdomen',.63),('waist',.66),('hips',.522)]:
            sec=Section(v,f,level*s.height_cm/100)
            if sec.torso is None:
                raise ValueError('无法测量模型躯干截面。')
            p=sec.torso[3]
            rows[key]=dict(level_fraction=level,girth_cm=round(sec.girth(v),2),width_cm=round(np.ptp(p[:,0])*100,2),depth_cm=round(np.ptp(p[:,2])*100,2))
        gaps = [Section(v,f,p*s.height_cm/100).has_gaps(n) for p,n in [(.61,3),(.65,3),(.29,2),(.36,2)]]
        if not all(gaps):
            raise ValueError('该组合未通过四肢间隙检查，请减小局部厚度或改变选项。')
        report.update(mesh_sections=rows,gap_checks=gaps,joints=len(j),vertices=len(v),triangles=len(f))
    return Body(s,v,f,joints,report)


def font(size):
    return ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',size)


def preview(body, size=(880,700), region=None):
    """Orthographic front/side views of the actual deformed mesh; no generated images."""
    output_size=size
    if region is not None:
        size=(size[0]*2,size[1]*2)
    w,h=size
    canvas=Image.new('RGB',size,'#edf0f1'); d=ImageDraw.Draw(canvas)
    v=body.vertices; f=body.faces; height=body.settings.height_cm/100
    bounds = {'arms':(.57,.84),'torso':(.49,.83),'legs':(.27,.59),'neck':(.78,1.01)}
    low,high=bounds.get(region,(0,1.03))
    if region is None:
        sc=min((h-48)/((high-low)*height),(w/2-26)/np.ptp(v[:,0]))
    else:
        crop_width={'arms':.20,'torso':.28,'legs':.27,'neck':.28}[region]*height
        sc=min((h-16)/((high-low)*height),(w/2-12)/crop_width)
    for col,side in enumerate((False,True)):
        # Side faces right; +z is anatomical front.
        coords=v[:,[2,1,0]].copy() if side else v.copy()
        tri=coords[f]
        ns=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
        vn=np.zeros_like(coords)
        for corner in range(3): np.add.at(vn,f[:,corner],ns)
        vn/=np.maximum(np.linalg.norm(vn,axis=1)[:,None],1e-12)
        ns=vn[f].mean(1)
        ns/=np.maximum(np.linalg.norm(ns,axis=1)[:,None],1e-12)
        light=np.clip(np.abs(ns@np.array([-.25,.38,.89])),0,1)
        centerx = 0 if not side else .03*height/1.86
        if region=='arms' and not side:
            centerx=.31*height/1.86
        py=(h/2-(coords[:,1]-(low+high)*height/2)*sc) if region else h-20-(coords[:,1]-low*height)*sc
        pos=np.c_[(coords[:,0]-centerx)*sc+(col+.5)*w/2, py]
        visible=(tri[:,:,1].max(1)>=low*height)&(tri[:,:,1].min(1)<=high*height)
        panel=Image.new('RGB',(w//2,h),'#edf0f1'); pd=ImageDraw.Draw(panel)
        for idx in np.argsort(tri[:,:,2].mean(1)):
            if not visible[idx]: continue
            color=int(154+95*light[idx])
            points=pos[f[idx]].copy();points[:,0]-=col*w/2
            pd.polygon([tuple(p) for p in points],fill=(color,color,min(255,color+1)))
        canvas.paste(panel,(col*w//2,0))
    d=ImageDraw.Draw(canvas)
    d.line((w/2,0,w/2,h),fill='#d2d8da')
    if region is None:
        for x,label in [(16,'正面'),(w//2+16,'侧面')]: d.text((x,12),label,font=font(18),fill='#33434b')
        d.text((16,h-22),'同一模型 · A 姿势 · 体型待确认',font=font(12),fill='#65727a')
    return canvas.resize(output_size,Image.Resampling.LANCZOS) if region else canvas


def thumbnails(s):
    cards={}
    for key in GROUPS:
        for index in range(3):
            data=asdict(s);data[key]=index
            cards[key,index]=preview(build(Settings(**data),False),(144,88),key)
    return cards


def export_bundle(path,body,include_preview=True):
    path=Path(path)
    template_dir=(Path(__file__).parent/'templates').resolve()
    if path.resolve().is_relative_to(template_dir):
        raise ValueError('请保存为独立试验文件，不要覆盖固定人物模板。')
    glb=body.glb()
    if include_preview:
        buf=BytesIO();preview(body).save(buf,format='PNG')
    report=dict(body.report,glb_sha256=hashlib.sha256(glb).hexdigest())
    with ZipFile(path,'x',ZIP_DEFLATED) as z:
        z.writestr('body.glb',glb)
        if include_preview:z.writestr('front-side.png',buf.getvalue())
        z.writestr('shape-project.json',json.dumps(dict(schema=VERSION,settings=asdict(body.settings)),ensure_ascii=False,indent=2))
        z.writestr('report.json',json.dumps(report,ensure_ascii=False,indent=2))
    return report


def load_settings(path):
    path=Path(path)
    if path.stat().st_size>20_000_000: raise ValueError('项目文件过大。')
    if path.suffix.lower()=='.zip':
        with ZipFile(path) as z:
            info=z.getinfo('shape-project.json')
            if info.file_size>8192: raise ValueError('项目配置过大。')
            data=json.loads(z.read(info))
    else:
        if path.stat().st_size>8192: raise ValueError('项目配置过大。')
        data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') not in (VERSION,'male-four-region-v1','male-four-region-v1.1'): raise ValueError('不是本版四区外形项目。')
    try: return Settings(**data['settings']).validated()
    except (TypeError,KeyError,ZeroDivisionError) as e: raise ValueError('项目参数格式错误。') from e
