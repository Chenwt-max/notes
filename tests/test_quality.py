import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lecture_notes import quality,materials,store,server
from lecture_notes.common import write_json,read_json


@pytest.fixture
def output(tmp_path):
    (tmp_path/'images').mkdir()
    (tmp_path/'images/a.png').write_bytes(b'kept-source')
    write_json(tmp_path/'manifest.json',{'windows':[[0,20]],'completed_stages':['asr','visuals','compact','ocr']})
    write_json(tmp_path/'visuals.json',[{'id':'v1','image':'images/a.png','content_id':'p1','poster_id':'v1',
        'capture_ts':2,'start':0,'end':20,'kind':'slides','layout':'x','quad':None,'flags':[],
        'ocr':'source','quality_score':1,'is_representative':True,'formulas':[
            {'id':'f1','latex':r'\frac{1}{','status':'unverified'}]}])
    write_json(tmp_path/'source_records.json',[{'id':'r1','representative_id':'v1','page_id':'p1','poster_id':'v1','capture_ts':2,'start':0,'end':20}])
    write_json(tmp_path/'transcript.json',[{'id':'s1','start':0,'end':5,'text':'原始字幕','flags':[]}])
    write_json(tmp_path/'audio_audit.json',{'uncovered_speech':[[6,9]]})
    return tmp_path


def test_actual_renderer_detects_invalid_formula_and_never_certifies_semantics(output):
    result=quality.audit_output(output)
    assert result['integrity_ok']
    assert not result['semantic_accuracy_verified'] and result['state']=='needs_review'
    assert result['formulas']['syntax']['available']
    assert result['formulas']['syntax']['errors'][0]['id']=='f1'
    assert result['subtitles']['uncovered_speech']==[[6,9]]
    assert read_json(output/'visuals.json')[0]['formulas'][0]['latex']==r'\frac{1}{'


def test_missing_source_bad_timing_and_unfinished_stage_are_not_success(output):
    (output/'images/a.png').unlink()
    write_json(output/'transcript.json',[{'id':'s1','start':7,'end':4,'text':'逆向时间'}])
    manifest=read_json(output/'manifest.json');manifest['completed_stages'].remove('asr')
    write_json(output/'manifest.json',manifest)
    result=quality.audit_output(output)
    assert result['state']=='blocked'
    assert {'missing_image','invalid_subtitle_time','unfinished_stage'} <= {e['code'] for e in result['integrity_errors']}


def test_missing_formula_checker_is_reported_not_passed(monkeypatch):
    monkeypatch.setattr(quality.shutil,'which',lambda name:None)
    result=quality.formula_syntax([{'id':'x','latex':'x'}])
    assert not result['available']


def test_invalid_manual_revision_is_rejected_without_changing_saved_data(output,monkeypatch):
    monkeypatch.setattr(store,'DATA',output/'db')
    monkeypatch.setattr(store,'OUTPUT',output/'out')
    job=store.create_job({'title':'test','path':'source.mp4'})
    jobout=output/'out'/job['id']
    write_json(jobout/'visuals.json',read_json(output/'visuals.json'))
    store.update_job(job['id'],status='paused')
    monkeypatch.setattr(server,'OUTPUT',output/'out')
    client=TestClient(server.app)
    response=client.put(f"/api/jobs/{job['id']}/formula",json={'id':'f1','latex':r'\frac{1}{'})
    assert response.status_code==400 and '渲染' in response.json()['detail']
    assert not (jobout/'formula_corrections.json').exists()


def test_regroup_preserves_organized_text_and_rolls_back_on_failed_integrity(output,monkeypatch):
    from lecture_notes.synthesis import build_sections
    segments=read_json(output/'transcript.json');visuals=read_json(output/'visuals.json')
    notes=build_sections(segments,visuals,[[0,20]])
    notes[0].update(id='semantic-chapter',body='必须保留的已整理内容',organized=True,
                    source_note_ids=['n0001','n0002'],reviewed_body_hash='body-hash',reviewed_source_hash='source-hash')
    write_json(output/'notes.json',notes)
    monkeypatch.setattr(materials,'regroup_existing',lambda *a,**kw:{'groups':1,'previous_groups':1})
    monkeypatch.setattr(materials,'export_notes',lambda *a,**kw:None)
    job={'spec':{'title':'test'}}
    materials.review_materials(job,output,regroup=True)
    assert read_json(output/'notes.json')==notes
    before=(output/'visuals.json').read_bytes()
    monkeypatch.setattr(materials,'audit_output',lambda *a,**kw:{'integrity_ok':False})
    with pytest.raises(ValueError,match='恢复'):
        materials.review_materials(job,output,regroup=True)
    assert (output/'visuals.json').read_bytes()==before


def test_invalid_formula_export_uses_original_image_instead_of_broken_math(output):
    from lecture_notes.export import export_notes
    from lecture_notes.synthesis import build_sections
    segments=read_json(output/'transcript.json');visuals=read_json(output/'visuals.json')
    quality.audit_output(output)
    sections=build_sections(segments,visuals,[[0,20]])
    text=export_notes('test',sections,segments,visuals,output)
    assert '未通过渲染检查' in text and r'\frac{1}{' not in text
    assert 'images/a.png' in text


def test_regroup_and_rollback_work_before_whole_manuscript_publication(output,monkeypatch):
    write_json(output/'notes.json',[])
    write_json(output/'notes_working.json',[{'body':'尚未公开的完整片段'}])
    private=(output/'notes_working.json').read_bytes()
    monkeypatch.setattr(materials,'regroup_existing',lambda *a,**kw:{'groups':1,'previous_groups':1})
    monkeypatch.setattr(materials,'export_notes',lambda *a,**kw:None)
    job={'spec':{'title':'test'}}
    materials.review_materials(job,output,regroup=True)
    assert read_json(output/'notes.json')==[] and (output/'notes_working.json').read_bytes()==private
    write_json(output/'materials_pending.json',{'state':'regrouping'})
    materials.recover_materials(job,output)
    assert read_json(output/'notes.json')==[] and not (output/'materials_pending.json').exists()


def test_interrupted_regroup_recovers_only_whitelisted_metadata(output,monkeypatch):
    from lecture_notes.synthesis import build_sections
    visuals=read_json(output/'visuals.json')
    notes=build_sections(read_json(output/'transcript.json'),visuals,[[0,20]])
    backup={name:read_json(output/name) for name in materials.SNAPSHOT_FILES}
    backup['notes.json']=notes
    backup['../outside.json']={'must_not_be_written':True}
    write_json(output/'materials_backup.json',backup)
    write_json(output/'materials_pending.json',{'state':'regrouping'})
    write_json(output/'visuals.json',[])
    monkeypatch.setattr(materials,'export_notes',lambda *a,**kw:None)
    materials.recover_materials({'spec':{'title':'test'}},output)
    assert read_json(output/'visuals.json')==visuals
    assert not (output/'materials_pending.json').exists()
    assert not (output.parent/'outside.json').exists()


def test_database_context_closes_windows_file_handle(tmp_path,monkeypatch):
    import sqlite3
    monkeypatch.setattr(store,'DATA',tmp_path)
    with store.connect() as db:
        db.execute('SELECT 1').fetchone()
    with pytest.raises(sqlite3.ProgrammingError,match='closed'):
        db.execute('SELECT 1')
    (tmp_path/'jobs.sqlite').unlink()


def test_renderable_but_conflicting_operator_is_not_used_as_math(output):
    from lecture_notes.synthesis import build_sections
    visual=read_json(output/'visuals.json')[0]
    visual['formulas']=[{'id':'f1','latex':r'\cos(w)+\lambda w^2','box':[0,0,200,60]}]
    visual['ocr_lines']=[{'text':'Loss(w) + λw²','score':.97,'box':[[10,10],[160,10],[160,40],[10,40]]}]
    write_json(output/'visuals.json',[visual])
    result=quality.audit_output(output)
    assert not result['formulas']['syntax']['errors']
    assert result['formulas']['disagreements'][0]['id']=='f1'
    sections=build_sections([], [visual], [[0,20]], quality.unsafe_formula_ids(result))
    assert not sections[0]['evidence'][0]['formula_candidates']
    visual['formulas'][0]['latex']=r'\operatorname{Loss}(w)+\lambda w^2'
    assert not quality.operator_disagreements(visual)


def test_organized_export_reads_as_notes_without_appending_slide_pileup(output):
    from lecture_notes.synthesis import build_sections
    from lecture_notes.export import export_notes
    segments=read_json(output/'transcript.json');visuals=read_json(output/'visuals.json')
    sections=build_sections(segments,visuals,[[0,20]])
    sections[0].update(body='## 知识主题\n\n整理后的定义和推导。',organized=True)
    text=export_notes('课程',sections,segments,visuals,output)
    assert '整理后的定义和推导' in text and '![课件' not in text
    assert '原始字幕' in text and '原始字幕\n\n' not in text
