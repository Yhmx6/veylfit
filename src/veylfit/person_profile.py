"""Versioned local person contract shared by intake and manual try-on."""
from copy import deepcopy
import hashlib
import json
import math

SCHEMA = 'veylfit.person-profile.v1'
MEASURES = ('chest', 'waist', 'abdomen', 'hips', 'shoulder_width', 'inseam')

def checksum(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False).encode('utf-8')).hexdigest()

def payload(profile):
    return {k: v for k, v in profile.items() if k not in ('revision', 'content_hash')}

def validate_profile(profile, assets):
    if profile.get('schema') != SCHEMA or not isinstance(profile.get('profile_id'), str):
        raise ValueError('人物档案格式不支持。')
    if type(profile.get('revision')) is not int or profile['revision'] < 1:
        raise ValueError('人物档案版本无效。')
    if profile.get('content_hash') != checksum(payload(profile)):
        raise ValueError('人物档案内容校验失败。')
    if set(profile['measurements']) != set(MEASURES):
        raise ValueError('人物补充尺寸缺失。')
    if profile.get('intake'):
        import intake_flow
        intake_flow.validate_state(deepcopy(profile['intake']['state']))
        for key in profile['intake']['photos'].values():
            if key not in assets:raise ValueError('建档照片缺失。')
    for role, item in profile['references'].items():
        if item['asset'] not in assets:
            raise ValueError('人物档案缺少参考素材：' + role)
    for item in profile['confirmed_baselines'].values():
        if item['asset'] not in assets:
            raise ValueError('人物档案缺少已确认基准。')

class PersonProfile:
    def _profile_content(self):
        intake = self.state.get('intake_record')
        basic = dict.fromkeys(('gender', 'height_cm', 'weight_kg', 'age_years'))
        measures = {k: dict(value=None, unit='cm', source='unknown',
                            status='missing', applied_to_model=False) for k in MEASURES}
        refs = deepcopy(self.state['refs'])
        choices = {}
        if intake:
            b = intake['state']['basic']
            basic['gender'] = b['gender'] or None
            for key in ('height_cm', 'weight_kg', 'age_years'):
                try: basic[key] = float(b[key]) if str(b[key]).strip() else None
                except (ValueError, TypeError): basic[key] = None
                if basic[key] is not None and not math.isfinite(basic[key]):basic[key] = None
            choices = deepcopy(intake['state']['choices'])
            for key, value in intake['state']['measurements'].items():
                if value is not None:
                    measures[key].update(value=value, source='user_entered', status='unverified')
                    row=(((intake.get('report') or {}).get('body_report') or {}).get('measurement_fit') or {}).get('rows',{}).get(key,{})
                    if row.get('applied') and row.get('input_cm')==value and self.state['refs'].get('body'):
                        measures[key].update(applied_to_model=True,model_cm=row['model_cm'],difference_cm=row['difference_cm'])
            refs.update({'body_photo_' + k: dict(asset=v, source='intake_photo')
                         for k, v in intake['photos'].items()})
        baseline = self.state.get('baseline')
        views = deepcopy(baseline['views']) if baseline and self.state.get('baseline_active') else {}
        candidate = next((c for c in self.state['candidates'] if c and c['id'] == self.state['selected']), None)
        if candidate and candidate['face_approved'] and candidate['body_approved']:
            views = {'front': dict(asset=candidate['asset'], source='selected_candidate')}
        return dict(schema=SCHEMA, profile_id=self.state['project_id'], basic=basic,
                    basic_source='intake_user_input' if intake else 'legacy_unknown',
                    shape_choices=choices, measurements=measures, references=refs,
                    confirmed_baselines=views, intake=deepcopy(intake),
                    approvals=dict(refs_approved=self.state['refs_approved'],
                        baseline=deepcopy(baseline), selected_candidate=deepcopy(candidate),
                        calibration=deepcopy(self.state.get('calibration'))),
                    status='ready' if views else 'draft')

    def sync_profile(self):
        content = self._profile_content()
        old = self.state.get('person_profile')
        history = self.state.setdefault('profile_history', [])
        if old:
            validate_profile(old, self.assets)
        if old is None or payload(old) != content:
            if old: history.append(deepcopy(old))
            self.state['person_profile'] = dict(content, revision=old['revision'] + 1 if old else 1,
                                                 content_hash=checksum(content))
        return deepcopy(self.state['person_profile'])

    def profile_snapshot(self, require_ready=False):
        if require_ready: self.tryon_person()
        profile = self.sync_profile()
        if require_ready and profile['status'] != 'ready':
            raise ValueError('请先在人物建档中确认人物基准。')
        return profile

    def validate_profiles(self):
        for key,blob in self.resources.items():
            if hashlib.sha256(blob).hexdigest()!=key or len(blob)>30*1024**2 or blob[:4]!=b'glTF':
                raise ValueError('人体模型资源校验失败。')
        records=[self.state.get('intake_record')]
        records += [v.get('intake') for v in self.state.get('profile_history',[])]
        records += [j.get('person_profile',{}).get('intake') for j in self.state.get('tryon_jobs',[])]
        for record in records:
            if record and record.get('body_model') and record['body_model']['sha256'] not in self.resources:
                raise ValueError('人物档案缺少人体模型资源。')
        if self.state.get('person_profile'):
            validate_profile(self.state['person_profile'], self.assets)
        for profile in self.state.get('profile_history', []):
            validate_profile(profile, self.assets)
        for job in self.state.get('tryon_jobs', []):
            profile = job.get('person_profile')
            if profile:
                validate_profile(profile, self.assets)
                if job.get('profile_binding') != {k: profile[k] for k in ('profile_id', 'revision', 'content_hash')}:
                    raise ValueError('试衣任务的人物版本绑定不一致。')
                person = job['person_source']['asset']
                if person not in [v['asset'] for v in profile['confirmed_baselines'].values()]:
                    raise ValueError('试衣任务未使用此人物版本的基准。')
                for role in ('body', 'face_front', 'face_side'):
                    if profile['references'][role]['asset'] != job['asset_hashes'][role + '.png']:
                        raise ValueError('试衣任务与人物档案的参考不一致。')

    def attach_intake(self, state, photos, result=None):
        """Validate and stage everything before updating, retaining historical jobs."""
        import intake_flow as flow
        import shape_engine as shapes
        from identity_flow import image_bytes, digest
        clean = flow.validate_state(deepcopy(state))
        if set(photos) - set(flow.ROLES): raise ValueError('未知建档照片类型。')
        if result and result[1]['input_fingerprint'] != flow.fingerprint(state, photos):
            raise ValueError('建档输入已改变，请重新处理体型后交接。')
        if result:flow.validate_complete(state,photos)
        blobs = {k: image_bytes(v) for k, v in photos.items()}
        record = dict(state=clean, photos={k: digest(v) for k, v in blobs.items()},
                      report=deepcopy(result[1]) if result else None)
        old = self.state.get('intake_record')
        def meaning(item):
            if item is None: return None
            s = deepcopy(item['state']); s.pop('step', None)
            return dict(state=s, photos=item['photos'])
        changed = meaning(old) != meaning(record)
        body_blob = image_bytes(shapes.preview(result[0])) if result else None
        geometry = result[0].glb() if result else None
        if geometry is not None:
            if len(geometry)>30*1024**2 or geometry[:4]!=b'glTF':raise ValueError('人体模型资源无效。')
            record['body_model']=dict(format='glb',sha256=digest(geometry),source='intake_processed')
        self.sync_profile()
        if changed:
            self.clear_candidates('人物建档资料或照片已更新，需要重新确认体型与脸')
            self.state['refs'].pop('body', None)
            self.state['refs_approved'] = False
            self.state.pop('fit_advice', None)
        elif old and not result:
            record['report'] = deepcopy(old.get('report'))
            record['body_model'] = deepcopy(old.get('body_model'))
        for blob in blobs.values(): self.assets[digest(blob)] = blob
        if geometry is not None:self.resources[digest(geometry)]=geometry
        self.state['intake_record'] = record
        if body_blob and self.state['refs'].get('body', {}).get('asset') != digest(body_blob):
            self.set_refs({'body': body_blob}, provenance={'body': {'source': 'current_intake_result'}})
        self.sync_profile()

    def restore_intake(self):
        record = self.state.get('intake_record')
        if not record: return None
        return deepcopy(record['state']), {k: self.assets[v] for k, v in record['photos'].items()}
