from __future__ import annotations

import json
import sqlite3
import time
import uuid
import threading
from collections import defaultdict

from .common import DATA, OUTPUT

JOB_LOCKS=defaultdict(threading.RLock)
DELETING={'delete_requested','delete_failed'}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA/'jobs.sqlite', timeout=30,factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, created REAL, updated REAL, status TEXT, stage TEXT, progress REAL, message TEXT, spec TEXT, error TEXT DEFAULT "")')
    conn.execute('CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY, job_id TEXT, created REAL, status TEXT, reserved REAL, actual REAL, input_tokens INTEGER, output_tokens INTEGER, detail TEXT)')
    conn.commit()
    return conn


def create_job(spec):
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with connect() as db:
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',
                   (job_id, now, now, 'queued', '等待处理', 0., '任务已加入队列', json.dumps(spec, ensure_ascii=False), ''))
    (OUTPUT/job_id).mkdir(parents=True, exist_ok=True)
    return get_job(job_id)


def decode(row):
    if row is None:
        raise KeyError('任务不存在')
    result = dict(row)
    result['spec'] = json.loads(result['spec'])
    return result


def get_job(job_id):
    with connect() as db:
        return decode(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())


def list_jobs():
    with connect() as db:
        return [decode(r) for r in db.execute('SELECT * FROM jobs ORDER BY created DESC')]


def update_job(job_id, **fields):
    allowed = {'status', 'stage', 'progress', 'message', 'error'}
    if not fields.keys() <= allowed:
        raise ValueError('无效任务字段')
    fields['updated'] = time.time()
    with connect() as db:
        condition='' if fields.get('status') in DELETING else ' AND status NOT IN ("delete_requested","delete_failed")'
        db.execute('UPDATE jobs SET '+','.join(f'{key}=?' for key in fields)+' WHERE id=?'+condition, [*fields.values(), job_id])


def request_delete(job_id):
    get_job(job_id)
    update_job(job_id,status='delete_requested',stage='正在删除',error='',message='正在停止任务并清理生成资料，原视频保留')
    return {'id':job_id,'status':'delete_requested'}


def claim_job(job_id):
    with connect() as db:
        return bool(db.execute('UPDATE jobs SET status="starting",updated=?,error="",message="正在启动本地处理" WHERE id=? AND status="queued"',
                               (time.time(),job_id)).rowcount)


def start_job(job_id):
    with connect() as db:
        changed=db.execute('UPDATE jobs SET status="running",updated=?,error="" WHERE id=? AND status IN ("queued","starting")',
                           (time.time(),job_id)).rowcount
    if not changed:
        check_job(job_id)
        raise ValueError('任务已启动，不能重复运行')


class TaskStopped(Exception):
    pass


def check_job(job_id):
    status = get_job(job_id)['status']
    if status in {'pause_requested', 'cancel_requested','paused','cancelled',*DELETING}:
        raise TaskStopped(status)


def usage_for(job_id, include_assistant=True):
    with connect() as db:
        rows = [dict(r) for r in db.execute('SELECT * FROM usage WHERE job_id=? ORDER BY created', (job_id,))]
    if not include_assistant:rows=[r for r in rows if json.loads(r['detail']).get('phase')!='assistant']
    return {'calls': rows, 'spent': sum(r['actual'] if r['actual'] is not None else r['reserved'] for r in rows)}


def reserve(job_id, request_id, amount, limit, detail):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        job=db.execute('SELECT status FROM jobs WHERE id=?',(job_id,)).fetchone()
        if job and job['status'] in DELETING:raise TaskStopped('delete_requested')
        old = db.execute('SELECT status FROM usage WHERE id=?', (request_id,)).fetchone()
        if old:
            raise ValueError('此请求已有调用记录；请查看缓存或核对超时账目')
        if limit is not None:
            rows=db.execute('SELECT actual,reserved,detail FROM usage WHERE job_id=?',(job_id,)).fetchall()
            used=sum(r['actual'] if r['actual'] is not None else r['reserved'] for r in rows if json.loads(r['detail']).get('phase')!='assistant')
            if used+amount > limit+1e-9:
                raise ValueError(f'预算不足：已用/预留 {used:.4f} 元，本次需 {amount:.4f} 元，上限 {limit:.4f} 元')
        db.execute('INSERT INTO usage VALUES(?,?,?,?,?,?,?,?,?)',
                   (request_id, job_id, time.time(), 'reserved', amount, None, 0, 0, json.dumps(detail, ensure_ascii=False)))


def settle(request_id, status, actual=None, input_tokens=0, output_tokens=0):
    with connect() as db:
        db.execute('UPDATE usage SET status=?, actual=?, input_tokens=?, output_tokens=? WHERE id=?',
                   (status, actual, input_tokens, output_tokens, request_id))
