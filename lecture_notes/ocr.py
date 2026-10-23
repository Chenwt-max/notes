from __future__ import annotations

from pathlib import Path
import time

import cv2
import numpy as np

from .common import read_json, write_json, digest
from .resources import cpu_threads,inference_device


def recognize(visuals, output, callback, check):
    from .asr import cuda_libraries
    if inference_device()=='cuda':cuda_libraries()
    import onnxruntime as ort
    from rapidocr import RapidOCR
    gpu = inference_device()=='cuda' and 'CUDAExecutionProvider' in ort.get_available_providers()
    engine = RapidOCR(params={'Global.log_level': 'error', 'EngineConfig.onnxruntime.intra_op_num_threads': cpu_threads(),
                             'EngineConfig.onnxruntime.use_cuda':gpu})
    output = Path(output)
    cache = output/'ocr_cache'
    cache.mkdir(exist_ok=True)
    for index, item in enumerate(visuals):
        work_start=time.monotonic()
        check()
        image_path = output/item['image']
        key = digest({'image': image_path.name, 'size': image_path.stat().st_size, 'version': 'rapidocr-3.10'})
        result = read_json(cache/f'{key}.json')
        if result is None:
            image = cv2.imdecode(np.fromfile(str(image_path), np.uint8), cv2.IMREAD_COLOR)
            recognized = engine(image)
            if not (output/'ocr_runtime.json').exists():
                providers = {name:getattr(engine,name).session.session.get_providers() for name in ['text_det','text_cls','text_rec'] if getattr(engine,name,None) is not None}
                write_json(output/'ocr_runtime.json',{'requested_gpu':gpu,'providers':providers})
            texts = list(recognized.txts) if recognized.txts is not None else []
            scores = list(recognized.scores) if recognized.scores is not None else []
            result = {'text': '\n'.join(texts), 'lines': [
                {'text': str(t), 'score': float(s), 'box': np.asarray(b).tolist()}
                for t, s, b in zip(texts, scores, recognized.boxes if recognized.boxes is not None else [])]}
            write_json(cache/f'{key}.json', result)
        item['ocr'], item['ocr_lines'] = result['text'], result['lines']
        callback((index+1)/max(1, len(visuals)), f'课件文字 {index+1}/{len(visuals)}')
        if index % 10 == 0:
            write_json(output/'visuals.json', visuals)
        from .resources import cooldown
        cooldown(work_start,check)
    write_json(output/'visuals.json', visuals)
    return visuals
