"""Optional tape-measure constraints on a skinned template; not a body scan."""
from copy import deepcopy
from functools import lru_cache
import numpy as np
import shape_engine as sh
from makehuman_fit import Template, Section

VERSION='six-measurements-v1'
LEVELS={'chest':.724,'waist':.66,'abdomen':.63,'hips':.522}
LIMITS={'chest':(65,165),'waist':(50,165),'abdomen':(55,175),
        'hips':(65,170),'shoulder_width':(30,60),'inseam':(55,110)}
LABELS={'chest':'胸围','waist':'自然腰围','abdomen':'腹围','hips':'臀围','shoulder_width':'肩宽','inseam':'腿内长'}

def validate(values,height):
    clean={k:values.get(k) for k in LIMITS}
    if set(values)-set(LIMITS):raise ValueError('存在未知尺寸项目。')
    for k,v in clean.items():
        if v is None:continue
        lo,hi=LIMITS[k]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) or not lo<=v<=hi:
            raise ValueError(f'{LABELS[k]}超出本版可拟合范围（{lo}–{hi} cm），请复测或留空。')
        clean[k]=float(v)
    if clean['inseam'] is not None and not .38<=clean['inseam']/height<=.55:
        raise ValueError('腿内长与身高比例超出本版范围，请按裆点到地面的垂直高度复测。')
    return clean

@lru_cache(maxsize=1)
def landmarks():
    t=Template('male');v=t.array(t.attrs['POSITION']).astype(float);h=np.ptp(v[:,1])
    center=np.where((abs(v[:,0])<.006*h)&(v[:,1]>.35*h)&(v[:,1]<.60*h))[0]
    crotch=int(center[np.argmin(v[center,1])])
    anchors=[]
    for side in ('L','R'):
        i=next(i for i,n in enumerate(t.nodes) if n.get('name')=='upperarm01.'+side)
        point=t.world[i][:3,3].copy();point[1]+=.02*h;point[0]+=(1 if side=='L' else -1)*.006*h
        anchors.append(int(np.argmin(np.linalg.norm(v-point,axis=1))))
    return crotch,anchors

def lengths(vertices):
    crotch,shoulders=landmarks()
    return dict(height=float(np.ptp(vertices[:,1])*100),
                inseam=float((vertices[crotch,1]-vertices[:,1].min())*100),
                shoulder_width=float(abs(vertices[shoulders[0],0]-vertices[shoulders[1],0])*100))

def fit(body,values):
    values=validate(values,body.settings.height_cm)
    if not any(v is not None for v in values.values()):return body
    h=body.settings.height_cm/100
    v0=body.vertices.copy();j0=body.joints.copy();floor=float(v0[:,1].min())
    old_crotch=v0[landmarks()[0],1]-floor
    new_crotch=values['inseam']/100 if values['inseam'] is not None else old_crotch
    # Monotone y map: feet and crown stay fixed, upper shoulder/head unscaled.
    def map_y(y):
        return np.interp(y-floor,[0,old_crotch,.83*h,h],[0,new_crotch,.83*h,h])+floor
    v0[:,1]=map_y(v0[:,1]);j0[:,1]=map_y(j0[:,1])
    levels={k:float(map_y(np.array([fraction*h+floor]))[0]) for k,fraction in LEVELS.items()}
    sections={k:Section(v0,body.faces,level) for k,level in levels.items()}
    keys=[k for k in LEVELS if values[k] is not None]
    shoulder=values['shoulder_width'] is not None
    n=len(keys)+int(shoulder)
    _,_,_,weights,jweights=sh.base()
    # Hat basis separates the nearby natural waist and umbilical abdomen constraints.
    order=sorted(LEVELS,key=lambda k:levels[k]);knots=[float(map_y(np.array([.43*h+floor]))[0])]+[levels[k] for k in order]+[.81*h+floor]
    def basis(points):
        cols=[]
        for key in keys:
            vals=np.zeros(len(knots));vals[order.index(key)+1]=1
            cols.append(np.interp(points[:,1],knots,vals,left=0,right=0))
        return np.stack(cols,axis=1) if cols else np.zeros((len(points),0))
    vb,jb=basis(v0),basis(j0)
    ax=max(abs(v0[landmarks()[1],0]))
    def warp(points,w,b,params):
        out=points.copy();arm,leg,neck,head=w.T
        if keys:
            influence=np.clip(1-arm-neck,0,1)*(1-sh.smooth(head/.55))
            factor=np.exp((b@params[:len(keys)])*influence)
            out[:,[0,2]]*=factor[:,None]
        if shoulder:
            band=sh.bell(points[:,1]/h,.815,.12)*(1-sh.smooth(head/.55))
            transition=arm+(1-arm)*band*np.clip(abs(points[:,0])/ax,0,1)
            out[:,0]+=np.sign(points[:,0])*params[-1]*transition
        return out
    target=np.array([values[k] for k in keys]+([values['shoulder_width']] if shoulder else []))
    def evaluate(params):
        v=warp(v0,weights,vb,params)
        measured=[sections[k].girth(v) for k in keys]
        if shoulder:measured.append(lengths(v)['shoulder_width'])
        return v,np.array(measured)
    params=np.zeros(n)
    if n:
        for _ in range(24):
            vertices,current=evaluate(params);error=target-current
            if np.max(abs(error))<.03:break
            delta=np.eye(n)*.0005
            jac=np.column_stack([(evaluate(params+d)[1]-current)/.0005 for d in delta])
            step=np.linalg.lstsq(jac,error,rcond=None)[0]
            accepted=False
            for rate in (1,.5,.25,.1):
                trial=params+rate*step
                trial[:len(keys)]=np.clip(trial[:len(keys)],np.log(.60),np.log(1.60))
                if shoulder:trial[-1]=np.clip(trial[-1],-.09,.09)
                if np.linalg.norm(target-evaluate(trial)[1])<np.linalg.norm(error):
                    params=trial;accepted=True;break
            if not accepted:break
    vertices,_=evaluate(params)
    joints=warp(j0,jweights,jb,params)
    # Measure float32 values as used in export rather than just solver doubles.
    vertices=vertices.astype(np.float32).astype(float)
    actual={k:Section(vertices,body.faces,levels[k]).girth(vertices) for k in LEVELS}
    actual.update(lengths(vertices))
    rows={k:dict(input_cm=values[k],model_cm=round(actual[k],4),difference_cm=None if values[k] is None else round(actual[k]-values[k],4),
                  applied=values[k] is not None,source='user_entered_unverified',
                  section_height_cm=round(levels[k]*100,4) if k in levels else None) for k in LIMITS}
    failed=[LABELS[k] for k,row in rows.items() if row['applied'] and abs(row['difference_cm'])>.3]
    if failed:raise ValueError('这些尺寸无法在当前体型上稳定拟合：'+ '、'.join(failed)+'。请复测或选择更接近的体型。')
    if abs(actual['height']-body.settings.height_cm)>.05:raise ValueError('尺寸拟合未保持身高。')
    gaps=[Section(vertices,body.faces,float(map_y(np.array([f*h+floor]))[0])).has_gaps(count) for f,count in ((.61,3),(.65,3),(.29,2),(.36,2))]
    if not all(gaps):raise ValueError('该尺寸组合造成四肢间隙不足，请复测或调整体型选项；未保存失败模型。')
    report=deepcopy(body.report)
    report['measurement_fit']=dict(version=VERSION,rows=rows,height_cm=actual['height'],gap_checks=gaps,
        tolerance_cm=.3,priority='reviewed_photo_first_then_user_measurements',
        definition='Template chest/waist/umbilical/hip proxy planes; shoulder surface landmarks; vertical perineum-to-floor inseam. Numerical mesh agreement is not anatomical accuracy.',
        limitations=['template landmark locations approximate anatomy','self-entered measurements not independently verified','not a scan or garment size guarantee'])
    warnings=[]
    if report.get('photo_fit'):
        for observation in report['photo_fit']['constraints']:
            region=observation['region']
            fraction={'abdomen':.63,'hips':.522,'thigh':.425}[region]
            section=Section(vertices,body.faces,float(map_y(np.array([fraction*h+floor]))[0]))
            if region=='thigh':
                loops=[p for _,_,_,p in section.components if p[:,0].mean()>0]
                points=max(loops,key=len) if loops else None
            else:points=section.torso[3] if section.torso else None
            if points is None:continue
            axis=0 if observation['axis']=='width_cm' else 2
            observed=observation['photo_projection_cm'];model=float(np.ptp(points[:,axis])*100)
            differs=(model>observed+max(3,.1*observed)) if observation['mode']=='loose' else abs(model-observed)>max(3,.1*observed)
            if differs:warnings.append('填写尺寸约束后的'+{'abdomen':'腹部','hips':'臀部','thigh':'大腿'}[region]+'与照片投影有差异，请复核测量位置、衣物和拍摄角度。')
    report['measurement_fit']['warnings']=list(dict.fromkeys(warnings))
    report['mesh_sections']={k:dict(level_fraction=levels[k]/h,girth_cm=round(actual[k],2),
        width_cm=round(float(np.ptp(Section(vertices,body.faces,levels[k]).torso[3][:,0])*100),2),
        depth_cm=round(float(np.ptp(Section(vertices,body.faces,levels[k]).torso[3][:,2])*100),2)) for k in LEVELS}
    result=sh.Body(body.settings,vertices,body.faces,joints,report)
    result.glb()  # Reject degenerate faces/normals and verify skeleton encoding before returning.
    return result
