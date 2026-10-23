"""Fetch official detector releases and verify pinned checksums."""
import hashlib,json,urllib.request
from pathlib import Path

root=Path(__file__).resolve().parents[1]/'models'
root.mkdir(exist_ok=True)
models={'yolox_tiny':'427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7'}
for name,expected in models.items():
 target=root/(name+'.onnx')
 url='https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/'+target.name
 if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=expected:
  temporary=target.with_suffix('.onnx.part');urllib.request.urlretrieve(url,temporary)
  if hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected:raise RuntimeError('人物模型校验失败')
  temporary.replace(target)
 (root/(name+'.provenance.json')).write_text(json.dumps({'source':url,'sha256':expected,'bytes':target.stat().st_size,'license':'Apache-2.0'},indent=2),encoding='utf-8')
if not (root/'YOLOX-LICENSE.txt').exists():urllib.request.urlretrieve('https://raw.githubusercontent.com/Megvii-BaseDetection/YOLOX/main/LICENSE',root/'YOLOX-LICENSE.txt')
print('本地人物模型已准备并校验')
