"""Recheck cached materials and regroup posters without rerunning any model."""
from __future__ import annotations

from .common import read_json,write_json
from .compaction import regroup_existing,GROUP_VERSION
from .quality import audit_output
from .export import export_notes

SNAPSHOT_FILES=('visuals.json','source_records.json','pages.json','notes.json','compaction.json','report.json','quality.json','visual_audit.json')


def restore_materials(job,output,backup):
    for name in SNAPSHOT_FILES:
        value=backup.get(name)
        if value is None:(output/name).unlink(missing_ok=True)
        else:write_json(output/name,value)
    export_notes(job['spec'].get('title') or '课程讲义',backup['notes.json'],
        read_json(output/'transcript.json',[]),backup['visuals.json'],output,(backup.get('report.json') or {}).get('warnings',[]))
    (output/'materials_pending.json').unlink(missing_ok=True)


def recover_materials(job,output):
    if not (output/'materials_pending.json').exists():return
    backup=read_json(output/'materials_backup.json',{})
    if not backup.get('visuals.json') or not isinstance(backup.get('notes.json'),list):
        raise ValueError('课件整理恢复备份缺失，停止写入并保留现场')
    restore_materials(job,output,backup)


def review_materials(job,output,regroup=False):
    visuals=read_json(output/'visuals.json',[])
    records=read_json(output/'source_records.json',[])
    manifest=read_json(output/'manifest.json',{})
    segments=read_json(output/'transcript.json',[])
    sections=read_json(output/'notes.json',[])
    report=read_json(output/'report.json',{})
    backup={}
    grouping=None
    quality=None
    if regroup:
        if not visuals or not records:
            raise ValueError('请先完成素材提取，再整理代表页')
        # Keep one bounded rollback snapshot; never duplicate bitmaps or videos.
        backup={name:read_json(output/name) for name in SNAPSHOT_FILES}
        write_json(output/'materials_backup.json',backup)
        write_json(output/'materials_pending.json',{'state':'regrouping'})
    try:
        if regroup:
            grouping=regroup_existing(visuals,records,output)
            write_json(output/'visuals.json',visuals)
            write_json(output/'source_records.json',records)
            pages=[{'content_id':v['content_id'],'representative':v['id'],'kind':v['kind'],
                    'appearances':[r for r in records if r['page_id']==v['content_id']]}
                   for v in visuals if v.get('is_representative',True)]
            write_json(output/'pages.json',pages)
            compaction=read_json(output/'compaction.json',{})
            compaction.update(grouping_version=GROUP_VERSION,page_count=len(pages),supplementary_images=len(visuals)-len(pages),last_regroup=grouping)
            write_json(output/'compaction.json',compaction)
            audit=read_json(output/'visual_audit.json',{})
            audit['content_groups']=len(pages)
            write_json(output/'visual_audit.json',audit)
            quality=audit_output(output,expect_subtitles=not job['spec'].get('visuals_only'))
            if not quality['integrity_ok']:
                raise ValueError('整理后完整性检查未通过，已恢复整理前的元数据')
            # Browsing groups change, not the manuscript or its chapter boundaries.
            # Keep every existing body, source link and independent-review hash.
            for section in sections:
                ids=set(section['visual_ids'])
                section['display_visual_ids']=[v['id'] for v in visuals if v['id'] in ids and v.get('is_representative',True)]
            write_json(output/'notes.json',sections)
        if quality is None:quality=audit_output(output,expect_subtitles=not job['spec'].get('visuals_only'))
        if regroup and not quality['integrity_ok']:
            raise ValueError('整理后完整性检查未通过，已恢复整理前的元数据')
        if sections:
            export_notes(job['spec'].get('title') or '课程讲义',sections,segments,visuals,output,report.get('warnings',[]))
        report['quality']=quality
        if grouping:
            report['formula_candidates']=sum(len(v.get('formulas',[])) for v in visuals if v.get('is_representative',True))
            report['supplementary_formula_candidates']=sum(len(v.get('formulas',[])) for v in visuals if not v.get('is_representative',True))
            report['visual_audit']=read_json(output/'visual_audit.json',{})
        write_json(output/'report.json',report)
        (output/'materials_pending.json').unlink(missing_ok=True)
        return {'quality':quality,'grouping':grouping}
    except Exception:
        if backup:
            restore_materials(job,output,backup)
        raise
