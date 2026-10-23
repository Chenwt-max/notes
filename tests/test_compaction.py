import cv2
import numpy as np
from lecture_notes.compaction import features,coverage,compact_visuals
from lecture_notes.media import save_image
from lecture_notes.compaction import choose_posters


def page():
    image=np.full((400,640,3),245,np.uint8)
    cv2.rectangle(image,(20,15),(620,40),(170,60,30),-1)
    cv2.putText(image,'Lecture 1',(30,100),0,1,(20,20,20),2)
    cv2.putText(image,'y = Xw',(45,180),0,1,(20,20,20),2)
    return image


def test_animation_prefers_complete_page_and_protects_unique_symbols():
    before=page();after=before.copy()
    cv2.putText(after,'Answer = 42',(45,280),0,1,(20,20,20),2)
    assert coverage(features(before),features(after))['covers']
    assert not coverage(features(after),features(before))['covers']
    minus=before.copy();cv2.line(minus,(400,180),(408,180),(0,0,0),2)
    assert not coverage(features(minus),features(before))['covers']
    decimal=before.copy();decimal[200:203,400:403]=0
    assert not coverage(features(decimal),features(before))['covers']


def test_same_template_different_content_is_not_a_duplicate():
    a=page();b=page()
    cv2.putText(a,'Important A',(70,300),0,1,(0,0,0),2)
    cv2.putText(b,'Different B',(70,300),0,1,(0,0,0),2)
    assert not coverage(features(a),features(b))['covers']
    assert not coverage(features(b),features(a))['covers']


def test_camera_shift_groups_posters_without_deleting_complementary_images():
    a=page()
    for index in range(8):
        cv2.putText(a,f'Equation {index} x+{index}',(45,130+index*28),0,.55,(0,0,0),1)
    b=cv2.warpAffine(a,np.float32([[1,0,9],[0,1,5]]),(640,400),borderValue=(245,245,245))
    c=page()
    for index in range(8):
        cv2.putText(c,f'Different {index} z={index}',(45,130+index*28),0,.55,(0,0,0),1)
    rows=[{'id':f'v{i}','kind':'slides','layout':'x','capture_ts':i*10,'flags':[],
           'quality_score':1,'formulas':[]} for i in range(3)]
    ff={v['id']:features(im) for v,im in zip(rows,[a,b,c])}
    count=choose_posters(rows,lambda identity:ff[identity])
    assert count==2 and rows[0]['content_id']==rows[1]['content_id']
    assert rows[2]['content_id']!=rows[0]['content_id']
    assert len(rows)==3


def test_plus_is_not_a_more_complete_version_of_minus():
    a=page();cv2.line(a,(400,220),(414,220),(0,0,0),2)
    b=a.copy();cv2.line(b,(407,213),(407,227),(0,0,0),2)
    assert not coverage(features(a),features(b))['covers']
    assert not coverage(features(b),features(a))['covers']


def test_occluded_target_cannot_replace_visible_original():
    a=page();b=a.copy();mask=np.zeros(a.shape[:2],np.uint8)
    mask[130:210,20:350]=1;b[mask>0]=80
    assert not coverage(features(a),features(b,mask))['covers']
    assert coverage(features(b,mask),features(a))['covers']


def test_compaction_keeps_all_times_and_corrected_material(tmp_path):
    a=page();b=a.copy();cv2.putText(b,'Answer',(45,280),0,1,(0,0,0),2)
    vs=[]
    for i,im in enumerate([a,b,b]):
        path=f'images/{i}.png';save_image(tmp_path/path,im)
        vs.append({'id':f'v{i}','kind':'slides','image':path,'start':i*10,'end':(i+1)*10,'capture_ts':i*10+1,
                   'layout':'classroom_0','quad':None,'quality_score':10,'flags':[],'formulas':[]})
    kept,records,report=compact_visuals(vs,tmp_path,commit=False)
    assert len(kept)==1 and len(records)==3 and report['all_sources_mapped']
    assert {r['capture_ts'] for r in records}=={1,11,21}
    assert len(kept[0]['appearances'])==3
    vs[0]['formulas']=[{'status':'corrected','corrected_latex':'x'}]
    kept,_,_=compact_visuals(vs,tmp_path,commit=False)
    assert 'v0' in {v['id'] for v in kept}


def test_late_complete_page_is_not_displayed_in_early_blank_interval():
    from lecture_notes.synthesis import build_sections
    visuals=[{'id':'v1','content_id':'p1','capture_ts':500,'start':490,'end':510,
              'appearances':[{'start':0,'end':20},{'start':490,'end':510}],
              'is_representative':True,'ocr':'later lesson','formulas':[]}]
    sections=build_sections([],visuals,[[0,600]])
    assert sections[0]['display_visual_ids']==[] and sections[0]['evidence']==[]
    assert sections[1]['display_visual_ids']==['v1']
