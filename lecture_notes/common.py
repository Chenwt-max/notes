from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from .runtime import PORTABLE

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT if PORTABLE else ROOT.parent
OUTPUT = WORKSPACE / 'outputs'
DATA = ROOT / 'data'
MODELS = ROOT / 'models'


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            # Windows readers/antivirus may briefly deny delete-sharing for atomic replace.
            if getattr(exc,'winerror',None) not in {5,32,33} or attempt==7:raise
            time.sleep(min(.01*2**attempt,.1))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def math_markdown(markdown):
    """Unify math delimiters before Markdown can consume LaTeX backslashes."""
    parts=re.split(r'(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)',markdown)
    for i in range(0,len(parts),2):
        parts[i]=re.sub(r'\\\[([\s\S]*?)\\\]',lambda m:'\n\n$$\n'+m[1].strip()+'\n$$\n\n',parts[i])
        parts[i]=re.sub(r'\\\(([\s\S]*?)\\\)',lambda m:'$'+m[1].strip()+'$',parts[i])
    return ''.join(parts)


def stamp(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'


def source_identity(path):
    path = Path(path).resolve()
    stat = path.stat()
    return {'path': str(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def safe_child(root, relative):
    root = Path(root).resolve()
    result = (root / relative).resolve()
    if not result.is_relative_to(root):
        raise ValueError('路径超出成果目录')
    return result
