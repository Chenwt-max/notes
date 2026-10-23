"""Allowlisted public source and portable artifacts; never publish a working directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RELEASE=ROOT/'dist-release'
CODE_DIRS=['lecture_notes','frontend/src','frontend/public','tests','docs','.github']
FILES=['LICENSE','README.md','THIRD_PARTY_NOTICES.md','.gitignore',
       'requirements.txt','requirements-asr.txt','requirements-formula.txt',
       'requirements-lock.txt','requirements-asr-lock.txt','requirements-formula-lock.txt',
       'frontend/package.json','frontend/package-lock.json','frontend/index.html','frontend/vite.config.ts','frontend/tsconfig.json',
       'notes.cmd','停止 notes.cmd','重启 notes.cmd','安装环境.ps1',
       'scripts/start-app.ps1','scripts/stop-app.ps1','scripts/create-desktop-shortcut.ps1',
       'scripts/render-presentation.ps1',
       'scripts/notes-desktop-mint-20261021.ico','scripts/prepare_asr.py','scripts/prepare_document.py','scripts/prepare_person.py',
       'scripts/启用显卡加速.ps1',
       'scripts/asr-models.json','scripts/document-model.json','scripts/model-manifest.json','scripts/runtime-downloads.json',
       'scripts/build_portable.py','scripts/package_release.py','scripts/portable_crt.py','scripts/merge-release.ps1']


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def source_files():
    for folder in CODE_DIRS:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and not any(x in p.parts for x in ['__pycache__','node_modules','.pytest_cache']) and p.suffix!='.pyc' and not (folder=='tests' and p.suffix=='.cjs'):
                yield p
    for relative in FILES:
        p=ROOT/relative
        if p.is_file():yield p


def scan(paths):
    # Print filenames only, never credential contents.
    for path in paths:
        if path.suffix.lower() in {'.py','.ts','.tsx','.js','.mjs','.json','.md','.txt','.yml','.ps1','.cmd','.html'}:
            text=path.read_text(encoding='utf-8-sig')
            if re.search(r'\bsk-[A-Za-z0-9_-]{20,}',text):raise ValueError('发现疑似密钥：'+str(path.relative_to(ROOT)))
            if re.search(r'D:[/\\]study[/\\](?:outputs|[123]\.mp4)',text,re.I):
                raise ValueError('发现私有课程路径或标识：'+str(path.relative_to(ROOT)))


def sync_source(portable):
    public=RELEASE/'notes-source-rc1';public.mkdir(parents=True,exist_ok=True)
    paths=sorted(set(source_files()))
    scan(paths)
    for path in paths:
        relative=path.relative_to(ROOT)
        for destroot in [public,portable]:
            dest=destroot/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
    built=portable/'frontend/dist'
    if built.resolve().is_relative_to(portable.resolve()) is False:
        raise ValueError('前端输出目录不在候选目录内')
    current={p.relative_to(ROOT/'frontend/dist') for p in (ROOT/'frontend/dist').rglob('*') if p.is_file()}
    for old in built.rglob('*'):
        if old.is_file() and old.relative_to(built) not in current:old.unlink()
    shutil.copytree(ROOT/'frontend/dist',built,dirs_exist_ok=True)
    return public


def archive(root,dest,allowlist=None):
    entries=[]
    with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as bundle:
        for p in sorted(root.rglob('*')):
            parts=p.relative_to(root).parts
            if not p.is_file() or parts[0] in {'data','outputs','models','cache','qa','.env','.git'} or '__pycache__' in parts:continue
            relative=p.relative_to(root).as_posix()
            if allowlist is not None and relative not in allowlist:continue
            entries.append({'path':relative,'bytes':p.stat().st_size,'sha256':sha(p)})
            bundle.write(p,root.name+'/'+relative)
    return entries


def split(path,maximum=int(1.8*1024**3)):
    parts=[]
    with path.open('rb') as stream:
        index=1
        while True:
            remaining=maximum;part=path.with_name(path.name+f'.part{index:03d}')
            with part.open('wb') as output:
                while remaining:
                    block=stream.read(min(8*1024**2,remaining))
                    if not block:break
                    output.write(block);remaining-=len(block)
            if part.stat().st_size==0:part.unlink();break
            parts.append({'file':part.name,'bytes':part.stat().st_size,'sha256':sha(part)});index+=1
    return parts


def validate_portable(root):
    required=['portable.json','runtime-locks.json','frontend/dist/index.html',
              *[f'runtime/{role}/python.exe' for role in ('core','asr','document')],
              *[f'runtime/tools/{name}.exe' for name in ('node','ffmpeg','ffprobe')]]
    missing=[name for name in required if not (root/name).is_file()]
    if missing:raise ValueError('便携候选未完整构建：'+', '.join(missing))


def main():
    p=argparse.ArgumentParser();p.add_argument('--sync-only',action='store_true');args=p.parse_args()
    portable=RELEASE/'notes-portable-rc1'
    validate_portable(portable)
    public=sync_source(portable)
    if args.sync_only:return
    result={}
    for name,root in [('source',public),('portable',portable)]:
        path=RELEASE/f'notes-{name}-1.0.0-rc.1.zip'
        allowlist={p.relative_to(ROOT).as_posix() for p in source_files()} if name=='source' else None
        entries=archive(root,path,allowlist)
        (RELEASE/f'{name}-manifest.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
        result[name]={'file':path.name,'bytes':path.stat().st_size,'sha256':sha(path),'files':len(entries)}
        if path.stat().st_size>=int(1.8*1024**3):result[name]['parts']=split(path)
        print(name,result[name]['bytes'],result[name]['files'],flush=True)
    (RELEASE/'release-manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')


if __name__=='__main__':main()
