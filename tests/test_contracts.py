from pathlib import Path
import json

import cv2
import numpy as np
import pytest

from lecture_notes import store,settings as config
from lecture_notes.common import safe_child,read_json
from lecture_notes.pipeline import validate_windows
from lecture_notes.synthesis import build_sections,organize,prepare_payload,SYSTEM
from lecture_notes.vision import geometry_match,same_content,is_flat_screen
from lecture_notes.media import image_at
from lecture_notes.asr import uncovered_speech


@pytest.fixture
def database(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path/'db')
    monkeypatch.setattr(store,'OUTPUT',tmp_path/'outputs')
    return store.create_job({'path':'test.mp4'})['id']


def test_budget_reservation_is_cumulative(database):
    store.reserve(database,'one',.6,1,{})
    with pytest.raises(ValueError,match='预算不足'):
        store.reserve(database,'two',.5,1,{})
    store.settle('one','completed',.3,100,20)
    store.reserve(database,'two',.5,1,{})
    assert store.usage_for(database)['spent']==pytest.approx(.8)
    with pytest.raises(ValueError,match='已有调用记录'):
        store.reserve(database,'two',.1,1,{})


def test_windows_and_assignment():
    with pytest.raises(ValueError):validate_windows([[0,5],[4,8]],10)
    with pytest.raises(ValueError):validate_windows([[0,11]],10)
    s=[{'id':'s1','start':299.,'end':301.,'text':'边界内容'}]
    v=[{'id':'v1','start':290.,'end':310.,'capture_ts':295.,'ocr':'定义','formulas':[]}]
    n=build_sections(s,v,[[0,600]])
    assert [sid for section in n for sid in section['segment_ids']]==['s1']
    assert sum('v1' in x['visual_ids'] for x in n)==2


def test_no_request_when_over_token_cap(database,tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('不应发起请求')
    monkeypatch.setattr('httpx.Client',forbidden)
    sections=build_sections([{'id':'s','start':0,'end':10,'text':'课堂文字'*100}],[],[[0,60]])
    c={**config.DEFAULTS,'api_key':'local-test','base_url':'https://example.invalid/v1','model':'test','input_price':1,'output_price':1,'input_tokens_per_hour':60000}
    n,message=organize(database,sections,60,tmp_path,c,lambda *a:None,lambda:None)
    assert 'token上限' in message
    assert store.usage_for(database)['calls']==[]


def test_request_error_keeps_reservation(database,tmp_path,monkeypatch):
    import httpx
    class TimeoutClient:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,*a,**kw):raise httpx.ReadTimeout('test')
    monkeypatch.setattr(httpx,'Client',TimeoutClient)
    sections=build_sections([{'id':'s','start':0,'end':10,'text':'测试'}],[],[[0,3600]])
    c={**config.DEFAULTS,'api_key':'test','base_url':'https://example.invalid/v1','model':'test','input_price':.1,'output_price':.1}
    with pytest.raises(ValueError,match='不自动重试'):
        organize(database,sections,3600,tmp_path,c,lambda *a:None,lambda:None)
    usage=store.usage_for(database)
    assert usage['spent']>0 and usage['calls'][0]['status']=='uncertain'


def test_successful_api_result_is_cached(database,tmp_path,monkeypatch):
    import httpx
    calls=[]
    class LocalMock:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,*a,**kw):
            calls.append(kw)
            return httpx.Response(200,request=httpx.Request('POST','https://example.invalid'),json={
                'choices':[{'message':{'content':'定义与推导 [00:00:00]'},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':100,'completion_tokens':30}})
    monkeypatch.setattr(httpx,'Client',LocalMock)
    sections=build_sections([{'id':'s','start':0,'end':10,'text':'测试'}],[],[[0,60]])
    c={**config.DEFAULTS,'api_key':'test','base_url':'https://example.invalid/v1','model':'test','input_price':.1,'output_price':.1,'input_tokens_per_hour':600000}
    for _ in range(2):
        result,_=organize(database,sections,60,tmp_path,c,lambda *a:None,lambda:None)
        assert result[0]['organized']
    assert len(calls)==1
    assert store.usage_for(database)['spent']==pytest.approx(.000013)


def test_evidence_dedup_preserves_new_lines():
    visuals=[{'id':'v1','start':0,'end':5,'capture_ts':0,'ocr':'定义\n公式甲','formulas':[]},
             {'id':'v2','start':5,'end':10,'capture_ts':5,'ocr':'定义\n公式甲\n新增推导','formulas':[]}]
    section=build_sections([],visuals,[[0,10]])[0]
    assert section['visual_ids']==['v1','v2']
    assert section['evidence'][1]['text']=='新增推导'


def test_budget_payload_preserves_every_subtitle():
    segments=[{'id':f's{i}','start':i*4,'end':i*4+3,'text':f'完整的推导步骤{i}'} for i in range(15)]
    section=build_sections(segments,[],[[0,60]])[0]
    text=json.loads(prepare_payload(section))['完整字幕']
    assert all(s['text'] in text for s in segments)
    assert text.index(segments[0]['text'])<text.index(segments[-1]['text'])


@pytest.mark.parametrize('count',[150,1400])
def test_public_transcript_fixture_fits_default_input_cap(count):
    segments=[{'id':f's{i}','start':i*4.,'end':i*4.+3.,'text':'线性模型的误差平方和需要在给定条件下求最小值。'} for i in range(count)]
    sections=build_sections(segments,[],[[0,count*4]])
    bound=sum(len((SYSTEM+prepare_payload(n)).encode('utf-8'))+64 for n in sections)
    assert bound<=count*4/3600*config.DEFAULTS['input_tokens_per_hour']


def test_safe_paths(tmp_path):
    with pytest.raises(ValueError):safe_child(tmp_path,'../settings.json')
    assert safe_child(tmp_path,'images/1.png')==tmp_path/'images/1.png'


def test_speech_audit_exposes_real_gaps():
    assert uncovered_speech([[0,10]],[{'start':0,'end':3},{'start':8,'end':10}])==[[3,8]]
    assert uncovered_speech([[0,10]],[{'start':0,'end':10}])==[]


def test_dpapi_and_redaction(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    monkeypatch.setattr(config,'SESSION_KEY','')
    config.save_settings({'api_key':'test-secret','remember_key':True})
    assert 'test-secret' not in (tmp_path/'settings.json').read_text()
    assert 'api_key' not in config.settings()
    monkeypatch.setattr(config,'SESSION_KEY','')
    assert config.settings(True)['api_key']=='test-secret'


def test_dark_fullscreen_and_degenerate_match():
    image=np.full((360,640,3),55,np.uint8)
    cv2.line(image,(20,250),(600,250),(230,230,230),2)
    assert is_flat_screen(image)
    assert geometry_match(image,np.zeros_like(image)) is None


def test_calibration_uses_its_own_reference_time(tmp_path,monkeypatch):
    from lecture_notes import vision
    captures=[]
    def capture(path,second):
        captures.append(second)
        return np.zeros((180,320,3),np.uint8)
    class Decoder:
        def __init__(self,*a,**kw):pass
        def release(self):pass
    monkeypatch.setattr(vision,'image_at',capture)
    monkeypatch.setattr(vision,'stream_frames',lambda *a,**kw:iter([]))
    monkeypatch.setattr(vision.cv2,'VideoCapture',Decoder)
    region=[{'kind':'slides','quad':[[0,0],[.6,0],[.6,.6],[0,.6]]}]
    vision.extract_video('fixture',[[0,60]],tmp_path,lambda *a:None,lambda:None,region,30)
    assert captures==[30]
    assert read_json(tmp_path/'profiles.json')[0]['capture_ts']==30


def test_same_template_different_page_is_not_duplicate(sample_video):
    a=image_at(sample_video,1)
    b=image_at(sample_video,7)
    assert not same_content(a,b)
    match=geometry_match(a,b)
    assert match is None or match['edge_agreement']<.9


def test_public_slide_is_fullscreen(sample_video):
    assert is_flat_screen(image_at(sample_video,1))
