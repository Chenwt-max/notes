"""Local integrity checks and review queues; never certify semantic correctness."""
from __future__ import annotations

from collections import Counter
import json
import math
import re
from pathlib import Path
import shutil
import subprocess
import time

from .common import ROOT, read_json, write_json, safe_child, source_identity

OPERATORS={'loss','sin','cos','tan','arccos','arcsin','log','exp','sigmoid','softmax','relu','argmin','argmax'}


def operator_disagreements(visual):
    conflicts=[]
    for formula in visual.get('formulas',[]):
        if formula.get('status')=='corrected':continue
        box=formula.get('box')
        if not box:continue
        if len(box)==4 and isinstance(box[0],(int,float)):x0,y0,x1,y1=box
        elif len(box)==4 and all(len(p)==2 for p in box):
            x0=min(p[0] for p in box);x1=max(p[0] for p in box)
            y0=min(p[1] for p in box);y1=max(p[1] for p in box)
        else:continue
        tokens=set()
        for line in visual.get('ocr_lines_before_document',visual.get('ocr_lines',[])):
            if line.get('score',0)<.85:continue
            points=line.get('box',[])
            if not points or not all(x0-3<=p[0]<=x1+3 and y0-3<=p[1]<=y1+3 for p in points):continue
            tokens.update(set(re.findall(r'[A-Za-z]{3,}',line['text'].lower()))&OPERATORS)
        latex=re.sub(r'\s+','',formula.get('corrected_latex',formula['latex']).lower())
        missing=sorted(t for t in tokens if t not in latex)
        recognized=sorted(t for t in OPERATORS if re.search(r'(?<![a-z])'+t+r'(?![a-z])',latex))
        if missing and recognized:
            conflicts.append({'id':formula['id'],'visual_id':visual['id'],'time':visual['capture_ts'],
                'representative':visual.get('is_representative',True),'ocr_operators':missing,
                'formula_operators':recognized,'error':f'同一位置文字识别含 {", ".join(missing)}，公式识别为 {", ".join(recognized)}，需要对照原图'})
    return conflicts


def unsafe_formula_ids(report):
    formulas=report.get('formulas',{})
    return {f['id'] for f in formulas.get('syntax',{}).get('errors',[])+formulas.get('disagreements',[])}


def formula_syntax(rows):
    if not rows:
        return {'available':True, 'errors':[]}
    node = shutil.which('node')
    if not node or not (ROOT/'frontend/node_modules/katex').is_dir():
        return {'available':False, 'errors':[], 'message':'缺少本地公式检查组件，未验证公式语法'}
    try:
        result = subprocess.run([node,str(ROOT/'lecture_notes/validate_formulas.cjs')],
            input=json.dumps(rows,ensure_ascii=False).encode('utf-8'),capture_output=True,timeout=60,check=True)
        checked = json.loads(result.stdout)
        return {'available':True,'errors':[r for r in checked if r['error']]}
    except (OSError,subprocess.SubprocessError,ValueError):
        return {'available':False,'errors':[], 'message':'本地公式检查未完成，不能视为通过'}


def audit_output(output, expect_subtitles=True):
    output=Path(output)
    manifest=read_json(output/'manifest.json',{})
    windows=manifest.get('windows',[])
    visuals=read_json(output/'visuals.json',[])
    segments=read_json(output/'transcript.json',[])
    records=read_json(output/'source_records.json',[])
    audio=read_json(output/'audio_audit.json',{})
    video=read_json(output/'visual_audit.json',{})
    errors=[]
    def issue(code,identity,message):
        errors.append({'code':code,'id':identity,'message':message})
    for label,items in [('画面',visuals),('字幕',segments),('来源',records)]:
        counts=Counter(v['id'] for v in items)
        for identity,count in counts.items():
            if count>1:issue('duplicate_id',identity,f'{label}编号重复')
    if not visuals:issue('missing_visuals','', '尚无有效课件画面')
    if visuals and not records:issue('missing_source_records','','尚无完整来源映射，不能确认覆盖')
    stages=manifest.get('completed_stages')
    if stages is not None:
        required={'visuals','compact','ocr'}|({'asr'} if expect_subtitles else set())
        for stage in sorted(required-set(stages)):
            issue('unfinished_stage',stage,'相应处理阶段尚未完成')
    mapping={v['id']:v for v in visuals}
    for visual in visuals:
        try:
            exists=safe_child(output,visual['image']).is_file()
        except ValueError:
            exists=False
        if not exists:issue('missing_image',visual['id'],'课件原图不存在或路径不合法')
    for record in records:
        if record.get('representative_id') not in mapping:
            issue('missing_source_mapping',record['id'],'原始时刻没有对应的保留图')
    for segment in segments:
        a,b=segment.get('start'),segment.get('end')
        valid=all(isinstance(x,(int,float)) and math.isfinite(x) for x in (a,b))
        if not valid or not a<b or not any(a>=x-.1 and b<=y+.1 for x,y in windows):
            issue('invalid_subtitle_time',segment['id'],'字幕时间无效或超出处理区间')
        if not str(segment.get('text','')).strip():
            issue('empty_subtitle',segment['id'],'字幕文字为空')
    if expect_subtitles and not segments:issue('missing_subtitles','','尚无有效字幕')
    source=manifest.get('source',{})
    if source.get('path'):
        path=Path(source['path'])
        if not path.is_file() or source_identity(path)!=source:
            issue('source_changed','','原视频身份已改变，不能继续复用对应结果')
    formulas=[]
    for visual in visuals:
        for formula in visual.get('formulas',[]):
            formulas.append({'id':formula['id'],'latex':formula.get('corrected_latex',formula['latex']),
                'visual_id':visual['id'],'time':visual['capture_ts'],
                'representative':visual.get('is_representative',True),'status':formula.get('status','unverified')})
    syntax=formula_syntax([{'id':f['id'],'latex':f['latex']} for f in formulas])
    by_formula={f['id']:f for f in formulas}
    for row in syntax['errors']:
        row.update({k:by_formula[row['id']][k] for k in ('visual_id','time','representative')})
    flags=Counter(flag for segment in segments for flag in segment.get('flags',[]))
    representatives=[v for v in visuals if v.get('is_representative',True)]
    report={'version':1,'checked_at':time.time(),'integrity_ok':not errors,
        'state':'blocked' if errors else 'needs_review','semantic_accuracy_verified':False,
        'integrity_errors':errors,
        'subtitles':{'count':len(segments),'flagged':sum(bool(s.get('flags')) or any(w.get('probability',1)<.25 for w in s.get('words',[])) for s in segments),
            'flags':dict(flags),'coverage_checked':bool(audio),'uncovered_speech':audio.get('uncovered_speech',[]),
            'word_confidence_segments':sum(any('probability' in w for w in s.get('words',[])) for s in segments),
            'low_confidence_words':[{'segment_id':s['id'],**w} for s in segments for w in s.get('words',[])
                if w.get('probability',1)<.25 and str(w.get('word','')).strip()]},
        'visuals':{'retained':len(visuals),'representatives':len(representatives),'source_records':len(records),
            'supplements':len(visuals)-len(representatives),
            'coverage_gaps':video.get('uncovered_intervals_over_0_6s',[]),
            'region_gaps':video.get('region_coverage_gaps_over_0_6s',[])},
        'formulas':{'count':len(formulas),'representatives':sum(f['representative'] for f in formulas),
            'disagreements':[r for v in visuals for r in operator_disagreements(v)],
            'unverified':sum(f['status']!='corrected' for f in formulas),'syntax':syntax},
        'limits':['时间覆盖和公式渲染检查不能证明转写或数学含义正确','原图、补充状态与原视频仍是核对依据']}
    write_json(output/'quality.json',report)
    return report
