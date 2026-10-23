"""Prepare official local document weights; no video or paid API is used."""
import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
os.environ.setdefault('PADDLE_PDX_MODEL_SOURCE', 'modelscope')
os.environ.setdefault('MODELSCOPE_DOWNLOAD_PARALLELS', '4')
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('MKL_NUM_THREADS', '2')
from lecture_notes.document_model import configure_libraries, create_document_pipeline, DOCUMENT_MODEL
from prepare_asr import download

root=Path(__file__).resolve().parents[1]
receipt=json.loads((root/'scripts/document-model.json').read_text(encoding='utf-8'))
target=root/'models'/DOCUMENT_MODEL
for row in receipt['files']:
    path=(target/row['Path']).resolve()
    if not path.is_relative_to(target.resolve()):raise ValueError('模型路径越界')
    download(path,'https://www.modelscope.cn/api/v1/models/'+receipt['repo']+'/repo',
             {'Revision':row['Revision'],'FilePath':row['Path']},row['Size'],row['Sha256'])
(target/'PROVENANCE.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')

handles = configure_libraries()
import paddle
device = 'gpu:0' if paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() else 'cpu'
pipeline = create_document_pipeline(device, 2)
pipeline.close()
print(DOCUMENT_MODEL+' 已准备：'+device, flush=True)
