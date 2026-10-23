import argparse
import json
from pathlib import Path

from .store import create_job,list_jobs
from .pipeline import run_job

def main():
    parser=argparse.ArgumentParser(description='本地课程笔记工具')
    parser.add_argument('video',nargs='?')
    parser.add_argument('--window',action='append',help='开始秒:结束秒，可重复指定')
    parser.add_argument('--visuals-only',action='store_true')
    parser.add_argument('--no-formulas',action='store_true')
    parser.add_argument('--organize',action='store_true')
    parser.add_argument('--resume')
    args=parser.parse_args()
    if args.resume:
        from .store import update_job
        update_job(args.resume,status='queued')
        run_job(args.resume)
    elif args.video:
        from .settings import settings
        local_models = settings()
        spec={'path':str(Path(args.video).resolve()),'windows':[list(map(float,w.split(':'))) for w in args.window] if args.window else None,
              'person_model':local_models['person_model'],'formula_model':local_models['formula_model'],
              'visuals_only':args.visuals_only,'formulas':not args.no_formulas,'organize':args.organize}
        job=create_job(spec)
        print(job['id'],flush=True)
        run_job(job['id'])
    else:
        print(json.dumps(list_jobs(),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
