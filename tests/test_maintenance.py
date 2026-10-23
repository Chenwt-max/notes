import pytest
from lecture_notes import maintenance
from lecture_notes.common import write_json,source_identity
from lecture_notes.formula_targets import formula_targets


def prepared(tmp_path,monkeypatch):
    root=tmp_path/'outputs';output=root/'job';output.mkdir(parents=True)
    monkeypatch.setattr(maintenance,'OUTPUT',root)
    monkeypatch.setattr(maintenance,'get_job',lambda _: {'status':'materials_ready'})
    source=tmp_path/'video.mp4';source.write_bytes(b'original')
    for name in ['images/keep.png','images/drop.png','formulas/keep.png','formulas/drop.png']:
        path=output/name;path.parent.mkdir(exist_ok=True);path.write_bytes(b'image')
    write_json(output/'visuals.json',[{'id':'v1','image':'images/keep.png','formulas':[{'image':'formulas/keep.png'}]}])
    write_json(output/'source_records.json',[{'id':'v1','representative_id':'v1'},{'id':'v2','representative_id':'v1'}])
    write_json(output/'compaction.json',{'all_sources_mapped':True,'original_count':2})
    write_json(output/'manifest.json',{'source':source_identity(source)})
    return output,source


def test_cleanup_only_unreferenced_generated_files(tmp_path,monkeypatch):
    output,source=prepared(tmp_path,monkeypatch)
    result=maintenance.clean_job('job',True)
    assert result['deleted_bytes']==10
    assert (output/'images/keep.png').exists() and (output/'formulas/keep.png').exists()
    assert not (output/'images/drop.png').exists() and source.read_bytes()==b'original'


def test_document_cache_keeps_referenced_source_and_removes_orphan(tmp_path,monkeypatch):
    output,_=prepared(tmp_path,monkeypatch)
    write_json(output/'document_cache/v1.json',{'text':'保留来源'})
    write_json(output/'document_cache/v2.json',{'text':'无引用'})
    maintenance.clean_job('job',True)
    assert (output/'document_cache/v1.json').exists()
    assert not (output/'document_cache/v2.json').exists()


def test_cleanup_refuses_changed_source_and_incomplete_mapping(tmp_path,monkeypatch):
    output,source=prepared(tmp_path,monkeypatch)
    source.write_bytes(b'changed video')
    with pytest.raises(ValueError,match='源视频'):maintenance.clean_job('job',True)
    assert (output/'images/drop.png').exists()
    write_json(output/'source_records.json',[{'id':'v1','representative_id':'missing'}])
    with pytest.raises(ValueError,match='映射不完整'):maintenance.cleanup_plan(output)


def test_cleanup_refuses_active_job_and_outside_directory(tmp_path,monkeypatch):
    prepared(tmp_path,monkeypatch)
    monkeypatch.setattr(maintenance,'get_job',lambda _: {'status':'running'})
    with pytest.raises(ValueError,match='仍在运行'):maintenance.clean_job('job',True)
    with pytest.raises(ValueError,match='范围'):maintenance.cleanup_plan(tmp_path)


def test_formula_selection_uses_posters_or_explicit_supplement(tmp_path):
    visuals=[{'id':'v1','is_representative':True},{'id':'v2','is_representative':False}]
    write_json(tmp_path/'visuals.json',visuals)
    assert [v['id'] for v in formula_targets(tmp_path)]==['v1']
    write_json(tmp_path/'formula_selection.json',['v2'])
    assert [v['id'] for v in formula_targets(tmp_path)]==['v2']


def test_asr_cleanup_preserves_resume_checkpoints_until_verified_completion(tmp_path,monkeypatch):
    import hashlib
    output,source=prepared(tmp_path,monkeypatch)
    (output/'asr_work').mkdir();(output/'asr_work/chunk.wav').write_bytes(b'audio')
    (output/'asr_chunks').mkdir();checkpoint=output/'asr_chunks/qwen_v3_test.json'
    checkpoint.write_text('checkpoint')
    maintenance.clean_job('job',True)
    assert not (output/'asr_work/chunk.wav').exists() and checkpoint.exists()
    transcript=output/'transcript.json';transcript.write_text('verified subtitles')
    write_json(output/'asr_runtime.json',{'completed':True,'transcript_sha256':hashlib.sha256(transcript.read_bytes()).hexdigest()})
    maintenance.clean_job('job',True)
    assert not checkpoint.exists() and transcript.exists() and source.read_bytes()==b'original'
