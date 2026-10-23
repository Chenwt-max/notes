"""Reconstruct standalone CPython trees from verified archives and locked installed packages.

No venv executable, pyvenv.cfg, user settings, course file or model cache is copied.
The input installations are build dependencies; the resulting Python homes are independent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def copy_tree(source,target):
    files=[]
    for folder,dirs,names in __import__('os').walk(source):
        dirs[:]=[d for d in dirs if d!='__pycache__']
        dest=target/Path(folder).relative_to(source)
        dest.mkdir(parents=True,exist_ok=True)
        for name in names:
            if name.endswith(('.pyc','.pyo')):continue
            src=Path(folder)/name;out=dest/name
            if out.is_file() and (src.stat().st_size,src.stat().st_mtime_ns)==(out.stat().st_size,out.stat().st_mtime_ns):continue
            files.append((src,out))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda pair:shutil.copy2(*pair),files))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();target=args.destination.resolve()
    if not target.is_relative_to(ROOT/'dist-release'):raise ValueError('候选输出必须位于 dist-release 中')
    target.mkdir(parents=True,exist_ok=True)
    receipts=json.loads((ROOT/'scripts/runtime-downloads.json').read_text(encoding='utf-8'))
    archives={}
    for name,row in receipts.items():
        path=ROOT/'dist-release/downloads'/row['file']
        if not path.is_file():
            import urllib.request
            path.parent.mkdir(parents=True,exist_ok=True)
            part=path.with_suffix(path.suffix+'.part')
            urllib.request.urlretrieve(row['url'],part)
            if sha(part)!=row['sha256']:raise ValueError('下载的运行时校验失败：'+name)
            part.replace(path)
        if sha(path)!=row['sha256']:raise ValueError('运行时校验失败：'+name)
        archives[name]=path
    runtime=target/'runtime';runtime.mkdir(exist_ok=True)
    for role,env in [('core','.venv'),('asr','.venv-asr'),('document','.venv-formula')]:
        home=runtime/role;home.mkdir(exist_ok=True)
        with zipfile.ZipFile(archives['python']) as z:
            for entry in z.infolist():
                if entry.filename.startswith('tools/') and not entry.is_dir():
                    rel=Path(entry.filename).relative_to('tools');dest=home/rel
                    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(entry))
        copy_tree(ROOT/env/'Lib/site-packages',home/'Lib/site-packages')
        # Keep import paths relative. Build-time console launchers are intentionally excluded.
        for p in (home/'Lib/site-packages').glob('*.pth'):
            for line in p.read_text(encoding='utf-8').splitlines():
                if line and not line.startswith(('#','import ')) and Path(line).is_absolute():
                    raise ValueError('依赖包含不可迁移的路径：'+p.name)
        print('runtime copied',role,flush=True)
    # Match the developer's selected ONNX GPU runtime, without CPU/GPU package overlap.
    core=runtime/'core/Lib/site-packages'
    for name in ['onnxruntime',*[p.name for p in core.glob('onnxruntime-*.dist-info')]]:
        path=core/name
        if path.is_dir():shutil.rmtree(path)
    copy_tree(ROOT/'models/ortgpu12',core)
    tools=runtime/'tools';tools.mkdir(exist_ok=True)
    licenses=target/'licenses';licenses.mkdir(exist_ok=True)
    from portable_crt import install_local,enable_utf8_manifest
    crt=install_local(archives['vc_runtime'],ROOT/'dist-release/downloads/crt-extracted',target)
    for role in ('core','asr','document'):
        for name in ('python.exe','pythonw.exe'):enable_utf8_manifest(runtime/role/name)
    (licenses/'Microsoft-VC-files.json').write_text(json.dumps(crt,indent=2),encoding='utf-8')
    (licenses/'ffmpeg').mkdir(exist_ok=True)
    for name in ('ffmpeg_source','ffmpeg_recipes'):shutil.copy2(archives[name],licenses/'ffmpeg'/archives[name].name)
    for name in ('node','ffmpeg'):
        with zipfile.ZipFile(archives[name]) as z:
            for entry in z.infolist():
                if entry.is_dir():continue
                p=Path(entry.filename)
                if (name=='node' and p.name=='node.exe') or (name=='ffmpeg' and 'bin' in p.parts):
                    (tools/p.name).write_bytes(z.read(entry))
                elif any(token in p.name.lower() for token in ('license','copying','notice','readme')):
                    dest=licenses/name/p.name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(entry))
    copy_tree(ROOT/'frontend/node_modules/katex',target/'frontend/node_modules/katex')
    copy_tree(ROOT/'frontend/node_modules/markdown-it/dist',target/'frontend/node_modules/markdown-it/dist')
    shutil.copy2(ROOT/'frontend/node_modules/markdown-it/LICENSE',licenses/'markdown-it-LICENSE.txt')
    locks={}
    for role in ('core','asr','document'):
        python=runtime/role/'python.exe'
        result=subprocess.run([str(python),'-I','-c',
            'import importlib.metadata as m,json;print(json.dumps(sorted({d.metadata["Name"]:d.version for d in m.distributions()}.items())))'],
            capture_output=True,check=True,text=True,encoding='utf-8')
        locks[role]=dict(json.loads(result.stdout))
    (target/'runtime-locks.json').write_text(json.dumps(locks,indent=2),encoding='utf-8')
    (target/'portable.json').write_text(json.dumps({'version':'1.0.0-rc.1','runtime_downloads':receipts},indent=2),encoding='utf-8')
    print('Independent runtime trees reconstructed:',target,flush=True)


if __name__=='__main__':main()
