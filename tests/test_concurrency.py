import os
import sys
import subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
from lecture_notes import resources,runner,store,settings
from lecture_notes.common import write_json


@pytest.fixture
def queue(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'OUTPUT',tmp_path/'out')
    monkeypatch.setattr(runner,'OUTPUT',tmp_path/'out')
    config={'max_concurrent_jobs':0,'api_key':''}
    monkeypatch.setattr(runner,'settings',lambda *_:config)
    class Process:
        def __init__(self,*args,**kwargs):self.returncode=None
        def poll(self):return self.returncode
    monkeypatch.setattr(runner.subprocess,'Popen',Process)
    ids=[store.create_job({'path':f'{i}.mp4'})['id'] for i in range(3)]
    return ids,config


def test_default_starts_every_requested_course_once(queue):
    ids,config=queue;active={}
    runner.tick(active)
    assert set(active)==set(ids)
    assert all(store.get_job(j)['status']=='starting' for j in ids)
    runner.tick(active)
    assert len(active)==3
    for _,log in active.values():log.close()


def test_concurrency_limit_and_failure_do_not_block_other_courses(queue):
    ids,config=queue;config['max_concurrent_jobs']=2;active={}
    runner.tick(active)
    assert set(active)==set(ids[:2]) and store.get_job(ids[2])['status']=='queued'
    process,log=active[ids[0]];process.returncode=1
    runner.tick(active)
    assert log.closed and store.get_job(ids[0])['status']=='needs_attention'
    assert set(active)==set(ids[1:])
    for _,log in active.values():log.close()


def test_paused_job_cannot_be_claimed_or_restart_itself(queue):
    ids,_=queue;store.update_job(ids[0],status='paused')
    assert not store.claim_job(ids[0])
    with pytest.raises(store.TaskStopped):store.start_job(ids[0])
    assert store.get_job(ids[0])['status']=='paused'
    assert store.claim_job(ids[1])
    store.update_job(ids[1],status='pause_requested')
    with pytest.raises(store.TaskStopped):store.start_job(ids[1])


@pytest.mark.parametrize('key,value',[('cpu_threads',0),('cpu_threads',1.5),('cpu_threads',True),('gpu_concurrency',-1),('max_concurrent_jobs',129),('device','unknown')])
def test_invalid_resource_settings_are_rejected(tmp_path,monkeypatch,key,value):
    monkeypatch.setattr(settings,'DATA',tmp_path)
    with pytest.raises(ValueError):settings.save_settings({key:value})


def test_resource_preferences_persist_and_default_unlimited(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'DATA',tmp_path)
    assert settings.settings()['max_concurrent_jobs']==0
    saved=settings.save_settings({'cpu_threads':1,'gpu_concurrency':2,'max_concurrent_jobs':3,'device':'cpu'})
    assert saved['cpu_threads']==1 and settings.settings()['gpu_concurrency']==2
    assert saved['max_concurrent_jobs']==3 and saved['device']=='cpu'


def test_gpu_slots_limit_release_and_cpu_bypass(tmp_path,monkeypatch):
    monkeypatch.setattr(resources,'DATA',tmp_path)
    monkeypatch.setattr(resources,'gpu_memory',lambda:(16384,16384))
    monkeypatch.setenv('LECTURE_INFERENCE_DEVICE','cuda')
    write_json(tmp_path/'settings.json',{'gpu_concurrency':2})
    def stop():raise store.TaskStopped('paused')
    with resources.gpu_slot():
        with resources.gpu_slot():
            attempts=[]
            def check():
                if attempts:stop()
                attempts.append(True)
            with pytest.raises(store.TaskStopped):
                with resources.gpu_slot(check):raise AssertionError('超出并发数')
    with resources.gpu_slot():pass
    monkeypatch.setenv('LECTURE_INFERENCE_DEVICE','cpu')
    with resources.gpu_slot(stop):pass


def test_gpu_slot_is_cross_process_and_released_after_crash(tmp_path,monkeypatch):
    monkeypatch.setattr(resources,'DATA',tmp_path)
    monkeypatch.setenv('LECTURE_INFERENCE_DEVICE','cuda')
    write_json(tmp_path/'settings.json',{'gpu_concurrency':1})
    code="""from pathlib import Path
import sys
from lecture_notes import resources
resources.DATA=Path(sys.argv[1])
with resources.gpu_slot():
 print('held',flush=True)
 sys.stdin.read(1)
"""
    process=subprocess.Popen([sys.executable,'-X','utf8','-c',code,str(tmp_path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        assert process.stdout.readline().strip()==b'held'
        attempts=[]
        def check():
            if attempts:raise store.TaskStopped('paused')
            attempts.append(True)
        with pytest.raises(store.TaskStopped):
            with resources.gpu_slot(check):raise AssertionError('不应抢到其他进程占用的显卡槽')
    finally:
        runner.terminate_tree(process);process.stdin.close();process.stdout.close()
    with resources.gpu_slot():pass


def test_switching_device_reuses_completed_asr_chunks(tmp_path,monkeypatch):
    from lecture_notes.asr import process_audio,make_request
    from lecture_notes.common import read_json
    source=tmp_path/'source.mp4';source.write_bytes(b'unchanged')
    calls=[]
    class Backend:
        def recognize(self,path,start,end):
            calls.append(start)
            a=max(0,60-start) if start else 0
            return {'text':'已完成字幕','words':[{'start':a,'end':a+3,'word':'已完成字幕'}],
                    'speech_intervals':[[a,a+3]]}
        def runtime(self):return {}
    def pause(progress,message):
        if progress>0:raise store.TaskStopped('paused')
    monkeypatch.setenv('LECTURE_PROCESSING_MODE','fast')
    request=make_request(source,[[0,65]],'cuda')
    with pytest.raises(store.TaskStopped):
        process_audio(request,tmp_path,pause,lambda:None,Backend)
    assert calls==[0] and (tmp_path/'asr_chunks').is_dir()
    request.update(device='cpu',cpu_threads=1)
    segments=process_audio(request,tmp_path,lambda *_:None,lambda:None,Backend)
    assert calls==[0,58] and len(segments)==2
    runtime=read_json(tmp_path/'asr_runtime.json')
    assert runtime['cached_chunks']==1 and runtime['computed_chunks']==1
    assert runtime['cpu_threads']==1 and runtime['cache_source_devices']==['cpu','cuda']
    assert not (tmp_path/'asr_chunks').exists()


def test_formula_cpu_choice_and_thread_count_reach_model(tmp_path,monkeypatch):
    from lecture_notes.formula_worker import recognize_pages
    monkeypatch.setenv('LECTURE_INFERENCE_DEVICE','cpu')
    monkeypatch.setenv('LECTURE_CPU_THREADS','1')
    options={}
    class Pipeline:
        def predict(self,*_,**kwargs):return [SimpleNamespace(json={'res':{'parsing_res_list':[]}})]
        def close(self):pass
    def create(device,threads):
        options.update(device=device,cpu_threads=threads)
        return Pipeline()
    monkeypatch.setitem(sys.modules,'paddle',SimpleNamespace(__version__='test',is_compiled_with_cuda=lambda:True,device=SimpleNamespace(cuda=SimpleNamespace(device_count=lambda:1))))
    monkeypatch.setattr('lecture_notes.document_model.create_document_pipeline',create)
    (tmp_path/'unused.png').write_bytes(b'fixture-image')
    write_json(tmp_path/'visuals.json',[{'id':'v1','image':'unused.png'}])
    recognize_pages(tmp_path,lambda:None)
    assert options['device']=='cpu' and options['cpu_threads']==1


def test_live_subtitles_exist_before_frame_extraction_and_are_reused(tmp_path,monkeypatch):
    from lecture_notes import pipeline
    from lecture_notes.common import read_json
    monkeypatch.setattr(store,'DATA',tmp_path/'db')
    monkeypatch.setattr(store,'OUTPUT',tmp_path/'out')
    monkeypatch.setattr(pipeline,'OUTPUT',tmp_path/'out')
    monkeypatch.setenv('LECTURE_INFERENCE_DEVICE','cpu')
    monkeypatch.setattr(pipeline,'probe',lambda _: {'duration':10,'audio':True})
    monkeypatch.setattr(pipeline,'settings',lambda *_: {'asr_model':'test'})
    source=tmp_path/'course.mp4';source.write_bytes(b'source unchanged')
    job=store.create_job({'path':str(source),'windows':[[0,10]]})
    output=tmp_path/'out'/job['id'];calls=[]
    def transcribe(*args):
        calls.append('asr')
        write_json(output/'transcript.json',[{'id':'s1','start':0,'end':5,'text':'可边听边读'}])
    def extract(*args,**kwargs):
        assert read_json(output/'transcript.json')[0]['text']=='可边听边读'
        assert 'asr' in read_json(output/'manifest.json')['completed_stages']
        raise store.TaskStopped('paused')
    monkeypatch.setattr(pipeline,'transcribe',transcribe)
    monkeypatch.setattr(pipeline,'extract_video',extract)
    pipeline.run_job(job['id'])
    assert store.get_job(job['id'])['status']=='paused'
    store.update_job(job['id'],status='queued')
    pipeline.run_job(job['id'])
    assert calls==['asr']
