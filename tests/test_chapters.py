import copy
import json

import httpx
import pytest

from lecture_notes import store,settings
from lecture_notes.chapters import divide_chapters,merge_chapters,validate_plan
from lecture_notes.common import digest,read_json,write_json
from lecture_notes.synthesis import is_note_reviewed


@pytest.fixture
def manuscript(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path/'db')
    job=store.create_job({'path':'local.mp4'})['id']
    sections=[]
    for i in range(4):
        part={'id':f'n{i}','start':i*300,'end':(i+1)*300,'body':f'## 主题{i}\n\n公式 $x_{i}^2$ 与推导。',
              'organized':True,'speech':[{'id':f's{i}','text':str(i)}],'evidence':[{'id':f'v{i}'}],
              'segment_ids':[f's{i}'],'visual_ids':[f'v{i}'],'display_visual_ids':[f'v{i}']}
        part['reviewed_source_hash']=digest({'speech':part['speech'],'evidence':part['evidence']})
        part['reviewed_body_hash']=digest(part['body']);sections.append(part)
    config={**settings.DEFAULTS,'api_key':'test','base_url':'https://fixture.invalid','model':'test','input_price':2,
            'output_price':8,'budget_per_hour':3,'input_tokens_per_hour':200000,'output_tokens_per_hour':200000}
    plan={'chapters':[{'title':'定义与推导','ids':['n0','n1']},{'title':'应用与结论','ids':['n2','n3']}]}
    return job,tmp_path,sections,config,plan


def test_chapter_merge_retains_all_content_math_and_sources_once(manuscript):
    _,_,sections,_,plan=manuscript;original=copy.deepcopy(sections)
    merged=merge_chapters(plan,sections)
    assert len(merged)==2 and sections==original
    for i in range(4):
        assert sum(f'公式 $x_{i}^2$ 与推导。' in c['body'] for c in merged)==1
    for field in ['segment_ids','visual_ids','source_note_ids']:
        assert len([v for c in merged for v in c[field]])==4
    assert all(is_note_reviewed(c) for c in merged)


def test_chapter_title_does_not_repeat_identical_internal_heading(manuscript):
    _,_,sections,_,_=manuscript
    part=sections[0]
    merged=merge_chapters({'chapters':[{'title':'主题0','ids':['n0']}]},[part])[0]
    assert merged['body']=='## 主题0\n\n公式 $x_0^2$ 与推导。'
    assert merged['segment_ids']==part['segment_ids']


@pytest.mark.parametrize('ids',[['n0','n1','n2'],['n0','n0','n2','n3'],['n1','n0','n2','n3'],['n0','n1','n2','n9']])
def test_plan_rejects_missing_duplicate_reordered_or_unknown_sources(manuscript,ids):
    with pytest.raises(ValueError,match='遗漏、重复或顺序'):
        validate_plan({'chapters':[{'title':'主题','ids':ids}]},manuscript[2])


def client_fixture(monkeypatch,plan,calls,finish='stop'):
    class Client:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,url,**kwargs):
            calls.append(kwargs['json'])
            return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':json.dumps(plan)},'finish_reason':finish}],
                'usage':{'prompt_tokens':200,'completion_tokens':100}})
    monkeypatch.setattr(httpx,'Client',Client)


def test_api_reads_whole_manuscript_and_reuses_cache_without_rebilling(manuscript,monkeypatch):
    job,out,sections,config,plan=manuscript;calls=[]
    client_fixture(monkeypatch,plan,calls)
    merged,message=divide_chapters(job,sections,1200,out,config,lambda:None)
    assert not message and len(merged)==2
    sent=json.loads(calls[0]['messages'][1]['content'])
    assert [p['body'] for p in sent]==[s['body'] for s in sections]
    again,message=divide_chapters(job,sections,1200,out,config,lambda:None)
    assert again==merged and not message and len(calls)==1
    assert len(store.usage_for(job)['calls'])==1
    assert read_json(out/'chapter_plan.json')['source_order']==['n0','n1','n2','n3']


@pytest.mark.parametrize('case',['sources_pending','cash_exhausted','tokens_exhausted','uncertain'])
def test_no_api_until_ready_and_within_cumulative_budget(manuscript,monkeypatch,case):
    job,out,sections,config,plan=manuscript;calls=[]
    client_fixture(monkeypatch,plan,calls)
    if case=='sources_pending':sections[1]['publication_pending']=True
    elif case=='tokens_exhausted':config['input_tokens_per_hour']=1
    else:
        store.reserve(job,'prior',1,1,{'phase':'chapters' if case=='uncertain' else 'organize'})
        if case=='uncertain':store.settle('prior','uncertain')
    merged,message=divide_chapters(job,sections,1200,out,config,lambda:None)
    assert merged is None and message and not calls


@pytest.mark.parametrize('truncated',[True,False])
def test_invalid_plan_preserves_manuscript_and_does_not_retry(manuscript,monkeypatch,truncated):
    job,out,sections,config,plan=manuscript;calls=[];original=copy.deepcopy(sections)
    if not truncated:plan['chapters'][1]['ids']=['n2']
    client_fixture(monkeypatch,plan,calls,'length' if truncated else 'stop')
    for _ in range(2):
        merged,message=divide_chapters(job,sections,1200,out,config,lambda:None)
        assert merged is None and '未自动重试' in message and sections==original
    assert len(calls)==1


def test_obsolete_early_setting_is_ignored_and_removed_on_save(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'DATA',tmp_path)
    write_json(tmp_path/'settings.json',{'early_notes':True,'cpu_threads':1})
    assert 'early_notes' not in settings.settings()
    saved=settings.save_settings({'early_notes':True})
    assert 'early_notes' not in saved and 'early_notes' not in read_json(tmp_path/'settings.json')
