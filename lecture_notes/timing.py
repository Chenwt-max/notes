"""Persist wall-clock component timings, including interrupted work and resumes."""
from contextlib import contextmanager
from pathlib import Path
import time
from .common import read_json,write_json


class Timings:
    def __init__(self,output,group):
        self.path=Path(output)/f'timing_{group}.json'

    @contextmanager
    def measure(self,name):
        start=time.perf_counter();completed=False
        try:
            yield
            completed=True
        finally:
            data=read_json(self.path,{'version':1,'metrics':{}})
            row=data['metrics'].setdefault(name,{'seconds':0.,'completed':0,'interrupted':0})
            row['seconds']+=max(0,time.perf_counter()-start)
            row['completed' if completed else 'interrupted']+=1
            data['updated']=time.time()
            write_json(self.path,data)

    def call(self,name,function,*args,**kwargs):
        with self.measure(name):return function(*args,**kwargs)


def timing_summary(output):
    groups={name:read_json(Path(output)/f'timing_{name}.json',{}).get('metrics',{})
            for name in ('pipeline','asr','formula','synthesis')}
    for part in sorted((Path(output)/'parts').glob('[0-9][0-9][0-9]')):
        for name in ('pipeline','asr','formula'):
            for metric,row in read_json(part/f'timing_{name}.json',{}).get('metrics',{}).items():
                target=groups[name].setdefault(metric,{'seconds':0.,'completed':0,'interrupted':0})
                for key in ('seconds','completed','interrupted'):target[key]+=row.get(key,0)
    return {'version':1,'groups':groups,
            'scope':'累计墙钟时间；阶段包含子项，不能相加；历史未计时的工作不补估'}
