"""Self-authored images and a mock provider: no private course or paid calls."""
import json
from contextlib import nullcontext
from types import SimpleNamespace
import sys

import cv2
import httpx
import numpy as np
import pytest

from lecture_notes import slide_review,synthesis,store,settings,pipeline,maintenance,formula_worker
from lecture_notes.common import read_json,write_json


def decision(vid,**kw):
    return {'id':vid,'kind':'course','keep':True,'duplicate_of':None,'final_state':'unknown',
        'replaced_by':None,'content_preserved':False,'reason':'保留独有内容',**kw}


def parse(rows,ids=('a','b')):
    return slide_review.parse_decisions(json.dumps({'slides':rows}),ids)


def test_duplicate_and_final_state_require_an_explicit_retained_source():
    rows,warning=parse([decision('a',keep=False,replaced_by='b',final_state='intermediate',content_preserved=True),decision('b',final_state='final')])
    assert not warning and rows[0]['keep'] is False and rows[1]['keep']
    rows,warning=parse([decision('a',keep=False,duplicate_of='b',content_preserved=True),decision('b')])
    assert not warning and rows[0]['keep'] is False
    rows,warning=parse([decision('a',keep=False,duplicate_of='b',replaced_by='b',content_preserved=True),decision('b')])
    assert not warning and rows[0]['keep'] is False


@pytest.mark.parametrize('change',[
    {'replaced_by':'missing','final_state':'intermediate','content_preserved':True},
    {'replaced_by':'a','final_state':'intermediate','content_preserved':True},
    {'replaced_by':'b','final_state':'intermediate','content_preserved':False},
    {'duplicate_of':'b','content_preserved':False},
    {'replaced_by':'b','final_state':'unknown','content_preserved':True},
    {'kind':'uncertain'},
])
def test_uncertain_or_unsafe_hiding_is_rejected(change):
    rows,warning=parse([decision('a',keep=False,**change),decision('b')])
    assert warning and rows[0]['keep']


def test_cycles_missing_metadata_and_duplicate_ids_do_not_hide_sources():
    rows,warning=parse([decision('a',keep=False,duplicate_of='b',content_preserved=True),decision('b',keep=False,duplicate_of='a',content_preserved=True)])
    assert warning and all(r['keep'] for r in rows)
    assert parse([decision('a'),decision('a')])[0]==[]
    assert slide_review.parse_decisions('{bad',{'a'})[0]==[]
    assert slide_review.parse_decisions('{"body":"有效正文"}',{'a'})[0]==[]


def test_explicit_non_course_can_be_hidden_but_conflicts_keep_original(tmp_path):
    write_json(tmp_path/'visuals.json',[{'id':'a'},{'id':'b'},{'id':'c'}])
    bad=decision('a',keep=False,kind='non_course')
    sections=[{'id':'n1','organized':True,'slide_image_ids':['a','b'],'slide_decisions':[bad,decision('b')]}]
    result=slide_review.apply_decisions(tmp_path,sections)
    assert result[0]['api_display']['keep'] is False and result[2]['api_display']['keep']
    sections.append({'id':'n2','organized':True,'slide_image_ids':['a'],'slide_decisions':[]})
    assert slide_review.apply_decisions(tmp_path,sections)[0]['api_display']['keep']
    sections[-1]['slide_decisions']=[decision('a')]
    assert slide_review.apply_decisions(tmp_path,sections)[0]['api_display']['keep']
    assert read_json(tmp_path/'slide_review.json')['source_images_deleted'] is False


def test_compact_export_uses_retained_final_even_if_old_group_poster_was_hidden():
    visuals=[{'id':'a','content_id':'p1','is_representative':True,'api_display':{'keep':False}},
        {'id':'b','content_id':'p1','is_representative':False,'api_display':{'keep':True,'decisions':[decision('b',final_state='final')]}},
        {'id':'c','content_id':'p2','is_representative':True}]
    assert [v['id'] for v in slide_review.display_pages(visuals)]==['b','c']


def images(tmp_path):
    visuals=[]
    for i in range(2):
        image=np.full((120,240,3),240,np.uint8);cv2.putText(image,str(i),(20,60),0,1,(0,0,0),2)
        cv2.imencode('.png',image)[1].tofile(str(tmp_path/f'{i}.png'))
        visuals.append({'id':f'v{i}','kind':'slides','capture_ts':i,'start':0,'end':60,'image':f'{i}.png',
            'content_id':f'p{i}','ocr':'','formulas':[]})
    write_json(tmp_path/'visuals.json',visuals)
    return visuals


@pytest.fixture
def context(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path/'db');monkeypatch.setattr(store,'OUTPUT',tmp_path/'jobs')
    job=store.create_job({'path':'self-authored.mp4'})['id']
    visuals=images(tmp_path)
    write_json(tmp_path/'manifest.json',{'slide_mode':'vision_api'})
    sections=synthesis.build_sections([{'id':'s1','start':1,'end':2,'text':'矩阵定义。'}],visuals,[[0,60]])
    config={**settings.DEFAULTS,'api_key':'fixture','base_url':'https://api.deepseek.com','model':'deepseek-flash',
        'budget_per_hour':60,'input_price':2,'output_price':8,'input_tokens_per_hour':10**7,'output_tokens_per_hour':10**7}
    return tmp_path,job,sections,config


def provider(monkeypatch,slides):
    calls=[]
    class Client:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,url,**kw):
            calls.append(kw['json'])
            return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':json.dumps({
                'body':'## 矩阵定义\n\n保留矩阵维数及符号。','repairs':[],'slides':slides})},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':3500,'completion_tokens':500}})
    monkeypatch.setattr(httpx,'Client',Client)
    return calls


def test_images_and_judgments_share_one_paid_receipt_and_cache(context,monkeypatch):
    path,job,sections,config=context
    before=[(path/f'{i}.png').read_bytes() for i in range(2)]
    calls=provider(monkeypatch,[decision('v0',keep=False,duplicate_of='v1',content_preserved=True),decision('v1',final_state='final')])
    result,message=synthesis.organize(job,sections,60,path,config,lambda *_:None,lambda:None)
    assert not message and len(calls)==1 and result[0]['organized']
    content=calls[0]['messages'][1]['content']
    assert len([c for c in content if c['type']=='image_url'])==2
    assert all(c['image_url']['detail']=='high' for c in content if c['type']=='image_url')
    assert read_json(path/'visuals.json')[0]['api_display']['keep'] is False
    estimate=read_json(path/'api_estimate.json');assert estimate['reserved_input_tokens']>=2240
    synthesis.organize(job,result,60,path,config,lambda *_:None,lambda:None)
    assert len(calls)==1 and len(store.usage_for(job)['calls'])==1
    assert before==[(path/f'{i}.png').read_bytes() for i in range(2)]


def test_invalid_slide_metadata_preserves_body_and_never_recharges(context,monkeypatch):
    path,job,sections,config=context;calls=provider(monkeypatch,{'bad':'metadata'})
    result,_=synthesis.organize(job,sections,60,path,config,lambda *_:None,lambda:None)
    assert result[0]['organized'] and '矩阵定义' in result[0]['body'] and result[0]['slide_review_warning']
    assert all(v['api_display']['keep'] for v in read_json(path/'visuals.json'))
    synthesis.organize(job,result,60,path,config,lambda *_:None,lambda:None)
    assert len(calls)==1


def test_budget_counts_images_and_refuses_before_call(context,monkeypatch):
    path,job,sections,config=context;calls=provider(monkeypatch,[])
    config['budget_per_hour']=.00001
    _,message=synthesis.organize(job,sections,60,path,config,lambda *_:None,lambda:None)
    assert '额度' in message and not calls and not store.usage_for(job)['calls']


@pytest.mark.parametrize('complete',[True,False])
def test_thinking_review_settles_full_usage_and_never_replays_partial_stream(context,monkeypatch,complete):
    path,job,sections,config=context
    sections[0].update(body='## 定义\n\n旧数值。',organized=True)
    original_client=httpx.Client;calls=[]
    def handle(request):
        data=json.loads(request.content);calls.append(data)
        assert data['thinking']=={'type':'enabled'} and data['reasoning_effort']=='low'
        assert data['max_tokens']==config['review_max_output_tokens']==16384
        answer=json.dumps({'edits':[{'before':'旧数值。','after':'已核算的数值。','reason':'代回定义'}]})
        chunks=[{'choices':[{'delta':{'content':answer},'finish_reason':'stop'}]},
                {'choices':[],'usage':{'prompt_tokens':3500,'completion_tokens':8000}}]
        lines=['data: '+json.dumps(c) for c in chunks]
        if complete:lines.append('data: [DONE]')
        return httpx.Response(200,text='\n'.join(lines))
    monkeypatch.setattr(httpx,'Client',lambda **kw:original_client(transport=httpx.MockTransport(handle)))
    if complete:
        result,message=synthesis.organize(job,sections,60,path,config,lambda *_:None,lambda:None,review_mode=True)
        assert not message and '已核算的数值' in result[0]['body']
        receipt=store.usage_for(job)['calls'][0]
        assert receipt['status']=='completed' and receipt['output_tokens']==8000 and receipt['reserved']>=receipt['actual']
    else:
        with pytest.raises(ValueError,match='未能确认完成'):
            synthesis.organize(job,sections,60,path,config,lambda *_:None,lambda:None,review_mode=True)
        result=sections
        assert result[0]['body']=='## 定义\n\n旧数值。'
        assert store.usage_for(job)['calls'][0]['status']=='uncertain'
    synthesis.organize(job,result,60,path,config,lambda *_:None,lambda:None,review_mode=True)
    assert len(calls)==1


def test_image_source_is_native_resolution_and_recovered_only_once(tmp_path,monkeypatch):
    from lecture_notes import media
    visuals=images(tmp_path);calls=[]
    write_json(tmp_path/'manifest.json',{'source':{'path':'public-fixture.mp4'},'sha256':'fixture-hash'})
    monkeypatch.setattr(media,'native_frame',lambda *a,**kw:(calls.append(a) or (np.full((1080,1920,3),255,np.uint8),0)))
    section={'end':60,'visual_ids':['v0']}
    first,_=slide_review.source_images(section,visuals,tmp_path)
    second,_=slide_review.source_images(section,visuals,tmp_path)
    assert len(calls)==1 and first[0]['sha256']==second[0]['sha256']
    import base64
    image=cv2.imdecode(np.frombuffer(base64.b64decode(first[0]['url'].split(',')[1]),np.uint8),1)
    assert image.shape[:2]==(1080,1920)


@pytest.mark.parametrize('capture_ts',[.8,.98])
def test_hd_api_image_preserves_the_page_displayed_before_a_cut(tmp_path,capture_ts):
    import base64
    from lecture_notes.common import digest
    video=tmp_path/'two-pages.mp4'
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),1,(320,180))
    assert writer.isOpened()
    for value in (35,210):writer.write(np.full((180,320,3),value,np.uint8))
    writer.release()
    visuals=[{'id':'v0','image':'thumb.png','capture_ts':capture_ts}]
    cv2.imwrite(str(tmp_path/'thumb.png'),np.full((90,160,3),35,np.uint8))
    write_json(tmp_path/'manifest.json',{'source':{'path':str(video)},'sha256':'fixture'})
    stale=tmp_path/'api_images'/(digest({'source':'fixture','id':'v0','time':capture_ts,'quad':None})+'.png')
    stale.parent.mkdir()
    cv2.imwrite(str(stale),np.full((180,320,3),210,np.uint8))
    result,_=slide_review.source_images({'end':1,'visual_ids':['v0']},visuals,tmp_path)
    image=cv2.imdecode(np.frombuffer(base64.b64decode(result[0]['url'].split(',')[1]),np.uint8),1)
    assert image.shape[:2]==(180,320)
    assert image.mean()<80, 'HD recovery must not take the next slide after the requested time'


def test_original_image_viewer_preserves_the_same_page_as_api(tmp_path,monkeypatch):
    from lecture_notes import server
    from lecture_notes.common import source_identity
    video=tmp_path/'viewer.mp4'
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),1,(320,180))
    assert writer.isOpened()
    for value in (35,210):writer.write(np.full((180,320,3),value,np.uint8))
    writer.release()
    monkeypatch.setattr(store,'DATA',tmp_path/'data');monkeypatch.setattr(store,'OUTPUT',tmp_path/'jobs')
    monkeypatch.setattr(server,'OUTPUT',store.OUTPUT);monkeypatch.setattr(server,'WORKSPACE',tmp_path)
    job=store.create_job({'path':str(video)})['id'];output=store.OUTPUT/job
    write_json(output/'manifest.json',{'source':source_identity(video)})
    write_json(output/'source_records.json',[{'id':'v0','capture_ts':.98}])
    response=server.source_frame(job,'v0')
    image=cv2.imdecode(np.frombuffer(response.body,np.uint8),1)
    assert image.mean()<80, 'Original-image modal must show the same displayed frame as API input'


def test_scanned_document_every_page_reaches_image_requests_without_fake_times(tmp_path):
    visuals=images(tmp_path)
    for i,v in enumerate(visuals):v.update(document_page=i+1,untimed=True)
    sections=synthesis.build_sections([{'id':'s1','start':1,'end':2,'text':'口头知识'}],visuals,[[0,600]])
    assert {i for s in sections for i in s['api_visual_ids']}=={'v0','v1'}
    for section in sections:
        _,metadata=slide_review.source_images(section,visuals,tmp_path)
        assert all('无视频时间戳' in row['source'] for row in metadata)


def test_paddle_screening_deduplicates_exact_images_without_formula_extraction(tmp_path,monkeypatch):
    monkeypatch.setenv('LECTURE_INFERENCE_DEVICE','cpu');monkeypatch.setenv('LECTURE_PROCESSING_MODE','fast')
    monkeypatch.setitem(sys.modules,'paddle',SimpleNamespace(__version__='fixture'))
    visuals=images(tmp_path);(tmp_path/'1.png').write_bytes((tmp_path/'0.png').read_bytes());calls=[]
    class Model:
        def predict(self,path,**kw):
            calls.append(kw)
            return [SimpleNamespace(json={'res':{'parsing_res_list':[{'block_label':'text','block_content':'课件筛选线索'}]}})]
        def close(self):pass
    monkeypatch.setattr('lecture_notes.document_model.create_document_pipeline',lambda *_:Model())
    formula_worker.recognize_pages(tmp_path,lambda:None,screen=True)
    assert calls==[{'max_new_tokens':512}]
    assert read_json(tmp_path/'screening_cache/v1.json')['purpose']=='grouping_only'
    assert not (tmp_path/'formula_cache').exists() and not (tmp_path/'document_cache').exists()
    formula_worker.recognize_pages(tmp_path,lambda:None,screen=True)
    assert len(calls)==1


def test_screening_reads_group_representatives_without_removing_api_sources(tmp_path):
    visuals=images(tmp_path)
    visuals[0].update(content_id='p',is_representative=False)
    visuals[1].update(content_id='p',is_representative=True)
    assert [v['id'] for v in slide_review.screening_targets(visuals)]==['v1']
    section={'end':60,'visual_ids':['v0','v1']}
    images_sent,_=slide_review.source_images(section,visuals,tmp_path)
    assert [i['id'] for i in images_sent]==['v0','v1']
    for i,v in enumerate(visuals):v['document_page']=i+1
    assert [v['id'] for v in slide_review.screening_targets(visuals)]==['v0','v1']


def test_new_pipeline_keeps_image_compaction_and_screening_but_skips_rapidocr_and_formulas(tmp_path,monkeypatch,sample_video):
    for module in (store,pipeline,maintenance):monkeypatch.setattr(module,'OUTPUT',tmp_path/'out')
    monkeypatch.setattr(store,'DATA',tmp_path/'db')
    job=store.create_job({'path':str(sample_video),'slide_mode':'vision_api','windows':[[0,10]],'organize':False})['id']
    output=tmp_path/'out'/job;output.mkdir(parents=True,exist_ok=True);visuals=images(output);events=[]
    monkeypatch.setattr(pipeline,'probe',lambda _: {'duration':10,'audio':True})
    monkeypatch.setattr(pipeline,'gpu_slot',lambda *_:nullcontext());monkeypatch.setattr(pipeline,'wait_for_gpu_memory',lambda *_:None)
    def speech(*a):events.append('asr');write_json(output/'transcript.json',[{'id':'s1','start':1,'end':2,'text':'数学定义'}])
    def extract(*a,**kw):events.append('yolox_visuals')
    def compact(*a):
        events.append('image_compaction')
        write_json(output/'source_records.json',[{'id':v['id'],'representative_id':v['id']} for v in visuals])
        return visuals,[],{}
    monkeypatch.setattr(pipeline,'transcribe',speech);monkeypatch.setattr(pipeline,'extract_video',extract)
    monkeypatch.setattr(pipeline,'compact_visuals',compact)
    monkeypatch.setattr(pipeline,'run_screening',lambda *_:events.append('paddle_screening'))
    monkeypatch.setattr(pipeline,'regroup_existing',lambda *_:{'groups':2})
    def forbidden(*a):raise AssertionError('Redundant recognition stage called')
    monkeypatch.setattr(pipeline,'recognize',forbidden);monkeypatch.setattr(pipeline,'run_formula',forbidden)
    monkeypatch.setattr(pipeline,'audit_visuals',lambda *_:{'uncovered_intervals_over_0_6s':[],'region_coverage_gaps_over_0_6s':[]})
    monkeypatch.setattr(pipeline,'export_notes',lambda *_:None);monkeypatch.setattr(maintenance,'clean_job',lambda *a,**kw:None)
    pipeline.run_job(job)
    assert store.get_job(job)['status']=='materials_ready'
    assert events==['asr','yolox_visuals','image_compaction','paddle_screening']
    assert read_json(output/'quality.json')['integrity_ok']
