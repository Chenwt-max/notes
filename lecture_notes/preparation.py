"""Pinned, resumable model preparation. Readiness is a verified receipt, never a download flag."""
from __future__ import annotations

import hashlib
import threading
import time

import httpx

from .common import ROOT,DATA,read_json,write_json,safe_child,digest
from .runtime import PORTABLE

LOCK = threading.Lock()
CANCEL = threading.Event()
THREAD = None


def manifest():
    return read_json(ROOT/'scripts/model-manifest.json')


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def asset_path(row):
    relative=row['path']
    if not PORTABLE and row.get('bundled'):
        for role,env in [('core','.venv'),('asr','.venv-asr'),('document','.venv-formula')]:
            relative=relative.replace('runtime/'+role+'/',env+'/',1)
    return safe_child(ROOT,relative)


def signature(rows):
    result = []
    for row in rows:
        path = asset_path(row)
        if not path.is_file():return None
        stat = path.stat()
        if stat.st_size != row['size']:return None
        result.append([row['path'],stat.st_size,stat.st_mtime_ns])
    return result


def state():
    pinned = manifest()
    rows = pinned['files']
    saved = read_json(DATA/'preparation.json',{})
    receipt = read_json(DATA/'models-verified.json',{})
    ready = receipt.get('manifest_hash') == digest(pinned) and receipt.get('signature') == signature(rows)
    running = bool(THREAD and THREAD.is_alive())
    status = 'ready' if ready else saved.get('status','required')
    if status == 'ready' and not ready:status = 'required'
    if status in {'downloading','verifying'} and not running:status = 'interrupted'
    return {**saved,'status':status,'ready':ready,'running':running,'portable':PORTABLE,
            'total_bytes':sum(r['size'] for r in rows),'models':list(dict.fromkeys(r['model'] for r in rows)),
            'message':saved.get('message','首次使用前下载并校验本地模型。下载可取消，重新开始会续传。')}


def download(row,check,progress):
    path = asset_path(row)
    path.parent.mkdir(parents=True,exist_ok=True)
    check()
    if path.is_file() and path.stat().st_size == row['size'] and file_hash(path) == row['sha256']:
        progress(row['size'])
        return
    part = path.with_name(path.name+'.part')
    offset = part.stat().st_size if part.exists() else 0
    if offset > row['size']:part.unlink();offset=0
    if offset < row['size']:
        params = {'Revision':row['revision'],'FilePath':row['remote_path']} if row.get('repo') else None
        with httpx.Client(timeout=httpx.Timeout(60,connect=25),follow_redirects=True) as client:
            with client.stream('GET',row['url'],params=params,headers={'Range':f'bytes={offset}-'}) as response:
                response.raise_for_status()
                if response.status_code == 206:
                    expected = f"bytes {offset}-{row['size']-1}/{row['size']}"
                    if response.headers.get('Content-Range') != expected:raise ValueError('下载服务器的续传范围不正确')
                elif response.status_code == 200:
                    offset=0
                else:raise ValueError('下载响应无效')
                with part.open('ab' if offset else 'wb') as stream:
                    for block in response.iter_bytes(1024*1024):
                        check()
                        if offset+len(block)>row['size']:raise ValueError('下载文件超出清单大小')
                        stream.write(block);offset+=len(block);progress(offset)
    check()
    if part.stat().st_size != row['size'] or file_hash(part) != row['sha256']:
        part.unlink(missing_ok=True)
        raise ValueError('模型 SHA-256 校验失败，请重新下载该文件')
    part.replace(path)
    progress(row['size'])


def prepare():
    pinned=manifest();rows=pinned['files'];completed=0;last=[0.]
    def save(status,message,**fields):
        write_json(DATA/'preparation.json',{'status':status,'message':message,'completed_bytes':completed,**fields})
    def check():
        if CANCEL.is_set():raise InterruptedError('下载已取消；已下载片段保留，可继续')
    try:
        for index,row in enumerate(rows):
            check()
            save('downloading',row['model'],file=row['path'],file_index=index+1,file_count=len(rows))
            def progress(amount):
                now=time.monotonic()
                if now-last[0]>.4 or amount==row['size']:
                    last[0]=now
                    save('downloading',row['model'],completed_bytes=completed+amount,file=row['path'],file_index=index+1,file_count=len(rows))
            download(row,check,progress)
            completed+=row['size']
        save('verifying','正在核对全部模型')
        for row in rows:
            check()
            if file_hash(asset_path(row)) != row['sha256']:raise ValueError('完整性核验失败：'+row['model'])
        for model in dict.fromkeys(r['model'] for r in rows if r.get('repo')):
            selected=[r for r in rows if r['model']==model]
            write_json(ROOT/'models'/model/'PROVENANCE.json',{'repo':selected[0]['repo'],'files':[
                {'Path':r['remote_path'],'Revision':r['revision'],'Size':r['size'],'Sha256':r['sha256']} for r in selected]})
        write_json(DATA/'models-verified.json',{'manifest_hash':digest(pinned),'signature':signature(rows)})
        save('ready','全部模型下载与 SHA-256 核验通过')
    except InterruptedError as exc:save('cancelled',str(exc))
    except (OSError,ValueError,httpx.HTTPError) as exc:
        save('failed','准备未完成，已保留断点：'+str(exc)[:240])


def control(action):
    global THREAD
    with LOCK:
        if action=='cancel':CANCEL.set()
        elif action=='start':
            if THREAD and THREAD.is_alive():return state()
            CANCEL.clear()
            THREAD=threading.Thread(target=prepare,daemon=True)
            THREAD.start()
        else:raise ValueError('未知模型准备操作')
    return state()
