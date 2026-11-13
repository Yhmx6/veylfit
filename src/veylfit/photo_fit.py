"""Reviewed 2D calipers -> bounded regional mesh corrections, never true tape measurements."""
from copy import deepcopy
import hashlib, math
import numpy as np
from PIL import Image, ImageDraw
import shape_engine as sh
from makehuman_fit import Section

VERSION = 'photo-calipers-v1'
REGIONS = {'abdomen':('腹部',.63), 'hips':('臀部',.522), 'thigh':('单侧大腿中段',.425)}
MODES = {'clear':'轮廓清楚', 'loose':'衣物外沿（仅作上限）', 'skip':'遮挡 / 不采用'}

def hashes(photos):
    return {k:hashlib.sha256(v).hexdigest() for k,v in photos.items()}

def propose(captures, photos, height):
    views={}
    for role,cap in captures.items():
        w,h=cap.image.size; p=cap.points; mask=cap.segmentation
        crown=list(p['crown']);ground=list(p['ground'])
        if mask is not None:
            ys,xs=np.where(mask>.65)
            if len(ys): crown[1]=float(ys.min());ground[1]=float(ys.max())
        span=max(10,ground[1]-crown[1]);cx=np.mean([p[k][0] for k in ('left_hip','right_hip')])
        rows={}
        for key,(_,level) in REGIONS.items():
            y=ground[1]-level*span
            center=cx
            if key=='thigh' and role=='front':
                center=(p['left_hip'][0]+p['left_knee'][0])/2
            ends=[center-span*.09,center+span*.09]
            if mask is not None:
                row=mask[int(np.clip(y,0,h-1))]>.65
                edges=np.diff(np.r_[False,row,False].astype(int));runs=list(zip(np.where(edges==1)[0],np.where(edges==-1)[0]-1))
                runs=[r for r in runs if r[1]-r[0]>5]
                if runs:
                    a,b=min(runs,key=lambda r:abs((r[0]+r[1])/2-center));ends=[float(a),float(b)]
            rows[key]={'a':[float(np.clip(ends[0],0,w-1)),float(y)],'b':[float(np.clip(ends[1],0,w-1)),float(y)],'mode':'skip'}
        views[role]={'size_px':[w,h],'crown':crown,'ground':ground,'roll_degrees':cap.roll,'rows':rows}
    return {'version':VERSION,'photo_hashes':hashes(photos),'height_cm':height,'reviewed':False,'reviewer':'unreviewed','views':views}

def validate(cal, photos=None, height=None):
    if not isinstance(cal,dict) or cal.get('version')!=VERSION: raise ValueError('照片校正版本不支持。')
    if type(cal.get('reviewed')) is not bool or cal.get('reviewer') not in ('unreviewed','user','operator'):raise ValueError('照片校正审核状态错误。')
    if not isinstance(cal.get('photo_hashes'),dict) or set(cal['photo_hashes'])!={'front','side'}:raise ValueError('照片校正来源错误。')
    if photos is not None and cal['photo_hashes']!=hashes(photos):raise ValueError('照片已更换，请重新检查校正标记。')
    if height is not None and cal.get('height_cm')!=height:raise ValueError('身高已变化，请重新检查照片标尺。')
    if set(cal.get('views',{}))!={'front','side'}:raise ValueError('校正需要正侧两组标记。')
    for view in cal['views'].values():
        w,h=view['size_px']
        if not all(type(n) is int and 100<=n<=2400 for n in (w,h)):raise ValueError('标记画布大小错误。')
        def point(p):
            if not isinstance(p,list) or len(p)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in p) or not 0<=p[0]<w or not 0<=p[1]<h:raise ValueError('照片标记超出画面。')
        for k in ('crown','ground'):point(view[k])
        if not isinstance(view['roll_degrees'],(int,float)) or not math.isfinite(view['roll_degrees']) or abs(view['roll_degrees'])>10:raise ValueError('倾斜校正只支持±10度，请重拍明显倾斜的照片。')
        span=view['ground'][1]-view['crown'][1]
        if span<h*.35:raise ValueError('请检查头顶和脚底标尺。')
        if set(view['rows'])!=set(REGIONS):raise ValueError('部位标记缺失。')
        for key,row in view['rows'].items():
            point(row['a']);point(row['b'])
            if row['mode'] not in MODES:raise ValueError('轮廓可见性选项错误。')
            if row['mode']=='skip':continue
            dx=row['b'][0]-row['a'][0]
            if not .025*span<dx<.40*span or abs(row['a'][1]-row['b'][1])>.08*span:raise ValueError('请把两端放在同一身体截面的两侧。')
            level=(view['ground'][1]-(row['a'][1]+row['b'][1])/2)/span
            if not {'abdomen':(.48,.75),'hips':(.38,.65),'thigh':(.28,.53)}[key][0]<level<{'abdomen':(.48,.75),'hips':(.38,.65),'thigh':(.28,.53)}[key][1]:raise ValueError('部位高度偏离范围，请检查标记。')
    return cal

def dimensions(body):
    out={};height=body.settings.height_cm/100
    for key,(_,level) in REGIONS.items():
        sec=Section(body.vertices,body.faces,level*height)
        if key=='thigh':
            loops=[p for _,_,_,p in sec.components if p[:,0].mean()>0 and np.ptp(p[:,0])>.02]
            if not loops:raise ValueError('大腿截面不完整。')
            p=max(loops,key=lambda p:len(p))
        else:
            if sec.torso is None:raise ValueError('躯干截面不完整。')
            p=sec.torso[3]
        out[key]={'width_cm':float(np.ptp(p[:,0])*100),'depth_cm':float(np.ptp(p[:,2])*100)}
    return out

def observations(cal):
    result=[]
    for role,view in cal['views'].items():
        angle=math.radians(view['roll_degrees']);c,s=math.cos(angle),math.sin(angle)
        def rotate(p):return np.array([c*p[0]+s*p[1],-s*p[0]+c*p[1]])
        scale=cal['height_cm']/(rotate(view['ground'])[1]-rotate(view['crown'])[1])
        for key,row in view['rows'].items():
            if row['mode']=='skip':continue
            length=abs(rotate(row['b'])[0]-rotate(row['a'])[0])*scale
            result.append({'view':role,'region':key,'axis':'width_cm' if role=='front' else 'depth_cm','photo_projection_cm':float(length),'mode':row['mode']})
    return result

def fit(body,cal,photos):
    validate(cal,photos,body.settings.height_cm)
    if not cal['reviewed']:raise ValueError('请先检查原图标记，自动候选线不会直接改变体型。')
    obs=observations(cal)
    if not obs:raise ValueError('至少选择一条可采用的轮廓。')
    before=dimensions(body);targets=[];warnings=[]
    for o in obs:
        current=before[o['region']][o['axis']];target=o['photo_projection_cm']
        # Clothes define an upper bound: never inflate the body to a loose garment edge.
        weight=.2 if o['mode']=='loose' else .65
        if o['mode']=='loose':target=min(target,current)
        ratio=target/current
        if not .65<=ratio<=1.5:raise ValueError('照片轮廓与基础体型相差过大，请复查标尺、拍摄角度及轮廓。')
        desired=current+weight*(target-current)
        o.update(before_cm=current,weighted_target_cm=desired,weight=weight)
        targets.append(desired)
    params=np.zeros(6);height=body.settings.height_cm/100
    _,_,_,weights,jweights=sh.base()
    # Independent width/depth basis, softly blended over height. Same field moves joints.
    def warp(points,w,p):
        x,y,z=points.T;yn=y/height;arm,leg,neck,head=w.T
        trunk=np.clip(1-arm-neck,0,1)*(1-sh.smooth(head/.55))
        out=points.copy();side=np.where(x>=0,1.,-1.)
        # Baseline mesh centers make thigh scaling independent of the A-pose stance width.
        sec=Section(body.vertices,body.faces,.425*height)
        lp=max([v for _,_,_,v in sec.components if v[:,0].mean()>0],key=len)
        cx=side*float(lp[:,0].mean());cz=float(lp[:,2].mean())
        for i,(key,(_,level)) in enumerate(REGIONS.items()):
            influence=sh.bell(yn,level,.115 if key=='abdomen' else .095 if key=='hips' else .14)
            influence*=trunk if key!='thigh' else leg
            out[:,0]+=(x if key!='thigh' else x-cx)*p[2*i]*influence
            # Belly expands forward; hip depth expands towards the back, not the crotch.
            anchor=(-.09*height/1.86 if key=='abdomen' else .095*height/1.86 if key=='hips' else cz)
            out[:,2]+=(z-anchor)*p[2*i+1]*influence
        return out
    def evaluate(p):
        v=warp(body.vertices,weights,p)
        candidate=sh.Body(body.settings,v,body.faces,body.joints,{})
        d=dimensions(candidate)
        return v,np.array([d[o['region']][o['axis']] for o in obs])
    target=np.array(targets)
    for _ in range(12):
        _,current=evaluate(params)
        if np.max(np.abs(target-current))<.04:break
        jac=np.column_stack([(evaluate(params+np.eye(6)[i]*.001)[1]-current)/.001 for i in range(6)])
        delta=np.linalg.lstsq(np.vstack([jac,np.eye(6)*.5]),np.r_[target-current,np.zeros(6)],rcond=None)[0]
        params=np.clip(params+np.clip(delta,-.08,.08),-.20,.20)
    vertices,_=evaluate(params);joints=warp(body.joints,jweights,params)
    gaps=[Section(vertices,body.faces,p*height).has_gaps(n) for p,n in ((.61,3),(.65,3),(.29,2),(.36,2))]
    if not np.isfinite(vertices).all() or not np.isfinite(joints).all() or not all(gaps):raise ValueError('照片校正未通过几何检查；请降低约束或修正轮廓。')
    if abs(np.ptp(vertices[:,1])*100-body.settings.height_cm)>.05:raise ValueError('照片校正改变了身高。')
    report=deepcopy(body.report);report.update(engine=VERSION,base_engine=body.report['engine'],gap_checks=gaps)
    candidate=sh.Body(body.settings,vertices,body.faces,joints,report);after=dimensions(candidate)
    for o in obs:
        o['after_cm']=after[o['region']][o['axis']];o['residual_to_weighted_target_cm']=o['after_cm']-o['weighted_target_cm']
    if any(abs(o['residual_to_weighted_target_cm'])>.5 for o in obs):warnings.append('受限形变未完全达到加权目标，不强行拉伸。')
    # Refresh all reported mesh sections; never carry stale pre-fit dimensions.
    for key,old in report['mesh_sections'].items():
        sec=Section(vertices,body.faces,old['level_fraction']*height);p=sec.torso[3]
        old.update(girth_cm=round(sec.girth(vertices),2),width_cm=round(np.ptp(p[:,0])*100,2),depth_cm=round(np.ptp(p[:,2])*100,2))
    report['photo_fit']={'version':VERSION,'before':before,'after':after,'constraints':obs,'parameters':params.tolist(),
        'reviewer':cal['reviewer'],'warnings':warnings,'leg_lengths':'unchanged; perspective and clothing prevent reliable length recovery',
        'limitations':['2D approximate scale; no perspective reconstruction','clothing/occlusion remains uncertain','not real tape measurements or body approval']}
    return candidate

def overlay(image,view):
    im=image.copy();d=ImageDraw.Draw(im)
    for k in ('crown','ground'):
        x,y=view[k];d.line((0,y,im.width,y),fill='#ffdb65',width=2);d.ellipse((x-5,y-5,x+5,y+5),fill='#ffdb65')
    for key,row in view['rows'].items():
        color={'abdomen':'#ff7043','hips':'#00aee8','thigh':'#24c873'}[key]
        d.line((*row['a'],*row['b']),fill=color,width=3)
        for x,y in (row['a'],row['b']):d.ellipse((x-5,y-5,x+5,y+5),fill=color)
    return im
