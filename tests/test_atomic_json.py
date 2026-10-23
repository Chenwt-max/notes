import ctypes
import os
import threading

import pytest

from lecture_notes import common


def test_atomic_write_retries_only_transient_windows_sharing_errors(tmp_path,monkeypatch):
    path=tmp_path/'progress.json';common.write_json(path,{'old':True})
    replace=common.os.replace;attempts=[];sleeps=[]
    def busy_once(source,target):
        attempts.append(1)
        if len(attempts)==1:
            error=PermissionError('Windows sharing violation');error.winerror=5;raise error
        return replace(source,target)
    monkeypatch.setattr(common.os,'replace',busy_once)
    monkeypatch.setattr(common.time,'sleep',sleeps.append)
    common.write_json(path,{'new':'完整进度'})
    assert len(attempts)==2 and sleeps==[.01]
    assert common.read_json(path)=={'new':'完整进度'} and not path.with_suffix('.json.tmp').exists()


def test_atomic_write_preserves_old_file_on_permanent_error_and_bounds_wait(tmp_path,monkeypatch):
    path=tmp_path/'progress.json';common.write_json(path,{'old':True})
    attempts=[];sleeps=[]
    def denied(*args):
        attempts.append(1);error=PermissionError('permission denied');error.winerror=5;raise error
    monkeypatch.setattr(common.os,'replace',denied)
    monkeypatch.setattr(common.time,'sleep',sleeps.append)
    with pytest.raises(PermissionError):common.write_json(path,{'new':True})
    assert len(attempts)==8 and sum(sleeps)<1 and common.read_json(path)=={'old':True}


@pytest.mark.skipif(os.name!='nt',reason='Requires real Windows sharing semantics')
def test_atomic_write_survives_real_windows_reader_without_delete_sharing(tmp_path):
    from ctypes import wintypes
    path=tmp_path/'progress.json';common.write_json(path,{'old':True})
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                                wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0,None)
    assert handle!=wintypes.HANDLE(-1).value,ctypes.get_last_error()
    release=threading.Timer(.06,lambda:kernel.CloseHandle(handle));release.start()
    try:common.write_json(path,{'new':'读写同时进行'})
    finally:release.join()
    assert common.read_json(path)=={'new':'读写同时进行'}


def test_progress_journal_can_append_while_reader_is_open_and_ignores_partial_line(tmp_path):
    from lecture_notes.asr import append_progress,read_progress
    append_progress(tmp_path,.3,'读取检查点')
    path=tmp_path/'asr_progress.jsonl'
    with path.open('rb') as reader:
        append_progress(tmp_path,.4,'下一分钟')
        assert b'\n' in reader.read()
        assert read_progress(tmp_path)=={'progress':.4,'message':'下一分钟'}
    with path.open('ab') as writer:writer.write(b'{"progress":0.5,"message":"')
    assert read_progress(tmp_path)['progress']==.4
