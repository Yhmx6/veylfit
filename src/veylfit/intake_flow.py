"""Local intake records with optional, explicitly reviewed photo constraints."""
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from dataclasses import asdict
import hashlib,json,math
from PIL import Image,ImageOps
import shape_engine as shapes

SCHEMA='veylfit.intake.v1'
MEASURES={'chest':'胸围','waist':'自然腰围','abdomen':'脐水平腹围','hips':'臀围','shoulder_width':'肩宽','inseam':'人体腿内长'}
ROLES=('front','side')

def new_state():
    return {'schema':SCHEMA,'basic':{'gender':'','height_cm':'','weight_kg':'','age_years':''},'choices':{},
            'measurements':{k:None for k in MEASURES},'photos_confirmed':False,'step':0,'photo_fit':None}

def basic_values(state):
    b=state['basic']
    if b.get('gender') not in ('male','female'):raise ValueError('请选择性别。')
    try:
        height=float(b['height_cm']);weight=float(b['weight_kg']);age=float(b['age_years'])
    except (ValueError,TypeError,KeyError):raise ValueError('请填写身高、体重和整数年龄。') from None
    if not math.isfinite(age) or age!=int(age) or not 1<=age<=120:raise ValueError('年龄请填写1–120之间的整数。')
    shapes.Settings(height_cm=height,weight_kg=weight).validated()
    return dict(gender=b['gender'],height_cm=height,weight_kg=weight,age_years=int(age))

def parse_measures(values):
    result={}
    for key,label in MEASURES.items():
        raw=values.get(key)
        if raw is None or str(raw).strip()=='':result[key]=None;continue
        try:value=float(raw)
        except (TypeError,ValueError):raise ValueError(label+'请填厘米数或留空。') from None
        if not math.isfinite(value) or not 0<value<=300:raise ValueError(label+'请填大于0且不超过300的厘米数，或留空。')
        result[key]=value
    return result

def photo_bytes(raw):
    if len(raw)>30*1024**2:raise ValueError('照片超过30MiB，请缩小文件后导入。')
    with Image.open(BytesIO(raw)) as im:
        if im.format not in ('JPEG','PNG','WEBP') or im.width*im.height>25_000_000:raise ValueError('请选择2500万像素以内的JPG、PNG或WebP。')
        if min(im.size)<300:raise ValueError('照片短边至少300像素，请使用清晰原照。')
        image=ImageOps.exif_transpose(im).convert('RGB');image.load()
    image.thumbnail((2400,2400),Image.Resampling.LANCZOS)
    buffer=BytesIO();image.save(buffer,'JPEG',quality=94)
    return buffer.getvalue()

def import_photo(path):
    p=Path(path)
    if p.stat().st_size>30*1024**2:raise ValueError('照片超过30MiB。')
    return photo_bytes(p.read_bytes())

def fingerprint(state,photos):
    data={'state':{k:v for k,v in state.items() if k!='step'},'photos':{k:hashlib.sha256(v).hexdigest() for k,v in photos.items()}}
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def shape_settings(state):
    b=basic_values(state);c=state['choices']
    if b['gender']!='male':raise ValueError('女性资料可以保存；女性部位选项和本轮建模尚未接入。')
    if b['age_years']<18:raise ValueError('本轮体型测试使用成人模板，未成年人资料暂只保存草稿。')
    if c.get('family') not in shapes.FAMILIES:raise ValueError('请确认整体体型。')
    if any(type(c.get(k)) is not int or c[k] not in (0,1,2) for k in shapes.GROUPS):raise ValueError('请完成四个部位选择。')
    return shapes.Settings(height_cm=b['height_cm'],weight_kg=b['weight_kg'],body_family=c['family'],**{k:c[k] for k in shapes.GROUPS}).validated()

def validate_complete(state,photos):
    settings=shape_settings(state);parse_measures(state['measurements'])
    if set(photos)!=set(ROLES):raise ValueError('请导入正面、侧面全身照各一张。')
    if photos['front']==photos['side']:raise ValueError('两张照片相同，请分别导入正面和侧面。')
    if state['photos_confirmed'] is not True:raise ValueError('请检查并确认两张照片。')
    return settings

def process(state,photos):
    settings=validate_complete(state,photos)
    import engine as pose
    import photo_fit as pf
    analyses={};captures={}
    # Analyze in memory; avoid writing another set of private photos to a temp folder.
    for role in ROLES:
        cap=pose.analyze_bytes(photos[role],role,with_mask=True);captures[role]=cap
        analyses[role]={'size_px':list(cap.image.size),'roll_degrees_estimate':cap.roll,
            'points':{k:list(v) for k,v in cap.points.items()},'visibility':cap.visibility,
            'quality_status':'manual_landmark_review_required'}
    body=shapes.build(settings)
    cal=state.get('photo_fit')
    if cal is not None:
        pf.validate(cal,photos,settings.height_cm)
        if any(cal['views'][role]['size_px']!=list(captures[role].image.size) for role in ROLES):raise ValueError('照片标记尺寸已失效，请重新检查。')
    applied=bool(cal and cal['reviewed'])
    if applied:body=pf.fit(body,cal,photos)
    import measurement_fit
    values=measurement_fit.validate(parse_measures(state['measurements']),settings.height_cm)
    body=measurement_fit.fit(body,values)
    proposal=cal or pf.propose(captures,photos,settings.height_cm)
    report={'input_fingerprint':fingerprint(state,photos),'geometry_inputs':['height_cm','weight_kg','family','arms','torso','legs','neck'],
        'recorded_not_fitted':['age_years']+(['measurements'] if not any(v is not None for v in values.values()) else [])+([] if applied else ['photos']),'photo_analysis':analyses,
        'body_report':body.report,'status':'photo_corrected_pending_user_review' if applied else 'photo_markers_need_review','face_body_approved':False,
        'photo_fit_applied':applied,'photo_fit_proposal':proposal}
    if applied:report['geometry_inputs'].append('reviewed_photo_calipers')
    if any(v is not None for v in values.values()):report['geometry_inputs'].append('user_measurements')
    return body,report

def validate_state(state):
    if not isinstance(state,dict) or state.get('schema')!=SCHEMA:raise ValueError('不是本版建档文件。')
    state.setdefault('photo_fit',None) # Additive migration for existing v1 intake archives.
    if set(state)!=set(new_state()):raise ValueError('档案字段不完整或不支持。')
    if not isinstance(state['basic'],dict) or set(state['basic'])!=set(new_state()['basic']):raise ValueError('基本资料格式错误。')
    if any(not isinstance(v,str) or len(v)>64 for v in state['basic'].values()):raise ValueError('基本资料格式错误。')
    c=state['choices']
    if not isinstance(c,dict) or set(c)-{'family',*shapes.GROUPS}:raise ValueError('体型选项格式错误。')
    if 'family' in c and c['family'] not in shapes.FAMILIES:raise ValueError('体型类别错误。')
    if any(type(v) is not int or v not in (0,1,2) for k,v in c.items() if k!='family'):raise ValueError('部位选项错误。')
    if not isinstance(state['measurements'],dict) or set(state['measurements'])!=set(MEASURES):raise ValueError('尺寸字段错误。')
    state['measurements']=parse_measures(state['measurements'])
    if type(state['photos_confirmed']) is not bool or type(state['step']) is not int or not 0<=state['step']<=8:raise ValueError('流程状态错误。')
    if state['photo_fit'] is not None:
        import photo_fit
        photo_fit.validate(state['photo_fit'])
    return state

def save_project(path,state,photos,result=None):
    validate_state(json.loads(json.dumps(state)))
    if set(photos)-set(ROLES):raise ValueError('照片角色错误。')
    path=Path(path)
    if path.resolve().is_relative_to((Path(__file__).parent/'templates').resolve()):raise ValueError('请另存档案，不能覆盖固定人物模板。')
    meta={'state':state,'photos':{k:{'file':'photos/'+k+'.jpg','sha256':hashlib.sha256(v).hexdigest()} for k,v in photos.items()}}
    if result is not None:
        if result[1]['input_fingerprint']!=fingerprint(state,photos):raise ValueError('输入已变化，请重新处理后保存结果。')
        validate_complete(state,photos)
    # Build completely before exclusive creation; never overwrite an existing file.
    buf=BytesIO()
    with ZipFile(buf,'w',ZIP_DEFLATED) as z:
        z.writestr('intake.json',json.dumps(meta,ensure_ascii=False,indent=2,allow_nan=False))
        for k,data in photos.items():z.writestr('photos/'+k+'.jpg',data)
        if result:
            z.writestr('body.glb',result[0].glb());z.writestr('report.json',json.dumps(result[1],ensure_ascii=False,indent=2,allow_nan=False))
    with path.open('xb') as out:out.write(buf.getvalue())

def load_project(path):
    if Path(path).stat().st_size>75*1024**2:raise ValueError('档案过大。')
    with ZipFile(path) as z:
        names=z.namelist();allowed={'intake.json','photos/front.jpg','photos/side.jpg','body.glb','report.json'}
        if len(names)!=len(set(names)) or set(names)-allowed:raise ValueError('档案包含重复或不支持的文件。')
        if any(i.file_size>30*1024**2 for i in z.infolist()) or sum(i.file_size for i in z.infolist())>100*1024**2:raise ValueError('档案解压大小超限。')
        if z.getinfo('intake.json').file_size>128*1024:raise ValueError('档案配置过大。')
        meta=json.loads(z.read('intake.json'));state=validate_state(meta['state']);photos={}
        if set(meta['photos'])-set(ROLES):raise ValueError('照片角色错误。')
        for role,item in meta['photos'].items():
            if item['file']!='photos/'+role+'.jpg':raise ValueError('照片路径错误。')
            raw=z.read(item['file'])
            if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('照片校验不一致。')
            photo_bytes(raw);photos[role]=raw
        if set(photos)!=set(ROLES):state['photos_confirmed']=False
    # Revalidate completion; saved geometry is never blindly loaded as a current result.
    state['step']=0
    return state,photos
