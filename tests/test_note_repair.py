import json

import cv2
import httpx
import numpy as np
import pytest

from lecture_notes import quality,settings,store
from lecture_notes.common import read_json,write_json,digest
from lecture_notes.synthesis import build_sections,organize,compact_evidence,is_note_reviewed
from lecture_notes.repair import parse_review


@pytest.fixture
def context(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path/'db')
    monkeypatch.setattr(store,'OUTPUT',tmp_path/'out')
    job=store.create_job({'path':'source.mp4'})
    (tmp_path/'images').mkdir()
    cv2.imwrite(str(tmp_path/'images/source.png'),np.full((90,240,3),245,np.uint8))
    visuals=[{'id':'v1','capture_ts':10,'start':0,'end':300,'image':'images/source.png',
              'ocr':'Loss(w)','formulas':[{'id':f'f{i}','latex':r'\cos(w)',
              'box':[10,10,220,70]} for i in range(3)]}]
    write_json(tmp_path/'visuals.json',visuals)
    write_json(tmp_path/'quality.json',{'formulas':{'syntax':{'errors':[]},
        'disagreements':[{'id':f'f{i}','error':'Loss 与 cos 分歧','ocr_operators':['loss']} for i in range(3)]}})
    sections=build_sections([{'id':'s1','start':0,'end':5,'text':'这是正派分布'}],visuals,[[0,300]],{'f0','f1','f2'})
    config={**settings.DEFAULTS,'api_key':'local-test','base_url':'https://api.deepseek.com',
        'model':'deepseek-flash','input_price':2,'output_price':8,
        'input_tokens_per_hour':600000,'output_tokens_per_hour':60000}
    return tmp_path,job['id'],sections,config


def mock_client(monkeypatch,content):
    requests=[]
    class Client:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,*a,**kw):
            requests.append(kw['json'])
            return httpx.Response(200,request=httpx.Request('POST','https://api.deepseek.com'),json={
                'choices':[{'message':{'content':content},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':2500,'completion_tokens':500}})
    monkeypatch.setattr(httpx,'Client',Client)
    return requests


@pytest.mark.parametrize('deepseek',[True,False])
def test_review_mode_and_output_are_fully_reserved(context,monkeypatch,deepseek):
    path,job,sections,config=context
    if not deepseek:config.update(base_url='https://fixture.invalid/v1',model='configured-other')
    sections[0].update(body='## 定义\n完整定义与数值例题。',organized=True)
    calls=mock_client(monkeypatch,json.dumps({'edits':[]}))
    result,message=organize(job,sections,3600,path,config,lambda *a:None,lambda:None,review_mode=True)
    assert not message and is_note_reviewed(result[0]) and len(calls)==1
    request=calls[0]
    assert request['max_tokens']==1600
    if deepseek:
        assert request['thinking']=={'type':'disabled'} and 'reasoning_effort' not in request
    else:assert 'thinking' not in request and 'reasoning_effort' not in request
    call=store.usage_for(job)['calls'][0]
    detail=json.loads(call['detail'])
    assert detail['max_output']==request['max_tokens']
    assert call['reserved']==pytest.approx((detail['bound_input']*2+request['max_tokens']*8)/1e6)


@pytest.mark.parametrize('review',[True,False])
def test_unwrapped_math_retains_original_and_does_not_auto_retry(context,monkeypatch,review):
    path,job,sections,config=context
    old='## 定义\n完整的原始知识正文。'
    sections[0].update(body=old,organized=review)
    content=json.dumps({'edits':[{'before':'完整的原始知识正文。','after':r'拟合向量X\hat w是列空间投影。','reason':'修正数学含义'}]}) if review else json.dumps({'body':r'## 定义\n拟合向量X\hat w是列空间投影。','repairs':[]})
    calls=mock_client(monkeypatch,content)
    result,message=organize(job,sections,3600,path,config,lambda *a:None,lambda:None,review_mode=review)
    assert len(calls)==1
    if review:
        assert result[0]['body']==old and '数学分隔符' in result[0]['review_warning']
    else:assert not result[0]['organized'] and '数学分隔符' in result[0]['warning']
    organize(job,result,3600,path,config,lambda *a:None,lambda:None,review_mode=review)
    assert len(calls)==1 and len(store.usage_for(job)['calls'])==1


def run(context):
    path,job,sections,config=context
    return organize(job,sections,3600,path,config,lambda *a:None,lambda:None)


def test_repairs_share_one_bounded_cached_request_and_preserve_sources(context,monkeypatch):
    path,job,sections,config=context
    before=(path/'visuals.json').read_bytes()
    payload={'body':r'正态分布，损失函数 $\operatorname{Loss}(w)$。','repairs':[
        {'source':'subtitle','before':'正派分布','after':'正态分布','reason':'统计学上下文'},
        {'source':'f0','before':r'\cos(w)','after':r'\operatorname{Loss}(w)','reason':'原图明确写 Loss'},
        {'source':'unknown','before':'伪造','after':'内容','reason':'不可追溯'}]}
    calls=mock_client(monkeypatch,json.dumps(payload,ensure_ascii=False))
    for _ in range(2):
        result,message=run(context)
        assert not message and result[0]['organized']
        assert len(result[0]['repairs'])==2 and result[0]['deferred_formula_ids']==['f2']
    assert len(calls)==1
    assert calls[0]['thinking']=={'type':'disabled'}
    assert calls[0]['response_format']=={'type':'json_object'}
    content=calls[0]['messages'][1]['content']
    assert len([p for p in content if p['type']=='image_url'])==2
    estimate=read_json(path/'api_estimate.json')
    assert estimate['repair_in_same_request']
    assert read_json(path/'note_repairs.json')['originals_preserved']
    assert (path/'visuals.json').read_bytes()==before
    assert sections[0]['speech'][0]['text']=='这是正派分布'
    detail=json.loads(store.usage_for(job)['calls'][0]['detail'])
    text=''.join(m['content'] if isinstance(m['content'],str) else ''.join(p['text'] for p in m['content'] if p['type']=='text') for m in calls[0]['messages'])
    assert detail['bound_input']>=len(text.encode('utf-8'))+2*1024


def test_crop_changes_invalidate_repair_cache(context,monkeypatch):
    calls=mock_client(monkeypatch,json.dumps({'body':'笔记','repairs':[]}))
    run(context)
    path=context[0]/'images/source.png'
    image=cv2.imread(str(path));image[20:40,20:70]=0;cv2.imwrite(str(path),image)
    run(context)
    assert len(calls)==2


def test_invalid_json_is_charged_and_cached_without_automatic_retry(context,monkeypatch):
    calls=mock_client(monkeypatch,'{"body":"截断的输出')
    for _ in range(2):
        result,message=run(context)
        assert not result[0]['organized'] and not result[0]['body']
    assert len(calls)==1 and store.usage_for(context[1])['spent']>0


def test_budget_prevents_image_request(context,monkeypatch):
    calls=mock_client(monkeypatch,'must not call')
    context[3]['budget_per_hour']=.000001
    _,message=run(context)
    assert '未发起新请求' in message and not calls
    assert not store.usage_for(context[1])['calls']


def test_saved_manual_revision_is_not_overruled_by_operator_ocr():
    visual={'id':'v','capture_ts':0,'formulas':[{'id':'f','latex':r'\cos(w)',
        'corrected_latex':r'\cos(w)','status':'corrected','box':[0,0,100,50]}],
        'ocr_lines':[{'text':'Loss(w)','score':.99,'box':[[5,5],[80,5],[80,30],[5,30]]}]}
    assert not quality.operator_disagreements(visual)


def test_broken_model_repair_is_not_accepted_as_complete(context,monkeypatch):
    calls=mock_client(monkeypatch,json.dumps({'body':r'损坏的公式 $\frac{1}{$','repairs':[
        {'source':'f0','before':r'\cos(w)','after':r'\frac{1}{','reason':'错误的模型输出'}]}))
    result,_=run(context)
    assert len(calls)==1 and not result[0]['organized'] and not result[0]['body']


def test_repair_log_drops_changes_not_used_in_notes(context,monkeypatch):
    mock_client(monkeypatch,json.dumps({'body':'课程定义','repairs':[
        {'source':'subtitle','before':'正派分布','after':'正态分布','reason':'正文未采用此修改'}]}))
    result,_=run(context)
    assert result[0]['organized'] and not result[0]['repairs']


def test_full_ocr_option_is_bounded_without_dropping_transcript(context,monkeypatch):
    path,job,sections,config=context
    config.update(include_ocr_context=True,input_tokens_per_hour=12000)
    sections[0]['evidence'][0]['text']='核心定义\n'+'重复画面中的长文字'*20000
    calls=mock_client(monkeypatch,json.dumps({'body':'整理后的核心定义','repairs':[]}))
    result,message=run(context)
    assert not message and result[0]['organized']
    content=calls[0]['messages'][1]['content']
    text=content if isinstance(content,str) else content[0]['text']
    assert '这是正派分布' in text and len(text.encode('utf-8'))<12000
    estimate=read_json(path/'api_estimate.json')
    assert estimate['reserved_input_tokens']<=12000
    assert estimate['context_mode']=='full_transcript_with_bounded_ocr'


def test_resume_only_requests_unfinished_chapters_and_keeps_ready_notes(context,monkeypatch):
    path,job,sections,config=context
    sections[0].update(body='已经完成的知识笔记',organized=True)
    sections.append({**sections[0],'id':'n0002','start':300,'end':336,'body':'','organized':False})
    calls=mock_client(monkeypatch,json.dumps({'body':'最后一小节的结论','repairs':[]}))
    result,message=organize(job,sections,336,path,config,lambda *a:None,lambda:None,reuse_completed=True)
    assert not message and len(calls)==1
    assert result[0]['body']=='已经完成的知识笔记' and result[1]['organized']
    assert calls[0]['max_tokens']>=512
    assert len(read_json(path/'notes.json'))==2


def test_representative_keeps_shared_text_and_complement_keeps_animation_answer():
    visuals=[{'id':'early','start':0,'end':300,'capture_ts':10,'is_representative':False,'ocr':'共同定义\n动画答案：2','formulas':[]},
             {'id':'final','start':0,'end':300,'capture_ts':30,'is_representative':True,'ocr':'共同定义\n完整推导','formulas':[]}]
    section=build_sections([{'id':'s','start':0,'end':3,'text':'课堂文字'}],visuals,[[0,300]])[0]
    evidence=compact_evidence(section,{'final'},2000)
    assert evidence[0]['id']=='final' and '共同定义' in evidence[0]['text']
    assert any('动画答案：2' in e['text'] for e in evidence)
    assert sum('共同定义' in e['text'] for e in evidence)==1


def test_review_preserves_before_version_and_does_not_charge_twice(context,monkeypatch):
    path,job,sections,config=context
    sections[0].update(body='## 回归\n最小二乘法必须假设正态分布。',organized=True)
    old=sections[0]['body']
    revised='## 回归\n最小二乘是优化准则；高斯误差假设用于推导与极大似然的等价关系。'
    calls=mock_client(monkeypatch,json.dumps({'edits':[{'before':old,'after':revised,'reason':'区分优化定义与概率解释'}]},ensure_ascii=False))
    for _ in range(2):
        result,message=organize(job,sections,3600,path,config,lambda *a:None,lambda:None,review_mode=True)
        assert not message and result[0]['body']==revised and result[0]['organized']
    assert len(calls)==1 and result[0]['body_before_review']==old
    assert result[0]['review_repairs'][0]['source']=='note'
    assert read_json(path/'note_review.json')['sections'][0]['reviewed']
    assert json.loads(store.usage_for(job)['calls'][0]['detail'])['phase']=='review'


@pytest.mark.parametrize('body',['invalid JSON','broken_math','destructive'])
def test_failed_or_destructive_review_never_overwrites_ready_notes(context,monkeypatch,body):
    path,job,sections,config=context
    old='## 完整笔记\n'+'原有推导、条件与例题需要保留。'*20
    sections[0].update(body=old,organized=True)
    if body!='invalid JSON':
        after=r'## 公式\n错误 $\frac{1}{$' if body=='broken_math' else '摘要'
        body=json.dumps({'edits':[{'before':old,'after':after,'reason':'测试非法修订'}]})
    mock_client(monkeypatch,body)
    result,_=organize(job,sections,3600,path,config,lambda *a:None,lambda:None,review_mode=True)
    assert result[0]['body']==old and result[0]['organized']
    assert result[0].get('review_warning') and not result[0].get('reviewed_body_hash')
    assert not read_json(path/'note_review.json')['sections'][0]['reviewed']


def test_review_ocr_uses_remaining_tokens_after_historical_calls(context,monkeypatch):
    path,job,sections,config=context
    sections[0].update(body='## 定义\n需要对照来源核对的课程定义。',organized=True)
    sections[0]['evidence'][0]['text']='补充知识\n'+'独有课件文字'*2000
    config.update(include_ocr_context=True,input_tokens_per_hour=14000)
    store.reserve(job,'previous',.02,1,{'bound_input':7000,'max_output':500})
    store.settle('previous','completed',.016,7000,250)
    calls=mock_client(monkeypatch,json.dumps({'edits':[]}))
    result,message=organize(job,sections,3600,path,config,lambda *a:None,lambda:None,review_mode=True)
    assert not message and len(calls)==1 and result[0].get('reviewed_body_hash')
    assert read_json(path/'review_estimate.json')['reserved_input_tokens']+7000<=14000


def test_changed_notes_or_sources_invalidate_review_status():
    section={'body':'知识笔记','speech':[{'text':'课堂内容'}],'evidence':[]}
    section.update(reviewed_body_hash=digest(section['body']),
        reviewed_source_hash=digest({'speech':section['speech'],'evidence':section['evidence']}))
    assert is_note_reviewed(section)
    assert not is_note_reviewed({**section,'body':'修订后的笔记'})
    assert not is_note_reviewed({**section,'evidence':[{'text':'动画新增答案'}]})
    assert not is_note_reviewed({**section,'review_warning':'仍有内容矛盾待核对'})


def test_review_edits_are_atomic_and_preserve_unedited_content():
    old='## 定义\n唯一原文。\n其他细节。'
    revised,edits=parse_review(json.dumps({'edits':[{'before':'唯一原文。','after':'修订原文。','reason':'定义推导'}]}),{'body':old})
    assert revised=='## 定义\n修订原文。\n其他细节。' and edits[0]['source']=='note'
    with pytest.raises(ValueError,match='无法唯一定位'):
        parse_review(json.dumps({'edits':[{'before':'唯一原文。','after':'修订原文。','reason':'定义推导'},
            {'before':'不存在的原文','after':'猜测修改','reason':'无依据'}]}),{'body':old})
    assert old=='## 定义\n唯一原文。\n其他细节。'
    with pytest.raises(ValueError,match='无法唯一定位'):
        parse_review(json.dumps({'edits':[{'before':'重复','after':'修改','reason':'不唯一'}]}),{'body':'重复又重复'})


def test_review_cannot_target_text_introduced_by_another_edit():
    section={'body':'条件是 N > M。'}
    edits=[{'before':'N > M','after':'N ≥ M+1','reason':'补充条件'},
           {'before':'N ≥ M+1','after':'N ≥ M+2','reason':'不能引用新插入文字'}]
    with pytest.raises(ValueError,match='无法唯一定位'):
        parse_review(json.dumps({'edits':edits}),section)
    assert section['body']=='条件是 N > M。'


def test_review_rejects_overlapping_original_ranges():
    edits=[{'before':'abc','after':'abc+','reason':'第一处'},
           {'before':'bc','after':'BC','reason':'与第一处重叠'}]
    with pytest.raises(ValueError,match='重叠'):
        parse_review(json.dumps({'edits':edits}),{'body':'abcdef'})


def test_review_uniqueness_counts_overlapping_occurrences():
    with pytest.raises(ValueError,match='无法唯一定位'):
        parse_review(json.dumps({'edits':[{'before':'aaa','after':'b','reason':'出现三次'}]}),{'body':'aaaaa'})


@pytest.mark.parametrize('reverse',[False,True])
def test_review_independent_edits_reference_original_offsets(reverse):
    edits=[{'before':'原句。','after':'结论。','reason':'新文字不能影响后一处定位'},
           {'before':'结论。','after':'推导。','reason':'只改原稿中的这一处'}]
    revised,repairs=parse_review(json.dumps({'edits':list(reversed(edits)) if reverse else edits}),
                                {'body':'原句。结论。其他细节。'})
    assert revised=='结论。推导。其他细节。'
    assert len(repairs)==2


def test_review_adjacent_ranges_are_allowed():
    edits=[{'before':'甲','after':'甲一','reason':'第一处'},
           {'before':'乙','after':'乙二','reason':'第二处'}]
    assert parse_review(json.dumps({'edits':edits}),{'body':'甲乙'})[0]=='甲一乙二'


def test_legacy_review_cache_revalidates_original_offsets_without_new_charge(context,monkeypatch):
    path,job,sections,config=context
    sections[0].update(body='## 复核\n原句。结论。其他细节。',organized=True)
    original=json.loads(json.dumps(sections))
    response=json.dumps({'edits':[{'before':'原句。','after':'结论。','reason':'第一处'},
                                  {'before':'结论。','after':'推导。','reason':'第二处'}]})
    calls=mock_client(monkeypatch,response)
    organize(job,sections,3600,path,config,lambda *a:None,lambda:None,review_mode=True)
    cache=next((path/'api_cache').glob('*.json'));saved=read_json(cache)
    saved.update(body='',parse_error='旧解析器误判无法唯一定位',incomplete=True)
    write_json(cache,saved)
    original[0]['review_warning']='旧解析器误判无法唯一定位'
    spent=store.usage_for(job)['spent']
    result,_=organize(job,original,3600,path,config,lambda *a:None,lambda:None,review_mode=True)
    assert result[0]['body']=='## 复核\n结论。推导。其他细节。'
    assert is_note_reviewed(result[0]) and len(calls)==1
    assert store.usage_for(job)['spent']==spent
    assert read_json(cache)['response_body']==response


@pytest.mark.parametrize('kind',['cascading','broken_math','truncated'])
def test_unsafe_legacy_review_cache_keeps_original_and_ledger(context,monkeypatch,kind):
    path,job,sections,config=context
    old='## 复核\n条件是 N > M。其他推导保持原样。'
    sections[0].update(body=old,organized=True)
    original=json.loads(json.dumps(sections))
    edits=([{'before':'N > M','after':'N ≥ M+1','reason':'第一处'},
            {'before':'N ≥ M+1','after':'N ≥ M+2','reason':'不能引用新增文字'}] if kind=='cascading' else
           [{'before':'N > M','after':r'$\frac{1}{$' if kind=='broken_math' else 'N ≥ M+1','reason':'复核'}])
    response=json.dumps({'edits':edits})
    calls=mock_client(monkeypatch,response)
    organize(job,sections,3600,path,config,lambda *a:None,lambda:None,review_mode=True)
    cache=next((path/'api_cache').glob('*.json'));saved=read_json(cache)
    saved.update(body='## 复核\n不应发布的旧缓存内容。',parse_error='',incomplete=False,
                 finish_reason='length' if kind=='truncated' else 'stop')
    write_json(cache,saved)
    spent=store.usage_for(job)['spent']
    result,_=organize(job,original,3600,path,config,lambda *a:None,lambda:None,review_mode=True)
    assert result[0]['body']==old and result[0]['review_warning']
    assert not is_note_reviewed(result[0]) and len(calls)==1
    assert store.usage_for(job)['spent']==spent
    assert read_json(cache)['response_body']==response


def test_non_learning_segment_can_be_omitted_and_is_not_retried(context,monkeypatch):
    path,job,sections,config=context
    calls=mock_client(monkeypatch,json.dumps({'body':'','repairs':[],'omit':True}))
    result,message=organize(job,sections,3600,path,config,lambda *a:None,lambda:None)
    assert not message and result[0]['organized'] and result[0]['omitted']
    result,message=organize(job,result,3600,path,config,lambda *a:None,lambda:None,reuse_completed=True)
    assert not message and len(calls)==1
