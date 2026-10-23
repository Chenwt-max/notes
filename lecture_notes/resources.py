"""Bound sustained inference load without changing model outputs."""
import os
import time
import errno
import subprocess
from contextlib import contextmanager
from .common import DATA,read_json


def gpu_memory():
    """Query the same physical GPU 0 used by the inference workers, in MiB."""
    try:
        result=subprocess.run(['nvidia-smi','--id=0','--query-gpu=memory.total,memory.free',
            '--format=csv,noheader,nounits'],capture_output=True,text=True,check=True,timeout=5,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        total,free=(int(x.strip()) for x in result.stdout.strip().split(','))
        if total>0 and 0<=free<=total:return total,free
    except (OSError,ValueError,subprocess.SubprocessError):pass
    return None


def wait_for_gpu_memory(check=lambda:None,waiting=lambda message:None):
    """Leave headroom before loading either heavy model; never shrink its input."""
    while True:
        check()
        memory=gpu_memory()
        if memory is None:raise RuntimeError('无法读取显卡显存，未加载大模型；请检查NVIDIA驱动或选择CPU')
        total,free=memory
        if total<7168:raise RuntimeError('当前显卡不足7GiB，已阻止加载大模型；请在设置中选择CPU')
        if free>=7168:return
        waiting(f'等待可用显存 · 当前{free/1024:.1f}GiB，需要至少7GiB；可关闭其他占用显卡的程序')
        for _ in range(10):
            check();time.sleep(.2)


def cpu_threads():
    return max(1,min(os.cpu_count() or 1,int(os.environ.get('LECTURE_CPU_THREADS','2'))))


def inference_device():
    return os.environ.get('LECTURE_INFERENCE_DEVICE','cuda')


def duty_cycle():
    return {'fast':1.0,'balanced':.8,'listening':.5}.get(os.environ.get('LECTURE_PROCESSING_MODE','balanced'),.8)


def cooldown(start,check=lambda:None):
    deadline=time.monotonic()+max(0,time.monotonic()-start)*(1/duty_cycle()-1)
    while time.monotonic()<deadline:
        check()
        time.sleep(min(.2,max(0,deadline-time.monotonic())))


def configure(mode='balanced',threads=2,device='cuda'):
    os.environ['LECTURE_PROCESSING_MODE']=mode
    os.environ['LECTURE_CPU_THREADS']=str(threads)
    os.environ['LECTURE_INFERENCE_DEVICE']=device
    for name in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']:
        os.environ[name]=str(cpu_threads())
    import cv2
    cv2.setNumThreads(cpu_threads())


@contextmanager
def gpu_slot(check=lambda:None,waiting=lambda:None):
    """Hold an OS-owned slot for the model's entire lifetime, including loading.

    Locks are released by the OS after a crash; no stale lease database remains.
    Each slot budgets 8GiB for a heavy model. User concurrency is an upper
    bound, including when set to unlimited; unavailable telemetry stays serial.
    """
    if inference_device()=='cpu':
        yield;return
    memory=gpu_memory()
    safe_limit=max(1,memory[0]//8192) if memory else 1
    folder=DATA/'gpu-slots';folder.mkdir(parents=True,exist_ok=True)
    held=None;announced=False
    while held is None:
        check()
        limit=read_json(DATA/'settings.json',{}).get('gpu_concurrency',1)
        limit=min(limit,safe_limit) if limit else safe_limit
        for index in range(limit):
            handle=(folder/f'{index}.lock').open('a+b',buffering=0)
            if handle.seek(0,2)==0:handle.write(b'0')
            handle.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc:
                handle.close()
                if exc.errno not in {errno.EACCES,errno.EAGAIN}:raise
            else:
                held=handle;break
        if held is None:
            if not announced:waiting();announced=True
            time.sleep(.2)
    try:
        yield
    finally:
        held.seek(0)
        if os.name=='nt':msvcrt.locking(held.fileno(),msvcrt.LK_UNLCK,1)
        else:fcntl.flock(held.fileno(),fcntl.LOCK_UN)
        held.close()
