"""Recognize document text and formulas in the isolated Paddle environment."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
os.environ.setdefault('PADDLE_PDX_MODEL_SOURCE', 'modelscope')
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('MKL_NUM_THREADS', '2')


def main():
    from .document_model import configure_libraries
    dll_handles = configure_libraries()
    from .resources import gpu_slot,inference_device,wait_for_gpu_memory
    from .store import TaskStopped
    output=Path(sys.argv[1]).resolve()
    def check():
        if (output/'formula.stop').exists():raise TaskStopped('paused')
    try:
        with gpu_slot(check,lambda:(output/'formula.waiting').touch()):
            if inference_device()!='cpu':
                wait_for_gpu_memory(check,lambda message:(output/'formula.waiting').touch())
            (output/'formula.waiting').unlink(missing_ok=True)
            recognize_pages(output,check,screen='--screen' in sys.argv)
    except TaskStopped:return


def recognize_pages(output,check,screen=False):
    from .resources import cpu_threads,inference_device
    import paddle
    from .document_model import create_document_pipeline,DOCUMENT_MODEL
    from .formula_targets import formula_targets
    from .common import read_json,write_json
    from .timing import Timings
    timing=Timings(output,'screening' if screen else 'formula')
    import hashlib
    visuals = read_json(output/'visuals.json',[]) if screen else formula_targets(output)
    check()
    device = 'gpu:0' if inference_device()=='cuda' and paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() else 'cpu'
    print(json.dumps({'formula_device':device}),flush=True)
    runtime={'device':device,'paddle_version':paddle.__version__,'model':DOCUMENT_MODEL,
             'batch_size':1,'cpu_threads':cpu_threads(),'backend':'native','computed_pages':0,'cached_pages':0}
    if device.startswith('gpu'):
        runtime['allocator_limit_mib']=6656
    runtime_path=output/('screening_runtime.json' if screen else 'formula_runtime.json')
    write_json(runtime_path,runtime)
    pipeline = timing.call('model_load',create_document_pipeline,device,cpu_threads())
    model=getattr(getattr(pipeline,'paddlex_pipeline',None),'vl_rec_model',None)
    runtime['precision']=getattr(model,'dtype',None)
    cache = output/('screening_cache' if screen else 'formula_cache')
    cache.mkdir(exist_ok=True)
    try:
        for index, visual in enumerate(visuals):
            work_start=time.monotonic()
            dest = cache/f"{visual['id']}.json"
            check()
            if not screen and dest.exists():
                runtime['cached_pages']+=1
                continue  # Preserve completed recognition and manual corrections.
            image=output/visual['image']
            image_hash=hashlib.sha256(image.read_bytes()).hexdigest()
            if screen:
                saved=read_json(dest,{})
                if saved.get('image_sha256')==image_hash and saved.get('model')==DOCUMENT_MODEL and saved.get('version')==1:
                    runtime['cached_pages']+=1;continue
                shared=cache/(image_hash+'.json')
                saved=read_json(shared,{})
                if saved.get('model')==DOCUMENT_MODEL and saved.get('version')==1 and saved.get('image_sha256')==image_hash:
                    timing.call('file_write',write_json,dest,saved);runtime['cached_pages']+=1;continue
                with timing.measure('screening'):
                    pages=list(pipeline.predict(str(image),max_new_tokens=512))
                if len(pages)!=1:raise RuntimeError('课件筛选未返回唯一页面，未保存为完成')
                blocks=pages[0].json['res']['parsing_res_list']
                # Screening signatures are never used as recognized note formulas.
                saved={'version':1,'model':DOCUMENT_MODEL,'image_sha256':image_hash,
                    'text':'\n'.join(b.get('block_content','') for b in blocks)[:6000],
                    'labels':[b.get('block_label','') for b in blocks],'purpose':'grouping_only'}
                del pages
                timing.call('file_write',write_json,shared,saved)
                timing.call('file_write',write_json,dest,saved)
                runtime['computed_pages']+=1
                if device.startswith('gpu'):
                    paddle.device.synchronize();paddle.device.cuda.empty_cache()
                from .resources import cooldown
                with timing.measure('cooldown'):cooldown(work_start,check)
                continue
            document_path=output/'document_cache'/f"{visual['id']}.json"
            document=read_json(document_path,{})
            if document.get('model')!=DOCUMENT_MODEL or document.get('image_sha256')!=image_hash:
                with timing.measure('recognition'):
                    pages=list(pipeline.predict(str(image),max_new_tokens=4096))
                if len(pages)!=1:raise RuntimeError('课件识别未返回唯一页面，未保存为完成')
                document=parse_document(pages[0].json['res'])
                del pages
                document.update(model=DOCUMENT_MODEL,image_sha256=image_hash)
                timing.call('file_write',write_json,document_path,document)
                runtime['computed_pages']+=1
            timing.call('file_write',write_json,dest,document['formulas'])
            if device.startswith('gpu'):
                paddle.device.synchronize()
                paddle.device.cuda.empty_cache()
            print(json.dumps({'completed':index+1,'total':len(visuals),'visual_id':visual['id'],
                              'formulas':len(document['formulas'])}),flush=True)
            from .resources import cooldown
            with timing.measure('cooldown'):cooldown(work_start,check)
        runtime['completed']=True
        if device.startswith('gpu'):
            runtime['peak_allocated_mib']=paddle.device.cuda.max_memory_allocated()/1024**2
            runtime['peak_reserved_mib']=paddle.device.cuda.max_memory_reserved()/1024**2
        write_json(runtime_path,runtime)
        write_json(output/('screening_complete.json' if screen else 'formula_complete.json'),{'completed':True,'model':DOCUMENT_MODEL})
    finally:
        pipeline.close()


def parse_document(result):
    import re
    from .common import math_markdown
    from .document_model import DOCUMENT_MODEL
    blocks=result['parsing_res_list']
    text=[];lines=[];formulas=[]
    ignored={'chart','seal','header','header_image','footer','footer_image','number','formula_number'}
    for block in blocks:
        label=block['block_label'];content=block['block_content'].strip();box=block['block_bbox']
        if not content or label in ignored:continue
        if 'formula' in label:
            latex=content
            for left,right in [('$$','$$'),('\\[','\\]'),('\\(','\\)'),('$','$')]:
                if latex.startswith(left) and latex.endswith(right):
                    latex=latex[len(left):-len(right)].strip();break
            if latex:
                formulas.append({'latex':latex,'box':box,'status':'unverified',
                                 'flags':['needs_visual_check'],'model':DOCUMENT_MODEL})
        else:
            text.append(content)
            lines.append({'text':content,'box':[[box[0],box[1]],[box[2],box[1]],
                          [box[2],box[3]],[box[0],box[3]]],'model':DOCUMENT_MODEL})
            for match in re.finditer(r'\$\$([\s\S]*?)\$\$|\$([^$\n]+)\$',math_markdown(content)):
                latex=(match[1] if match[1] is not None else match[2]).strip()
                if latex:
                    formulas.append({'latex':latex,'box':box,'status':'unverified',
                        'flags':['needs_visual_check','embedded_math'],'model':DOCUMENT_MODEL})
    return {'text':'\n'.join(text),'lines':lines,'blocks':blocks,'formulas':formulas}


if __name__ == '__main__':
    main()
