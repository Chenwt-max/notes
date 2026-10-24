from fastapi.testclient import TestClient
from lecture_notes import server,store,settings


def test_local_api_redacts_key_and_rejects_foreign_origin(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'DATA',tmp_path/'config')
    monkeypatch.setattr(settings,'SESSION_KEY','test-secret')
    client=TestClient(server.app)
    response=client.get('/api/settings')
    assert response.status_code==200
    assert response.json()['has_key']
    assert 'test-secret' not in response.text and 'api_key' not in response.json()
    assert client.put('/api/settings',json={},headers={'Origin':'https://example.invalid'}).status_code==403


def test_job_creation_and_artifact_boundary(tmp_path,monkeypatch,prepared_models):
    monkeypatch.setattr(store,'DATA',tmp_path/'db')
    monkeypatch.setattr(store,'OUTPUT',tmp_path/'out')
    monkeypatch.setattr(server,'OUTPUT',tmp_path/'out')
    monkeypatch.setattr(server,'WORKSPACE',tmp_path)
    monkeypatch.setattr(server,'probe',lambda p:{'duration':60})
    path=tmp_path/'course.mp4';path.write_bytes(b'fixture-not-decoded')
    client=TestClient(server.app)
    r=client.post('/api/jobs',json={'path':str(path),'windows':[[0,30]],'formulas':False})
    assert r.status_code==200,r.text
    job_id=r.json()['id']
    assert client.get('/api/jobs/'+job_id).status_code==200
    assert client.get(f'/api/artifacts/{job_id}/%2e%2e/settings.json').status_code==400
    assert client.post('/api/jobs',json={'path':str(tmp_path.parent/'elsewhere.mp4')}).status_code==400
    regions=[{'kind':'slides','quad':[[.1,.1],[.6,.1],[.6,.7],[.1,.7]]}]
    r=client.post('/api/jobs',json={'path':str(path),'regions':regions,'regions_capture_ts':20})
    assert r.status_code==200
    assert r.json()['spec']['regions_capture_ts']==20


def test_review_queues_existing_job_and_rejects_running_job(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path/'db')
    monkeypatch.setattr(store,'OUTPUT',tmp_path/'out')
    job=store.create_job({'path':'source.mp4','organize':False})
    store.update_job(job['id'],status='ready')
    client=TestClient(server.app)
    response=client.post(f"/api/jobs/{job['id']}/review")
    assert response.status_code==409
    assert store.get_job(job['id'])['status']=='ready'
    response=client.post(f"/api/jobs/{job['id']}/review",json={'confirm_reprocess':True})
    assert response.status_code==200
    assert response.json()['status']=='queued'
    assert response.json()['spec']['organize'] and response.json()['spec']['review_notes']
    store.update_job(job['id'],status='running')
    assert client.post(f"/api/jobs/{job['id']}/review").status_code==400


def test_duplicate_creation_needs_explicit_confirmation(tmp_path,monkeypatch,prepared_models):
    monkeypatch.setattr(store,'DATA',tmp_path/'db')
    monkeypatch.setattr(store,'OUTPUT',tmp_path/'out')
    monkeypatch.setattr(server,'WORKSPACE',tmp_path)
    monkeypatch.setattr(server,'probe',lambda p:{'duration':60})
    path=tmp_path/'course.mp4';path.write_bytes(b'fixture-not-decoded')
    client=TestClient(server.app)
    first=client.post('/api/jobs',json={'path':str(path)}).json()
    response=client.post('/api/jobs',json={'path':str(path),'windows':[[10,20]]})
    assert response.status_code==409
    assert response.json()['detail']['existing_job_id']==first['id']
    assert len(store.list_jobs())==1
    second=client.post('/api/jobs',json={'path':str(path),'confirm_reprocess':True})
    assert second.status_code==200 and second.json()['id']!=first['id']
    assert len(store.list_jobs())==2


def test_import_local_path_registers_once_without_copying(tmp_path,monkeypatch):
    workspace=tmp_path/'workspace';workspace.mkdir()
    monkeypatch.setattr(server,'WORKSPACE',workspace)
    monkeypatch.setattr(server,'DATA',tmp_path/'data')
    monkeypatch.setattr(server,'probe',lambda p:{'duration':60,'width':1280,'height':720,'audio':True})
    video=tmp_path/'outside.mp4';video.write_bytes(b'fixture-not-decoded')
    client=TestClient(server.app)
    assert client.get('/api/video',params={'path':str(video)}).status_code==400
    response=client.post('/api/library/path',json={'path':'"'+str(video)+'"'})
    assert response.status_code==200 and response.json()['path']==str(video.resolve())
    assert client.post('/api/library/path',json={'path':str(video)}).status_code==200
    assert len(client.get('/api/library').json())==1
    assert client.get('/api/video',params={'path':str(video)}).content==b'fixture-not-decoded'
    assert not list(workspace.iterdir())
    assert client.post('/api/library/path',json={'path':'https://example.com/video.mp4'}).status_code==400
    assert client.post('/api/library/path',json={'path':str(tmp_path/'missing.mp4')}).status_code==400
    assert client.post('/api/library/path',json={'path':str(video)},headers={'Origin':'https://example.invalid'}).status_code==403


def test_import_rejects_corrupt_video_without_registering(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA',tmp_path/'data')
    def invalid(p):raise ValueError('no video')
    monkeypatch.setattr(server,'probe',invalid)
    video=tmp_path/'broken.mp4';video.write_bytes(b'broken')
    response=TestClient(server.app).post('/api/library/path',json={'path':str(video)})
    assert response.status_code==400 and not (tmp_path/'data/library.json').exists()


def test_batch_import_is_atomic_and_deduplicates_paths(tmp_path,monkeypatch):
    workspace=tmp_path/'workspace';workspace.mkdir()
    monkeypatch.setattr(server,'WORKSPACE',workspace)
    monkeypatch.setattr(server,'DATA',tmp_path/'data')
    monkeypatch.setattr(server,'probe',lambda p:{'duration':60,'width':1280,'height':720,'audio':True})
    a=tmp_path/'第一节.mp4';b=tmp_path/'第二节.mp4'
    a.write_bytes(b'a');b.write_bytes(b'b')
    client=TestClient(server.app)
    failed=client.post('/api/library/paths',json={'paths':[str(a),str(tmp_path/'missing.mp4')]})
    assert failed.status_code==400 and '第2条' in failed.json()['detail']
    assert not (tmp_path/'data/library.json').exists()
    response=client.post('/api/library/paths',json={'paths':[str(a),'"'+str(b)+'"',str(a)]})
    assert response.status_code==200 and len(response.json()['videos'])==2
    assert len(client.get('/api/library').json())==2
    assert client.post('/api/library/paths',json={'paths':[str(b),str(a)]}).status_code==200
    assert len(client.get('/api/library').json())==2 and not list(workspace.iterdir())
    assert client.post('/api/library/paths',json={'paths':[]}).status_code==400


def test_short_imported_video_preview_stays_inside_duration(tmp_path,monkeypatch):
    import numpy as np
    monkeypatch.setattr(server,'WORKSPACE',tmp_path)
    monkeypatch.setattr(server,'probe',lambda p:{'duration':2})
    sampled=[]
    def frame(p,second):
        sampled.append(second)
        return np.zeros((16,16,3),dtype=np.uint8)
    monkeypatch.setattr(server,'image_at',frame)
    video=tmp_path/'short.mp4';video.write_bytes(b'fixture')
    result=TestClient(server.app).get('/api/snapshot',params={'path':str(video),'second':60})
    assert result.status_code==200 and 0<=sampled[0]<2
