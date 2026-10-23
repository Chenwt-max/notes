"""Resolve developer and portable tools without modifying the system environment."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.0.0-rc.1'
PORTABLE = (ROOT/'portable.json').is_file()


def python_for(role='core'):
    if PORTABLE:
        return ROOT/'runtime'/role/'python.exe'
    env = {'core': '.venv', 'asr': '.venv-asr', 'document': '.venv-formula'}[role]
    return ROOT/env/'Scripts/python.exe'


def site_packages(role):
    python = python_for(role)
    return (python.parent if PORTABLE else python.parent.parent)/'Lib/site-packages'


def configure():
    if not PORTABLE:
        return
    cache = ROOT/'cache'
    # Child processes inherit these locations, including implicit Paddle/HF assets.
    for name, relative in {'HF_HOME':'huggingface', 'TORCH_HOME':'torch',
                           'TORCH_EXTENSIONS_DIR':'torch_extensions', 'CUDA_CACHE_PATH':'cuda', 'NUMBA_CACHE_DIR':'numba',
                           'PADDLE_PDX_CACHE_HOME':'paddlex', 'MODELSCOPE_CACHE':'modelscope',
                           'XDG_CACHE_HOME':'xdg', 'TEMP':'tmp', 'TMP':'tmp'}.items():
        path = cache/relative
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    os.environ['PATH'] = os.pathsep.join([str(ROOT/'runtime/tools'), str(Path(sys.executable).parent), os.environ.get('PATH','')])


def status():
    return {'portable':PORTABLE,
            'python':{role:python_for(role).is_file() for role in ('core','asr','document')},
            'tools':{name:(ROOT/'runtime/tools'/(name+'.exe')).is_file() if PORTABLE else bool(shutil.which(name))
                     for name in ('node','ffmpeg','ffprobe')}}
