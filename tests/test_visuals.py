from pathlib import Path

import cv2
import numpy as np
import pytest

from lecture_notes import vision
from lecture_notes.media import save_image,stream_frames,image_at


def test_new_symbol_and_erasure_are_kept():
    before = np.full((360,640,3),240,np.uint8)
    cv2.putText(before,'f(x) = x + 1',(60,120),0,1.1,(30,30,30),2)
    after = before.copy()
    cv2.putText(after,'2',(218,90),0,.6,(20,20,20),2)
    clear = np.zeros(before.shape[:2],np.uint8)
    assert not vision.same_content(before,after,clear,clear)
    assert not vision.same_content(after,before,clear,clear)
    minus = before.copy()
    cv2.line(minus,(280,180),(292,180),(10,10,10),2)
    assert not vision.same_content(before,minus,clear,clear)


def test_moving_person_mask_does_not_make_a_new_page():
    original = np.full((360,640,3),240,np.uint8)
    cv2.putText(original,'Lecture: f(x) = x + 1',(30,100),0,1,(30,30,30),2)
    a,b = original.copy(),original.copy()
    ma,mb = np.zeros((360,640),np.uint8),np.zeros((360,640),np.uint8)
    a[180:,50:140],ma[180:,50:140] = 80,1
    b[180:,350:440],mb[180:,350:440] = 80,1
    assert vision.same_content(a,b,ma,mb)
    assert not vision.same_content(a,b,np.ones_like(ma),np.ones_like(mb))


def test_groups_do_not_follow_transitive_occlusion_chain(tmp_path,monkeypatch):
    items = []
    for i in range(3):
        name = f'images/{i}.png'
        save_image(tmp_path/name,np.full((64,64,3),i*60,np.uint8))
        items.append({'id':f'v{i+1:05d}','kind':'slides','image':name,'content_id':f'c{i}',
                      'layout':'classroom_0','flags':[],'start':i,'end':i+1,'capture_ts':i})
    monkeypatch.setattr(vision,'same_content',lambda a,b,*args:abs(int(a[0,0,0])-int(b[0,0,0]))<=60)
    result = vision.link_views(items,tmp_path,lambda:None,lambda *args:None)
    assert result[0]['content_id']==result[1]['content_id']
    assert result[2]['content_id']!=result[0]['content_id']


def test_visual_audit_exposes_gap_and_retains_every_appearance(tmp_path):
    items = [{'id':'v1','kind':'slides','content_id':'c1','image':'a.png','start':0,'end':3},
             {'id':'v2','kind':'slides','content_id':'c1','image':'b.png','start':6,'end':10}]
    report = vision.audit_visuals(items,[],[[0,10]],tmp_path)
    assert report['uncovered_intervals_over_0_6s']==[[3,6]]
    assert report['grouped_repeats']==1
    import json
    pages = json.loads((tmp_path/'pages.json').read_text())
    assert [x['id'] for x in pages[0]['appearances']]==['v1','v2']


def test_audit_does_not_hide_a_missing_board_behind_present_slides(tmp_path):
    from lecture_notes.common import write_json
    write_json(tmp_path/'profiles.json',[{'regions':[{'kind':'slides'},{'kind':'board'}]}])
    items = [{'id':'v1','kind':'slides','layout':'classroom_0','content_id':'c1','image':'a.png','start':0,'end':10}]
    layouts = [{'id':'l1','kind':'classroom_0','start':0,'end':10}]
    report = vision.audit_visuals(items,layouts,[[0,10]],tmp_path)
    assert report['uncovered_intervals_over_0_6s']==[]
    assert report['region_coverage_gaps_over_0_6s']==[{'layout':'l1','kind':'board','start':0,'end':10}]


def test_decoded_pts_match_native_frame_on_public_video(sample_video):
    frames=list(stream_frames(sample_video,2,4,width=640))
    assert len(frames)==4
    for second,frame in frames:
        native=cv2.resize(image_at(sample_video,second),(640,360))
        assert np.abs(frame.astype(float)-native).mean()<4
    assert max(b[0]-a[0] for a,b in zip(frames,frames[1:]))<.55


def test_public_animation_answer_is_not_merged(sample_video):
    assert not vision.same_content(image_at(sample_video,1),image_at(sample_video,3))
