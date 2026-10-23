"""Local document model shared by preparation and the isolated worker."""
from pathlib import Path
from .runtime import site_packages

DOCUMENT_MODEL = 'PaddleOCR-VL-1.6'
MODEL_DIR = Path(__file__).resolve().parents[1]/'models'/DOCUMENT_MODEL


def models_ready():
    from .common import read_json
    receipt=read_json(MODEL_DIR/'PROVENANCE.json',{})
    return bool(receipt.get('files')) and all((MODEL_DIR/r['Path']).is_file() and
        (MODEL_DIR/r['Path']).stat().st_size==r['Size'] for r in receipt['files'])


def create_document_pipeline(device, threads):
    from paddleocr import PaddleOCRVL
    from paddlex.inference import load_pipeline_config
    config = load_pipeline_config(DOCUMENT_MODEL)
    config['batch_size'] = 1
    config['layout_prep_cpu_workers'] = threads
    for name in ('LayoutDetection', 'VLRecognition'):
        config['SubModules'][name]['batch_size'] = 1
    if not models_ready():raise RuntimeError('课件模型未就绪，请运行 scripts/prepare_document.py')
    config['SubModules']['VLRecognition']['model_dir']=str(MODEL_DIR)
    layout = MODEL_DIR.parent/'PP-DocLayoutV3'
    if (layout/'inference.pdiparams').is_file():
        config['SubModules']['LayoutDetection']['model_dir']=str(layout)
    return PaddleOCRVL(pipeline_version='v1.6', paddlex_config=config,
        device=device, cpu_threads=threads, enable_mkldnn=False,
        vl_rec_backend='native', use_queues=False,
        use_ocr_for_image_block=True,
        use_doc_orientation_classify=False, use_doc_unwarping=False)


def configure_libraries():
    import os
    # Set before importing Paddle. This bounds its allocator, not all CUDA/driver memory.
    os.environ['FLAGS_allocator_strategy']='auto_growth'
    os.environ['FLAGS_gpu_memory_limit_mb']='6656'
    os.environ['FLAGS_auto_growth_chunk_size_in_mb']='32'
    os.environ['FLAGS_free_when_no_cache_hit']='True'
    root = Path(__file__).resolve().parents[1]
    handles = []
    directories = {p.parent for role in ('core', 'document')
                   for p in (site_packages(role)/'nvidia').rglob('*.dll')}
    for directory in sorted(directories):
        os.environ['PATH'] = str(directory)+os.pathsep+os.environ.get('PATH', '')
        if hasattr(os, 'add_dll_directory'):
            handles.append(os.add_dll_directory(str(directory)))
    return handles
