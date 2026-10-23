$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt -c requirements-lock.txt
if ($LASTEXITCODE) { throw '主环境安装失败' }
py -3.11 -m venv .venv-asr
& .\.venv-asr\Scripts\python.exe -m pip install --timeout 120 -r requirements-asr.txt
if ($LASTEXITCODE) { throw '字幕环境安装失败' }
& .\.venv\Scripts\python.exe -m pip install nvidia-cublas-cu12==12.9.2.10 nvidia-cudnn-cu12==9.27.0.42 nvidia-cuda-nvrtc-cu12==12.9.86
py -3.11 -m venv .venv-formula
& .\.venv-formula\Scripts\python.exe -m pip install -r requirements-formula.txt
if ($LASTEXITCODE) { throw '公式环境安装失败' }
Push-Location frontend
try { npm.cmd ci --no-audit --no-fund; if ($LASTEXITCODE) { throw '网页依赖安装失败' }; npm.cmd run build; if ($LASTEXITCODE) { throw '网页构建失败' } } finally { Pop-Location }
& .\.venv\Scripts\python.exe -X utf8 scripts/prepare_person.py
if ($LASTEXITCODE) { throw '人物模型准备失败' }
& .\.venv-asr\Scripts\python.exe -X utf8 scripts/prepare_asr.py
if ($LASTEXITCODE) { throw '语音模型准备失败' }
& .\.venv-formula\Scripts\python.exe -X utf8 scripts/prepare_document.py
if ($LASTEXITCODE) { throw '课件文字与公式模型准备失败' }
Write-Host '安装完成。双击 notes.cmd 打开网页。FFmpeg 和 ffprobe 需在系统路径中。'
