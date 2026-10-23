"""Explicit retries change an attempt key once; reading/resuming never changes it."""
from __future__ import annotations

import json

from .common import digest,read_json,write_json
from .store import usage_for


def attempt_fingerprint(output,phase,section_id,fingerprint):
    attempt=read_json(output/'api_attempts.json',{}).get('attempts',{}).get(phase+':'+section_id,0)
    return digest({'original':fingerprint,'attempt':attempt}) if attempt else fingerprint


def status(job,output):
    sections=read_json(output/'notes_working.json',[])
    usage=usage_for(job['id'],include_assistant=False)
    uncertain=[c['id'] for c in usage['calls'] if c['status'] in {'reserved','uncertain','completed_usage_unknown'}]
    rows=[]
    for phase in ('organize','review','chapters'):
        if phase=='chapters':
            complete=bool(read_json(output/'chapter_plan.json',{}))
            failed=not complete and any(json.loads(c['detail']).get('phase')==phase and c['status'] in {'completed','completed_usage_unknown','confirmed','rejected'} for c in usage['calls'])
            rows.append({'phase':phase,'status':'completed' if complete else 'failed' if failed else 'pending',
                         'failed_ids':['whole'] if failed else []})
        else:
            failed=[s['id'] for s in sections if s.get('warning' if phase=='organize' else 'review_warning') and not s.get('review_deferred')]
            for call in usage['calls']:
                detail=json.loads(call['detail'])
                section=next((s for s in sections if s['id']==detail.get('section_id')),None)
                if detail.get('phase')==phase and call['status'] in {'confirmed','rejected'} and section and not section.get('organized' if phase=='organize' else 'reviewed_body_hash'):
                    if section['id'] not in failed:failed.append(section['id'])
            done=sum(bool(s.get('organized')) if phase=='organize' else bool(s.get('reviewed_body_hash')) for s in sections)
            rows.append({'phase':phase,'status':'failed' if failed else 'completed' if sections and done==len(sections) else 'pending',
                         'completed':done,'total':len(sections),'failed_ids':failed})
    return {'phases':rows,'billing_confirmation_required':uncertain,
            'recoverable_reason':'有尚未确认计费的请求，请先核账' if uncertain else '失败响应已保留，可明确确认后重试' if any(r['failed_ids'] for r in rows) else '',
            'metadata_warnings':list(dict.fromkeys(r.get('metadata_warning') for p in (output/'api_cache').glob('*.json')
                 if (r:=read_json(p,{})).get('metadata_warning')))}


def retry(job,output,value):
    token=value.get('request_id')
    if not isinstance(token,str) or not 16<=len(token)<=80:raise ValueError('重试请求缺少唯一标识')
    saved=read_json(output/'api_attempts.json',{'attempts':{},'requests':[]})
    if token in saved['requests']:return False
    current=status(job,output)
    if current['billing_confirmation_required']:raise ValueError('请先核对并确认未完成请求的账单，不能直接再次收费')
    phase=value.get('phase')
    target=next((r for r in current['phases'] if r['phase']==phase),None)
    if not target or not target['failed_ids']:raise ValueError('这个阶段没有可重试的失败响应')
    for identity in target['failed_ids']:
        key=phase+':'+identity
        saved['attempts'][key]=saved['attempts'].get(key,0)+1
    saved['requests'].append(token)
    write_json(output/'api_attempts.json',saved)
    if phase=='review':
        sections=read_json(output/'notes_working.json',[])
        for section in sections:
            if section['id'] in target['failed_ids']:
                if section.get('review_warning'):section['review_feedback']=section['review_warning'][:1000]
                section.pop('review_warning',None)
                section.pop('review_deferred',None)
                section.pop('reviewed_body_hash',None)
        write_json(output/'notes_working.json',sections)
    return True
