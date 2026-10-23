from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

from .common import ROOT, OUTPUT, source_identity, digest, read_json, write_json
from .store import get_job, update_job, check_job, TaskStopped, usage_for,start_job
from .settings import settings
from .media import probe, save_image
from .vision import extract_video, link_views, audit_visuals
from .compaction import compact_visuals,regroup_existing,GROUP_VERSION
from .chapters import divide_chapters,planning_allowance
from .ocr import recognize
from .asr import transcribe,ASR_MODEL,ALIGNER_MODEL,ASR_VERSION
from .synthesis import build_sections, organize, is_note_reviewed,pending_review_ids
from .export import export_notes
from .resources import gpu_slot,inference_device,cpu_threads,wait_for_gpu_memory
from .quality import audit_output,unsafe_formula_ids
from .document_model import DOCUMENT_MODEL
from .timing import Timings,timing_summary
from .note_content import clean_note


def validate_windows(windows, duration):
    windows = windows or [[0., duration]]
    normalized = []
    for pair in sorted(windows):
        start, end = map(float, pair)
        if not 0 <= start < end <= duration+.01:
            raise ValueError('片段范围必须在视频时长内，且结束晚于开始')
        if normalized and start < normalized[-1][1]:
            raise ValueError('处理片段不能重叠')
        normalized.append([start, min(end, duration)])
    return normalized


def attach_formulas(visuals, output):
    corrections = read_json(output/'formula_corrections.json', {})
    for visual in visuals:
        document=read_json(output/'document_cache'/f"{visual['id']}.json",{})
        if document.get('model')==DOCUMENT_MODEL and document.get('text'):
            if 'ocr_before_document' not in visual:
                visual['ocr_before_document']=visual.get('ocr','')
                visual['ocr_lines_before_document']=visual.get('ocr_lines',[])
            # Retain initial OCR lines outside the regions actually read by the document model.
            lines=list(document['lines'])
            boxes=[b['block_bbox'] for b in document['blocks'] if b.get('block_content') and
                   b['block_label'] not in {'image','chart','seal'}]
            for line in visual['ocr_lines_before_document']:
                points=line.get('box',[])
                if not points:continue
                x=sum(p[0] for p in points)/len(points);y=sum(p[1] for p in points)/len(points)
                if not any(a<=x<=c and b<=y<=d for a,b,c,d in boxes):lines.append(line)
            visual['ocr_lines']=lines
            visual['ocr']='\n'.join(line['text'] for line in lines)
            visual['ocr_model']=DOCUMENT_MODEL
        found = read_json(output/'formula_cache'/f"{visual['id']}.json", [])
        visual['formulas'] = []
        source = None
        for index, formula in enumerate(found):
            formula = {**formula, 'id':f"{visual['id']}_f{index+1}", 'visual_id':visual['id']}
            if formula['id'] in corrections:
                formula['corrected_latex'] = corrections[formula['id']]
                formula['status'] = 'corrected'
            box = formula.get('box')
            if box and len(box) == 4 and all(isinstance(v,(int,float)) for v in box):
                if source is None:
                    source = cv2.imdecode(np.fromfile(str(output/visual['image']),np.uint8),cv2.IMREAD_COLOR)
                h,w = source.shape[:2]
                x0,y0,x1,y1 = [int(v) for v in box]
                crop = source[max(0,y0):min(h,y1),max(0,x0):min(w,x1)]
                if crop.size:
                    name = f"formulas/{formula['id']}.png"
                    save_image(output/name,crop)
                    formula['image'] = name
            visual['formulas'].append(formula)
    write_json(output/'visuals.json',visuals)
    return visuals


def run_formula(job_id, output, callback, check):
    from .formula_targets import formula_targets
    targets=formula_targets(output)
    if all((output/'formula_cache'/f"{v['id']}.json").exists() for v in targets):return
    from .runtime import python_for
    python = python_for('document')
    if not python.exists():
        raise RuntimeError('公式识别环境未安装，请运行安装入口')
    stop = output/'formula.stop'
    stop.unlink(missing_ok=True)
    (output/'formula.waiting').unlink(missing_ok=True)
    with (output/'formula.log').open('a',encoding='utf-8') as log:
        process = subprocess.Popen([str(python),'-X','utf8','-m','lecture_notes.formula_worker',str(output)],
            cwd=ROOT,stdout=log,stderr=log,env={**os.environ,'PYTHONUTF8':'1'})
        try:
            while process.poll() is None:
                check()
                count = sum((output/'formula_cache'/f"{v['id']}.json").exists() for v in targets)
                total = max(1,len(targets))
                callback(min(1,count/total),f'等待显卡资源或可用显存 · 已有{count}/{total}幅' if (output/'formula.waiting').exists() else f'课件文字与公式 {count}/{total} · {DOCUMENT_MODEL}')
                time.sleep(1)
            if process.returncode:
                tail = (output/'formula.log').read_text(encoding='utf-8',errors='replace')[-1600:]
                raise RuntimeError('公式进程失败：'+tail)
        except TaskStopped:
            stop.touch()
            from .runner import terminate_tree
            terminate_tree(process)
            raise


def run_job(job_id):
    return run_block(job_id)


def run_block(job_id):
    job = get_job(job_id)
    spec = job['spec']
    output = OUTPUT/job_id
    output.mkdir(parents=True,exist_ok=True)
    path = Path(spec['path']).resolve()
    check = lambda: check_job(job_id)
    stage = '检查视频'
    warnings = []
    start_clock = time.time()
    timing=Timings(output,'pipeline')
    def callback(progress,message):
        update_job(job_id,stage=stage,progress=max(0,min(1,float(progress))),message=message)
    try:
        start_job(job_id)
        update_job(job_id,stage=stage,progress=0,message='正在检查原视频和处理范围')
        write_json(output/'resource_runtime.json',{'cpu_threads':cpu_threads(),'device':inference_device(),
                   'processing_mode':os.environ.get('LECTURE_PROCESSING_MODE','balanced')})
        metadata = probe(path)
        windows = validate_windows(spec.get('windows'),metadata['duration'])
        identity = source_identity(path)
        manifest = read_json(output/'manifest.json',{})
        visual_version = manifest.get('visual_version',4) if manifest else 6
        if manifest and visual_version<5 and 'visuals' not in manifest.get('completed_stages',[]):
            raise ValueError('此任务的旧版画面扫描尚未完成，请新建任务使用优化提取；原检查点保留')
        fingerprint = digest({'source':identity,'windows':windows,'regions':spec.get('regions'),'visual_version':visual_version,
                              **({'asr_model':spec['asr_model']} if 'asr_model' in spec else {}),
                              **({k:spec[k] for k in ['person_model','formula_model'] if spec.get(k)}),
                              **({'regions_capture_ts':spec['regions_capture_ts']} if spec.get('regions_capture_ts') is not None else {})})
        if manifest and manifest.get('fingerprint') != fingerprint:
            raise ValueError('输入或处理配置已改变，请创建新任务，避免混用旧结果')
        if not manifest:
            h = hashlib.sha256()
            with path.open('rb') as file:
                for block in iter(lambda:file.read(8*1024*1024),b''):
                    check()
                    h.update(block)
            manifest = {'fingerprint':fingerprint,'source':identity,'sha256':h.hexdigest(),'metadata':metadata,
                        'models':{'person':spec.get('person_model','yolox-tiny'),'formula':DOCUMENT_MODEL},
                        'windows':windows,'visual_version':visual_version,'completed_stages':[],'created':time.time()}
            write_json(output/'manifest.json',manifest)
        done = manifest['completed_stages']
        def completed(name):
            if name not in done:
                done.append(name)
            write_json(output/'manifest.json',manifest)
        if not spec.get('visuals_only') and metadata['audio'] and ('asr' not in done or not read_json(output/'transcript.json',[])):
            stage = '提取课程字幕'
            with gpu_slot(check,lambda:callback(0,'等待显卡资源，其他课程仍在处理')):
                if inference_device()!='cpu':wait_for_gpu_memory(check,lambda message:callback(0,message))
                timing.call('asr_stage',transcribe,path,windows,output,callback,check,inference_device())
            manifest['asr_version'] = ASR_VERSION
            manifest['models'].update({'asr':ASR_MODEL,'alignment':ALIGNER_MODEL})
            completed('asr')
        stage = '提取课件与板书'
        if 'visuals' not in done:
            with gpu_slot(check,lambda:callback(0,'等待显卡资源，其他课程仍在处理')):
                try:
                    timing.call('visuals_stage',extract_video,path,windows,output,callback,check,spec.get('regions'),spec.get('regions_capture_ts'),spec.get('person_model','yolox-tiny'),low_resolution=visual_version>=6)
                finally:
                    from .person import detector
                    detector.cache_clear()
            completed('visuals')
        from .person import detector
        detector.cache_clear()  # Release detection VRAM before OCR, ASR and the formula process.
        visuals = read_json(output/'visuals.json',[])
        if not visuals:
            raise RuntimeError('未得到有效画面，需检查视频或区域设置')
        stage = '关联放大与重复画面'
        if 'relations' not in done:
            if visual_version<6:visuals = link_views(visuals,output,check,callback)
            completed('relations')
        stage = '保留完整课件与精简重复'
        if 'compact' not in done:
            visuals,_,_ = timing.call('compaction',compact_visuals,visuals,output,check,callback)
            completed('compact')
        visual_audit = audit_visuals(visuals,read_json(output/'layouts.json',[]),windows,output,visual_version)
        if visual_audit['uncovered_intervals_over_0_6s'] or visual_audit['region_coverage_gaps_over_0_6s']:
            warnings.append('画面时间轴存在待核对的覆盖间隙，请查看画面核对报告')
        stage = '识别课件文字'
        if 'ocr' not in done:
            with gpu_slot(check,lambda:callback(0,'等待显卡资源，其他课程仍在处理')):
                visuals = timing.call('ocr',recognize,visuals,output,callback,check)
            completed('ocr')
        if spec.get('visuals_only'):
            segments = []
            warnings.append('此任务选择了仅提取画面，尚未转写语音或识别公式')
        else:
            stage = '提取课程字幕'
            if not metadata['audio']:
                raise ValueError('视频没有音轨；画面成果已保留，无法完成课堂语音笔记')
            segments = read_json(output/'transcript.json',[])
            audio_audit = read_json(output/'audio_audit.json',{})
            gaps = audio_audit.get('uncovered_speech',[])
            if gaps:
                warnings.append(f'检测到{len(gaps)}处有语音而未覆盖字幕的候选区间，请对照原视频核查')
            if spec.get('formulas',True):
                stage = '识别课件文字与公式'
                if 'formulas' not in done:
                    timing.call('formula_stage',run_formula,job_id,output,callback,check)
                    visuals = attach_formulas(visuals,output)
                    if read_json(output/'formula_runtime.json',{}).get('model')==DOCUMENT_MODEL:
                        manifest['document_model']=DOCUMENT_MODEL
                    completed('formulas')
                (output/'formula_selection.json').unlink(missing_ok=True)
            else:
                warnings.append('此任务未启用公式识别，公式原图仍保留')
        records=read_json(output/'source_records.json',[])
        # Refine browsing groups after document recognition, so a newly grouped
        # complementary page never loses its original formula-recognition pass.
        if records and manifest.get('browse_group_version')!=GROUP_VERSION:
            stage='结合课件文字精简展示'
            grouping=timing.call('post_ocr_grouping',regroup_existing,visuals,records,output,check,callback)
            write_json(output/'visuals.json',visuals)
            write_json(output/'source_records.json',records)
            compact=read_json(output/'compaction.json',{})
            write_json(output/'compaction.json',{**compact,'page_count':grouping['groups'],'post_ocr_grouping':grouping})
            manifest['browse_group_version']=GROUP_VERSION
            write_json(output/'manifest.json',manifest)
            visual_audit=audit_visuals(visuals,read_json(output/'layouts.json',[]),windows,output,visual_version)
        stage = '核验识别结果与来源'
        quality=timing.call('quality',audit_output,output,expect_subtitles=not spec.get('visuals_only'))
        if not quality['integrity_ok']:
            raise RuntimeError('识别素材完整性检查未通过，请查看quality.json；未标记为完成')
        invalid=len(quality['formulas']['syntax']['errors'])
        if invalid:warnings.append(f'{invalid}个公式候选未通过渲染检查，讲义保留原图并提示核对')
        if quality['formulas']['disagreements']:
            warnings.append('部分公式与同一位置文字识别存在分歧，讲义保留原图，不自动选用任一候选')
        if not quality['formulas']['syntax']['available']:
            warnings.append('公式渲染检查未运行，不能视为通过；详见核验页面')
        stage = '生成图文讲义'
        sections = build_sections(segments,visuals,windows,unsafe_formula_ids(quality))
        previous=read_json(output/'notes_working.json',read_json(output/'notes.json',[]))
        prior={digest({'speech':s['speech'],'evidence':s['evidence']}):s for s in previous}
        by_speech={digest(s['speech']):s for s in previous}
        for section in sections:
            old=prior.get(digest({'speech':section['speech'],'evidence':section['evidence']}),by_speech.get(digest(section['speech']),{}))
            for key in ('body','organized','omitted','editorial_notes','body_before_cleanup','repairs','warning','deferred_formula_ids','body_before_review','review_repairs','reviewed_source_hash','reviewed_body_hash','review_warning','review_feedback','review_deferred','publication_pending'):
                if key in old:section[key]=old[key]
            if spec.get('organize') and not section.get('organized'):section['publication_pending']=True
        title = spec.get('title') or path.stem
        chaptered=None
        def public_sections():
            # Internal request batches are never the reader's chapter directory.
            if spec.get('organize'):return [clean_note(s) for s in chaptered] if chaptered is not None else []
            return [clean_note(s) for s in sections]
        write_json(output/'notes_working.json',sections)
        write_json(output/'notes.json',public_sections())
        export_notes(title,public_sections(),segments,visuals,output,['本地素材已保存；文字整理状态见网页'])
        if spec.get('organize',False):
            stage = '整理笔记与核算费用'
            config=settings(True)
            if spec.get('budget_cny') is not None:
                hours=sum(b-a for a,b in windows)/3600
                budget=float(spec['budget_cny'])
                config={**config,'budget_per_hour':budget/hours}
                # A fixed per-note cash budget must not inherit a smaller hourly token preset.
                for limit,price in [('input_tokens_per_hour','input_price'),('output_tokens_per_hour','output_price')]:
                    if config[price]>0:config[limit]=max(config[limit],budget*1e6/config[price]/hours)
            review_enabled=config.get('review_notes') or spec.get('review_notes')
            seconds=sum(b-a for a,b in windows)
            hours=seconds/3600
            content_config={**config,'budget_per_hour':max(0,config['budget_per_hour']-planning_allowance(sections,config)/hours)}
            for section in sections:
                sections,message = timing.call('organize_stage',organize,job_id,sections,seconds,output,content_config,callback,check,
                                              reuse_completed=True,staged=True,organize_ids={section['id']})
                if message and message not in warnings:warnings.append(message)
            if review_enabled:
                stage='复核笔记内容与推导'
                for section in sections:
                    if section.get('organized') and not section.get('omitted') and not is_note_reviewed(section):section['publication_pending']=True
                write_json(output/'notes_working.json',sections)
                pending=pending_review_ids(sections)
                for ids in [{s['id']} for s in sections if s['id'] in pending]:
                    sections,message=timing.call('deferred_review',organize,job_id,sections,seconds,output,content_config,callback,check,
                                                 review_mode=True,review_ids=ids,staged=True)
                    if message and '笔记复核：'+message not in warnings:warnings.append('笔记复核：'+message)
            stage='按整课知识主题划分章节'
            chaptered,message=divide_chapters(job_id,sections,seconds,output,config,check)
            if message:warnings.append(message)
        else:
            warnings.append('尚未调用API整理；当前为完整字幕与来源图文讲义')
        stage = '导出并检查来源'
        write_json(output/'notes_working.json',sections)
        write_json(output/'notes.json',public_sections())
        title = spec.get('title') or path.stem
        timing.call('final_export',export_notes,title,public_sections(),segments,visuals,output,warnings)
        ids = {sid for section in sections for sid in section['segment_ids']}
        vids = {vid for section in sections for vid in section['visual_ids']}
        report = {'title':title,'source_sha256':manifest['sha256'],'source_unchanged':source_identity(path)==identity,
                  'processed_seconds':sum(b-a for a,b in windows),'visuals':len(visuals),'layouts':len(read_json(output/'layouts.json',[])),
                  'transcript_segments':len(segments),'assigned_segments':len(ids),'assigned_visuals':len(vids),
                  'formula_candidates':sum(len(v.get('formulas',[])) for v in visuals if v.get('is_representative',True)),
                  'supplementary_formula_candidates':sum(len(v.get('formulas',[])) for v in visuals if not v.get('is_representative',True)),
                  'source_mapping_complete':len(ids)==len(segments) and len(vids)==len(visuals),
                  'semantic_accuracy_verified':False,'ai_reviewed_sections':sum(is_note_reviewed(s) for s in (chaptered or [])),
                  'published_sections':sum(s['organized'] and not s.get('publication_pending') for s in public_sections()),
                  'quality':quality,'warnings':warnings,'usage':usage_for(job_id),
                  'audio_audit':read_json(output/'audio_audit.json',{}),
                  'visual_audit':visual_audit,
                  'elapsed_seconds':time.time()-start_clock,'timings':timing_summary(output)}
        write_json(output/'report.json',report)
        if not report['source_unchanged'] or not report['source_mapping_complete']:
            raise RuntimeError('来源完整性检查失败，请查看报告')
        organized = bool(segments) and bool(chaptered) and all(s['organized'] for s in chaptered)
        update_job(job_id,status='ready' if organized else 'materials_ready',stage='学习笔记已整理' if organized else '素材提取完成',progress=1,
                   message=f'{report["published_sections"]}章已发布 · {len(segments)}段来源字幕' if organized else '完整素材与处理进度已保存，整课笔记尚未全部完成')
        from .maintenance import clean_job
        clean_job(job_id,apply=True)
    except TaskStopped as exc:
        update_job(job_id,status='paused' if str(exc) in {'pause_requested','paused'} else 'cancelled',message='已保存完成阶段和分段检查点')
    except Exception as exc:
        error=str(exc)
        if any(token in error.lower() for token in ['out of memory','outofmemory','cuda_error_out_of_memory']):
            error='内存或显存不足：请降低课程/GPU并发，或改用CPU，再继续处理。已有缓存保留。'
        update_job(job_id,status='needs_attention',stage=stage,error=error,message='当前阶段未完成；已生成的素材和缓存均保留')
        raise
