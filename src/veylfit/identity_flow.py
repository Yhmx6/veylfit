"""Local candidate review and manual image-generation handoff; no network calls."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json
import math
import os
import tempfile
from PIL import Image, ImageOps
from garment_workflow import GarmentWorkflow
from calibration_flow import CalibrationFlow
from fit_advice import FitAdvice
from person_profile import PersonProfile

SCHEMA = 'fitlogic.identity-project.v1'
ROLES = ('face_front', 'face_side', 'body')
ANGLES = ('front', 'oblique', 'side')
ANGLE_LABELS = {'front': '正面', 'oblique': '斜侧面（朝画面右）', 'side':'正侧面（朝画面右）'}
def valid_angle_pair(views):return set(views) in ({'front','oblique'},{'front','side'})
MAX_FILE = 30 * 1024**2
MAX_ARCHIVE = 240 * 1024**2

def now():
    return datetime.now(timezone.utc).isoformat()

def digest(blob):
    return hashlib.sha256(blob).hexdigest()

def image_bytes(source):
    if isinstance(source, Image.Image):
        src = source
    else:
        blob = source if isinstance(source, bytes) else Path(source).read_bytes()
        if len(blob) > MAX_FILE:
            raise ValueError('图片不得超过 30 MiB。')
        src = Image.open(BytesIO(blob))
        if src.format not in ('JPEG', 'PNG', 'WEBP'):
            raise ValueError('请使用 JPG、PNG 或 WebP 图片。')
    if min(src.size) < 32 or src.width * src.height > 25_000_000:
        raise ValueError('图片尺寸应在 32 像素至 2500 万像素之间。')
    rgb = ImageOps.exif_transpose(src).convert('RGB')
    clean = Image.frombytes('RGB', rgb.size, rgb.tobytes())
    buf = BytesIO(); clean.save(buf, format='PNG')
    if len(buf.getvalue()) > MAX_FILE:
        raise ValueError('转换后的图片过大，请缩小后重试。')
    return buf.getvalue()

def atomic_write(path, blob):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.veylfit-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(blob)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def archive_bytes(manifest, files):
    out = BytesIO()
    with ZipFile(out, 'w', ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        for name, blob in files.items():
            z.writestr(name, blob)
    return out.getvalue()

class IdentityProject(PersonProfile,FitAdvice,CalibrationFlow,GarmentWorkflow):
    def __init__(self):
        self.assets = {}
        self.resources = {}
        self.state = dict(schema=SCHEMA, project_id=uuid4().hex, refs={}, refs_approved=False,
                          request=None, candidates=[None]*3, selected=None, garment=None,
                          history=[], events=[], baseline=None, baseline_active=False, angle='front',
                          garment_info=None,tryon_jobs=[],calibration=None,tryon_mode='faithful')

    def event(self, action, **data):
        self.state['events'].append(dict(time=now(), action=action, **data))

    def add_asset(self, source):
        blob = image_bytes(source); key = digest(blob)
        self.assets[key] = blob
        return key

    def image(self, key):
        return Image.open(BytesIO(self.assets[key])).convert('RGB')

    def fingerprint(self):
        return digest(json.dumps(self.state['refs'], sort_keys=True, ensure_ascii=False).encode())

    def clear_candidates(self, reason):
        if self.state.get('calibration'):
            self.state['history'].append(dict(reason=reason,calibration=deepcopy(self.state['calibration'])))
        self.state['calibration']=None
        if self.state.get('baseline'):
            self.state['history'].append(dict(reason=reason, time=now(),
                baseline=deepcopy(self.state['baseline'])))
            self.state.update(baseline=None, baseline_active=False, angle='front')
        if any(self.state['candidates']):
            self.state['history'].append(dict(reason=reason, time=now(),
                candidates=deepcopy(self.state['candidates']), request=deepcopy(self.state['request'])))
        self.state.update(candidates=[None]*3, selected=None, request=None)
        self.event('confirmation_invalidated', reason=reason)

    def set_refs(self, sources, provenance=None):
        if not sources or not set(sources).issubset(ROLES):
            raise ValueError('参考类型不正确。')
        # Decode all inputs before mutating the current reference set.
        blobs = {role: image_bytes(source) for role, source in sources.items()}
        self.clear_candidates('面部或白模参考已更新')
        body_source=(provenance or {}).get('body')
        if 'body' in sources and self.state.get('intake_record') and not (isinstance(body_source,dict) and body_source.get('source')=='current_intake_result'):
            # A manually replaced preview is not the geometry produced by intake.
            self.state['intake_record']['body_model']=None
            self.state['intake_record']['report']=None
        for role, blob in blobs.items():
            key = digest(blob); self.assets[key] = blob
            self.state['refs'][role] = dict(asset=key, provenance=(provenance or {}).get(role, '用户导入'))
        self.state['refs_approved'] = False

    def remove_refs(self, roles, reason):
        if not any(r in self.state['refs'] for r in roles):
            return
        self.clear_candidates(reason)
        for role in roles:
            self.state['refs'].pop(role, None)
        self.state['refs_approved'] = False

    def approve_refs(self, value):
        if value and set(self.state['refs']) != set(ROLES):
            raise ValueError('请准备正面、斜侧面和白模三种参考。')
        if not value and self.state['refs_approved']:
            self.clear_candidates('取消素材确认')
        self.state['refs_approved'] = bool(value)

    def require_refs(self):
        if set(self.state['refs']) != set(ROLES) or not self.state['refs_approved']:
            raise ValueError('请先准备并确认两张面部参考和白模。')

    def start_batch(self):
        self.require_refs()
        self.clear_candidates('新一批候选（上一批保留在项目历史）')
        self.state['request'] = dict(id=uuid4().hex, fingerprint=self.fingerprint(), created_at=now())
        self.event('batch_prepared', request_id=self.state['request']['id'])

    def require_batch(self):
        self.require_refs()
        if not self.state['request'] or self.state['request']['fingerprint'] != self.fingerprint():
            raise ValueError('请先导出本批三候选生成包，再导入对应结果。')

    def generation_package(self, path):
        self.require_batch()
        prompt = ('请使用 face_front.png 和 face_side.png 中同一人的真实五官、脸型、眼镜与发型，'
            '结合 body.png 的身体体积，分别独立生成三张人物底图。三张都从这组原始参考出发，不串联编辑。'
            '白模头部不代表本人。三张使用相同的正面自然站姿、轻微闭口浅笑、浅灰背景和柔和光线，'
            '普通灰色圆领 T 恤、炭灰直筒裤和白鞋。头脚完整，比例自然，不瘦身、不美颜、不刻意改变脸型。'
            '每次只输出一张独立全身图，分别保存为 candidate_1.png、candidate_2.png、candidate_3.png。'
            '用户将先看脸部，再确认全身体型。不要生成三联画。')
        files = {r+'.png':self.assets[self.state['refs'][r]['asset']] for r in ROLES}
        files['生成要求.txt'] = prompt.encode('utf-8')
        files['操作说明.txt'] = ('本程序未上传图片，也未自动调用生图。解压后将三张参考及生成要求交给聊天生图，'
            '三次独立生成；返回本程序导入三张结果。导入时须确认结果属于本批素材。'
            '本包包含真人照片，请自行决定是否提交外部服务。').encode('utf-8')
        manifest = dict(schema='fitlogic.candidate-request.v1', request=self.state['request'],
                        reference_fingerprint=self.fingerprint(), references=self.state['refs'], count=3)
        atomic_write(path, archive_bytes(manifest, files))

    def put_candidate(self, index, source, belongs_to_batch, box=None):
        self.require_batch()
        if index not in range(3) or not belongs_to_batch:
            raise ValueError('请确认这张完整人物图来自当前这批生成素材。')
        key = self.add_asset(source)
        if any(c and c['asset']==key for i,c in enumerate(self.state['candidates']) if i != index):
            raise ValueError('这张图已在另一个候选位，请导入不同的结果。')
        old = self.state['candidates'][index]
        if old:
            self.state['history'].append(dict(time=now(), reason='替换候选', candidates=[deepcopy(old)]))
        w,h = self.image(key).size
        candidate = dict(id=uuid4().hex, asset=key, request_id=self.state['request']['id'],
            fingerprint=self.fingerprint(), face_box=list(box or (w*.25,h*.01,w*.75,h*.28)),
            face_approved=False, body_approved=False, face_time=None, body_time=None)
        self.validate_box(candidate['face_box'], (w,h))
        self.state['candidates'][index] = candidate
        self.state['selected'] = None
        self.event('candidate_imported', candidate_id=candidate['id'], slot=index+1)

    @staticmethod
    def validate_box(box, size):
        if len(box)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box):
            raise ValueError('脸部预览框无效。')
        x0,y0,x1,y1=box;w,h=size
        if not (0<=x0<x1<=w and 0<=y0<y1<=h and x1-x0>=8 and y1-y0>=8):
            raise ValueError('请画出至少 8×8 像素的脸部预览范围。')

    def candidate(self, index):
        self.require_batch()
        if index not in range(3):
            raise ValueError('候选位置无效。')
        c=self.state['candidates'][index]
        if not c or c['request_id']!=self.state['request']['id'] or c['fingerprint']!=self.fingerprint():
            raise ValueError('候选缺失或已过期，请重新导入。')
        return c

    def set_box(self,index,box):
        c=self.candidate(index);self.validate_box(box,self.image(c['asset']).size)
        c.update(face_box=list(box), face_approved=False, face_time=None)
        self.state['selected']=None

    def approve(self,index,kind,value):
        if kind not in ('face','body'):
            raise ValueError('确认类型不正确。')
        c=self.candidate(index)
        c[kind+'_approved']=bool(value); c[kind+'_time']=now() if value else None
        self.state['selected']=None
        self.event('review',candidate_id=c['id'],kind=kind,value=bool(value))

    def select(self,index):
        if not all(self.state['candidates']):
            raise ValueError('请先导入三张候选，完成比较。')
        c=self.candidate(index)
        if not c['face_approved'] or not c['body_approved']:
            raise ValueError('请分别确认此候选的脸部与全身体型。')
        self.state['selected']=c['id']
        self.state['baseline_active']=False
        self.event('candidate_selected',candidate_id=c['id'])

    def selected(self):
        self.require_batch()
        for i,c in enumerate(self.state['candidates']):
            if c and c['id']==self.state['selected']:
                self.candidate(i)
                if c['face_approved'] and c['body_approved']:
                    return c
        raise ValueError('请先选定已确认脸部和体型的人物。')

    def freeze_baseline(self, sources, approval_note, provenance=None, label='已确认双角度基准'):
        """Freeze an explicitly approved pair, without fabricating a candidate batch."""
        self.require_refs()
        if not valid_angle_pair(sources) or not isinstance(approval_note,str) or not approval_note.strip():
            raise ValueError('固定基准需要正面、斜侧面及明确的用户确认记录。')
        blobs={angle:image_bytes(source) for angle,source in sources.items()}
        if len({digest(blob) for blob in blobs.values()}) != 2:
            raise ValueError('正面与斜侧面不能是同一张图片。')
        views={angle:dict(asset=digest(blob), provenance=(provenance or {}).get(angle,'用户确认导入'))
               for angle,blob in blobs.items()}
        old=self.state.get('baseline')
        if old:
            self.state['history'].append(dict(reason='固定新一版双角度基准',time=now(),baseline=deepcopy(old)))
        for angle,blob in blobs.items():self.assets[views[angle]['asset']]=blob
        self.state.update(baseline=dict(id=uuid4().hex,label=label,created_at=now(),
            fingerprint=self.fingerprint(),references=deepcopy(self.state['refs']),
            views=views,approval_note=approval_note,approved=True),
            baseline_active=True,angle='front',selected=None)
        self.event('baseline_frozen',baseline_id=self.state['baseline']['id'],approval_note=approval_note)

    def fixed_baseline(self):
        self.require_refs()
        b=self.state.get('baseline')
        if not b or b.get('approved') is not True or not b.get('approval_note'):
            raise ValueError('没有已确认的双角度基准。')
        if b['fingerprint']!=self.fingerprint() or b['references']!=self.state['refs']:
            raise ValueError('基准与当前面部或白模版本不一致，请重新确认基准。')
        if not valid_angle_pair(b['views']) or len({v['asset'] for v in b['views'].values()})!=2:
            raise ValueError('双角度基准不完整或图片重复。')
        if not isinstance(b['id'],str) or not b['id'] or not isinstance(b['label'],str):
            raise ValueError('基准版本记录无效。')
        for v in b['views'].values():self.assets[v['asset']]
        return b

    def set_angle(self, angle):
        self.fixed_baseline()
        if angle not in self.state['baseline']['views']:raise ValueError('该版本没有这个角度的已确认基准。')
        self.state['angle']=angle
        self.event('baseline_angle_selected',angle=angle)

    def tryon_person(self):
        self.validate_calibration()
        if self.state.get('baseline_active'):
            b=self.fixed_baseline();angle=self.state.get('angle','front')
            if angle not in b['views']:raise ValueError('该版本没有这个角度的已确认基准。')
            return dict(asset=b['views'][angle]['asset'],source='fixed_baseline',
                        baseline_id=b['id'],baseline_label=b['label'],angle=angle)
        c=self.selected()
        return dict(asset=c['asset'],source='selected_candidate',candidate_id=c['id'])

    def tryon_package(self,path):
        person=self.tryon_person()
        profile=self.profile_snapshot(require_ready=True)
        advice=deepcopy(self.current_fit_advice())
        if not self.state['garment']:
            raise ValueError('请先导入想试穿的衣物参考。')
        keys={'person.png':person['asset'],'garment.png':self.state['garment']}
        garment=deepcopy(self.garment_info())
        keys.update({'garment_detail_'+str(i)+'.png':key for i,key in enumerate(garment['details'],1)})
        keys.update({r+'.png':self.state['refs'][r]['asset'] for r in ROLES})
        def profile_assets(value):
            if isinstance(value,dict):
                for v in value.values():profile_assets(v)
            elif isinstance(value,list):
                for v in value:profile_assets(v)
            elif isinstance(value,str) and value in self.assets:
                keys['profile_assets/'+value+'.png']=value
        profile_assets(profile)
        files={name:self.assets[key] for name,key in keys.items()}
        prompt=(('以 person.png 为已确认人物底图，还原 garment.png 中明确展示的衣物；' if self.tryon_mode()=='faithful' else '以 person.png 为已确认人物底图，garment.png 作为搭配参考，按下述明确要求生成服装方案；')+
            '保留底图的脸型、眼镜、发型、表情、身体体积、姿势、镜头与背景。'
            'face_front.png 和 face_side.png 是本人真实参考，body.png 仅辅助体型。'
            '未明确要求改色时保持参考衣物颜色；按本次明确要求处理配色。保持图案和款式结构，允许自然褶皱，不瘦身，不改脸。输出一张完整全身试衣照。'
            '不要用其他试衣结果串联生成。')
        if person['source']=='fixed_baseline':
            prompt += ('当前固定角度：'+ANGLE_LABELS[person['angle']]+'。直接沿用 person.png 的角度，'
                '不要再次转身或改变头部朝向。保留衣物下面的真实腰腹及大腿体积，不缩腰、不收腹；'
                '衣服外轮廓与身体轮廓分开处理，按本次用户想要的效果选择松量和垂坠，不默认遮腹或显瘦。厚衣保留合理填充厚度，薄衣保持轻薄。完整替换底图中对应的原衣物，'
                '不把底图的原衣物当成必须保留的内搭，除非衣物要求明确需要。'
                '未来换衣仍从此固定底图出发，生成结果不能自动替换基准。')
        prompt += ('衣物名称：'+garment['name']+'；品类：'+garment['category']+'。'
            '附加 garment_detail 图片仅补充同一件衣物的背面或局部细节，不视为额外衣物。'
            '用户衣物说明：'+garment['notes']+'。没有尺寸资料时不承诺真实合身或尺码准确。')
        prompt+=self.fit_prompt(advice)
        files['人物档案.json']=json.dumps(profile,ensure_ascii=False,indent=2).encode('utf-8')
        model=(profile.get('intake') or {}).get('body_model')
        if model:files['body_model.glb']=self.resources[model['sha256']]
        files['试衣要求.txt']=prompt.encode('utf-8')
        if advice:files['视觉松量建议.json']=json.dumps(advice,ensure_ascii=False,indent=2).encode('utf-8')
        files['操作说明.txt']='解压后将图片及试衣要求交给聊天生图。本程序未自动上传或生成，生成图仅用于外观参考。'.encode('utf-8')
        job_id=uuid4().hex
        manifest=dict(schema='fitlogic.tryon-request.v1',project_id=self.state['project_id'],job_id=job_id,
            garment_info=garment,fit_advice=advice,mode=self.tryon_mode(),
            selected_candidate=deepcopy(self.selected()) if person['source']=='selected_candidate' else None,
            person_source=person,person_profile=profile,
            profile_binding={k:profile[k] for k in ('profile_id','revision','content_hash')},
            fixed_baseline=deepcopy(self.state['baseline']) if person['source']=='fixed_baseline' else None,
            request=deepcopy(self.state['request']),
            reference_fingerprint=self.fingerprint(),asset_hashes=keys,created_at=now())
        atomic_write(path,archive_bytes(manifest,files))
        self.state['tryon_jobs'].append(dict(id=job_id,**deepcopy(manifest),prompt=prompt,results=[]))
        self.event('tryon_package_exported',job_id=job_id,person_source=person,garment=self.state['garment'])
        return job_id

    def save(self,path):
        if Path(path).resolve().is_relative_to((Path(__file__).parent/"templates").resolve()):
            raise ValueError("固定人物模板不可覆盖，请另存项目。")
        self.sync_profile()
        self.validate_profiles()
        self.validate_calibration()
        self.validate_workflow()
        if len(self.assets)+len(self.resources)+1>300 or sum(len(v) for v in [*self.assets.values(),*self.resources.values()])+len(json.dumps(self.state).encode())>MAX_ARCHIVE:
            raise ValueError('项目已接近容量上限，请新建试衣项目，避免生成无法重新打开的文件。')
        if len(json.dumps(self.state,ensure_ascii=False).encode())>2*1024**2:raise ValueError('项目记录过大，请新建项目。')
        files={'assets/'+k+'.png':v for k,v in self.assets.items()}
        files.update({'resources/'+k+'.glb':v for k,v in self.resources.items()})
        atomic_write(path,archive_bytes(self.state,files))

    @classmethod
    def load(cls,path):
        path=Path(path)
        if path.stat().st_size>MAX_ARCHIVE:
            raise ValueError('项目包过大。')
        p=cls()
        with ZipFile(path) as z:
            infos=z.infolist()
            if len(infos)>300 or sum(i.file_size for i in infos)>MAX_ARCHIVE or len({i.filename for i in infos})!=len(infos):
                raise ValueError('项目包大小或文件列表无效。')
            if z.getinfo('manifest.json').file_size>2*1024**2:
                raise ValueError('项目记录过大。')
            state=json.loads(z.read('manifest.json'))
            if state.get('schema')!=SCHEMA or len(state.get('candidates',[]))!=3:
                raise ValueError('这不是支持的映衣间人物项目。')
            for info in infos:
                if info.filename.startswith('resources/'):
                    key=info.filename[10:-4]
                    if len(key)!=64 or info.filename!='resources/'+key+'.glb' or info.file_size>MAX_FILE:
                        raise ValueError('模型资源记录无效。')
                    blob=z.read(info)
                    if digest(blob)!=key or blob[:4]!=b'glTF':raise ValueError('模型资源校验失败。')
                    p.resources[key]=blob
                if info.filename.startswith('assets/'):
                    key=info.filename[7:-4]
                    if len(key)!=64 or info.filename!='assets/'+key+'.png' or info.file_size>MAX_FILE:
                        raise ValueError('项目图片记录无效。')
                    blob=z.read(info)
                    if digest(blob)!=key:
                        raise ValueError('项目图片校验失败。')
                    image_bytes(blob)  # Validate decoding and size, retain exact saved bytes.
                    p.assets[key]=blob
        state.setdefault('baseline',None)
        state.setdefault('baseline_active',False)
        state.setdefault('angle','front')
        state.setdefault('calibration',None)
        p.state=state
        try:
            p.init_workflow_state()
            p.validate_profiles()
            p.sync_profile()
            p.validate_workflow()
            p.validate_calibration()
            if type(state['baseline_active']) is not bool or state['angle'] not in ANGLES:
                raise ValueError('固定基准状态或角度无效。')
            if state['baseline']:p.fixed_baseline()
            if state['baseline_active']:
                p.fixed_baseline()
                if state['selected']:raise ValueError('不能同时选用候选与固定基准。')
            if type(state['refs_approved']) is not bool:
                raise ValueError('素材确认记录无效。')
            if not set(state['refs']).issubset(ROLES):raise ValueError('未知参考类型')
            for r in state['refs'].values():p.assets[r['asset']]
            if state['garment']:p.assets[state['garment']]
            for c in state['candidates']:
                if c:
                    p.validate_box(c['face_box'],p.image(c['asset']).size)
                    if type(c['face_approved']) is not bool or type(c['body_approved']) is not bool:
                        raise ValueError('确认记录无效')
            if state['refs_approved']:p.require_refs()
            if state['request']:p.require_batch()
            if any(state['candidates']):
                candidates=[c for c in state['candidates'] if c]
                if len({c['asset'] for c in candidates})!=len(candidates) or len({c['id'] for c in candidates})!=len(candidates):
                    raise ValueError('候选重复。')
                for i,c in enumerate(state['candidates']):
                    if c:p.candidate(i)
            if state['selected']:
                if not all(state['candidates']):raise ValueError('选定记录缺少三张候选。')
                p.selected()
        except (KeyError,TypeError,IndexError) as e:
            raise ValueError('项目记录不完整或引用缺失。') from e
        return p
