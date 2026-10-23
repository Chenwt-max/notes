# 第三方软件与项目来源

本项目是独立实现，主要复用公开软件包、公开模型与算法接口。调研不代表复制项目代码。

| 软件 / 模型 | 来源 | 许可证 / 用途 |
|---|---|---|
| Look-Tongji-Notes | https://github.com/WALKERKILLER/Look-Tongji-Notes | MIT；参考课程笔记流程。其字幕上传音频至外部服务，本项目没有沿用该传输路线 |
| Qwen3-ASR-1.7B / Qwen3-ForcedAligner-0.6B | https://github.com/QwenLM/Qwen3-ASR | Apache-2.0；本地语音识别和词级时间对齐；逐文件SHA256及固定版本在models各自PROVENANCE.json |
| Silero VAD | https://github.com/snakers4/silero-vad | MIT；本地语音活动和字幕覆盖检查 |
| PyTorch / TorchAudio | https://pytorch.org/ | BSD-style；独立字幕运行时 |
| RapidOCR | https://github.com/RapidAI/RapidOCR | Apache-2.0；本地文字识别 |
| PaddleOCR / PaddleX | https://github.com/PaddlePaddle/PaddleOCR | Apache-2.0；公式识别、版面检测及公开模型 |
| PaddlePaddle | https://github.com/PaddlePaddle/Paddle | Apache-2.0；公式运行时 |
| OpenCV | https://github.com/opencv/opencv | Apache-2.0；画面分析及几何匹配 |
| YOLOX-Tiny / YOLOX-S | https://github.com/Megvii-BaseDetection/YOLOX | Apache-2.0，Copyright Megvii 2021–2022；本地人物检测。person.py 的预处理和解码改自官方 ONNX 示例，已改为仅检测人物并使用明确的 CPU / CUDA 执行设备；许可证副本及模型 SHA256 在 models/ |
| FFmpeg | https://ffmpeg.org/legal.html | 便携包采用 BtbN LGPL shared 构建；版本、下载 SHA-256、原许可证和源代码获取信息随包保留。开发者本机的 GPL 构建不复制入包。 |
| pypdfium2 / PDFium | https://github.com/pypdfium2-team/pypdfium2 | pypdfium2 采用 Apache-2.0 或 BSD-3-Clause；PDFium 及其依赖许可证随运行时原样保留。用于原文档页面渲染和文字层提取，不执行OCR。 |
| FastAPI | https://github.com/fastapi/fastapi | MIT；本地接口 |
| React | https://github.com/facebook/react | MIT；网页 |
| GSAP | https://gsap.com/community/standard-license/ | GSAP Standard License / No Charge；保留软件包中的许可证，不将其称为 MIT 或 OSI 开源 |
| Lucide | https://github.com/lucide-icons/lucide | ISC；图标 |
| KaTeX | https://github.com/KaTeX/KaTeX | MIT；公式渲染及字体 |
| markdown-it / react-markdown | https://github.com/markdown-it/markdown-it / https://github.com/remarkjs/react-markdown | MIT；讲义渲染 |

Python 与前端依赖的完整版本由 requirements-lock.txt、requirements-asr-lock.txt、requirements-formula-lock.txt 和 frontend/package-lock.json 记录；各软件包自带许可证保留在安装目录。NVIDIA CUDA/cuDNN 运行库遵循 NVIDIA 对应分发条款，不包含在本项目源代码授权内。

研究中还参考了 vidistiller、video-slide-extractor、lecture-to-notes 等 MIT 项目的说明和源代码行为，具体比较见 findings.md。没有复制 GPL 项目 slideo 的实现代码。
# 页面装饰素材

`frontend/public/images/learning-pages.webp` 为本次经用户允许使用 imagegen 生成的首页纸页装饰；生成原图保存在 `qa/studio-artwork-original.png`。不用于课程视频、课件来源、字幕或公式结果。设计参考站点为 https://linear.app/ 与 https://readwise.io/read ，未复制其图片或品牌素材。


## 离线名言资料

首页内置428条古籍格言，文本为公有领域《论语》和张潮《幽梦影》原文摘录，逐条标注原书篇名或条目。电子数据来自chinese-poetry项目（MIT）：https://github.com/chinese-poetry/chinese-poetry ，未混入现代译写或无出处网传语录。原始下载和生成范围记录在qa/page-refresh。

## notes 助手社区角色参考（2026-10-21）

当前六姿态图集为内置imagegen根据社区参考制作的比例改编，详见frontend/public/assistants/SOURCES.md。CrossPet动作库仅用于研究，未作为生产素材分发；QA研究副本附其CC BY-NC-SA 4.0原声明。


## 便携运行时改动和许可证

独立 CPython 3.11.9 来自官方 NuGet，保留 PSF LICENSE；仅为 python.exe/pythonw.exe 应用清单加入 Windows UTF-8 activeCodePage，以兼容中文目录中的原生依赖，不改变解释器和识别算法。运行时最终 SHA-256 记录已包含这一改动。Microsoft CRT 来自签名有效的官方 Redistributable，仅 app-local 提取，保留 licenses/Microsoft-VC-LICENSE.rtf；不适用项目 MIT。Node 官方 LICENSE、FFmpeg LGPL shared 原 LICENSE、对应 FFmpeg 源码与构建配方均随便携包保留。前端依赖授权全文和版本清单位于 docs/licenses。

公式渲染使用MIT授权的KaTeX0.18.2，前端锁文件通过override统一其传递依赖；便携本地检查和离线导出均使用相同版本。对应授权全文与版本记录已更新至docs/licenses。
