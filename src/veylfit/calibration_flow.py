"""Sequential, human-reviewed identity calibration before manual try-on."""
from copy import deepcopy
import hashlib,json
from uuid import uuid4

class CalibrationFlow:
    def calibration(self):
        self.require_refs()
        c=self.state.get('calibration')
        if c is None:
            c={'version':1,'fingerprint':self.fingerprint(),'body':{'views':{},'approved':False},'front':None,'side':None,'requests':{}}
            self.state['calibration']=c
        if c['fingerprint']!=self.fingerprint():raise ValueError('素材已变化，请重新校准。')
        return c

    def invalidate_calibration_baseline(self,reason):
        b=self.state.get('baseline')
        if b:self.state['history'].append({'reason':reason,'baseline':deepcopy(b)})
        self.state.update(baseline=None,baseline_active=False,angle='front',selected=None)
        self.event('calibration_changed',reason=reason)

    def set_body_view(self,angle,source):
        if angle not in ('front','side'):raise ValueError('请选择正面或正侧面。')
        c=self.calibration();key=self.add_asset(source)
        other='side' if angle=='front' else 'front'
        if key==c['body']['views'].get(other):raise ValueError('正侧面不能是同一张图片。')
        self.invalidate_calibration_baseline('体型参考图更换')
        c['body']['views'][angle]=key;c['body']['approved']=False;c.update(front=None,side=None,requests={})

    def approve_body_views(self,value):
        c=self.calibration()
        if value and set(c['body']['views'])!={'front','side'}:raise ValueError('请先导入正面与正侧面着装体型参考。')
        if c['body']['approved']==bool(value):return
        self.invalidate_calibration_baseline('体型确认更新');c['body']['approved']=bool(value)
        c.update(front=None,side=None,requests={});self.event('calibration_body_review',approved=bool(value))

    def calibration_signature(self,stage):
        c=self.calibration();data={'references':self.state['refs'],'body':c['body'],'stage':stage}
        if stage=='side':data['approved_front']=c['front']
        return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

    def calibration_package(self,path,stage):
        from identity_flow import archive_bytes,atomic_write
        if stage not in ('body','front','side'):raise ValueError('不支持的校准阶段。')
        c=self.calibration()
        if stage!='body' and not c['body']['approved']:raise ValueError('先确认正侧体型，再校准面部。')
        if stage=='side' and not (c['front'] and c['front']['approved']):raise ValueError('先确认正脸，再校准侧脸。')
        sources={r+'.png':v['asset'] for r,v in self.state['refs'].items()}
        if stage=='body':
            prompt='以后台body.png体型为约束、真实面部照片作身份参考，生成同一体型的正面和朝右90度侧面着装参考，各自完整全身。浅灰轻薄T恤、深灰长裤、白鞋、灰背景、中性放松表情。不得瘦身或夸大腹部。本步只检查体型，面部稍后单独校准。不要把白模头部当真人。'
        else:
            sources={'original_face.png':self.state['refs']['face_'+stage]['asset'],'edit_target.png':c['body']['views'][stage]}
            if stage=='side':sources['approved_front.png']=c['front']['asset']
            prompt=('以original_face.png原始照片为主要身份依据，局部校正edit_target.png的头脸、眼镜、发型，仅最小化融合颈部。'
                '保留身体体积、腹部厚度、臀腿、衣物、动作、镜头和背景，不瘦脸，不美颜，不改变表情。'
                '原始照片衣物和房间不要带入结果，输出一张完整全身图。')
            prompt+=('保持正面。原始正脸是本步唯一身份来源，编辑目标中的旧脸不作身份标准。' if stage=='front' else
                '保持朝右正侧面，approved_front.png仅校对已确认身份。若原始侧脸实际是微侧脸，正侧轮廓仍需模型补全，不得当精确还原。')
        request={'id':uuid4().hex,'stage':stage,'signature':self.calibration_signature(stage),'sources':sources}
        files={name:self.assets[key] for name,key in sources.items()};files['生成要求.txt']=prompt.encode('utf-8')
        files['操作说明.txt']='手动交给聊天生图后导回本阶段。程序未自动上传。请核对结果对应本包；确认后才能进入下一步。'.encode('utf-8')
        atomic_write(path,archive_bytes({'schema':'veylfit.calibration-request.v1',**request},files))
        if stage!='body':
            self.invalidate_calibration_baseline('导出新一轮'+stage+'校准')
            c[stage]=None
            if stage=='front':c['side']=None;c['requests'].pop('side',None)
        c['requests'][stage]=request;self.event('calibration_package_exported',request=deepcopy(request));return request

    def put_calibration_result(self,stage,source,belongs_to_request):
        if stage not in ('front','side') or belongs_to_request is not True:raise ValueError('请确认图片属于本阶段、本次生成包。')
        c=self.calibration();request=c['requests'].get(stage)
        if not request or request['signature']!=self.calibration_signature(stage):raise ValueError('校准任务不存在或输入已变更，请重新导出。')
        key=self.add_asset(source)
        if key in request['sources'].values():raise ValueError('这是输入参考，请导入生成的校准结果。')
        self.invalidate_calibration_baseline('替换'+stage+'校准结果')
        c[stage]={'asset':key,'request_id':request['id'],'signature':request['signature'],'approved':False,'body_preserved':False}
        if stage=='front':c['side']=None;c['requests'].pop('side',None)

    def approve_calibration(self,stage,face_ok,body_preserved):
        if stage not in ('front','side'):raise ValueError('校准角度无效。')
        c=self.calibration();item=c[stage]
        if not item:raise ValueError('请先导入本阶段结果。')
        if item['signature']!=self.calibration_signature(stage):raise ValueError('结果已过期。')
        if face_ok and not body_preserved:raise ValueError('请同时确认体型、衣物、背景未出现明显变化。')
        self.invalidate_calibration_baseline('更新'+stage+'确认')
        item.update(approved=bool(face_ok),body_preserved=bool(body_preserved))
        if stage=='front':c['side']=None;c['requests'].pop('side',None)
        self.event('calibration_face_review',stage=stage,approved=item['approved'],body_preserved=item['body_preserved'])

    def freeze_calibration(self,note):
        c=self.calibration()
        if not c['body']['approved'] or not all(c[k] and c[k]['approved'] and c[k]['body_preserved'] for k in ('front','side')):raise ValueError('必须先依次确认体型、正脸、侧脸。')
        self.validate_calibration()
        self.freeze_baseline({k:self.assets[c[k]['asset']] for k in ('front','side')},note,label='逐步校准 · 已确认正面 / 正侧面')
        self.state['baseline']['calibration_signature']=self.calibration_signature('side')

    def validate_calibration(self):
        c=self.state.get('calibration')
        if c is None:return
        if c.get('version')!=1 or c.get('fingerprint')!=self.fingerprint():raise ValueError('校准来源不一致。')
        body=c['body']
        if type(body['approved']) is not bool or set(body['views'])-{'front','side'}:raise ValueError('体型校准记录无效。')
        for key in body['views'].values():self.assets[key]
        if body['approved'] and (set(body['views'])!={'front','side'} or len(set(body['views'].values()))!=2):raise ValueError('缺少不同的正侧体型图。')
        for stage in ('front','side'):
            item=c[stage]
            if item:
                self.assets[item['asset']];r=c['requests'].get(stage)
                if not r or item['request_id']!=r['id'] or item['signature']!=r['signature'] or item['signature']!=self.calibration_signature(stage):raise ValueError('校准结果与请求不一致。')
                expected={'original_face.png':self.state['refs']['face_'+stage]['asset'],'edit_target.png':body['views'][stage]}
                if stage=='side':expected['approved_front.png']=c['front']['asset']
                if r.get('stage')!=stage or r.get('sources')!=expected or item['asset'] in expected.values():raise ValueError('校准素材与结果来源不一致。')
                if type(item['approved']) is not bool or type(item['body_preserved']) is not bool:raise ValueError('校准确认记录无效。')
                if not body['approved'] or (stage=='side' and not(c['front'] and c['front']['approved'])):raise ValueError('校准确认顺序错误。')
                if item['approved'] and not item['body_preserved']:raise ValueError('尚未确认体型保持。')
        b=self.state.get('baseline')
        if b and b.get('calibration_signature'):
            if not all(c[k] and c[k]['approved'] for k in ('front','side')) or b['calibration_signature']!=self.calibration_signature('side'):raise ValueError('固定基准的校准确认失效。')
            if any(b['views'][k]['asset']!=c[k]['asset'] for k in ('front','side')):raise ValueError('固定图与校准结果不一致。')
