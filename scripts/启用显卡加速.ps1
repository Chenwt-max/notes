$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe -m pip install onnxruntime-gpu==1.23.2 --no-deps --target models/ortgpu12
if ($LASTEXITCODE) { throw '文字识别显卡运行时安装失败' }
& .\.venv\Scripts\python.exe -m pip install nvidia-cuda-runtime-cu12==12.6.77
& .\.venv-formula\Scripts\python.exe -m pip download paddlepaddle-gpu==3.2.2 --no-deps --only-binary=:all: --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/ --dest models/wheels
if ($LASTEXITCODE) { throw '公式显卡运行时下载失败，原CPU环境仍可使用' }
& .\.venv-formula\Scripts\python.exe -m pip uninstall -y paddlepaddle
& .\.venv-formula\Scripts\python.exe -m pip install models/wheels/paddlepaddle_gpu-3.2.2-cp311-cp311-win_amd64.whl --no-deps
if ($LASTEXITCODE) { throw '公式显卡运行时安装失败' }
& .\.venv-formula\Scripts\python.exe -m pip install nvidia-cuda-runtime-cu12==12.6.77 nvidia-cufft-cu12==11.3.0.4 nvidia-curand-cu12==10.3.7.77 nvidia-cusolver-cu12==11.7.1.2 nvidia-cusparse-cu12==12.5.4.2 opt-einsum==3.3.0
if ($LASTEXITCODE) { throw '公式显卡依赖安装失败' }
Remove-Item -LiteralPath 'models/wheels/paddlepaddle_gpu-3.2.2-cp311-cp311-win_amd64.whl' -ErrorAction SilentlyContinue
Write-Host '显卡运行时已安装，安装包已清理。请在任务停止后重启网页服务。'
