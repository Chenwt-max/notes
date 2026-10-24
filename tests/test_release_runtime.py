import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from lecture_notes import preparation,runtime,settings,store,server,workflow
from lecture_notes.common import read_json,write_json,digest
from lecture_notes.repair import repair_payload,parse_repair,parse_review


def test_portable_paths_follow_relocated_root(tmp_path,monkeypatch):
    root=tmp_path/'中文 路径'/'notes'
    monkeypatch.setattr(runtime,'ROOT',root)
    monkeypatch.setattr(runtime,'PORTABLE',True)
    assert runtime.python_for('core')==root/'runtime/core/python.exe'
    assert runtime.python_for('asr')==root/'runtime/asr/python.exe'
    assert runtime.site_packages('document')==root/'runtime/document/Lib/site-packages'
    monkeypatch.setattr(runtime,'PORTABLE',False)
    assert runtime.python_for('asr')==root/'.venv-asr/Scripts/python.exe'


@pytest.mark.parametrize('ready',[False,True])
def test_portable_job_creation_requires_verified_models(tmp_path,monkeypatch,ready):
    monkeypatch.setattr(runtime,'PORTABLE',True)
    monkeypatch.setattr(preparation,'state',lambda:{'ready':ready})
    monkeypatch.setattr(settings,'DATA',tmp_path/'config')
    monkeypatch.setattr(store,'DATA',tmp_path/'db')
    monkeypatch.setattr(store,'OUTPUT',tmp_path/'out')
    monkeypatch.setattr(server,'WORKSPACE',tmp_path)
    monkeypatch.setattr(server,'probe',lambda _: {'duration':10})
    video=tmp_path/'course.mp4';video.write_bytes(b'fixture-not-decoded')
    response=TestClient(server.app).post('/api/jobs',json={'path':str(video)})
    if ready:
        assert response.status_code==200,response.text
        assert len(store.list_jobs())==1
    else:
        assert response.status_code==400 and '模型准备' in response.json()['detail']
        assert store.list_jobs()==[]


def test_foreign_account_key_does_not_block_existing_documents(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'DATA',tmp_path)
    monkeypatch.setattr(settings,'SESSION_KEY','')
    monkeypatch.delenv('LECTURE_API_KEY',raising=False)
    def locked(*a,**kw):raise OSError('different Windows account')
    monkeypatch.setattr(settings,'crypt',locked)
    write_json(tmp_path/'settings.json',{'encrypted_key':'c2VjcmV0','remember_key':True})
    value=settings.settings(True)
    assert not value['has_key'] and value['key_reentry_required'] and value['api_key']==''
    assert 'encrypted_key' not in value
    settings.save_settings({'cpu_threads':1})
    assert read_json(tmp_path/'settings.json')['encrypted_key']=='c2VjcmV0'


def test_complete_body_survives_only_damaged_auxiliary_metadata():
    raw='{"body":"## 定义\\n完整推导 $x^2$。","repairs":[{"reason":"missing end}]}'
    text,repairs=parse_repair(raw,{'speech':[]},[])
    assert text=='## 定义\n完整推导 $x^2$。' and repairs==[]
    assert repair_payload(raw)['metadata_warning']
    for truncated in ['{"body":"截断','{"unknown":1,"body":"正文",','{"body":"正文"]']:
        with pytest.raises(ValueError):repair_payload(truncated)


def test_unsafe_review_keeps_original():
    original='同样的式子和同样的式子'
    with pytest.raises(ValueError,match='无法唯一定位'):
        parse_review(json.dumps({'edits':[{'before':'同样的式子','after':'猜测修改','reason':'test'}]}),{'body':original})
    assert original=='同样的式子和同样的式子'


@pytest.fixture
def release_job(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'OUTPUT',tmp_path/'outputs')
    monkeypatch.setattr(server,'OUTPUT',tmp_path/'outputs')
    job=store.create_job({'path':'fixture.mp4','organize':True})
    store.update_job(job['id'],status='materials_ready')
    output=store.OUTPUT/job['id']
    write_json(output/'notes_working.json',[{'id':'n1','body':'原稿','organized':True,'review_warning':'无法定位'}])
    return store.get_job(job['id']),output


def test_retry_is_confirmed_idempotent_and_preserves_ledger_and_responses(release_job):
    job,output=release_job
    (output/'api_cache').mkdir()
    write_json(output/'api_cache/old.json',{'response_body':'bad old response'})
    store.reserve(job['id'],'old',.2,1,{'phase':'review','section_id':'n1'})
    store.settle('old','completed',.1,10,10)
    client=TestClient(server.app);url=f"/api/jobs/{job['id']}/retry/review"
    body={'request_id':'unique-confirmation-001'}
    assert client.post(url,json=body).status_code==409
    assert not (output/'api_attempts.json').exists()
    for _ in range(2):
        assert client.post(url,json={**body,'confirm_reprocess':True}).status_code==200
    assert read_json(output/'api_attempts.json')['attempts']=={'review:n1':1}
    assert store.usage_for(job['id'])['spent']==.1
    assert read_json(output/'api_cache/old.json')['response_body']=='bad old response'
    assert workflow.attempt_fingerprint(output,'review','n1','base')==digest({'original':'base','attempt':1})
    store.update_job(job['id'],status='materials_ready')
    replay=client.post(url,json={**body,'confirm_reprocess':True})
    assert replay.json()['status']=='materials_ready'


def test_retry_invalidates_prior_review_certainty_without_losing_body(release_job):
    job,output=release_job
    rows=read_json(output/'notes_working.json')
    rows[0]['reviewed_body_hash']=digest(rows[0]['body'])
    write_json(output/'notes_working.json',rows)
    assert workflow.retry(job,output,{'request_id':'retry-review-again-001','phase':'review'})
    updated=read_json(output/'notes_working.json')[0]
    assert updated['body']=='原稿' and not updated.get('reviewed_body_hash')


def test_unknown_charge_must_be_confirmed_before_retry(release_job):
    job,output=release_job
    store.reserve(job['id'],'uncertain',.1,1,{'phase':'review','section_id':'n1'})
    store.settle('uncertain','uncertain')
    with pytest.raises(ValueError,match='核对'):
        workflow.retry(job,output,{'request_id':'retry-000000000001','phase':'review'})
    client=TestClient(server.app)
    for amount in [-1,float('inf')]:
        if amount<0:assert client.post(f"/api/jobs/{job['id']}/billing/uncertain",json={'confirmed':True,'actual_cny':amount}).status_code==400
    assert client.post(f"/api/jobs/{job['id']}/billing/uncertain",json={'confirmed':True,'actual_cny':0}).status_code==200
    assert workflow.retry(job,output,{'request_id':'retry-000000000001','phase':'review'})
    assert store.usage_for(job['id'])['calls'][0]['status']=='confirmed'


def test_pinned_download_resumes_and_rejects_corruption(tmp_path,monkeypatch):
    monkeypatch.setattr(preparation,'ROOT',tmp_path)
    payload=b'x'*2000000
    row={'path':'models/model.bin','size':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'url':'https://fixture.invalid/model'}
    part=tmp_path/'models/model.bin.part';part.parent.mkdir();part.write_bytes(payload[:100])
    ranges=[];real_client=httpx.Client
    def response(request):
        ranges.append(request.headers['Range'])
        return httpx.Response(206,content=payload[100:],headers={'Content-Range':f'bytes 100-{len(payload)-1}/{len(payload)}'})
    monkeypatch.setattr(httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(response)))
    preparation.download(row,lambda:None,lambda _:None)
    assert ranges==['bytes=100-'] and not part.exists()
    assert preparation.file_hash(tmp_path/row['path'])==row['sha256']
    (tmp_path/row['path']).unlink();part.write_bytes(payload)
    with pytest.raises(ValueError,match='SHA-256'):
        preparation.download({**row,'sha256':'0'*64},lambda:None,lambda _:None)
    assert not part.exists()


def test_cancelled_setup_and_modified_model_are_never_ready(tmp_path,monkeypatch):
    monkeypatch.setattr(preparation,'ROOT',tmp_path)
    monkeypatch.setattr(preparation,'DATA',tmp_path/'data')
    pinned={'files':[{'path':'models/a','model':'fixture','size':1,'sha256':hashlib.sha256(b'a').hexdigest()}]}
    monkeypatch.setattr(preparation,'manifest',lambda:pinned)
    preparation.CANCEL.set()
    try:preparation.prepare()
    finally:preparation.CANCEL.clear()
    assert preparation.state()['status']=='cancelled' and not preparation.state()['ready']
    (tmp_path/'models').mkdir();(tmp_path/'models/a').write_bytes(b'a')
    write_json(tmp_path/'data/models-verified.json',{'manifest_hash':digest(pinned),'signature':preparation.signature(pinned['files'])})
    assert preparation.state()['ready']
    (tmp_path/'models/a').write_bytes(b'corrupt')
    assert not preparation.state()['ready']


def test_health_exposes_version_and_tools_but_no_private_body_or_key():
    response=TestClient(server.app).get('/api/health')
    value=response.json()
    assert value['version']==runtime.VERSION and len(value['instance'])==24
    assert 'python' in value['runtime'] and 'api_key' not in value


def test_existing_note_budget_changes_preserve_cumulative_spend(release_job):
    job,output=release_job
    store.reserve(job['id'],'paid',.4,1,{'phase':'organize'})
    store.settle('paid','completed',.3)
    client=TestClient(server.app);url=f"/api/jobs/{job['id']}/budget"
    assert client.patch(url,json={'budget_cny':.2}).status_code==400
    assert client.patch(url,json={'budget_cny':.8}).status_code==200
    assert store.get_job(job['id'])['spec']['budget_cny']==.8
    assert store.usage_for(job['id'])['spent']==.3


def test_download_server_ignoring_range_restarts_instead_of_appending(tmp_path,monkeypatch):
    monkeypatch.setattr(preparation,'ROOT',tmp_path)
    payload=b'correct complete model'
    row={'path':'model','size':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'url':'https://fixture.invalid'}
    (tmp_path/'model.part').write_bytes(payload[:3]);real=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=payload))))
    preparation.download(row,lambda:None,lambda _:None)
    assert (tmp_path/'model').read_bytes()==payload


def test_disk_error_during_preparation_never_marks_ready(tmp_path,monkeypatch):
    monkeypatch.setattr(preparation,'ROOT',tmp_path);monkeypatch.setattr(preparation,'DATA',tmp_path/'data')
    monkeypatch.setattr(preparation,'manifest',lambda:{'files':[{'path':'model','model':'fixture','size':1}]})
    def full(*args):raise OSError('disk full')
    monkeypatch.setattr(preparation,'download',full)
    preparation.prepare()
    assert preparation.state()['status']=='failed' and not preparation.state()['ready']
    assert not (tmp_path/'data/models-verified.json').exists()


def test_cascade_loads_from_unicode_path_without_native_filename_loader(tmp_path,monkeypatch):
    import cv2
    import numpy as np
    from lecture_notes import vision
    path=tmp_path/'中文 路径';path.mkdir()
    name='haarcascade_frontalface_default.xml'
    (path/name).write_bytes((Path(cv2.data.haarcascades)/name).read_bytes())
    monkeypatch.setattr(cv2.data,'haarcascades',str(path))
    vision.face_detector.cache_clear()
    try:
        detector=vision.face_detector(name)
        assert not detector.empty()
        assert len(detector.detectMultiScale(np.zeros((100,100),np.uint8)))==0
    finally:vision.face_detector.cache_clear()


@pytest.mark.parametrize('bad_usage',[None,'123',-1])
def test_bad_usage_preserves_valid_response_and_reservation(release_job,monkeypatch,bad_usage):
    from lecture_notes.synthesis import build_sections,organize
    job,output=release_job
    class Client:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kw):
            return httpx.Response(200,request=httpx.Request('POST','https://fixture.invalid'),json={
                'choices':[{'message':{'content':'## 定义\n完整课程知识。'},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':bad_usage,'completion_tokens':12}})
    monkeypatch.setattr(httpx,'Client',Client)
    sections=build_sections([{'id':'s1','start':0,'end':3,'text':'完整课程知识。'}],[],[[0,60]])
    config={**settings.DEFAULTS,'api_key':'fixture','base_url':'https://fixture.invalid/v1','model':'fixture','input_price':.1,'output_price':.1}
    result,message=organize(job['id'],sections,3600,output,config,lambda *a:None,lambda:None)
    assert not message and result[0]['organized'] and '完整课程知识' in result[0]['body']
    call=store.usage_for(job['id'])['calls'][0]
    assert call['status']=='completed_usage_unknown' and call['actual'] is None and call['reserved']>0
    assert workflow.status(job,output)['billing_confirmation_required']==[call['id']]


def test_windows_utf8_manifest_preserves_python_and_enables_native_unicode(tmp_path):
    import os,sys,shutil,subprocess,importlib.util
    if os.name!='nt':pytest.skip('Windows application manifest')
    base=Path(sys.base_prefix);original=base/'python.exe';before=hashlib.sha256(original.read_bytes()).hexdigest()
    for name in ['python.exe','python3.dll','python311.dll','vcruntime140.dll','vcruntime140_1.dll']:
        if (base/name).is_file():shutil.copy2(base/name,tmp_path/name)
    helper=Path(__file__).resolve().parents[1]/'scripts/portable_crt.py'
    spec=importlib.util.spec_from_file_location('portable_crt_test',helper)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.enable_utf8_manifest(tmp_path/'python.exe')
    result=__import__('subprocess').run([str(tmp_path/'python.exe'),'-c','import ctypes;print(ctypes.windll.kernel32.GetACP())'],
        env={**os.environ,'PYTHONHOME':str(base),'PYTHONNOUSERSITE':'1'},capture_output=True,text=True,check=True)
    assert result.stdout.strip()=='65001'
    assert hashlib.sha256(original.read_bytes()).hexdigest()==before
