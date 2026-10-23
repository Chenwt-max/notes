import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lecture_notes import catalog,deletion,runner,server,store


@pytest.fixture
def local(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'OUTPUT',tmp_path/'outputs')
    monkeypatch.setattr(runner,'OUTPUT',tmp_path/'outputs')
    monkeypatch.setattr(server,'OUTPUT',tmp_path/'outputs')
    monkeypatch.setattr(server,'WORKSPACE',tmp_path)
    monkeypatch.setattr(runner,'settings',lambda *_:{'api_key':'','max_concurrent_jobs':0})
    source=tmp_path/'original.mp4';source.write_bytes(b'original-video')
    return source


def make_job(source,status='paused'):
    job=store.create_job({'path':str(source),'title':'删除测试'})
    store.update_job(job['id'],status=status)
    output=store.OUTPUT/job['id']
    (output/'images').mkdir()
    (output/'images/frame.png').write_bytes(b'image')
    (output/'notes.json').write_text('[]')
    return store.get_job(job['id']),output


def test_delete_generated_files_preserves_source_other_jobs_models_and_billing(local):
    job,output=make_job(local)
    other,other_output=make_job(local)
    model=local.parent/'models/model.bin';model.parent.mkdir();model.write_bytes(b'shared-model')
    store.reserve(job['id'],'paid-call',.1,1,{})
    client=TestClient(server.app)
    assert client.delete('/api/jobs/'+job['id']).status_code==202
    runner.tick({})
    assert not output.exists() and other_output.exists()
    assert local.read_bytes()==b'original-video' and model.read_bytes()==b'shared-model'
    with pytest.raises(KeyError):store.get_job(job['id'])
    assert store.usage_for(job['id'])['spent']==.1
    assert store.get_job(other['id'])['status']=='paused'


def test_delete_request_cannot_be_overwritten_requeued_or_billed(local):
    job,output=make_job(local,'queued')
    store.request_delete(job['id'])
    store.update_job(job['id'],status='ready',message='late worker callback')
    assert store.get_job(job['id'])['status']=='delete_requested'
    assert not store.claim_job(job['id'])
    with pytest.raises(store.TaskStopped):store.check_job(job['id'])
    with pytest.raises(store.TaskStopped):store.reserve(job['id'],'new-call',.1,1,{})
    assert TestClient(server.app).post('/api/jobs/'+job['id']+'/resume').status_code==400
    runner.tick({})
    assert not output.exists()


def test_course_delete_cascades_all_runs_but_does_not_recreate_catalog(local):
    second=local.parent/'second.mp4';second.write_bytes(b'second')
    catalog.initialize([local,second])
    first=catalog.list_courses()[0]
    other=catalog.create_course({'title':'另一门课程'})['id']
    catalog.update_lesson(first['lessons'][1]['id'],{'course_id':other})
    jobs=[make_job(local,status) for status in ['queued','running','ready']]
    keep,keep_output=make_job(second)
    client=TestClient(server.app)
    result=client.delete('/api/courses/'+first['id'])
    assert result.status_code==202 and len(result.json()['job_ids'])==3
    assert all(store.get_job(j['id'])['status']=='delete_requested' for j,_ in jobs)
    assert [c['id'] for c in client.get('/api/courses').json()]==[other]
    runner.tick({})
    assert all(not output.exists() for _,output in jobs)
    assert keep_output.exists() and store.get_job(keep['id'])['status']=='paused'
    assert local.read_bytes()==b'original-video' and second.read_bytes()==b'second'


def test_locked_directory_failure_can_retry_without_losing_record(local,monkeypatch):
    job,output=make_job(local)
    remove=deletion.shutil.rmtree
    def locked(_):raise PermissionError('fixture locked file')
    monkeypatch.setattr(deletion.shutil,'rmtree',locked)
    store.request_delete(job['id']);runner.tick({})
    assert store.get_job(job['id'])['status']=='delete_failed' and output.exists()
    monkeypatch.setattr(deletion.shutil,'rmtree',remove)
    store.request_delete(job['id']);runner.tick({})
    assert not output.exists()


def test_pending_delete_survives_service_restart_without_restoring_materials(local):
    job,output=make_job(local)
    (output/'materials_pending.json').write_text('{}')
    store.request_delete(job['id'])
    with TestClient(server.app) as client:
        deadline=time.monotonic()+4
        while client.get('/api/jobs').json() and time.monotonic()<deadline:time.sleep(.1)
        assert client.get('/api/jobs').json()==[]
    assert not output.exists() and local.read_bytes()==b'original-video'


def test_process_stop_failure_never_deletes_live_output(local,monkeypatch):
    job,output=make_job(local,'running')
    log=(output/'worker.log').open('w')
    class Process:
        def poll(self):return None
    active={job['id']:(Process(),log)}
    def fail(_):raise subprocess.TimeoutExpired('fixture',1)
    monkeypatch.setattr(runner,'terminate_tree',fail)
    store.request_delete(job['id']);runner.tick(active)
    assert output.exists() and not log.closed and job['id'] in active
    assert store.get_job(job['id'])['status']=='delete_failed'
    monkeypatch.setattr(runner,'terminate_tree',lambda _:None)
    store.request_delete(job['id']);runner.tick(active)
    assert not output.exists() and log.closed and not active


@pytest.mark.parametrize('job_id',['../outside','..','a'*11,'/'+'a'*12])
def test_invalid_job_directory_never_recursively_deleted(local,job_id):
    with pytest.raises(ValueError):deletion.output_for_deletion({'id':job_id,'spec':{'path':str(local)}})
    assert local.read_bytes()==b'original-video'


def test_source_inside_output_is_never_deleted(local):
    folder=store.OUTPUT/('a'*12);folder.mkdir(parents=True)
    source=folder/'original.mp4';source.write_bytes(b'keep')
    with pytest.raises(ValueError,match='原视频'):deletion.output_for_deletion({'id':'a'*12,'spec':{'path':str(source)}})
    assert source.read_bytes()==b'keep'


def test_link_to_other_directory_is_not_followed(local):
    job,output=make_job(local)
    outside=local.parent/'outside';outside.mkdir();(outside/'keep').write_bytes(b'keep')
    try:(output/'linked').symlink_to(outside,target_is_directory=True)
    except OSError:
        if os.name!='nt':raise
        import _winapi
        _winapi.CreateJunction(str(outside),str(output/'linked'))
    store.request_delete(job['id']);runner.tick({})
    assert store.get_job(job['id'])['status']=='delete_failed'
    assert (outside/'keep').read_bytes()==b'keep'


@pytest.mark.skipif(os.name!='nt',reason='Windows process-tree behavior')
def test_running_parent_and_child_stop_before_directory_delete(local):
    job,output=make_job(local,'running')
    child_code="""import sys,time
from pathlib import Path
memory=bytearray(8*1024*1024)
folder=Path(sys.argv[1])
while True:
 folder.mkdir(parents=True,exist_ok=True)
 (folder/'heartbeat').write_text('running')
 time.sleep(.03)
"""
    parent_code=f"""import subprocess,sys,time
p=subprocess.Popen([sys.executable,'-u','-c',{child_code!r},sys.argv[1]],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
print(p.pid,flush=True)
while True:time.sleep(1)
"""
    process=subprocess.Popen([sys.executable,'-u','-c',parent_code,str(output)],stdout=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    child_pid=int(process.stdout.readline())
    log=(output/'worker.log').open('w')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]
    kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x1000,False,child_pid)
    assert handle
    try:
        deadline=time.monotonic()+8
        while not (output/'heartbeat').exists() and time.monotonic()<deadline:time.sleep(.03)
        assert (output/'heartbeat').exists()
        store.request_delete(job['id'])
        active={job['id']:(process,log)};runner.tick(active)
        assert process.poll() is not None and not active and log.closed
        exit_code=ctypes.c_uint32()
        assert kernel.GetExitCodeProcess(handle,ctypes.byref(exit_code)) and exit_code.value!=259
        time.sleep(.15)
        assert not output.exists() and local.read_bytes()==b'original-video'
    finally:
        if process.poll() is None:runner.terminate_tree(process)
        kernel.CloseHandle(handle);process.stdout.close();log.close()
