import sys
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from lecture_notes import settings,server,store
from lecture_notes.common import read_json,write_json
from lecture_notes.document_model import DOCUMENT_MODEL
from lecture_notes.formula_worker import parse_document,recognize_pages
from lecture_notes.pipeline import attach_formulas


def test_document_factory_uses_pinned_local_v16_and_single_batch(tmp_path,monkeypatch):
    from lecture_notes import document_model
    monkeypatch.setattr(document_model,'MODEL_DIR',tmp_path)
    (tmp_path/'model.safetensors').write_bytes(b'fixture')
    assert not document_model.models_ready()
    write_json(tmp_path/'PROVENANCE.json',{'files':[{'Path':'model.safetensors','Size':7}]})
    options={}
    def create(**kwargs):options.update(kwargs);return 'pipeline'
    config={'SubModules':{'LayoutDetection':{},'VLRecognition':{}}}
    monkeypatch.setitem(sys.modules,'paddleocr',SimpleNamespace(PaddleOCRVL=create))
    monkeypatch.setitem(sys.modules,'paddlex.inference',SimpleNamespace(load_pipeline_config=lambda _:config))
    assert document_model.create_document_pipeline('gpu:0',2)=='pipeline'
    assert options['pipeline_version']=='v1.6' and options['vl_rec_backend']=='native'
    assert options['paddlex_config']['SubModules']['VLRecognition']=={'batch_size':1,'model_dir':str(tmp_path)}
    assert options['paddlex_config']['batch_size']==1 and not options['use_queues']
    assert options['device']=='gpu:0' and options['cpu_threads']==2
    assert options['use_ocr_for_image_block']


def test_model_settings_migrate_and_new_jobs_capture_current_model(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'DATA',tmp_path/'config')
    monkeypatch.setattr(store,'DATA',tmp_path/'db')
    monkeypatch.setattr(server,'WORKSPACE',tmp_path)
    monkeypatch.setattr(server,'probe',lambda _: {'duration':10})
    write_json(tmp_path/'config/settings.json',{'formula_model':'PP-FormulaNet_plus-L','input_price':1.2})
    client=TestClient(server.app)
    assert client.get('/api/settings').json()['formula_model']==DOCUMENT_MODEL
    assert client.put('/api/settings',json={'formula_model':'invented'}).status_code==400
    saved=client.put('/api/settings',json={'formula_model':DOCUMENT_MODEL})
    assert saved.status_code==200 and saved.json()['input_price']==1.2
    video=tmp_path/'course.mp4';video.write_bytes(b'original')
    assert client.post('/api/jobs',json={'path':str(video),'organize':False}).json()['spec']['formula_model']==DOCUMENT_MODEL


def test_document_parse_preserves_text_table_formula_and_source_boxes():
    result=parse_document({'parsing_res_list':[
        {'block_label':'text','block_content':'定义与 $x_i$','block_bbox':[0,0,80,20]},
        {'block_label':'table','block_content':'<table><tr><td>1</td></tr></table>','block_bbox':[0,20,80,40]},
        {'block_label':'display_formula','block_content':r'$$\sum_i x_i$$','block_bbox':[5,40,80,60]},
        {'block_label':'formula_number','block_content':'(1)','block_bbox':[80,40,99,60]},
    ]})
    assert '定义与 $x_i$' in result['text'] and '<table>' in result['text']
    assert [f['latex'] for f in result['formulas']]==['x_i',r'\sum_i x_i']
    assert result['formulas'][1]['box']==[5,40,80,60]
    assert result['formulas'][1]['status']=='unverified'


def test_math_inside_image_region_is_not_discarded():
    result=parse_document({'parsing_res_list':[{'block_label':'image',
        'block_content':r'贝叶斯：\[p(Y|X)=\frac{p(X|Y)p(Y)}{p(X)}\]',
        'block_bbox':[10,20,200,100]}]})
    assert '贝叶斯' in result['text']
    assert len(result['formulas'])==1 and 'frac' in result['formulas'][0]['latex']


def test_legacy_completed_pages_and_manual_corrections_are_preserved(tmp_path,monkeypatch):
    monkeypatch.setenv('LECTURE_INFERENCE_DEVICE','cpu')
    monkeypatch.setenv('LECTURE_PROCESSING_MODE','fast')
    monkeypatch.setitem(sys.modules,'paddle',SimpleNamespace(__version__='test'))
    calls=[]
    class Pipeline:
        def predict(self,path,**kwargs):
            calls.append(path)
            return [SimpleNamespace(json={'res':{'parsing_res_list':[
                {'block_label':'text','block_content':'新文字','block_bbox':[0,0,50,20]},
                {'block_label':'formula','block_content':'$x^2$','block_bbox':[0,20,50,40]}]}})]
        def close(self):calls.append('closed')
    monkeypatch.setattr('lecture_notes.document_model.create_document_pipeline',lambda *_:Pipeline())
    image=np.full((50,100,3),255,np.uint8)
    for name in ('old.png','new.png'):cv2.imencode('.png',image)[1].tofile(str(tmp_path/name))
    visuals=[{'id':'old','image':'old.png','ocr':'原文字'},
             {'id':'new','image':'new.png','ocr':'初识别','ocr_lines':[
                 {'text':'图外补充','score':.9,'box':[[60,0],[90,0],[90,20],[60,20]]}]}]
    write_json(tmp_path/'visuals.json',visuals)
    write_json(tmp_path/'manifest.json',{'models':{'formula':'PP-FormulaNet_plus-L'}})
    write_json(tmp_path/'formula_cache/old.json',[{'latex':'y','box':[0,0,10,10]}])
    write_json(tmp_path/'formula_corrections.json',{'old_f1':'y^2'})
    before=(tmp_path/'formula_cache/old.json').read_bytes()
    recognize_pages(tmp_path,lambda:None)
    assert calls==[str(tmp_path/'new.png'),'closed']
    assert (tmp_path/'formula_cache/old.json').read_bytes()==before
    attached=attach_formulas(visuals,tmp_path)
    assert attached[0]['formulas'][0]['corrected_latex']=='y^2'
    assert attached[1]['ocr']=='新文字\n图外补充' and attached[1]['ocr_before_document']=='初识别'
    assert attached[1]['formulas'][0]['image']=='formulas/new_f1.png'
    assert read_json(tmp_path/'formula_runtime.json')['model']==DOCUMENT_MODEL
    # Reuse a fully written document if interrupted before the formula commit marker.
    (tmp_path/'formula_cache/new.json').unlink()
    recognize_pages(tmp_path,lambda:None)
    assert calls==[str(tmp_path/'new.png'),'closed','closed']


def test_document_oom_preserves_completed_page_and_resumes_missing_only(tmp_path,monkeypatch):
    monkeypatch.setenv('LECTURE_INFERENCE_DEVICE','cpu')
    monkeypatch.setenv('LECTURE_PROCESSING_MODE','fast')
    monkeypatch.setitem(sys.modules,'paddle',SimpleNamespace(__version__='test'))
    calls=[];fail=[True]
    class Pipeline:
        def predict(self,path,**kwargs):
            calls.append(Path(path).stem)
            if Path(path).stem=='second' and fail[0]:raise RuntimeError('CUDA out of memory')
            return [SimpleNamespace(json={'res':{'parsing_res_list':[
                {'block_label':'formula','block_content':'$x^2$','block_bbox':[0,0,20,20]}]}})]
        def close(self):calls.append('closed')
    from pathlib import Path
    monkeypatch.setattr('lecture_notes.document_model.create_document_pipeline',lambda *_:Pipeline())
    for name in ('first','second'):(tmp_path/f'{name}.png').write_bytes(b'original')
    write_json(tmp_path/'visuals.json',[{'id':name,'image':f'{name}.png'} for name in ('first','second')])
    with pytest.raises(RuntimeError,match='out of memory'):recognize_pages(tmp_path,lambda:None)
    saved=(tmp_path/'formula_cache/first.json').read_bytes()
    assert not (tmp_path/'formula_complete.json').exists()
    assert not (tmp_path/'formula_cache/second.json').exists()
    assert calls==['first','second','closed']
    fail[0]=False
    recognize_pages(tmp_path,lambda:None)
    assert calls==['first','second','closed','second','closed']
    assert (tmp_path/'formula_cache/first.json').read_bytes()==saved
    assert read_json(tmp_path/'formula_complete.json')['completed']
