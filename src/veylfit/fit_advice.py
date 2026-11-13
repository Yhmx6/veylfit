"""Store a chat-AI visual ease recommendation, without inventing retail sizes."""
from copy import deepcopy
FITS={'relaxed':'略宽松','regular':'常规','slim':'偏修身'}
GOALS={'natural':'自然合身','slimming':'显瘦利落','structured':'突出轮廓','relaxed':'宽松休闲','custom':'其他效果'}
COLORS={'preserve':'保留衣物原色','recommend':'允许推荐配色'}
MODES={'faithful':'真实衣物试穿','styling':'搭配推荐'}

def validate_goal(goal,detail,color):
    if goal not in GOALS or color not in COLORS:raise ValueError('穿着效果或配色选项无效。')
    if not isinstance(detail,str) or len(detail)>500 or (goal=='custom' and not detail.strip()):raise ValueError('其他效果需填写说明，最多500字。')

def binding(person,garment):
    return {'person_id':person.get('baseline_id') or person.get('candidate_id'),
            'garment_id':garment['id'],'garment_revision':garment['revision']}

def validate(advice,person,garment,mode=None):
    if advice is None:return
    if not isinstance(advice,dict):raise ValueError('松量建议必须是结构化对象。')
    if advice.get('schema')!='veylfit.visual-fit-advice.v1' or advice.get('binding')!=binding(person,garment):raise ValueError('松量建议已过期，请按当前人物和衣物重新判断。')
    if advice.get('recommended') not in tuple(FITS) or advice.get('selected') not in tuple(FITS):raise ValueError('松量选项无效。')
    if advice.get('source') not in ('chat_ai_visual_assessment','user_preference'):raise ValueError('建议来源无效。')
    if advice.get('size_basis')!='unknown' or advice.get('retail_size') is not None:raise ValueError('此流程只处理无尺码表时的视觉松量，不支持推算品牌尺码。')
    validate_goal(advice.get('goal','natural'),advice.get('goal_detail',''),advice.get('color_policy','preserve'))
    if 'mode' in advice and advice['mode'] not in MODES:raise ValueError('建议模式无效。')
    if mode is not None and advice.get('mode')!=mode:raise ValueError('建议未绑定当前模式，请重新判断；历史建议不会自动当作实物还原。')
    if advice.get('mode')=='faithful' and advice.get('color_policy','preserve')!='preserve':raise ValueError('真实衣物试穿必须保留原色；需要改色请切换搭配推荐。')
    for key in ('reason','construction'):
        if not isinstance(advice.get(key),str) or not advice[key].strip() or len(advice[key])>1600:raise ValueError('请填写有效的松量理由及衣物表现要求。')

class FitAdvice:
    def tryon_mode(self):
        mode=self.state.get('tryon_mode','faithful')
        if mode not in MODES:raise ValueError('试衣模式无效。')
        return mode

    def set_tryon_mode(self,mode):
        if mode not in MODES:raise ValueError('试衣模式无效。')
        previous=self.tryon_mode()
        if mode==previous and 'tryon_mode' in self.state:return
        old=deepcopy(self.state.pop('fit_advice',None));self.state['tryon_mode']=mode
        self.event('tryon_mode_changed',previous=previous,mode=mode,retired_advice=old)

    def fit_analysis_package(self,path,goal=None,goal_detail=None,color_policy=None):
        import json
        from identity_flow import atomic_write,archive_bytes
        person=self.tryon_person();garment=self.garment_info()
        profile=self.profile_snapshot(require_ready=True)
        mode=self.tryon_mode()
        old=self.state.get('fit_advice') or {}
        if old.get('mode')!=mode:old={}
        goal=goal if goal is not None else old.get('goal','natural')
        goal_detail=goal_detail if goal_detail is not None else old.get('goal_detail','')
        color_policy=color_policy if color_policy is not None else old.get('color_policy','preserve')
        validate_goal(goal,goal_detail,color_policy)
        if mode=='faithful' and color_policy!='preserve':raise ValueError('真实衣物试穿不允许改色。')
        keys={'person.png':person['asset'],'garment.png':garment['asset']}
        if person['source']=='fixed_baseline':
            keys.update({'person_'+angle+'.png':v['asset'] for angle,v in self.fixed_baseline()['views'].items()})
        files={name:self.assets[key] for name,key in keys.items()}
        summary={k:deepcopy(profile[k]) for k in ('profile_id','revision','content_hash','basic','basic_source','measurements','shape_choices')}
        files['人物资料.json']=json.dumps(summary,ensure_ascii=False,indent=2).encode('utf-8')
        schema={'schema':'veylfit.visual-fit-advice.v1','binding':binding(person,garment),'recommended':'relaxed / regular / slim','selected':'same as recommended','reason':'解释对这位用户、这件衣服的建议；不默认某种体型必须显瘦','construction':'说明肩袖、胸腹、下摆、内搭及开合；不修改人体','source':'chat_ai_visual_assessment','size_basis':'unknown','retail_size':None}
        schema.update(goal=goal,goal_detail=goal_detail,color_policy=color_policy,mode=mode)
        files['返回格式.json']=json.dumps(schema,ensure_ascii=False,indent=2).encode('utf-8')
        files['判断要求.txt']=('根据已确认人物图及衣物图判断目标穿着松量。三选一：略宽松relaxed、常规regular、偏修身slim。'
            '只有图片，没有衣物尺寸或尺码表，不推断实际衣物偏大偏小，不输出M/L/XL、厘米范围或合身保证。'
            '结合可见肩胸腹、服装结构、厚薄及叠穿空间；如用户没有明确审美目标，用舒适自然作为临时目标并说明。'
            '未观察到的特征不要编造。按返回格式输出JSON，保留mode、binding、goal、goal_detail、color_policy，selected设为recommended的值。'
            +self.effect_prompt(schema)).encode('utf-8')
        atomic_write(path,archive_bytes({'schema':'veylfit.fit-analysis-request.v1','person_profile':summary,'mode':mode,'goal':goal,'goal_detail':goal_detail,'color_policy':color_policy,'binding':binding(person,garment),'garment_notes':garment['notes'],'asset_hashes':keys},files))
        self.event('fit_analysis_package_exported',binding=binding(person,garment))

    def set_fit_advice(self,recommended,reason,construction,source='chat_ai_visual_assessment',selected=None,goal='natural',goal_detail='',color_policy='preserve'):
        person=self.tryon_person();garment=self.garment_info()
        advice={'schema':'veylfit.visual-fit-advice.v1','binding':binding(person,garment),'recommended':recommended,
            'selected':selected or recommended,'reason':reason,'construction':construction,'source':source,
            'size_basis':'unknown','retail_size':None,'goal':goal,'goal_detail':goal_detail,'color_policy':color_policy,'mode':self.tryon_mode()}
        validate(advice,person,garment,self.tryon_mode());self.state['fit_advice']=advice
        self.event('fit_advice_recorded',advice=deepcopy(advice))

    def current_fit_advice(self):
        advice=self.state.get('fit_advice')
        if advice:validate(advice,self.tryon_person(),self.garment_info(),self.tryon_mode())
        return advice

    def effect_prompt(self,advice):
        advice=advice or {};goal=advice.get('goal','natural');color=advice.get('color_policy','preserve')
        if self.tryon_mode()=='faithful':
            return ('\n当前模式：真实衣物试穿。目标是还原用户导入的这件衣服，保留原色、图案、领口、袖型、衣长结构、版型及可见面料特征。'
                '用户想要的效果仅用于评价是否满足期待，不能据此改宽衣身、改短衣长、增加不存在的松量、替换面料或配色。'
                '衣料随真实身体自然变形和垂坠，不强行勾出肚腩，也不为显瘦重设计衣服。衣物尺寸未知时只提供款式外观近似预览；不能确定实际松紧或拉链能否闭合，不承诺合身。'
                '更合适的尺码、版型和颜色只能作为单独的搭配建议，不能混入本张还原图。未展示的背面或细节是未知，不当成已知事实。'
                '最高优先约束：保留原衣物与人物真实身体体积、肩宽、腰腹、臀腿、身高比例和脸，不缩腰、不收腹、不拉长腿，不改变姿势、表情与背景。'
                '若用户衣物说明或AI建议要求改色、加大或重设计，在本模式不执行；需要改衣服时切换搭配推荐。')
        text='\n穿着效果：'+GOALS[goal]+'。用户补充：'+(advice.get('goal_detail') or '无')+'。不从性别、年龄、身高、体重或体型推断用户一定要显瘦。'
        text='\n当前模式：搭配推荐，生成服装方案预览，不标为原衣物实物还原；仅按本次明确目标提出版型、松量、材质和组合建议，未指定的细节沿用参考。'+text
        if goal=='slimming':
            text+='只通过衣服实现显瘦：胸腹留出合理松量，面料越过腹部最凸处后自然垂落，侧缝顺直、下摆不过紧，减少贴腹横向拉扯褶；依材质保留真实厚度。配色可降低局部视觉强调，但深色不保证显瘦，不能涂黑抹掉纹理。'
        else:text+='按所选效果调整服装松量、材质垂坠与细节，不自动套用遮腹、深色或显瘦方案。'
        text+=('配色约束：保留参考衣物原色，不因显瘦目标擅自改色。' if color=='preserve' else '用户允许推荐配色：结合所选效果、风格和场景选择，保留图案与面料细节；不默认全部深色。')
        return text+'最高优先约束：效果只改变服装表现，不改人物真实身体体积、肩宽、腰腹、臀腿、身高比例或脸；不收腹、缩腰、拉长腿，不改姿势和背景来制造效果。衣物轮廓不等于身体轮廓。若其他说明冲突，以真实体型和本次明确选择的效果及配色约束为准。'

    def fit_prompt(self,advice):
        if not advice:return self.effect_prompt(None)
        if self.tryon_mode()=='faithful':
            return ('\n用户期待：'+GOALS[advice.get('goal','natural')]+'；松量偏好：'+FITS[advice['selected']]+'。这些是评价标准，不是修改实物衣服的指令。'+self.effect_prompt(advice))
        return ('\n视觉松量建议已纳入本次任务：'+FITS[advice['selected']]+'。判断理由：'+advice['reason']+
            '。衣物实现要求：'+advice['construction']+'。只调整衣服的剪裁、松量及自然垂坠，人体尺寸和体型保持原基准。'
            '衣物实际尺寸未知；这是目标穿着观感，不能标成品牌尺码或真实尺码适配结论。'+self.effect_prompt(advice))
