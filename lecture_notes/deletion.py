"""Delete a stopped job's own generated directory, never its source or models."""
import re
import shutil
import stat
from pathlib import Path

from . import store


def output_for_deletion(job):
    job_id=job['id']
    if not re.fullmatch(r'[0-9a-f]{12}',job_id):raise ValueError('无效任务目录')
    root=store.OUTPUT.resolve()
    entry=store.OUTPUT/job_id
    target=entry.resolve()
    if target.parent!=root or target.name!=job_id or entry.is_symlink():
        raise ValueError('删除目录越界或包含链接，未删除')
    source=Path(job['spec']['path']).resolve()
    if source==target or source.is_relative_to(target):
        raise ValueError('原视频位于生成目录内，请先将原视频移出再删除')
    if target.exists():
        pending=[target]
        while pending:
            path=pending.pop()
            info=path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('生成目录包含链接，未删除；请移除链接后重试')
            if stat.S_ISDIR(info.st_mode):pending.extend(path.iterdir())
    return target


def finish_delete(job_id):
    """Only the scheduler calls this after terminating and closing the worker."""
    with store.JOB_LOCKS[job_id]:
        job=store.get_job(job_id)
        if job['status']!='delete_requested':return
        try:
            target=output_for_deletion(job)
            if target.exists():shutil.rmtree(target)
            with store.connect() as db:
                db.execute('DELETE FROM jobs WHERE id=? AND status="delete_requested"',(job_id,))
            # Tiny API billing entries remain independently auditable.
        except (OSError,ValueError) as exc:
            store.update_job(job_id,status='delete_failed',stage='清理未完成',error=str(exc),
                message='任务已停止；关闭占用文件的程序后，点击垃圾箱重试')
