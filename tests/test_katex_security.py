"""Render strings in a child process; never execute hostile HTML in a DOM."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('expression',[
    r'\href{javascript:alert(1)}{x}',
    r'\includegraphics{https://fixture.invalid/pixel.png}',
])
def test_katex_ignores_inherited_trust(expression):
    script=r'''const katex=require(process.argv[1]);
let html;
try {Object.prototype.trust=true;html=katex.renderToString(process.argv[2],{throwOnError:false});}
finally {delete Object.prototype.trust;}
console.log(JSON.stringify({active:/<(?:a|img)(?:\s|>)/.test(html)}));'''
    result=subprocess.run([shutil.which('node'),'-e',script,str(ROOT/'frontend/node_modules/katex'),expression],
                          capture_output=True,text=True,check=True,timeout=20)
    assert not json.loads(result.stdout)['active']
