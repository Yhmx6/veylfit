"""Local garment revisions and immutable exported-request/result associations."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
import math

CATEGORIES = ('未分类', 'T恤', '衬衫', '外套', '棉衣', '裤装', '裙装', '其他')
REVIEW_VALUES = ('pending', 'pass', 'issue')
REVIEW_LABELS = {'pending':'待检查', 'pass':'通过', 'issue':'有问题'}
STATUS_LABELS = {'pending':'待验收', 'accepted':'已接受', 'issues':'需改进'}

def stamp():
    return datetime.now(timezone.utc).isoformat()

def text_field(value, limit, label):
    if not isinstance(value,str) or len(value)>limit:
        raise ValueError(label+'内容过长或格式无效。')
    return value.strip()

def result_status(review):
    if set(review)!=set(('face','body','garment')) or any(v not in REVIEW_VALUES for v in review.values()):
        raise ValueError('验收项无效。')
    return 'issues' if 'issue' in review.values() else ('accepted' if all(v=='pass' for v in review.values()) else 'pending')

class GarmentWorkflow:
    def garment_info(self):
        info=self.state.get('garment_info')
        if not info or info['asset']!=self.state['garment']:
            raise ValueError('请先导入衣物主图。')
        return info

    def set_garment(self, source, name='未命名衣物', category='未分类'):
        name=text_field(name,100,'衣物名称') or '未命名衣物'
        if category not in CATEGORIES:raise ValueError('衣物品类无效。')
        key=self.add_asset(source)
        self.state['garment']=key
        self.state['garment_info']=dict(id=uuid4().hex,revision=1,name=name,category=category,
            original_asset=key,asset=key,crop=None,details=[],notes='')
        self.event('garment_imported',asset=key,garment_id=self.state['garment_info']['id'])

    def edit_garment(self,name,category,notes=''):
        info=self.garment_info()
        name=text_field(name,100,'衣物名称') or '未命名衣物'
        notes=text_field(notes,2000,'衣物说明')
        if category not in CATEGORIES:raise ValueError('衣物品类无效。')
        if (name,category,notes)==(info['name'],info['category'],info['notes']):return
        info.update(name=name,category=category,notes=notes,revision=info['revision']+1)
        self.event('garment_metadata_changed',garment_id=info['id'],revision=info['revision'])

    def crop_garment(self,box=None):
        info=self.garment_info();original=self.image(info['original_asset'])
        if box is None:key=info['original_asset'];crop=None
        else:
            if len(box)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box):
                raise ValueError('裁切范围无效。')
            crop=[round(v) for v in box];x0,y0,x1,y1=crop
            if not (0<=x0<x1<=original.width and 0<=y0<y1<=original.height and x1-x0>=32 and y1-y0>=32):
                raise ValueError('请在原图内选取至少 32×32 像素的衣物范围。')
            key=self.add_asset(original.crop(tuple(crop)))
        info.update(asset=key,crop=crop,revision=info['revision']+1)
        self.state['garment']=key
        self.event('garment_crop_changed',garment_id=info['id'],revision=info['revision'])

    def add_garment_detail(self,source):
        info=self.garment_info()
        if len(info['details'])>=3:raise ValueError('本轮最多添加三张背面或细节参考。')
        key=self.add_asset(source)
        if key in info['details'] or key in (info['original_asset'],info['asset']):
            raise ValueError('这张图片已作为主图或细节参考。')
        info['details'].append(key);info['revision']+=1
        self.event('garment_detail_added',garment_id=info['id'],asset=key)

    def remove_garment_detail(self,index):
        info=self.garment_info()
        if index not in range(len(info['details'])):raise ValueError('细节图不存在。')
        info['details'].pop(index);info['revision']+=1
        self.event('garment_detail_removed',garment_id=info['id'],index=index)

    def tryon_job(self,job_id):
        for j in self.state['tryon_jobs']:
            if j['id']==job_id:return j
        raise ValueError('请先选择已导出的试衣任务。')

    def import_tryon_result(self,job_id,source,belongs_to_job):
        job=self.tryon_job(job_id)
        if belongs_to_job is not True:raise ValueError('请先确认结果对应所选任务的衣物、人物和角度。')
        key=self.add_asset(source)
        if key in job['asset_hashes'].values():raise ValueError('导入的是本次输入参考，请选择生成的试穿结果。')
        if any(r['asset']==key for r in job['results']):raise ValueError('此结果已保存在本任务中。')
        result=dict(id=uuid4().hex,asset=key,imported_at=stamp(),source_confirmed=True,
            review=dict(face='pending',body='pending',garment='pending'),status='pending',note='',reviewed_at=None)
        job['results'].append(result)
        self.event('tryon_result_imported',job_id=job_id,result_id=result['id'])
        return result['id']

    def tryon_result(self,job_id,result_id):
        for r in self.tryon_job(job_id)['results']:
            if r['id']==result_id:return r
        raise ValueError('请先选择一个试穿结果。')

    def review_tryon_result(self,job_id,result_id,review,note=''):
        result=self.tryon_result(job_id,result_id)
        status=result_status(review);note=text_field(note,2000,'问题备注')
        result.update(review=deepcopy(review),status=status,note=note,reviewed_at=stamp())
        self.event('tryon_result_reviewed',job_id=job_id,result_id=result_id,status=status,review=deepcopy(review),note=note)

    def init_workflow_state(self):
        self.state.setdefault('tryon_mode','faithful')
        self.state.setdefault('tryon_jobs',[])
        if 'garment_info' not in self.state:
            key=self.state.get('garment')
            self.state['garment_info']=dict(id=uuid4().hex,revision=1,name='旧项目衣物',category='未分类',
                original_asset=key,asset=key,crop=None,details=[],notes='') if key else None

    def validate_garment_info(self,info):
        if not info['id'] or type(info['revision']) is not int or info['revision']<1:raise ValueError('衣物版本无效。')
        text_field(info['name'],100,'衣物名称');text_field(info['notes'],2000,'衣物说明')
        if info['category'] not in CATEGORIES or len(info['details'])>3 or len(set(info['details']))!=len(info['details']):
            raise ValueError('衣物品类或细节记录无效。')
        for key in [info['original_asset'],info['asset'],*info['details']]:self.assets[key]
        box=info['crop']
        if box is not None:
            w,h=self.image(info['original_asset']).size
            if len(box)!=4 or not all(type(v) is int for v in box):raise ValueError('衣物裁切记录无效。')
            x0,y0,x1,y1=box
            if not (0<=x0<x1<=w and 0<=y0<y1<=h and x1-x0>=32 and y1-y0>=32):raise ValueError('衣物裁切越界。')
            if self.image(info['asset']).size!=(x1-x0,y1-y0):raise ValueError('衣物裁切尺寸不符。')

    def validate_workflow(self):
        from fit_advice import validate as validate_fit,MODES
        self.tryon_mode()
        info=self.state['garment_info']
        if bool(info)!=bool(self.state['garment']):raise ValueError('衣物资料缺失。')
        if info:
            self.validate_garment_info(info)
            if info['asset']!=self.state['garment']:raise ValueError('衣物主图引用不一致。')
        ids=set();result_ids=set()
        for j in self.state['tryon_jobs']:
            if not j['id'] or j['id'] in ids:raise ValueError('试衣任务编号重复。')
            ids.add(j['id']);self.validate_garment_info(j['garment_info'])
            keys=j['asset_hashes']
            if not {'person.png','garment.png','face_front.png','face_side.png','body.png'}<=set(keys):raise ValueError('试衣快照不完整。')
            for key in keys.values():self.assets[key]
            if j['person_source']['asset']!=keys['person.png'] or j['garment_info']['asset']!=keys['garment.png']:
                raise ValueError('试衣快照引用不一致。')
            person=j['person_source']
            if 'mode' in j and j['mode'] not in MODES:raise ValueError('历史试衣任务模式无效。')
            validate_fit(j.get('fit_advice'),person,j['garment_info'],j.get('mode'))
            if person['source']=='fixed_baseline':
                baseline=j['fixed_baseline'];angle=person['angle']
                if baseline['id']!=person['baseline_id'] or baseline['views'][angle]['asset']!=keys['person.png']:
                    raise ValueError('人物角度与导出基准不一致。')
                for role in ('face_front','face_side','body'):
                    if baseline['references'][role]['asset']!=keys[role+'.png']:raise ValueError('人物参考版本不一致。')
            elif person['source']=='selected_candidate':
                if j['selected_candidate']['asset']!=keys['person.png']:raise ValueError('人物候选快照不一致。')
            else:raise ValueError('未知人物来源。')
            for i,key in enumerate(j['garment_info']['details'],1):
                if keys.get('garment_detail_'+str(i)+'.png')!=key:raise ValueError('细节参考快照不一致。')
            for r in j['results']:
                if not r['id'] or r['id'] in result_ids:raise ValueError('试穿结果编号重复。')
                result_ids.add(r['id']);self.assets[r['asset']]
                if r['source_confirmed'] is not True or r['status']!=result_status(r['review']):raise ValueError('试穿验收记录无效。')
                text_field(r['note'],2000,'问题备注')
