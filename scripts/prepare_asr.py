"""QA-only, resumable official assets with per-file SHA256 verification."""
import concurrent.futures
import hashlib
import json
import math
import threading
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PRINT_LOCK = threading.Lock()


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def download(path, url, params, size, sha256):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size == size and digest(path) == sha256:
        print('cached', path.name, flush=True)
        return
    count = min(8, max(1, math.ceil(size / (64 * 1024 * 1024))))
    width = math.ceil(size / count)
    parts = [path.with_name(path.name + f'.part-{i}') for i in range(count)]
    prefix = path.with_suffix(path.suffix + '.download')
    if prefix.exists() and not parts[0].exists():
        if prefix.stat().st_size > width:
            raise ValueError('Existing prefix is larger than the first part')
        prefix.replace(parts[0])
    started = time.monotonic()
    last_print = [started]

    def worker(i):
        start, end = i * width, min(size, (i + 1) * width) - 1
        part = parts[i]
        for attempt in range(20):
            offset = part.stat().st_size if part.exists() else 0
            if offset == end - start + 1:
                return
            if offset > end - start + 1:
                raise ValueError('Oversized part: ' + part.name)
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    with session.get(url, params=params, stream=True, timeout=(25, 60),
                                     headers={'Range': f'bytes={start + offset}-{end}'}) as response:
                        response.raise_for_status()
                        expected = f'bytes {start + offset}-{end}/{size}'
                        whole_file = start + offset == 0 and end == size - 1 and response.status_code == 200
                        if not whole_file and (response.status_code != 206 or response.headers.get('Content-Range') != expected):
                            raise ValueError('Server did not honor the exact byte range')
                        with part.open('ab') as output:
                            for block in response.iter_content(1024 * 1024):
                                output.write(block)
                                with PRINT_LOCK:
                                    now = time.monotonic()
                                    if now - last_print[0] >= 15:
                                        total = sum(p.stat().st_size for p in parts if p.exists())
                                        print(path.name, round(total / 1e6), '/', round(size / 1e6),
                                              'MB', flush=True)
                                        last_print[0] = now
                if part.stat().st_size != end - start + 1:
                    raise ValueError('Incomplete byte range')
                return
            except (requests.RequestException, ValueError) as error:
                print('retry', path.name, i, attempt + 1, type(error).__name__, flush=True)
                if attempt == 19:
                    raise
                time.sleep(min(10, attempt + 1))

    with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
        list(pool.map(worker, range(count)))
    assembled = path.with_suffix(path.suffix + '.assembling')
    with assembled.open('wb') as output:
        for part in parts:
            with part.open('rb') as source:
                for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
                    output.write(block)
    if assembled.stat().st_size != size or digest(assembled) != sha256:
        raise ValueError('SHA256 mismatch: ' + path.name)
    assembled.replace(path)
    for part in parts:
        part.unlink()
    print('verified', path.name, round(time.monotonic() - started, 1), 'seconds', flush=True)


if __name__ == '__main__':
    pinned = json.loads((HERE / 'asr-models.json').read_text(encoding='utf-8'))
    for name, receipt in pinned.items():
        target = ROOT / 'models' / name
        for row in receipt['files']:
            path = (target / row['Path']).resolve()
            if not path.is_relative_to(target.resolve()):
                raise ValueError('Invalid model path')
            download(path, 'https://www.modelscope.cn/api/v1/models/' + receipt['repo'] + '/repo',
                     {'Revision': row['Revision'], 'FilePath': row['Path']}, row['Size'], row['Sha256'])
        (target / 'PROVENANCE.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print('MODEL_READY', name, flush=True)
