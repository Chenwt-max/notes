from __future__ import annotations

import json
import mimetypes
import threading
import zipfile
import tempfile
import subprocess
from urllib.parse import quote
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .common import ROOT, WORKSPACE, OUTPUT, DATA, read_json, write_json, safe_child
from .store import list_jobs, create_job, get_job, update_job, connect, usage_for,JOB_LOCKS,request_delete,DELETING
from .settings import settings, save_settings
from .media import probe, image_at,displayed_image_at
from .pipeline import attach_formulas, validate_windows
from .export import export_notes
from .synthesis import build_sections, is_note_reviewed
from .note_content import clean_note
from . import catalog
from . import maintenance
from .runner import scheduler
from .quality import formula_syntax
from .materials import review_materials,recover_materials
from .timing import timing_summary

STOP = threading.Event()
EXPORT_LOCK = threading.Lock()
MATERIAL_LOCKS = JOB_LOCKS
CREATE_LOCK = threading.Lock()
LIBRARY_LOCK = threading.Lock()
mimetypes.add_type('application/javascript','.js')
mimetypes.add_type('text/css','.css')


@asynccontextmanager
async def lifespan(app):
    STOP.clear()
    for job in list_jobs():
        if job['status'] in DELETING:continue
        recover_materials(job,OUTPUT/job['id'])
        if job['status'] in {'running','starting','pause_requested','cancel_requested'}:
            update_job(job['id'],status='paused',message='应用重新启动，请点击继续处理')
    thread = threading.Thread(target=scheduler,args=(STOP,),daemon=True)
    thread.start()
    yield
    STOP.set()
    from .preparation import CANCEL
    CANCEL.set()
    thread.join(timeout=35)


app = FastAPI(title='notes · 课程笔记',lifespan=lifespan)


@app.middleware('http')
async def local_only(request: Request, call_next):
    host = request.headers.get('host','').split(':')[0]
    if host not in {'127.0.0.1','localhost','testserver'}:
        return Response('仅允许本机访问',status_code=403)
    origin = request.headers.get('origin','')
    if request.method not in {'GET','HEAD','OPTIONS'} and origin and origin not in {'http://127.0.0.1:8765','http://localhost:8765','http://127.0.0.1:5173','http://localhost:5173'}:
        return Response('来源不允许',status_code=403)
    try:
        return await call_next(request)
    except (ValueError,KeyError) as exc:
        return Response(json.dumps({'detail':str(exc)},ensure_ascii=False),status_code=400,media_type='application/json')


def source(path):
    resolved = Path(path).resolve()
    registered=read_json(DATA/'library.json',[])
    if (not resolved.is_relative_to(WORKSPACE) and str(resolved) not in registered) or resolved.suffix.lower() not in {'.mp4','.mkv','.mov','.avi','.webm'} or not resolved.is_file():
        raise HTTPException(400,'请选择已导入的本机课程视频')
    return resolved


@app.get('/api/library')
def library():
    result = []
    paths={p.resolve() for p in WORKSPACE.iterdir() if p.is_file() and p.suffix.lower() in {'.mp4','.mkv','.mov','.avi','.webm'}}
    paths.update(Path(p) for p in read_json(DATA/'library.json',[]))
    for path in paths:
        if path.is_file():
            info = probe(path)
            result.append({'path':str(path),'name':path.name,'size':path.stat().st_size,**{k:info[k] for k in ['duration','width','height','audio']}})
    return sorted(result,key=lambda x:x['name'])


@app.post('/api/library/path')
def import_video(value:dict):
    return import_videos({'paths':[value.get('path','')]})['videos'][0]


def local_video(raw):
    raw=str(raw).strip().strip('"')
    path=Path(raw)
    if not path.is_absolute() or raw.startswith('\\\\') or not path.is_file() or path.suffix.lower() not in {'.mp4','.mkv','.mov','.avi','.webm'}:
        raise ValueError('请填写存在的本机视频完整路径，支持 MP4、MKV、MOV、AVI 和 WebM')
    path=path.resolve()
    try:info=probe(path)
    except (subprocess.CalledProcessError,ValueError,KeyError):
        raise ValueError('无法读取这个视频，请检查文件是否完整、能否正常播放') from None
    return {'path':str(path),'name':path.name,'size':path.stat().st_size,**{k:info[k] for k in ['duration','width','height','audio']}}


@app.post('/api/library/paths')
def import_videos(value:dict):
    requested=value.get('paths')
    if not isinstance(requested,list) or not requested:raise ValueError('请填写视频路径，每行一个')
    videos={}
    for index,raw in enumerate(requested,1):
        if not isinstance(raw,str):raise ValueError(f'第{index}条路径必须是文本')
        try:video=local_video(raw)
        except ValueError as exc:raise ValueError(f'第{index}条：{exc}') from None
        videos[Path(video['path'])]=video
    with LIBRARY_LOCK:
        paths=read_json(DATA/'library.json',[])
        registered={Path(p) for p in paths}
        new=[str(p) for p in videos if p not in registered]
        if new:write_json(DATA/'library.json',[*paths,*new])
    return {'videos':list(videos.values())}


@app.get('/api/settings')
def get_settings():
    return settings()


@app.get('/api/courses')
def courses():
    paths = sorted((p for p in WORKSPACE.iterdir() if p.is_file() and p.suffix.lower() in {'.mp4','.mkv','.mov','.avi','.webm'}),key=lambda p:(not p.stem.isdigit(),int(p.stem) if p.stem.isdigit() else p.name))
    catalog.initialize(paths)
    return catalog.list_courses()


@app.post('/api/courses')
def create_course(value:dict):
    return catalog.create_course(value)


@app.patch('/api/courses/{course_id}')
def rename_course(course_id:str,value:dict):
    return catalog.rename_course(course_id,value)


@app.delete('/api/courses/{course_id}',status_code=202)
def delete_course(course_id:str):
    with CREATE_LOCK:return catalog.delete_course(course_id)


@app.post('/api/courses/{course_id}/lessons')
def add_lessons(course_id:str,value:dict):
    items = value.get('lessons',[])
    for item in items:
        item['path'] = str(source(item.get('path','')))
    return catalog.add_lessons(course_id,items)


@app.patch('/api/lessons/{lesson_id}')
def update_lesson(lesson_id:str,value:dict):
    return catalog.update_lesson(lesson_id,value)


@app.put('/api/courses/{course_id}/order')
def reorder_lessons(course_id:str,value:dict):
    return catalog.reorder_lessons(course_id,value.get('ids'))


@app.put('/api/settings')
def put_settings(value:dict):
    return save_settings(value)


@app.get('/api/health')
def health():
    from .runtime import VERSION,status,python_for
    from .app import instance_identity
    from .asr import models_ready,ASR_MODEL,ALIGNER_MODEL
    from .document_model import DOCUMENT_MODEL,models_ready as document_models_ready
    return {'ok':True,'version':VERSION,'instance':instance_identity(),'runtime':status(),
            'asr_model_ready':models_ready(),'asr_model':ASR_MODEL,'alignment_model':ALIGNER_MODEL,
            'document_model':DOCUMENT_MODEL,
            'document_model_ready':document_models_ready(),
            'formula_environment':python_for('document').is_file(),
            'local_only':True}


@app.get('/api/jobs')
def jobs():
    return list_jobs()


@app.get('/api/preparation')
def preparation_status():
    from .preparation import state
    return state()


@app.post('/api/preparation/{action}')
def prepare_models(action:str):
    from .preparation import control
    return control(action)


@app.post('/api/jobs')
def new_job(spec:dict):
    with CREATE_LOCK:
        return create_new_job(spec)


def create_new_job(spec):
    from .handouts import local_handout
    handout=local_handout(spec['handout_path']) if spec.get('handout_path') else None
    if handout and spec.get('handout_scope','auto') not in {'auto','all'}:raise ValueError('课件补充识别范围无效')
    from .runtime import PORTABLE
    if PORTABLE:
        from .preparation import state
        if not state()['ready']:raise ValueError('请先在模型准备页面完成下载和校验')
    path = source(spec.get('path',''))
    duration = probe(path)['duration']
    windows = validate_windows(spec.get('windows'),duration)
    previous=next((j for j in list_jobs() if str(Path(j['spec']['path']).resolve()).lower()==str(path).lower() and
        j['status'] not in {'cancelled',*DELETING} and all(any(x<=a and y>=b for x,y in j['spec'].get('windows',[[0,duration]])) for a,b in windows)),None)
    if previous and spec.get('confirm_reprocess') is not True:
        raise HTTPException(409,{'code':'confirmation_required','message':'这段视频已有处理记录。再次处理会新建独立结果，并可能占用计算资源和接口额度；现有资料会保留。','existing_job_id':previous['id']})
    regions = spec.get('regions')
    if regions:
        for region in regions:
            if region.get('kind') not in {'slides','board','screen'} or len(region.get('quad',[]))!=4 or any(len(p)!=2 or any(not 0<=float(v)<=1 for v in p) for p in region['quad']):
                raise ValueError('区域必须为画面内的四个点')
            points = np.float32(region['quad'])
            if not cv2.isContourConvex(points) or cv2.contourArea(points)<.015:
                raise ValueError('校准区域须为不交叉的四边形，并覆盖足够的画面')
        if not 0<=float(spec.get('regions_capture_ts',windows[0][0]))<duration:
            raise ValueError('校准参考时刻超出视频范围')
    local_models = settings()
    return create_job({'path':str(path),'title':str(spec.get('title') or path.stem),'windows':windows,
        'budget_cny':local_models['budget_per_note'],
        'asr_model':local_models['asr_model'],
        'person_model':local_models['person_model'],'formula_model':local_models['formula_model'],
        'slide_mode':'vision_api','formulas':False,
        'organize':bool(spec.get('organize',True)),
        'visuals_only':bool(spec.get('visuals_only',False)),'regions':regions if not handout else None,
        **({'handout_path':str(handout),'handout_recognize':bool(spec.get('handout_recognize',True)),
            'handout_scope':spec.get('handout_scope','auto')} if handout else {}),
        'regions_capture_ts':float(spec.get('regions_capture_ts',windows[0][0])) if regions else None})


@app.get('/api/jobs/{job_id}')
def job_detail(job_id:str):
    with MATERIAL_LOCKS[job_id]:
        return read_job_detail(job_id)


@app.delete('/api/jobs/{job_id}',status_code=202)
def delete_job(job_id:str):
    with MATERIAL_LOCKS[job_id]:return request_delete(job_id)


@app.get('/api/jobs/{job_id}/assistant')
def assistant_info(job_id:str):
    from .assistant import info
    return info(get_job(job_id),settings(True))


@app.post('/api/jobs/{job_id}/assistant')
def assistant_explain(job_id:str,value:dict):
    from .assistant import explain
    return explain(job_id,value,settings(True))


def read_job_detail(job_id):
    from .workflow import status as workflow_status
    job = get_job(job_id)
    output = OUTPUT/job_id
    return {**job,'workflow':workflow_status(job,output),'timings':timing_summary(output),'visuals':read_json(output/'visuals.json',[]),'layouts':read_json(output/'layouts.json',[]),
        'segments':read_json(output/'transcript.json',[]),'notes':[{**clean_note(n),'reviewed':is_note_reviewed(n)} for n in read_json(output/'notes.json',[])],
        'report':read_json(output/'report.json',{}),'usage':usage_for(job_id),'compaction':read_json(output/'compaction.json',{}),
        'profiles':read_json(output/'profiles.json',[]),'estimate':read_json(output/'api_estimate.json',{}),
        'quality':read_json(output/'quality.json',{}),'note_review':read_json(output/'note_review.json',{}),
        'exports':[p for p in ['notes.md','notes.html','visuals.html','transcript.srt','transcript.vtt','transcript.txt','ocr.txt','visual_audit.json','pages.json','report.json','quality.json','note_repairs.json','note_review.json','slide_review.json'] if (output/p).exists()]}


@app.post('/api/jobs/{job_id}/materials/{action}')
def review(job_id:str,action:str,value:dict|None=None):
    if action not in {'quality','regroup'}:raise ValueError('未知核验操作')
    with MATERIAL_LOCKS[job_id]:
        job=get_job(job_id)
        if job['status'] in {'running','starting','queued','pause_requested','cancel_requested'}:
            raise ValueError('请先暂停处理或等待完成，再核验和整理素材')
        if action=='regroup' and read_json(OUTPUT/job_id/'compaction.json',{}).get('last_regroup') and (value or {}).get('confirm_reprocess') is not True:
            raise HTTPException(409,{'code':'confirmation_required','message':'本节已经整理过重复课件。再次整理会重新计算分组，来源资料会保留。','existing_job_id':job_id})
        result=review_materials(job,OUTPUT/job_id,regroup=action=='regroup')
        if action=='regroup':
            q=result['quality']
            update_job(job_id,message=f"{q['subtitles']['count']}段字幕 · {q['visuals']['representatives']}组代表画面 · {q['formulas']['representatives']}个代表页公式候选")
        return result


@app.post('/api/jobs/{job_id}/{action}')
def control(job_id:str,action:str,value:dict|None=None):
    with MATERIAL_LOCKS[job_id]:
        return control_job(job_id,action,value)


@app.post('/api/jobs/{job_id}/retry/{phase}')
def retry_failed(job_id:str,phase:str,value:dict):
    from .workflow import retry
    with MATERIAL_LOCKS[job_id]:
        job=get_job(job_id)
        if job['status'] in {'running','starting','queued','pause_requested','cancel_requested',*DELETING}:
            # An idempotent replay after queuing is accepted without a new attempt.
            if value.get('request_id') in read_json(OUTPUT/job_id/'api_attempts.json',{}).get('requests',[]):return job
            raise ValueError('请先等待当前处理停止')
        if value.get('confirm_reprocess') is not True:
            raise HTTPException(409,{'code':'confirmation_required','message':'只重试这个阶段的失败响应。将产生一次新尝试，并可能再次计费；旧响应及累计账本保留。'})
        if not retry(job,OUTPUT/job_id,{**value,'phase':phase}):return job
        update_job(job_id,status='queued',error='',message='已确认一次失败重试，保留历史响应与费用')
        return get_job(job_id)


@app.post('/api/jobs/{job_id}/billing/{call_id}')
def confirm_billing(job_id:str,call_id:str,value:dict):
    import math
    amount=value.get('actual_cny')
    if value.get('confirmed') is not True or type(amount) not in {int,float} or not math.isfinite(amount) or amount<0:
        raise ValueError('请核对供应商账单并填写非负的实际费用')
    with MATERIAL_LOCKS[job_id],connect() as db:
        job=get_job(job_id)
        if job['status'] in {'running','starting','queued','pause_requested',*DELETING}:raise ValueError('请先等待当前处理停止')
        row=db.execute('SELECT * FROM usage WHERE id=? AND job_id=?',(call_id,job_id)).fetchone()
        if row is None:raise ValueError('调用记录不存在')
        if row['status'] not in {'reserved','uncertain','completed_usage_unknown'}:raise ValueError('该记录已经核算，不能再次确认')
        detail=json.loads(row['detail'])
        detail['billing_confirmation']={'previous_status':row['status'],'previous_reserved':row['reserved'],'actual_cny':amount}
        db.execute('UPDATE usage SET status="confirmed",actual=?,detail=? WHERE id=?',
                   (amount,json.dumps(detail,ensure_ascii=False),call_id))
        return {'ok':True}


@app.patch('/api/jobs/{job_id}/budget')
def change_job_budget(job_id:str,value:dict):
    import math
    budget=value.get('budget_cny')
    if type(budget) not in {int,float} or not math.isfinite(budget) or budget<0:raise ValueError('额度必须为非负数字')
    with MATERIAL_LOCKS[job_id]:
        job=get_job(job_id)
        if job['status'] in {'running','starting','queued','pause_requested',*DELETING}:raise ValueError('请先暂停任务再修改额度')
        if budget+1e-9<usage_for(job_id,include_assistant=False)['spent']:raise ValueError('额度不能低于累计已用和预留费用')
        spec={**job['spec'],'budget_cny':budget}
        with connect() as db:db.execute('UPDATE jobs SET spec=? WHERE id=?',(json.dumps(spec,ensure_ascii=False),job_id))
        return {'ok':True,'budget_cny':budget}


def control_job(job_id,action,value=None):
    job = get_job(job_id)
    if job['status'] in DELETING:raise ValueError('此笔记正在删除或等待清理重试，不能继续处理')
    active = job['status'] in {'running','starting'}
    if action in {'pause','cancel'}:
        update_job(job_id,status=('pause_requested' if action=='pause' else 'cancel_requested') if active else ('paused' if action=='pause' else 'cancelled'))
    elif action in {'resume','organize','formulas','review'}:
        if active or job['status'] in {'pause_requested','cancel_requested'}:
            raise ValueError('请等待当前处理停止')
        if job['status'] in {'ready','materials_ready'} and (value or {}).get('confirm_reprocess') is not True:
            raise HTTPException(409,{'code':'confirmation_required','message':'本节已有处理结果。再次处理会继续使用计算资源，整理或复核可能调用接口并计费；现有来源资料会保留。','existing_job_id':job_id})
        if action!='resume':
            spec = job['spec']
            spec['organize' if action in {'organize','review'} else 'formulas'] = True
            if action=='review':spec['review_notes']=True
            with connect() as db:
                db.execute('UPDATE jobs SET spec=? WHERE id=?',(json.dumps(spec,ensure_ascii=False),job_id))
        update_job(job_id,status='queued',error='',message='将从已保存的阶段继续')
    else:
        raise HTTPException(404,'未知操作')
    return get_job(job_id)


@app.get('/api/artifacts/{job_id}/{relative:path}')
def artifact(job_id:str,relative:str):
    get_job(job_id)
    path = safe_child(OUTPUT/job_id,relative)
    if not path.is_file() or path.suffix.lower() not in {'.png','.jpg','.json','.srt','.vtt','.txt','.html','.md','.js','.css','.woff2','.woff','.ttf'}:
        raise HTTPException(404,'成果文件不存在')
    if path.name in {'settings.json'}:
        raise HTTPException(403)
    return FileResponse(path)


@app.get('/api/video')
def video(path:str):
    return FileResponse(source(path),media_type='video/mp4')


@app.get('/api/jobs/{job_id}/sources')
def source_records(job_id:str,page:str):
    get_job(job_id)
    records=read_json(OUTPUT/job_id/'source_records.json',[])
    return [r for r in records if r.get('page_id')==page]


@app.get('/api/source-frame/{job_id}/{source_id}')
def source_frame(job_id:str,source_id:str,full:bool=False):
    from .common import source_identity
    from .vision import crop_quad
    job=get_job(job_id);output=OUTPUT/job_id
    record=next((r for r in read_json(output/'source_records.json',[]) if r['id']==source_id),None)
    if record is None:raise HTTPException(404,'来源时间不存在')
    if record.get('document_page'):
        return FileResponse(safe_child(output,record['image']),media_type='image/png')
    path=source(job['spec']['path']);manifest=read_json(output/'manifest.json',{})
    if manifest.get('source')!=source_identity(path):raise ValueError('源视频已变化，无法按原记录恢复')
    image=displayed_image_at(path,record['capture_ts'])
    if record.get('quad') and not full:image=crop_quad(image,record['quad'])
    ok,data=cv2.imencode('.png',image)
    if not ok:raise ValueError('来源画面编码失败')
    return Response(data.tobytes(),media_type='image/png',headers={'Cache-Control':'private, max-age=600',
        'X-Image-Width':str(image.shape[1]),'X-Image-Height':str(image.shape[0])})


@app.get('/api/maintenance')
def storage_status():
    return maintenance.storage_status(list_jobs())


@app.post('/api/maintenance/clean')
def clean_storage():
    total=0
    for job in list_jobs():
        if job['status'] in {'running','starting','queued','pause_requested','cancel_requested'}:continue
        total+=maintenance.clean_job(job['id'],True)['deleted_bytes']
    return {'deleted_bytes':total}


@app.post('/api/jobs/{job_id}/visual/{visual_id}/formulas')
def recognize_one_visual(job_id:str,visual_id:str):
    with MATERIAL_LOCKS[job_id]:
        return queue_visual_formulas(job_id,visual_id)


def queue_visual_formulas(job_id,visual_id):
    job=get_job(job_id);output=OUTPUT/job_id
    if job['spec'].get('slide_mode')=='vision_api':raise ValueError('新任务由API在整理时读取原图公式，不单独排队本地公式识别')
    if job['spec'].get('handout_path'):raise ValueError('此任务直接读取原课件，不调用图像识别；请在公式核对中手动修订')
    if job['status'] not in {'materials_ready','ready'}:raise ValueError('请等待本节提取完成后再识别补充画面')
    if not any(v['id']==visual_id for v in read_json(output/'visuals.json',[])):raise ValueError('画面不存在')
    write_json(output/'formula_selection.json',[visual_id])
    manifest=read_json(output/'manifest.json',{})
    manifest['completed_stages']=[s for s in manifest['completed_stages'] if s!='formulas']
    write_json(output/'manifest.json',manifest)
    spec={**job['spec'],'formulas':True,'organize':False}
    with connect() as db:db.execute('UPDATE jobs SET spec=? WHERE id=?',(json.dumps(spec,ensure_ascii=False),job_id))
    update_job(job_id,status='queued',error='',message='只识别选中画面的公式，复用已有字幕与课件')
    return {'ok':True}


@app.get('/api/download/{job_id}')
def download_bundle(job_id:str):
    with MATERIAL_LOCKS[job_id]:
        return prepare_bundle(job_id)


def prepare_bundle(job_id):
    job = get_job(job_id)
    if job['status'] in {'running','starting','queued','pause_requested'}:
        raise ValueError('请先暂停任务或等待处理完成，再打包导出')
    output = OUTPUT/job_id
    if not (output/'notes.html').exists():
        raise ValueError('图文讲义尚未生成')
    files = [p for p in output.iterdir() if p.name in {'notes.html','notes.md','visuals.html','notes.json','visuals.json','manifest.json','report.json','transcript.srt','transcript.vtt','transcript.txt','ocr.txt','audio_audit.json','visual_audit.json','pages.json','source_records.json','compaction.json','quality.json','note_repairs.json','note_review.json','slide_review.json'}]
    for folder in ['images','api_images','formulas','assets','documents']:
        files.extend(p for p in (output/folder).rglob('*') if p.is_file() and
                     (folder!='documents' or p.name in {'source.pdf','source.pptx','source.ppt','pages.pdf'}))
    return zipped_response(output,files,job['spec']['title']+'-学习资料.zip')


def zipped_response(output,files,filename,extra=None):
    temporary=tempfile.SpooledTemporaryFile(max_size=16*1024*1024,mode='w+b')
    try:
        with EXPORT_LOCK,zipfile.ZipFile(temporary,'w') as bundle:
            for path in files:
                bundle.write(path,str(path.relative_to(output)),compress_type=zipfile.ZIP_STORED if path.suffix=='.png' else zipfile.ZIP_DEFLATED)
            for name,text in (extra or {}).items():bundle.writestr(name,text)
        temporary.seek(0)
    except Exception:
        temporary.close();raise
    def chunks():
        try:
            while data:=temporary.read(1024*1024):yield data
        finally:temporary.close()
    return StreamingResponse(chunks(),media_type='application/zip',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename)})


@app.get('/api/download-pages/{job_id}')
def download_pages(job_id:str):
    with MATERIAL_LOCKS[job_id]:
        return prepare_pages(job_id)


def prepare_pages(job_id):
    import html
    job=get_job(job_id);output=OUTPUT/job_id
    if job['status'] in {'running','starting','queued','pause_requested'}:raise ValueError('请在本节处理完成后导出')
    from .slide_review import display_pages
    visuals=sorted(display_pages(read_json(output/'visuals.json',[])),key=lambda v:v['capture_ts'])
    if not visuals:raise ValueError('尚无可导出的代表画面')
    from .export import source_caption
    cards=''.join(f'<figure><img src="{html.escape(v["image"])}"><figcaption>{v["id"]} · {source_caption(v)}</figcaption></figure>' for v in visuals)
    index='<meta charset="utf-8"><title>精简课件</title><style>body{max-width:1000px;margin:30px auto;font-family:sans-serif}img{max-width:100%}figure{margin:30px 0}</style><h1>精简课件与板书</h1><p>仅含代表页；互补及待核对状态见完整学习资料包。</p>'+cards
    return zipped_response(output,[output/v['image'] for v in visuals],job['spec']['title']+'-精简课件.zip',{'index.html':index})



@app.get('/api/snapshot')
def snapshot(path:str,second:float=0):
    video=source(path)
    image = image_at(video,min(max(0,second),max(0,probe(video)['duration']-.1)))
    ok,data = cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,88])
    return Response(data.tobytes(),media_type='image/jpeg')


@app.put('/api/jobs/{job_id}/formula')
def correct_formula(job_id:str,value:dict):
    with MATERIAL_LOCKS[job_id]:
        return save_formula(job_id,value)


def save_formula(job_id,value):
    job = get_job(job_id)
    if job['status'] in {'running','starting','queued'}:
        raise ValueError('请在任务暂停或完成后修改公式')
    output = OUTPUT/job_id
    visuals = read_json(output/'visuals.json',[])
    formula_id = str(value['id'])
    if not any(f['id']==formula_id for v in visuals for f in v.get('formulas',[])):
        raise ValueError('公式不存在')
    latex=str(value['latex'])
    checked=formula_syntax([{'id':formula_id,'latex':latex}])
    if not checked['available']:raise ValueError(checked['message'])
    if checked['errors']:raise ValueError('公式未能正常渲染，请修正后保存：'+checked['errors'][0]['error'])
    corrections = read_json(output/'formula_corrections.json',{})
    corrections[formula_id] = latex
    write_json(output/'formula_corrections.json',corrections)
    visuals = attach_formulas(visuals,output)
    manifest = read_json(output/'manifest.json',{})
    segments = read_json(output/'transcript.json',[])
    from .quality import audit_output,unsafe_formula_ids
    quality=audit_output(output,expect_subtitles=not job['spec'].get('visuals_only'))
    sections = build_sections(segments,visuals,manifest['windows'],unsafe_formula_ids(quality))
    write_json(output/'notes_working.json',sections)
    public=[] if job['spec'].get('organize') else sections
    write_json(output/'notes.json',public)
    (output/'chapter_plan.json').unlink(missing_ok=True)
    export_notes(job['spec']['title'],public,segments,visuals,output,['公式已修改，文字整理需要重新执行以使用新版公式'])
    report=read_json(output/'report.json',{})
    report['formula_corrections']=len(corrections)
    report['warnings']=['公式已修改，文字整理需要重新执行以使用新版公式']
    write_json(output/'report.json',report)
    if job['status']=='ready':
        update_job(job_id,status='materials_ready',message='公式已更新，文字部分需要重新整理')
    return {'ok':True}


if (ROOT/'frontend/dist').exists():
    app.mount('/',StaticFiles(directory=ROOT/'frontend/dist',html=True),name='web')
