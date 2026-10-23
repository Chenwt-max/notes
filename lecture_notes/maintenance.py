"""Reference-checked generated-file cleanup; source videos are outside its scope."""
from pathlib import Path
import hashlib
from .common import OUTPUT,read_json,write_json,digest,source_identity
from .store import get_job


def asr_temporary_files(output):
    paths=[output/name for name in ['asr_request.json','asr_request.json.tmp','asr_progress.json',
                                   'asr_progress.json.tmp','asr.stop']]
    paths.extend((output/'asr_work').glob('*.wav'))
    runtime=read_json(output/'asr_runtime.json',{})
    transcript=output/'transcript.json'
    if runtime.get('completed') and transcript.exists() and \
       hashlib.sha256(transcript.read_bytes()).hexdigest()==runtime.get('transcript_sha256'):
        paths.extend((output/'asr_chunks').glob('qwen_v3_*.json'))
    candidates=[]
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(output):raise ValueError('清理目录包含外部链接')
        if path.is_file():candidates.append({'path':path.relative_to(output).as_posix(),'bytes':path.stat().st_size,
                                            'reason':'regenerable_asr_temporary_file'})
    return candidates


def cleanup_plan(output):
    output=Path(output).resolve()
    if not output.is_relative_to(OUTPUT.resolve()) or output==OUTPUT.resolve():
        raise ValueError('清理范围必须是输出目录内的一次任务')
    visuals=read_json(output/'visuals.json',[])
    compact=read_json(output/'compaction.json',{})
    temporary=asr_temporary_files(output)
    if not compact.get('all_sources_mapped') or not (output/'source_records.json').exists():return temporary
    records=read_json(output/'source_records.json',[])
    ids={v['id'] for v in visuals}
    if not records or len(records)!=compact['original_count'] or any(r['representative_id'] not in ids for r in records):
        raise ValueError('来源映射不完整，拒绝清理')
    keep=set()
    for v in visuals:
        keep.add(v['image'])
        if v.get('hd_image'):keep.add(v['hd_image'])
        if v.get('person_mask'):keep.add(v['person_mask'])
        keep.add(f"formula_cache/{v['id']}.json")
        keep.add(f"document_cache/{v['id']}.json")
        keep.add(f"screening_cache/{v['id']}.json")
        screened=read_json(output/f"screening_cache/{v['id']}.json",{})
        if screened.get('image_sha256'):keep.add(f"screening_cache/{screened['image_sha256']}.json")
        for f in v.get('formulas',[]):
            if f.get('image'):keep.add(f['image'])
        image=output/v['image']
        if not image.is_file():raise ValueError('代表页缺失，拒绝清理')
        keep.add('ocr_cache/'+digest({'image':image.name,'size':image.stat().st_size,'version':'rapidocr-3.10'})+'.json')
    candidates=list(temporary)
    for part in sorted((output/'parts').glob('[0-9][0-9][0-9]')):
        for row in cleanup_plan(part):
            candidates.append({**row,'path':part.relative_to(output).as_posix()+'/'+row['path']})
    for folder in ['images','masks','formulas','formula_cache','ocr_cache','document_cache','screening_cache','api_images']:
        parent=output/folder
        if not parent.exists():continue
        for path in parent.iterdir():
            if path.is_symlink() or not path.resolve().is_relative_to(output):raise ValueError('清理目录包含外部链接')
            relative=path.relative_to(output).as_posix()
            if path.is_file() and relative not in keep:
                try:size=path.stat().st_size
                except FileNotFoundError:continue
                candidates.append({'path':relative,'bytes':size,'reason':'unreferenced_generated_file'})
    snapshot=output/'visuals.precompact.json'
    if snapshot.exists():candidates.append({'path':snapshot.name,'bytes':snapshot.stat().st_size,'reason':'completed_compaction_snapshot'})
    for path in output.glob('*.zip'):
        candidates.append({'path':path.name,'bytes':path.stat().st_size,'reason':'regenerable_bundle'})
    return candidates


def clean_job(job_id,apply=False):
    job=get_job(job_id)
    if job['status'] in {'running','starting','queued','pause_requested','cancel_requested'}:
        raise ValueError('当前任务仍在运行，暂不清理')
    output=(OUTPUT/job_id).resolve()
    if output.name!=job_id:raise ValueError('任务目录发生重定向，拒绝清理')
    candidates=cleanup_plan(output)
    if candidates:
        manifest=read_json(output/'manifest.json',{})
        original=manifest.get('source',{})
        if not original or not Path(original.get('path','')).is_file() or source_identity(original['path'])!=original:
            raise ValueError('源视频缺失或已变化，保留重复原图以便恢复')
    report={'files':candidates,'candidate_bytes':sum(c['bytes'] for c in candidates),'deleted_bytes':0,'skipped':[]}
    if apply:
        for item in candidates:
            path=(output/item['path']).resolve()
            if not path.is_relative_to(output) or path==output:raise ValueError('清理路径越界')
            try:path.unlink()
            except FileNotFoundError:continue
            except PermissionError:
                report['skipped'].append(item['path']);continue
            report['deleted_bytes']+=item['bytes']
        write_json(output/'cleanup_report.json',report)
    return report


def storage_status(jobs):
    total=0;reclaimable=0;rows=[]
    for job in jobs:
        output=OUTPUT/job['id']
        size=0
        if output.exists():
            for path in output.rglob('*'):
                if path.is_file() and not path.is_symlink():
                    try:size+=path.stat().st_size
                    except FileNotFoundError:pass  # A running worker atomically renames caches.
        total+=size;can=0
        if job['status'] not in {'running','starting','queued','pause_requested','cancel_requested'}:
            can=sum(c['bytes'] for c in cleanup_plan(output))
        reclaimable+=can
        rows.append({'id':job['id'],'bytes':size,'reclaimable':can,'compaction':read_json(output/'compaction.json',{})})
    return {'bytes':total,'reclaimable':reclaimable,'jobs':rows}
