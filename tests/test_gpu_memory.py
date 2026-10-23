from types import SimpleNamespace
import subprocess

import pytest

from lecture_notes import resources
from lecture_notes.common import write_json


@pytest.mark.parametrize('requested',[0,2,64])
def test_eight_gib_gpu_cannot_start_second_model(tmp_path,monkeypatch,requested):
    monkeypatch.setattr(resources,'DATA',tmp_path)
    monkeypatch.setenv('LECTURE_INFERENCE_DEVICE','cuda')
    monkeypatch.setattr(resources,'gpu_memory',lambda:(8192,8192))
    write_json(tmp_path/'settings.json',{'gpu_concurrency':requested})
    attempts=[]
    def stop():
        if attempts:raise InterruptedError('paused')
        attempts.append(True)
    with resources.gpu_slot():
        with pytest.raises(InterruptedError):
            with resources.gpu_slot(stop):raise AssertionError('second model loaded')
    with resources.gpu_slot():pass


def test_occupied_gpu_waits_then_admits_without_loading_early(monkeypatch):
    samples=iter([(8192,3000),(8192,7600)])
    monkeypatch.setattr(resources,'gpu_memory',lambda:next(samples))
    checks=[];messages=[]
    monkeypatch.setattr(resources.time,'sleep',lambda _:None)
    resources.wait_for_gpu_memory(lambda:checks.append(True),messages.append)
    assert len(messages)==1 and '2.9GiB' in messages[0] and len(checks)>=2


def test_memory_wait_can_pause(monkeypatch):
    monkeypatch.setattr(resources,'gpu_memory',lambda:(8192,2000))
    def stop():raise InterruptedError('paused')
    with pytest.raises(InterruptedError):resources.wait_for_gpu_memory(stop)


@pytest.mark.parametrize('memory',[None,(6144,6144)])
def test_missing_or_insufficient_gpu_does_not_load(monkeypatch,memory):
    monkeypatch.setattr(resources,'gpu_memory',lambda:memory)
    with pytest.raises(RuntimeError,match='CPU'):resources.wait_for_gpu_memory()


def test_memory_query_failure_is_not_unlimited(monkeypatch):
    def fail(*args,**kwargs):raise subprocess.TimeoutExpired('nvidia-smi',5)
    monkeypatch.setattr(resources.subprocess,'run',fail)
    assert resources.gpu_memory() is None


def test_memory_query_rejects_bad_telemetry(monkeypatch):
    monkeypatch.setattr(resources.subprocess,'run',lambda *a,**kw:SimpleNamespace(stdout='8192, N/A'))
    assert resources.gpu_memory() is None
