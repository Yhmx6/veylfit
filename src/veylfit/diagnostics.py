"""Explicit offline installation self-test using synthetic images and dimensions."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json,hashlib
from PIL import Image

def run(output,intake=None):
    import mediapipe as mp
    import numpy as np
    import shape_engine as sh,measurement_fit as mf,intake_flow
    from engine import ASSETS
    from face_engine import MODEL
    from identity_flow import IdentityProject,image_bytes
    from desktop_app import DesktopApp
    from unittest.mock import patch
    import tkinter as tk
    result={'self_test':'synthetic engineering checks, not real likeness approval','network_used':False}
    vision=mp.tasks.vision
    # Exercise the native libraries and both bundled model files without a network download.
    with vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_buffer=(ASSETS/'pose.task').read_bytes()),running_mode=vision.RunningMode.IMAGE,output_segmentation_masks=True)) as detector:
        detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.zeros((320,320,3),dtype=np.uint8)))
    with vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(base_options=mp.tasks.BaseOptions(model_asset_buffer=MODEL.read_bytes()))) as detector:
        detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.zeros((320,320,3),dtype=np.uint8)))
    result['pose_and_face_runtime']='passed'
    state=intake_flow.new_state();state['basic'].update(gender='male',height_cm='175',weight_kg='75',age_years='30')
    state['choices']=dict(family='normal',arms=1,torso=1,legs=1,neck=1)
    state['measurements']=dict(chest=102.,waist=90.,abdomen=96.,hips=104.,shoulder_width=43.,inseam=81.)
    state['photos_confirmed']=True
    photos={k:image_bytes(Image.new('RGB',(320,480),color)) for k,color in [('front','red'),('side','blue')]}
    body=mf.fit(sh.build(intake_flow.shape_settings(state)),state['measurements'])
    report={'input_fingerprint':intake_flow.fingerprint(state,photos),'body_report':body.report}
    p=IdentityProject();p.attach_intake(state,photos,(body,report));p.set_refs({'face_front':photos['front'],'face_side':photos['side']});p.approve_refs(True)
    p.freeze_baseline({'front':Image.new('RGB',(320,480),'yellow'),'side':Image.new('RGB',(320,480),'purple')},'Synthetic self-test only, not a user approval')
    p.set_garment(Image.new('RGB',(320,480),'green'),category='T恤')
    Path(output).resolve().parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='veylfit-test-',dir=Path(output).resolve().parent) as tmp:
        folder=Path(tmp)
        for angle in ('front','side'):
            p.set_angle(angle);jid=p.tryon_package(folder/(angle+'.zip'))
            rid=p.import_tryon_result(jid,Image.new('RGB',(320,480),'orange' if angle=='front' else 'pink'),True)
            assert p.tryon_result(jid,rid)['status']=='pending'
        p.save(folder/'person.veylfit-person');q=IdentityProject.load(folder/'person.veylfit-person')
        assert len(q.state['tryon_jobs'])==2 and all(m['applied_to_model'] for m in q.profile_snapshot()['measurements'].values())
        original=q.profile_snapshot(True);q.set_tryon_mode('styling');assert q.profile_snapshot()==original
        q.set_fit_advice('relaxed','Synthetic test','Synthetic construction',color_policy='recommend');q.fit_analysis_package(folder/'analysis.zip')
        from copy import deepcopy
        old=deepcopy(q.state['tryon_jobs']);changed=deepcopy(state);changed['basic']['weight_kg']='76';q.attach_intake(changed,photos)
        assert q.profile_snapshot()['status']=='draft' and q.state['tryon_jobs']==old
        root=tk.Tk();root.withdraw();app=DesktopApp(root);app.identity_tab.project=p;app.identity_tab.refresh();app.show_identity('b');root.update()
        assert app.module=='b';app.show_intake();root.update();app.pool.shutdown(wait=False);root.destroy()
    result.update(profile_handoff='passed',manual_package_and_result_roundtrip='passed',approval_invalidation='passed',tk_modules='passed',
                  synthetic_measurement_rows=body.report['measurement_fit']['rows'],height_cm=body.report['measurement_fit']['height_cm'])
    if intake:
        state,photos=intake_flow.load_project(intake);body,report=intake_flow.process(state,photos)
        result['external_intake']={'photo_count':len(photos),'processed':True,'photo_fit_applied':report['photo_fit_applied'],'model_bytes':len(body.glb())}
    result['status']='passed'
    Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')

