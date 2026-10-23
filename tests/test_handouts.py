"""Self-authored document fixtures; no model, paid API or private course required."""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import pytest
from fastapi.testclient import TestClient

from lecture_notes import handouts,pipeline,store,maintenance,server,runtime
from lecture_notes.common import read_json
from lecture_notes.synthesis import build_sections


def make_pdf(path,texts):
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    ids=[]
    for text in texts:
        page_id=len(objects)+1;ids.append(page_id)
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 640 360] /Resources << /Font << /F1 3 0 R >> >> /Contents {page_id+1} 0 R >>'.encode())
        stream=f'BT /F1 24 Tf 40 240 Td ({text}) Tj ET'.encode()
        objects.append(f'<< /Length {len(stream)} >>\nstream\n'.encode()+stream+b'\nendstream')
    objects[1]=f'<< /Type /Pages /Count {len(ids)} /Kids [{" ".join(str(i)+" 0 R" for i in ids)}] >>'.encode()
    pdf=b'%PDF-1.7\n';offsets=[0]
    for index,obj in enumerate(objects,1):offsets.append(len(pdf));pdf+=f'{index} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(pdf);pdf+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    pdf+=b''.join(f'{n:010d} 00000 n \n'.encode() for n in offsets[1:])
    pdf+=f'trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    path.write_bytes(pdf);return path


def test_pdf_keeps_duplicate_and_blank_pages_without_recognition(tmp_path):
    path=make_pdf(tmp_path/'中文 课件.pdf',['Matrix dimensions','Matrix dimensions',''])
    output=tmp_path/'out';output.mkdir()
    pages=handouts.import_handout(path,output,[[0,60]],lambda *_:None,lambda:None)
    assert len(pages)==3 and pages[0]['ocr']=='Matrix dimensions'
    assert all(p['untimed'] and p['is_representative'] for p in pages)
    assert [p['document_page'] for p in pages]==[1,2,3]
    assert (output/pages[0]['image']).read_bytes()==(output/pages[1]['image']).read_bytes()
    from PIL import Image
    with Image.open(output/pages[0]['image']) as image:assert image.width==2560 and image.height==1440
    result=read_json(output/'handout.json');assert result['ocr_used'] is False and len(result['warnings'])==1
    assert result['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert (output/'documents/source.pdf').read_bytes()==path.read_bytes()


@pytest.mark.parametrize('body,latex',[
    ('<m:f><m:num><m:r><m:t>a</m:t></m:r></m:num><m:den><m:r><m:t>b</m:t></m:r></m:den></m:f>',r'\frac{a}{b}'),
    ('<m:sSubSup><m:e><m:r><m:t>x</m:t></m:r></m:e><m:sub><m:r><m:t>i</m:t></m:r></m:sub><m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSubSup>',r'{x}_{i}^{2}'),
    ('<m:m><m:mr><m:e><m:r><m:t>1</m:t></m:r></m:e><m:e><m:r><m:t>2</m:t></m:r></m:e></m:mr></m:m>',r'\begin{matrix}1&2\end{matrix}'),
])
def test_editable_office_math_preserves_structure(body,latex):
    node=ET.fromstring(f'<m:oMath xmlns:m="{handouts.NS["m"]}">{body}</m:oMath>')
    assert handouts.omml_latex(node)==latex


def test_unknown_office_math_is_not_flattened_into_false_formula():
    with pytest.raises(ValueError,match='公式结构'):
        handouts.omml_latex(ET.fromstring(f'<m:unknown xmlns:m="{handouts.NS["m"]}"><m:t>bad</m:t></m:unknown>'))


def test_pptx_content_uses_presentation_order(tmp_path):
    path=tmp_path/'order.pptx'
    ns=' '.join(f'xmlns:{k}="{v}"' for k,v in handouts.NS.items())
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('ppt/presentation.xml',f'<p:presentation {ns}><p:sldIdLst><p:sldId r:id="r2"/><p:sldId r:id="r1"/></p:sldIdLst></p:presentation>')
        z.writestr('ppt/_rels/presentation.xml.rels','<Relationships><Relationship Id="r1" Target="slides/slide2.xml"/><Relationship Id="r2" Target="slides/slide10.xml"/></Relationships>')
        for number,text in [(2,'second'),(10,'first')]:
            z.writestr(f'ppt/slides/slide{number}.xml',f'<p:sld {ns}><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>')
    assert [p['text'] for p in handouts.pptx_content(path)]==['first','second']


def test_document_sections_match_context_without_faking_timestamps():
    docs=[{'id':'d1','ocr':'矩阵维数与秩','formulas':[],'document_page':1,'capture_ts':0,'start':0,'end':600,'content_id':'d1'},
          {'id':'d2','ocr':'概率分布与期望','formulas':[],'document_page':2,'capture_ts':0,'start':0,'end':600,'content_id':'d2'}]
    sections=build_sections([{'id':'s1','start':1,'end':2,'text':'讨论概率分布'}],docs,[[0,600]])
    assert [e['id'] for e in sections[0]['evidence']]==['d2']
    assert '无视频时间戳' in sections[0]['evidence'][0]['time']
    assert set(sections[0]['visual_ids'])=={'d1','d2'}


def test_handout_pipeline_bypasses_all_visual_models(tmp_path,monkeypatch,sample_video):
    for module in (store,pipeline,maintenance):monkeypatch.setattr(module,'OUTPUT',tmp_path/'outputs')
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    path=make_pdf(tmp_path/'handout.pdf',['Public course'])
    job=store.create_job({'path':str(sample_video),'handout_path':str(path),'windows':[[0,10]],'visuals_only':True,'organize':False})
    monkeypatch.setattr(pipeline,'probe',lambda _: {'duration':10,'audio':False})
    monkeypatch.setattr(pipeline,'export_notes',lambda *args:None)
    def forbidden(*args,**kwargs):raise AssertionError('A visual recognition model was invoked')
    for name in ('extract_video','recognize','compact_visuals','run_formula','regroup_existing'):monkeypatch.setattr(pipeline,name,forbidden)
    pipeline.run_job(job['id'])
    result=store.get_job(job['id']);assert result['status']=='materials_ready'
    output=tmp_path/'outputs'/job['id']
    assert read_json(output/'report.json')['source_mapping_complete']
    assert read_json(output/'quality.json')['integrity_ok']
    assert read_json(output/'visual_audit.json')['timeline_coverage_applicable'] is False


def test_api_stores_local_handout_and_refuses_missing_path(tmp_path,monkeypatch,sample_video):
    monkeypatch.setattr(server,'source',lambda _:sample_video)
    monkeypatch.setattr(server,'probe',lambda _: {'duration':10})
    monkeypatch.setattr(server,'list_jobs',lambda:[])
    monkeypatch.setattr(server,'create_job',lambda spec:{'spec':spec})
    monkeypatch.setattr(runtime,'PORTABLE',False)
    path=make_pdf(tmp_path/'讲义.pdf',['Public'])
    client=TestClient(server.app)
    assert client.post('/api/jobs',json={'path':str(sample_video),'handout_path':str(tmp_path/'missing.pdf')}).status_code==400
    job=client.post('/api/jobs',json={'path':str(sample_video),'handout_path':str(path)}).json()
    assert job['spec']['handout_path']==str(path.resolve())


def test_document_large_image_uses_saved_page_not_video_decoder(tmp_path,monkeypatch):
    from lecture_notes.common import write_json
    output=tmp_path/'job';output.mkdir();(output/'page.png').write_bytes(b'page-image')
    write_json(output/'source_records.json',[{'id':'d1','document_page':1,'image':'page.png'}])
    monkeypatch.setattr(server,'OUTPUT',tmp_path);monkeypatch.setattr(server,'get_job',lambda _: {'spec':{}})
    response=server.source_frame('job','d1')
    assert Path(response.path)==output/'page.png'


def test_formula_fallback_selects_only_needed_pages(tmp_path,monkeypatch,sample_video):
    from contextlib import nullcontext
    from lecture_notes.common import write_json
    for module in (store,pipeline,maintenance):monkeypatch.setattr(module,'OUTPUT',tmp_path/'outputs')
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    path=make_pdf(tmp_path/'formulas.pdf',['Plain introduction','E = mc^2'])
    job=store.create_job({'path':str(sample_video),'handout_path':str(path),'handout_recognize':True,
        'windows':[[0,10]],'organize':False,'formulas':True})
    monkeypatch.setattr(pipeline,'probe',lambda _: {'duration':10,'audio':True})
    monkeypatch.setattr(pipeline,'gpu_slot',lambda *args:nullcontext())
    monkeypatch.setattr(pipeline,'wait_for_gpu_memory',lambda *args:None)
    monkeypatch.setattr(pipeline,'export_notes',lambda *args:None)
    def speech(path,windows,out,*args):write_json(out/'transcript.json',[{'id':'s1','start':1,'end':2,'text':'energy equation'}])
    monkeypatch.setattr(pipeline,'transcribe',speech)
    calls=[]
    def recognize(job_id,out,*args):
        selected=read_json(out/'formula_selection.json');calls.extend(selected)
        assert selected==['d0002']
        assert (out/'formula_cache/d0001.json').exists() and not (out/'formula_cache/d0002.json').exists()
        write_json(out/'formula_cache/d0002.json',[{'latex':'E=mc^2','status':'unverified'}])
    monkeypatch.setattr(pipeline,'run_formula',recognize)
    def forbidden(*args,**kwargs):raise AssertionError('Video slide recognition was invoked')
    for name in ('extract_video','recognize','compact_visuals','regroup_existing'):monkeypatch.setattr(pipeline,name,forbidden)
    pipeline.run_job(job['id']);assert calls==['d0002']
    out=tmp_path/'outputs'/job['id'];pages=read_json(out/'visuals.json')
    assert pages[0]['ocr']=='Plain introduction' and pages[1]['formulas'][0]['latex']=='E=mc^2'
    assert read_json(out/'handout.json')['recognized_page_ids']==['d0002']


def test_all_pages_fallback_does_not_reuse_native_only_cache(tmp_path):
    path=make_pdf(tmp_path/'all.pdf',['Ordinary text'])
    output=tmp_path/'out';output.mkdir()
    pages=handouts.import_handout(path,output,[[0,60]],lambda *_:None,lambda:None,'all')
    assert pages[0]['needs_document_recognition']
    assert not (output/'formula_cache/d0001.json').exists()


def test_native_formula_is_preserved_when_recognition_adds_candidates(tmp_path):
    from lecture_notes.common import write_json
    native={'latex':r'\frac{a}{b}','status':'native'}
    page={'id':'d1','document_page':1,'ocr':'Native text','native_text':'Native text','native_formulas':[native]}
    write_json(tmp_path/'formula_cache/d1.json',[{'latex':r'\frac{ a }{b}','status':'unverified'},{'latex':'x^2','status':'unverified'}])
    result=pipeline.attach_formulas([page],tmp_path)
    assert [f['latex'] for f in result[0]['formulas']]==[r'\frac{a}{b}','x^2']
    assert result[0]['formulas'][0]['status']=='native'
