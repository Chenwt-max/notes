import json
from types import SimpleNamespace
import httpx
import pytest
from lecture_notes import resources,settings,store,server
from lecture_notes.asr_worker import instrument_model
from lecture_notes.common import read_json,write_json
from lecture_notes.synthesis import build_sections,organize,is_note_reviewed,pending_review_ids
from lecture_notes.note_content import clean_note
from lecture_notes.timing import Timings,timing_summary


@pytest.mark.parametrize('mode,rest',[('listening',8),('balanced',2),('fast',0)])
def test_load_modes_have_bounded_pausable_sleep(monkeypatch,mode,rest):
    now=[8.];checks=[]
    monkeypatch.setenv('LECTURE_PROCESSING_MODE',mode)
    monkeypatch.setattr(resources,'time',SimpleNamespace(monotonic=lambda:now[0],sleep=lambda n:now.__setitem__(0,now[0]+n)))
    resources.cooldown(0,lambda:checks.append(now[0]))
    assert now[0]==pytest.approx(8+rest)
    assert bool(checks)==bool(rest)


def test_listening_mode_can_be_saved_without_replacing_other_preferences(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'DATA',tmp_path)
    write_json(tmp_path/'settings.json',{'cpu_threads':1,'gpu_concurrency':1})
    saved=settings.save_settings({'processing_mode':'listening'})
    assert saved['processing_mode']=='listening' and saved['cpu_threads']==1 and saved['gpu_concurrency']==1


def test_timing_survives_nested_recorders_interruptions_and_resume(tmp_path):
    one=Timings(tmp_path,'asr');two=Timings(tmp_path,'asr')
    with one.measure('total'):
        with two.measure('recognition'):pass
    with pytest.raises(store.TaskStopped):
        with one.measure('cooldown'):raise store.TaskStopped('paused')
    with Timings(tmp_path,'asr').measure('recognition'):pass
    m=timing_summary(tmp_path)['groups']['asr']
    assert m['recognition']['completed']==2 and m['cooldown']['interrupted']==1
    assert m['total']['completed']==1 and all(row['seconds']>=0 for row in m.values())


def test_instrumentation_keeps_sdk_results_and_arguments(tmp_path):
    calls=[]
    def recognize(*args,**kw):calls.append(('asr',args,kw));return ['文字']
    def align(*args,**kw):calls.append(('align',args,kw));return ['词级时间']
    model=SimpleNamespace(_infer_asr=recognize,forced_aligner=SimpleNamespace(align=align))
    instrument_model(model,Timings(tmp_path,'asr'))
    assert model._infer_asr(['context'],language='Chinese')==['文字']
    assert model.forced_aligner.align(audio='same audio',text='文字')==['词级时间']
    assert calls==[('asr',(['context'],),{'language':'Chinese'}),('align',(),{'audio':'same audio','text':'文字'})]
    assert set(timing_summary(tmp_path)['groups']['asr'])=={'recognition','alignment'}


@pytest.fixture
def chapters(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path/'db');monkeypatch.setattr(store,'OUTPUT',tmp_path/'out')
    monkeypatch.setattr(server,'OUTPUT',tmp_path/'out')
    job=store.create_job({'path':'source.mp4'})['id'];output=store.OUTPUT/job
    sections=build_sections([{'id':f's{i}','start':i*300,'end':i*300+5,'text':f'第{i+1}章数学定义'} for i in range(2)],[],[[0,600]])
    config={**settings.DEFAULTS,'api_key':'fixture','base_url':'https://api.deepseek.com','model':'deepseek-flash',
            'input_price':2,'output_price':8,'budget_per_hour':10,'max_output_tokens':800,
            'input_tokens_per_hour':1000000,'output_tokens_per_hour':1000000}
    calls=[]
    class Client:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,url,**kw):
            request=kw['json'];user=json.loads(request['messages'][1]['content']);review='已有笔记' in user
            if isinstance(user,list):
                assert all(s['body'] for s in user)
                calls.append(('chapters','all'))
                content={'chapters':[{'title':'完整数学主题','ids':[s['id'] for s in user]}]}
            else:
                calls.append(('review' if review else 'organize',user['时段']))
                content={'edits':[]} if review else {'body':'## 数学定义\n\n保留前提与完整公式。','repairs':[]}
            # Charging the full bound also exercises future-request protection.
            prompt=len(''.join(m['content'] for m in request['messages']).encode('utf-8'))+128
            return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':json.dumps(content,ensure_ascii=False)},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':prompt,'completion_tokens':request['max_tokens']}})
    monkeypatch.setattr(httpx,'Client',Client)
    return job,output,sections,config,calls


def test_chapter_is_reviewed_and_published_before_next_chapter(chapters):
    job,output,sections,config,calls=chapters;published=[]
    def publish(section):
        assert is_note_reviewed(section) and not section.get('publication_pending')
        if not published:assert not sections[1]['organized']
        published.append(section['id'])
    result,message=organize(job,sections,600,output,config,lambda *a:None,lambda:None,review_each=True,on_publish=publish)
    assert not message and published==['n0001','n0002']
    assert [c[0] for c in calls]==['organize','review','organize','review']
    assert all(is_note_reviewed(s) for s in result)
    before=len(calls)
    organize(job,result,600,output,config,lambda *a:None,lambda:None,reuse_completed=True,review_each=True,on_publish=publish)
    assert len(calls)==before


def test_pause_after_first_publication_keeps_it_and_resume_skips_its_requests(chapters):
    job,output,sections,config,calls=chapters
    def pause(_):raise store.TaskStopped('paused')
    with pytest.raises(store.TaskStopped):
        organize(job,sections,600,output,config,lambda *a:None,lambda:None,review_each=True,on_publish=pause)
    saved=read_json(output/'notes.json')
    assert is_note_reviewed(saved[0]) and not saved[1]['organized']
    organize(job,saved,600,output,config,lambda *a:None,lambda:None,reuse_completed=True,review_each=True)
    assert [c[0] for c in calls]==['organize','review','organize','review']


@pytest.mark.parametrize('cap',['money','input','output'])
def test_review_cannot_spend_tokens_or_money_needed_by_future_chapters(chapters,cap):
    job,output,sections,config,calls=chapters
    class Stop(Exception):pass
    def stop():raise Stop()
    with pytest.raises(Stop):organize(job,sections,600,output,config,lambda *a:None,stop)
    estimate=read_json(output/'api_estimate.json');hours=600/3600
    if cap=='money':config['budget_per_hour']=(estimate['estimated_max_cny']+1e-7)/hours
    elif cap=='input':config['input_tokens_per_hour']=(estimate['reserved_input_tokens']+.1)/hours
    else:config['output_tokens_per_hour']=(estimate['max_output_tokens']+.1)/hours
    result,message=organize(job,sections,600,output,config,lambda *a:None,lambda:None,review_each=True)
    assert not message and all(s['organized'] for s in result)
    assert [c[0] for c in calls]==['organize','organize']
    assert all(s.get('publication_pending') for s in result)
    assert pending_review_ids(result)=={'n0001','n0002'}
    organize(job,result,600,output,config,lambda *a:None,lambda:None,review_mode=True,review_ids=pending_review_ids(result))
    assert pending_review_ids(result)=={'n0001','n0002'}
    assert store.usage_for(job)['spent']<=config['budget_per_hour']*hours+1e-9
    for section in result:
        public=clean_note(section)
        assert not public['body'] and not public['organized']


def test_failed_review_is_not_automatically_retried_or_published(chapters,monkeypatch):
    job,output,sections,config,calls=chapters
    class Client:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,url,**kw):
            request=kw['json'];review='已有笔记' in json.loads(request['messages'][1]['content'])
            calls.append('review' if review else 'organize')
            body='invalid JSON' if review else json.dumps({'body':'## 定义\n完整知识。','repairs':[]})
            return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':body},'finish_reason':'stop'}],
                                                                         'usage':{'prompt_tokens':100,'completion_tokens':50}})
    monkeypatch.setattr(httpx,'Client',Client);published=[]
    result,_=organize(job,sections,600,output,config,lambda *a:None,lambda:None,review_each=True,on_publish=published.append)
    assert not published and all(s.get('publication_pending') for s in result)
    assert not pending_review_ids(result)
    organize(job,result,600,output,config,lambda *a:None,lambda:None,review_mode=True,review_ids=pending_review_ids(result))
    assert calls==['organize','review','organize','review']


def test_api_masks_unpublished_notes_and_exposes_component_timings(chapters,monkeypatch):
    from fastapi.testclient import TestClient
    from lecture_notes import assistant
    job,output,sections,config,calls=chapters
    sections[0].update(body='UNREVIEWED_BODY',organized=True,publication_pending=True)
    write_json(output/'notes.json',sections)
    with Timings(output,'asr').measure('recognition'):pass
    response=TestClient(server.app).get('/api/jobs/'+job)
    assert response.status_code==200
    data=response.json()
    assert not data['notes'][0]['body'] and not data['notes'][0]['organized']
    assert data['timings']['groups']['asr']['recognition']['completed']==1
    with pytest.raises(ValueError,match='发布后'):
        assistant.explain(job,{'request_id':'pending_test','note_id':sections[0]['id'],'question':'解释这个'},config)
    assert not calls


def test_offline_notes_do_not_publish_unreviewed_body_or_raw_transcript(chapters):
    from lecture_notes.export import export_notes
    job,output,sections,config,calls=chapters
    sections[0].update(body='UNREVIEWED_BODY',organized=True,publication_pending=True)
    sections[1].update(body='## 完成章节\n可阅读的定义。',organized=True)
    segments=[{'id':f's{i}','start':i*300,'end':i*300+5,'text':'RAW_UNREVIEWED_TRANSCRIPT'} for i in range(2)]
    export_notes('测试',sections,segments,[],output)
    markdown=(output/'notes.md').read_text(encoding='utf-8')
    assert 'UNREVIEWED_BODY' not in markdown and 'RAW_UNREVIEWED_TRANSCRIPT' not in markdown
    assert '本章整理与复核完成后发布' in markdown and '可阅读的定义' in markdown


@pytest.mark.parametrize('early',[True,False])
@pytest.mark.parametrize('fixed_budget',[None,1.])
def test_pipeline_waits_for_local_sources_then_publishes_chapters(chapters,monkeypatch,early,fixed_budget):
    from lecture_notes import pipeline,maintenance
    job,output,sections,config,calls=chapters
    original_client=httpx.Client
    class PrivateClient(original_client):
        def post(self,*args,**kwargs):
            assert all(not n.get('body') for n in read_json(output/'notes.json',[]))
            content=json.loads(kwargs['json']['messages'][1]['content'])
            if isinstance(content,dict) and '已有笔记' in content and content['时段'].startswith('00:00:00'):
                assert content['衔接参考']['后文成稿'],'Whole-course review sees adjacent drafts even before publication'
            return super().post(*args,**kwargs)
    monkeypatch.setattr(httpx,'Client',PrivateClient)
    monkeypatch.setenv('LECTURE_INFERENCE_DEVICE','cpu')
    monkeypatch.setattr(pipeline,'OUTPUT',store.OUTPUT)
    monkeypatch.setattr(pipeline,'settings',lambda *_:config)
    source=output/'source.mp4';source.write_bytes(b'unchanged source')
    spec={'path':str(source),'windows':[[0,600]],'formulas':True,'organize':True,'publish_early':early,'incremental_minutes':20}
    if fixed_budget is not None:spec['budget_cny']=fixed_budget
    with store.connect() as db:db.execute('UPDATE jobs SET spec=? WHERE id=?',(json.dumps(spec),job))
    segments=[{'id':f's{i}','start':i*300,'end':i*300+5,'text':f'第{i+1}章定义'} for i in range(2)]
    visual={'id':'v1','start':0,'end':600,'capture_ts':1,'image':'source.png','content_id':'p1','ocr':'课件定义','formulas':[]}
    events=[];exports=[]
    monkeypatch.setattr(pipeline,'probe',lambda _: {'duration':600,'audio':True})
    def transcribe(*args):
        events.append('asr');write_json(output/'transcript.json',segments)
    def extract(*args,**kw):
        events.append('visuals');write_json(output/'visuals.json',[visual])
    def compact(*args):
        events.append('compact');return [visual],[],{}
    def recognize(*args):events.append('ocr');return [visual]
    def formula(*args):events.append('formulas')
    def export(title,notes,*args):
        public=[clean_note(n) for n in notes]
        assert all(not n.get('body') or n.get('reviewed_body_hash') for n in public)
        exports.append([n['id'] for n in public if n.get('organized')])
    monkeypatch.setattr(pipeline,'transcribe',transcribe);monkeypatch.setattr(pipeline,'extract_video',extract)
    monkeypatch.setattr(pipeline,'compact_visuals',compact);monkeypatch.setattr(pipeline,'recognize',recognize)
    monkeypatch.setattr(pipeline,'run_formula',formula);monkeypatch.setattr(pipeline,'export_notes',export)
    monkeypatch.setattr(pipeline,'audit_visuals',lambda *a:{'uncovered_intervals_over_0_6s':[],'region_coverage_gaps_over_0_6s':[]})
    monkeypatch.setattr(pipeline,'audit_output',lambda *a,**kw:{'integrity_ok':True,'formulas':{'syntax':{'available':True,'errors':[]},'disagreements':[]}})
    monkeypatch.setattr(maintenance,'clean_job',lambda *a,**kw:None)
    real_organize=pipeline.organize
    def organized(*args,**kw):
        assert events==['asr','visuals','compact','ocr','formulas']
        if fixed_budget is not None:
            actual=args[4];hours=600/3600
            assert 0<actual['budget_per_hour']*hours<fixed_budget
            assert actual['input_tokens_per_hour']*hours>=fixed_budget*1e6/actual['input_price']
            assert actual['output_tokens_per_hour']*hours>=fixed_budget*1e6/actual['output_price']
        return real_organize(*args,**kw)
    monkeypatch.setattr(pipeline,'organize',organized)
    pipeline.run_job(job)
    assert store.get_job(job)['status']=='ready'
    assert exports==[[],['n0001']]
    assert [c[0] for c in calls]==['organize','organize','review','review','chapters']
    assert read_json(output/'report.json')['published_sections']==1
    assert read_json(output/'notes.json')[0]['source_note_ids']==['n0001','n0002']


@pytest.mark.parametrize('phase',['organize','review'])
def test_uncertain_request_does_not_retry_when_plan_limits_change(chapters,monkeypatch,phase):
    job,output,sections,config,calls=chapters
    class Client:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,url,**kw):calls.append(url);raise httpx.ReadTimeout('simulated uncertainty')
    monkeypatch.setattr(httpx,'Client',Client)
    if phase=='review':
        for section in sections:section.update(body='## 待复核\n完整定义。',organized=True,publication_pending=True)
    with pytest.raises(ValueError,match='不自动重试'):
        organize(job,sections,600,output,config,lambda *a:None,lambda:None,review_mode=phase=='review')
    changed={**config,'input_tokens_per_hour':config['input_tokens_per_hour']*2,'max_output_tokens':1200}
    _,message=organize(job,sections,600,output,changed,lambda *a:None,lambda:None,review_mode=phase=='review')
    assert '未确认' in message and len(calls)==1
    assert store.usage_for(job)['calls'][0]['status']=='uncertain'
    if phase=='review':assert not clean_note(sections[0])['body'] and sections[0].get('review_warning')
