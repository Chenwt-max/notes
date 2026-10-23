"""Independent course workers; one failure or pause does not block other courses."""
import os
import sys
import time
import subprocess
from .common import ROOT,OUTPUT
from .settings import settings
from .store import list_jobs,get_job,update_job,claim_job
from .deletion import finish_delete


def terminate_tree(process):
    if process.poll() is not None:return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
    else:process.terminate()
    process.wait(timeout=15)


def tick(active):
    for job_id,(process,log) in list(active.items()):
        if get_job(job_id)['status']=='delete_requested':
            try:terminate_tree(process)
            except (OSError,subprocess.SubprocessError) as exc:
                update_job(job_id,status='delete_failed',stage='停止未完成',error=str(exc),message='尚未删除文件，请点击垃圾箱重试')
                continue
            log.close();del active[job_id]
            continue
        if process.poll() is None:continue
        log.close();del active[job_id]
        if get_job(job_id)['status'] in {'running','starting','pause_requested','cancel_requested'}:
            update_job(job_id,status='needs_attention',error='处理进程提前退出，请查看 worker.log',message='已保留中间成果')
    for job in list_jobs():
        if job['status']=='delete_requested' and job['id'] not in active:finish_delete(job['id'])
    config=settings(True);limit=config['max_concurrent_jobs']
    for job in reversed(list_jobs()):
        if limit and len(active)>=limit:break
        if job['status']!='queued' or job['id'] in active or not claim_job(job['id']):continue
        output=OUTPUT/job['id'];output.mkdir(parents=True,exist_ok=True)
        log=(output/'worker.log').open('a',encoding='utf-8')
        try:
            process=subprocess.Popen([sys.executable,'-X','utf8','-m','lecture_notes.worker',job['id']],
                cwd=ROOT,env={**os.environ,'PYTHONUTF8':'1','LECTURE_API_KEY':config['api_key']},
                stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except OSError as exc:
            log.close();update_job(job['id'],status='needs_attention',error=str(exc),message='启动失败，其他课程继续处理')
        else:active[job['id']]=(process,log)


def shutdown(active,timeout=20):
    for job_id in active:
        if get_job(job_id)['status'] in {'running','starting'}:update_job(job_id,status='pause_requested')
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline and any(p.poll() is None for p,_ in active.values()):time.sleep(.1)
    for job_id,(process,log) in active.items():
        terminate_tree(process);log.close()
        if get_job(job_id)['status'] in {'running','starting','pause_requested','cancel_requested'}:
            update_job(job_id,status='paused',message='应用已关闭，完成的分段可继续')


def scheduler(stop):
    active={}
    try:
        while not stop.wait(.5):tick(active)
    finally:shutdown(active)
