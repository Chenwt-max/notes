from __future__ import annotations

import os
import re
import sys
import math
import hashlib
import json
import subprocess
import time
from pathlib import Path

from .common import ROOT, MODELS, read_json, write_json, stamp, source_identity, digest
from .resources import cpu_threads
from .runtime import python_for,site_packages

DLL_HANDLES = []
ASR_MODEL = 'Qwen3-ASR-1.7B'
ALIGNER_MODEL = 'Qwen3-ForcedAligner-0.6B'
ASR_VERSION = 3


def append_progress(output,progress,message):
    # Append-only IPC avoids replacing a file held open by Windows progress readers.
    with (Path(output)/'asr_progress.jsonl').open('a',encoding='utf-8') as writer:
        writer.write(json.dumps({'progress':progress,'message':message},ensure_ascii=False)+'\n')


def read_progress(output):
    path=Path(output)/'asr_progress.jsonl'
    if not path.exists():return None
    lines=path.read_bytes().split(b'\n')[:-1]
    return json.loads(lines[-1]) if lines else None


def cuda_libraries():
    for root in [Path(sys.prefix)/'Lib/site-packages/nvidia', site_packages('document')/'nvidia', MODELS/'cuda']:
        if root.exists():
            for directory in {p.parent for p in root.rglob('*.dll')}:
                os.environ['PATH'] = str(directory)+os.pathsep+os.environ.get('PATH', '')
                if hasattr(os, 'add_dll_directory'):
                    DLL_HANDLES.append(os.add_dll_directory(str(directory)))


def timestamp_ms(seconds, comma=True):
    value = max(0, round(seconds*1000))
    return f'{value//3600000:02d}:{value//60000%60:02d}:{value//1000%60:02d}{"," if comma else "."}{value%1000:03d}'


def export_subtitles(segments, output):
    output = Path(output)
    srt, vtt, text = [], ['WEBVTT\n'], []
    for index, segment in enumerate(segments, 1):
        srt.append(f"{index}\n{timestamp_ms(segment['start'])} --> {timestamp_ms(segment['end'])}\n{segment['text']}\n")
        vtt.append(f"{timestamp_ms(segment['start'], False)} --> {timestamp_ms(segment['end'], False)}\n{segment['text']}\n")
        text.append(f"[{stamp(segment['start'])}] {segment['text']}")
    (output/'transcript.srt').write_text('\n'.join(srt), encoding='utf-8')
    (output/'transcript.vtt').write_text('\n'.join(vtt), encoding='utf-8')
    (output/'transcript.txt').write_text('\n'.join(text), encoding='utf-8')


def uncovered_speech(speech,segments):
    gaps=[]
    for interval in speech:
        pieces=[interval]
        for segment in segments:
            next_pieces=[]
            for a,b in pieces:
                x,y=segment['start'],segment['end']
                if y<=a or x>=b:
                    next_pieces.append([a,b])
                else:
                    if a<x:next_pieces.append([a,x])
                    if y<b:next_pieces.append([y,b])
            pieces=next_pieces
        gaps.extend([a,b] for a,b in pieces if b-a>=2)
    return gaps


def models_ready():
    if not python_for('asr').is_file():return False
    for model in (ASR_MODEL, ALIGNER_MODEL):
        folder=MODELS/model
        receipt=read_json(folder/'PROVENANCE.json',{})
        if not receipt.get('files'):return False
        if any(not (folder/r['Path']).is_file() or (folder/r['Path']).stat().st_size!=r['Size'] for r in receipt['files']):return False
    return True


def make_request(path,windows,device):
    return {'source':source_identity(path),'windows':windows,'device':device,'cpu_threads':cpu_threads(),
            'version':ASR_VERSION,'chunk_seconds':60,'overlap_seconds':2,
            'model_fingerprints':{m:digest(read_json(MODELS/m/'PROVENANCE.json',{})) for m in (ASR_MODEL,ALIGNER_MODEL)}}


def request_key(request):
    return digest({k:v for k,v in request.items() if k not in {'device','cpu_threads'}})


def audio_parts(request):
    parts=[]
    for start,end in request['windows']:
        position=start
        while position<end-.001:
            core_end=min(position+request['chunk_seconds'],end)
            parts.append((position,core_end,max(start,position-request['overlap_seconds']),min(end,core_end+request['overlap_seconds'])))
            position=core_end
    return parts


def aligned_words(text,items,duration):
    """Restore original punctuation without inventing aligner confidence scores."""
    positions=[i for i,c in enumerate(text) if c.isalnum() or c=="'"]
    normalized=''.join(text[i] for i in positions)
    words=[];offset=0;cursor=0
    for item in items:
        token=''.join(c for c in item['text'] if c.isalnum() or c=="'")
        if not token:continue
        if normalized[offset:offset+len(token)]!=token:
            raise ValueError('时间对齐文字与转写不一致，未生成不完整字幕')
        a,b=float(item['start_time']),float(item['end_time'])
        if not all(math.isfinite(v) for v in (a,b)) or a>b or a<-.2 or b>duration+.2:
            raise ValueError('时间对齐超出音频范围')
        if words and a<words[-1]['start']-.001:raise ValueError('时间对齐顺序异常')
        start=positions[offset];end=positions[offset+len(token)-1]+1
        prefix=text[cursor:start]
        if words:words[-1]['word']+=prefix
        words.append({'start':min(duration,max(0,a)),'end':min(duration,max(0,b)),'word':('' if words else prefix)+text[start:end]})
        offset+=len(token);cursor=end
    if offset!=len(normalized):raise ValueError('部分转写没有时间对齐，未静默丢弃文字')
    if words:words[-1]['word']+=text[cursor:]
    return words


def validated_recognition(text,items,duration):
    words=aligned_words(text,items,duration)
    if words and not any(w['end']>w['start'] for w in words):
        raise ValueError('时间对齐没有有效时长')
    return words


def recognize_aligned(audio,sr,infer,report,check,depth=0,offset=0):
    """Retry anomalous recognition on shorter overlapping audio, never truncate its text."""
    check()
    result=infer(audio,sr)
    duration=len(audio)/sr
    try:
        words=validated_recognition(result['text'],result['items'],duration)
        return {'text':result['text'],'words':words,'recovered_parts':0}
    except ValueError as exc:
        report({'start':offset,'end':offset+duration,'depth':depth,'error':str(exc),**result})
        if depth>=3 or duration<=8:
            raise ValueError(f'短段重识别后仍未通过字幕检查（{offset:.2f}–{offset+duration:.2f}秒）：{exc}') from exc
    middle=len(audio)//2
    overlap=min(sr,middle//4)
    words=[];recovered=1
    for core_a,core_b,a,b in [(0,middle,0,middle+overlap),(middle,len(audio),middle-overlap,len(audio))]:
        part=recognize_aligned(audio[a:b],sr,infer,report,check,depth+1,offset+a/sr)
        recovered+=part['recovered_parts']
        for word in part['words']:
            start,end=a/sr+word['start'],a/sr+word['end']
            if core_a/sr<=(start+end)/2<core_b/sr:
                words.append({**word,'start':max(core_a/sr,start),'end':min(core_b/sr,end)})
    return {'text':''.join(w['word'] for w in words),'words':words,'recovered_parts':recovered}


def caption_segments(words):
    groups=[];current=[]
    for word in words:
        if current and (word['start']-current[-1]['end']>1 or word['end']-current[0]['start']>12 or
                        len(''.join(w['word'] for w in current))>=36) and current[-1]['end']>current[0]['start']:
            groups.append(current);current=[]
        current.append(word)
        if re.search(r'[。！？!?；;]\s*$',word['word']) and current[-1]['end']>current[0]['start']:
            groups.append(current);current=[]
    if current:
        if current[-1]['end']<=current[0]['start'] and groups:groups[-1].extend(current)
        else:groups.append(current)
    found=[]
    for group in groups:
        if group[-1]['end']<=group[0]['start']:raise ValueError('对齐没有有效时长')
        text=''.join(w['word'] for w in group).strip()
        flags=[]
        if re.search(r'(.{3,15})\1{2}',re.sub(r'\W','',text)) or any(w['end']-w['start']>3 and len(w['word'].strip())<=2 for w in group):
            flags.append('repetition_or_timing_needs_check')
        found.append({'start':group[0]['start'],'end':group[-1]['end'],'text':text,'words':group,'flags':flags,
                      'asr_model':ASR_MODEL,'alignment_model':ALIGNER_MODEL})
    return found


def process_audio(request,output,callback,check,backend_factory):
    """Persist each completed minute; resources may change without invalidating text."""
    output=Path(output);cache=output/'asr_chunks';cache.mkdir(parents=True,exist_ok=True)
    key=request_key(request);parts=audio_parts(request)
    segments=[];speech=[];completed_files=[];backend=None;computed=0;cached=0;recovered=0;devices=set()
    from .resources import cooldown
    from .timing import Timings
    timing=Timings(output,'asr')
    for index,(core_start,core_end,start,end) in enumerate(parts):
        check()
        dest=cache/f'qwen_v{ASR_VERSION}_{digest([key,start,end])[:24]}.json'
        chunk=read_json(dest)
        if chunk is not None and chunk.get('request_key')==key:
            try:
                validated_recognition(chunk['text'],[{'text':w['word'],'start_time':w['start'],'end_time':w['end']} for w in chunk['words']],end-start)
            except ValueError:chunk=None
        work_start=None
        if chunk is None or chunk.get('request_key')!=key:
            if backend is None:
                callback(index/max(1,len(parts)),'加载 Qwen 字幕与时间对齐模型')
                backend=backend_factory()
            callback(index/max(1,len(parts)),f'正在识别 {stamp(core_start)}—{stamp(core_end)} · {index+1}/{len(parts)}')
            work_start=time.monotonic()
            chunk={**backend.recognize(request['source']['path'],start,end),'request_key':key,'device':request['device']}
            timing.call('checkpoint',write_json,dest,chunk);computed+=1
        else:cached+=1
        completed_files.append(dest);devices.add(chunk['device'])
        recovered+=bool(chunk.get('recovered_parts'))
        speech.extend([max(core_start,start+a),min(core_end,start+b)] for a,b in chunk['speech_intervals']
                      if start+b>core_start and start+a<core_end)
        words=[]
        for word in chunk['words']:
            a,b=start+word['start'],start+word['end']
            if core_start<=(a+b)/2<core_end:
                words.append({**word,'start':max(core_start,a),'end':min(core_end,b)})
        for segment in caption_segments(words):
            segment['id']=f's{len(segments)+1:05d}';segments.append(segment)
        with timing.measure('checkpoint'):
            write_json(output/'transcript.json',segments);export_subtitles(segments,output)
        callback((index+1)/len(parts),f'已保存字幕 {stamp(core_end)} · {index+1}/{len(parts)}')
        if work_start is not None:
            with timing.measure('cooldown'):cooldown(work_start,check)
    if not segments:raise RuntimeError('未得到语音识别结果；空字幕不会标记为完成')
    write_json(output/'audio_audit.json',{'detected_speech_intervals':speech,'uncovered_speech':uncovered_speech(speech,segments),
        'minimum_gap_seconds':2,'scope':'Silero语音活动与对齐覆盖检查，不代表每字正确'})
    runtime={**(backend.runtime() if backend else {}),'model':ASR_MODEL,'aligner':ALIGNER_MODEL,'version':ASR_VERSION,
             'request_key':key,'device':request['device'],'cpu_threads':request['cpu_threads'],'computed_chunks':computed,
             'cached_chunks':cached,'recovered_chunks':recovered,'cache_source_devices':sorted(devices),'completed':True,
             'transcript_sha256':hashlib.sha256((output/'transcript.json').read_bytes()).hexdigest()}
    write_json(output/'asr_runtime.json',runtime)
    for dest in completed_files:dest.unlink(missing_ok=True)
    if not any(cache.iterdir()):cache.rmdir()
    return segments


def transcribe(path,windows,output,callback,check,device='cuda'):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    request=make_request(path,windows,device)
    runtime=read_json(output/'asr_runtime.json',{})
    transcript=output/'transcript.json'
    if runtime.get('completed') and runtime.get('request_key')==request_key(request) and transcript.exists() and \
       hashlib.sha256(transcript.read_bytes()).hexdigest()==runtime.get('transcript_sha256'):
        check();return read_json(transcript)
    if not models_ready():raise RuntimeError('Qwen字幕或时间对齐模型未就绪，请运行安装环境.ps1')
    write_json(output/'asr_request.json',request)
    (output/'asr.stop').unlink(missing_ok=True)
    (output/'asr_progress.json').unlink(missing_ok=True)
    (output/'asr_progress.jsonl').unlink(missing_ok=True)
    callback(0,'加载 Qwen3-ASR-1.7B 本地字幕模型')
    env={**os.environ,'PYTHONUTF8':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','TOKENIZERS_PARALLELISM':'false'}
    env.pop('LECTURE_API_KEY',None)
    success=False
    with (output/'asr.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen([str(python_for('asr')),'-X','utf8','-m','lecture_notes.asr_worker',str(output)],
            cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            last=None
            while process.poll() is None:
                check()
                progress=read_progress(output)
                if progress and progress!=last:callback(progress['progress'],progress['message']);last=progress
                time.sleep(.2)
            check()
            if process.returncode:
                raise RuntimeError('本地字幕进程失败：'+(output/'asr.log').read_text(encoding='utf-8',errors='replace')[-1800:])
            done=read_json(output/'asr_runtime.json',{})
            if not done.get('completed') or done.get('request_key')!=request_key(request):
                raise RuntimeError('字幕进程未完成，已保留分段检查点')
            success=True
        finally:
            if process.poll() is None:
                (output/'asr.stop').touch()
                from .runner import terminate_tree
                terminate_tree(process)
            for name in ['asr.stop','asr_request.json','asr_progress.json','asr_progress.jsonl','asr_progress.json.tmp','asr_request.json.tmp']:
                (output/name).unlink(missing_ok=True)
            for partial in (output/'asr_chunks').glob('qwen_v3_*.json.tmp'):partial.unlink(missing_ok=True)
            work=output/'asr_work'
            if work.exists():
                for wav in work.glob('*.wav'):wav.unlink(missing_ok=True)
                if not any(work.iterdir()):work.rmdir()
    if success:(output/'asr.log').unlink(missing_ok=True)
    return read_json(transcript)
