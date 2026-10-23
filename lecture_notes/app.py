"""Own one local server; file control permits checkpointed stop without a kill-all."""
from __future__ import annotations

import hashlib
import os
import secrets
import threading

from .common import ROOT,DATA,read_json,write_json
from .runtime import VERSION


def instance_identity():
    return hashlib.sha256(str(ROOT.resolve()).lower().encode('utf-8')).hexdigest()[:24]


def main():
    import uvicorn
    DATA.mkdir(parents=True, exist_ok=True)
    nonce = secrets.token_hex(24)
    record = {'pid':os.getpid(),'instance':instance_identity(),'version':VERSION,'nonce':nonce}
    path = DATA/'server-instance.json'
    request = DATA/'stop-request.json'
    request.unlink(missing_ok=True)
    write_json(path,record)
    server = uvicorn.Server(uvicorn.Config('lecture_notes.server:app',host='127.0.0.1',port=8765,
                                         access_log=False,timeout_graceful_shutdown=45))
    ended = threading.Event()

    def monitor():
        while not ended.wait(.4):
            try:
                value = __import__('json').loads(request.read_text(encoding='utf-8-sig')) if request.exists() else {}
                if value.get('nonce') == nonce:
                    server.should_exit = True
                    return
            except (OSError,ValueError):
                continue
    thread = threading.Thread(target=monitor,daemon=True)
    thread.start()
    try:
        server.run()
    finally:
        ended.set()
        thread.join(timeout=1)
        if read_json(path,{}).get('nonce') == nonce:
            path.unlink(missing_ok=True)
            request.unlink(missing_ok=True)
            pid_file=DATA/'background-server.pid'
            if pid_file.exists() and pid_file.read_text(encoding='utf-8-sig').strip()==str(os.getpid()):
                pid_file.unlink()


if __name__ == '__main__':
    main()
