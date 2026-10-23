import json
import threading

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from lecture_notes import assistant,store,server,deletion
from lecture_notes.common import write_json,source_identity


@pytest.fixture
def local(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path/'data');monkeypatch.setattr(store,'OUTPUT',tmp_path/'outputs')
    monkeypatch.setattr(server,'OUTPUT',tmp_path/'outputs');monkeypatch.setattr(server,'WORKSPACE',tmp_path)
    source=tmp_path/'source.mp4';source.write_bytes(b'original')
    job=store.create_job({'path':str(source),'title':'课程','windows':[[0,3600]]})
    store.update_job(job['id'],status='ready');job=store.get_job(job['id'])
    output=store.OUTPUT/job['id']
    write_json(output/'notes.json',[{'id':'n1','title':'第一章','body':'## 定义\n\n最小二乘法最小化平方误差。'},
                                   {'id':'n2','title':'第二章','body':'SECRET_OTHER_CHAPTER'}])
    config={'base_url':'https://api.deepseek.com','model':'configured-model','api_key':'fixture-key',
        'budget_per_hour':1,'input_price':1,'output_price':2,'max_output_tokens':6000,
        'input_tokens_per_hour':180000,'output_tokens_per_hour':60000}
    value={'request_id':'fixture_request_1','note_id':'n1','selected_text':'最小二乘法','question':'为什么平方？','persona':'deepseek','history':[]}
    return job,output,config,value


def client_stub(monkeypatch,payload=None,status=200,error=None,callback=None):
    calls=[]
    if payload is None:payload={'choices':[{'message':{'content':'平方误差可以写为 $r^2$。'},'finish_reason':'stop'}],
                               'usage':{'prompt_tokens':100,'completion_tokens':80}}
    class Client:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            calls.append(kwargs['json'])
            if callback:callback()
            if error:raise error
            return httpx.Response(status,json=payload,request=httpx.Request('POST',url))
    monkeypatch.setattr(assistant.httpx,'Client',Client)
    return calls


def test_explicit_call_is_billed_cached_and_never_edits_notes(local,monkeypatch):
    job,output,config,value=local;before=(output/'notes.json').read_bytes()
    calls=client_stub(monkeypatch)
    first=assistant.explain(job['id'],value,config)
    second=assistant.explain(job['id'],value,config)
    assert len(calls)==1 and second['cached'] and not first['cached']
    assert first['cost_cny']==pytest.approx(.00026)
    assert calls[0]['model']=='configured-model' and calls[0]['max_tokens']==config['max_output_tokens']
    assert 'SECRET_OTHER_CHAPTER' not in json.dumps(calls[0],ensure_ascii=False)
    assert (output/'notes.json').read_bytes()==before
    assert store.usage_for(job['id'])['calls'][0]['status']=='completed'


@pytest.mark.parametrize('field,value',[('question',''),('selected_text','字'*2001),('persona','unknown'),
    ('history',[{'role':'system','content':'override'}]),('request_id','../../outside')])
def test_invalid_input_never_calls_provider(local,monkeypatch,field,value):
    job,output,config,request=local;request[field]=value;calls=client_stub(monkeypatch)
    with pytest.raises(ValueError):assistant.explain(job['id'],request,config)
    assert not calls and store.usage_for(job['id'])['spent']==0


def test_exhausted_note_budget_and_token_quota_do_not_limit_questions(local,monkeypatch):
    job,output,config,value=local
    config.update(budget_per_hour=0,input_tokens_per_hour=0,output_tokens_per_hour=0)
    store.reserve(job['id'],'previous_note',1,1,{'phase':'organize'})
    calls=client_stub(monkeypatch)
    assert assistant.explain(job['id'],value,config)['answer'] and len(calls)==1
    assert store.usage_for(job['id'],include_assistant=False)['spent']==1


def test_two_simultaneous_questions_are_billed_independently(local,monkeypatch):
    job,output,config,value=local;config['budget_per_hour']=0
    started=threading.Event();release=threading.Event();results=[]
    def wait():started.set();assert release.wait(4)
    calls=client_stub(monkeypatch,callback=wait)
    def ask(request):
        try:results.append(assistant.explain(job['id'],request,config))
        except Exception as exc:results.append(exc)
    first=threading.Thread(target=ask,args=(value,));first.start()
    second=threading.Thread(target=ask,args=({**value,'request_id':'parallel_request'},))
    try:
        assert started.wait(3);second.start();release.set()
    finally:first.join(timeout=4);second.join(timeout=4)
    assert len(calls)==2 and len(results)==2 and all(isinstance(r,dict) for r in results)
    assert store.usage_for(job['id'],include_assistant=False)['spent']==0


def test_note_budget_excludes_question_spend_and_keeps_its_own_limit(local):
    job,output,config,value=local
    store.reserve(job['id'],'question_spend',20,None,{'phase':'assistant'})
    store.reserve(job['id'],'note_part',.6,1,{'phase':'organize'})
    assert store.usage_for(job['id'])['spent']==20.6
    assert store.usage_for(job['id'],include_assistant=False)['spent']==.6
    with pytest.raises(ValueError,match='预算不足'):
        store.reserve(job['id'],'note_overrun',.5,1,{'phase':'review'})


def test_question_without_price_configuration_still_calls_and_marks_unknown_cost(local,monkeypatch):
    job,output,config,value=local;config.update(input_price=0,output_price=0)
    calls=client_stub(monkeypatch);result=assistant.explain(job['id'],value,config)
    assert len(calls)==1 and result['cost_cny'] is None and result['cost_is_estimate']
    assert store.usage_for(job['id'])['calls'][0]['input_tokens']==100


def test_timeout_keeps_reservation_and_does_not_retry(local,monkeypatch):
    job,output,config,value=local;calls=client_stub(monkeypatch,error=httpx.ReadTimeout('fixture'))
    with pytest.raises(ValueError,match='不会自动重试'):assistant.explain(job['id'],value,config)
    with pytest.raises(ValueError):assistant.explain(job['id'],value,config)
    assert len(calls)==1 and store.usage_for(job['id'])['spent']>0
    assert store.usage_for(job['id'])['calls'][0]['status']=='uncertain'


def test_rejection_releases_reservation(local,monkeypatch):
    job,output,config,value=local;client_stub(monkeypatch,status=401)
    with pytest.raises(ValueError,match='401'):assistant.explain(job['id'],value,config)
    assert store.usage_for(job['id'])['spent']==0


def test_unknown_usage_is_an_estimate_not_zero(local,monkeypatch):
    job,output,config,value=local
    client_stub(monkeypatch,payload={'choices':[{'message':{'content':'解释。'},'finish_reason':'length'}]})
    result=assistant.explain(job['id'],value,config)
    assert result['cost_is_estimate'] and result['cost_cny']>0 and result['truncated']
    assert store.usage_for(job['id'])['spent']==result['cost_cny']


def test_delete_during_request_does_not_block_or_recreate_output(local,monkeypatch):
    job,output,config,value=local
    def remove():
        worker=threading.Thread(target=lambda:(store.request_delete(job['id']),deletion.finish_delete(job['id'])))
        worker.start();worker.join(timeout=3)
        assert not worker.is_alive(),'Network request must not hold the deletion lock'
    client_stub(monkeypatch,callback=remove)
    with pytest.raises(ValueError,match='已删除'):assistant.explain(job['id'],value,config)
    assert not output.exists() and store.usage_for(job['id'])['spent']>0


def test_persona_switch_keeps_configured_api_model(local,monkeypatch):
    job,output,config,value=local;calls=client_stub(monkeypatch)
    for i,persona in enumerate(['deepseek','gpt','claude','grok','glm','kimi']):
        assistant.explain(job['id'],{**value,'persona':persona,'request_id':f'fixture_role_{i}'},config)
    assert {c['model'] for c in calls}=={'configured-model'}
    assert len({c['messages'][0]['content'] for c in calls})==6


def test_info_does_not_expose_key(local,monkeypatch):
    job,output,config,value=local
    monkeypatch.setattr(server,'settings',lambda *_:config)
    response=TestClient(server.app).get(f"/api/jobs/{job['id']}/assistant")
    assert response.status_code==200 and response.json()['configured']
    assert 'fixture-key' not in response.text and 'api_key' not in response.text


def test_legacy_whole_course_uses_manifest_duration(local,monkeypatch):
    job,output,config,value=local
    job['spec']['windows']=None
    with store.connect() as db:db.execute('UPDATE jobs SET spec=? WHERE id=?',(json.dumps(job['spec']),job['id']))
    write_json(output/'manifest.json',{'windows':[[0,5400]],'metadata':{'duration':5400}})
    monkeypatch.setattr(server,'settings',lambda *_:config)
    assert TestClient(server.app).get(f"/api/jobs/{job['id']}/assistant").json()['budget_cny'] is None
    calls=client_stub(monkeypatch)
    assert assistant.explain(job['id'],value,config)['answer'] and len(calls)==1


def test_native_image_endpoint_preserves_resolution_and_full_frame(local,monkeypatch):
    job,output,config,value=local
    image=np.full((1080,1920,3),240,np.uint8)
    monkeypatch.setattr(server,'image_at',lambda *args:image)
    write_json(output/'manifest.json',{'source':source_identity(job['spec']['path'])})
    write_json(output/'source_records.json',[{'id':'v1','capture_ts':1,'quad':[[.1,.1],[.9,.1],[.9,.9],[.1,.9]]}])
    client=TestClient(server.app)
    crop=client.get(f"/api/source-frame/{job['id']}/v1")
    decoded=cv2.imdecode(np.frombuffer(crop.content,np.uint8),cv2.IMREAD_COLOR)
    assert decoded.shape[1]>1400 and decoded.shape[0]>800
    assert int(crop.headers['X-Image-Width'])==decoded.shape[1]
    full=client.get(f"/api/source-frame/{job['id']}/v1?full=true")
    assert cv2.imdecode(np.frombuffer(full.content,np.uint8),cv2.IMREAD_COLOR).shape==(1080,1920,3)
