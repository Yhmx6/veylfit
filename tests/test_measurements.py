"""Synthetic engineering inputs only; never interpreted as a person's tape measurements."""
from pathlib import Path
import sys,unittest,struct,json
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/veylfit'))
import shape_engine as sh
import measurement_fit as mf
from makehuman_fit import Template,Section

class MeasurementTests(unittest.TestCase):
    def test_six_values_and_export(self):
        for h,w,targets in [(160,52,(88,76,82,92,38,73)),(175,75,(102,90,96,104,43,81)),(190,112,(120,112,119,123,49,91))]:
            with self.subTest(height=h):
                body=sh.build(sh.Settings(height_cm=h,weight_kg=w))
                values=dict(zip(mf.LIMITS,targets));result=mf.fit(body,values)
                rows=result.report['measurement_fit']['rows']
                self.assertTrue(all(r['applied'] and abs(r['difference_cm'])<=.3 for r in rows.values()))
                self.assertLess(abs(mf.lengths(result.vertices)['height']-h),.05)
                # Independent readback of the GLB vertex buffer and skeleton bind matrices.
                blob=result.glb();size=struct.unpack_from('<I',blob,12)[0];doc=json.loads(blob[20:20+size]);binary=blob[28+size:]
                idx=doc['meshes'][0]['primitives'][0]['attributes']['POSITION'];acc=doc['accessors'][idx];view=doc['bufferViews'][acc['bufferView']]
                vertices=np.frombuffer(binary,dtype='<f4',count=acc['count']*3,offset=view.get('byteOffset',0)+acc.get('byteOffset',0)).reshape(-1,3)
                for key in mf.LEVELS:
                    actual=Section(vertices,result.faces,rows[key]['section_height_cm']/100).girth(vertices)
                    self.assertAlmostEqual(actual,values[key],delta=.3)
                self.assertEqual(len(doc['skins'][0]['joints']),len(body.joints))
                self.assertTrue(np.isfinite(result.joints).all())

    def test_optional_and_noop(self):
        body=sh.build();self.assertIs(mf.fit(body,{}),body)
        for key,value in [('chest',102),('waist',88),('abdomen',96),('hips',103),('shoulder_width',44),('inseam',82)]:
            result=mf.fit(body,{key:value});rows=result.report['measurement_fit']['rows']
            self.assertEqual(sum(r['applied'] for r in rows.values()),1)
            self.assertLess(abs(rows[key]['difference_cm']),.3)

    def test_invalid_and_conflicting(self):
        for values in ({'waist':float('nan')},{'chest':0},{'inseam':110},{'shoulder_width':True},{'wrong':12}):
            with self.assertRaises(ValueError):mf.fit(sh.build(),values)
        with self.assertRaises(ValueError):mf.fit(sh.build(),dict(chest=65,waist=165,abdomen=55,hips=170))

    def test_photo_conflict_is_reported(self):
        body=sh.build()
        body.report['photo_fit']={'constraints':[{'region':'abdomen','axis':'depth_cm','mode':'clear','photo_projection_cm':10}]}
        result=mf.fit(body,{'abdomen':96})
        self.assertTrue(result.report['measurement_fit']['warnings'])
        self.assertLess(abs(result.report['measurement_fit']['rows']['abdomen']['difference_cm']),.3)

if __name__=='__main__':unittest.main()
