# 开发、便携交付与首次准备

## 独立运行时

便携构建采用官方 CPython 3.11.9 NuGet 发行文件，新建三个完整 Python home，再复制锁定安装的 site-packages；不复制 venv 的 python.exe、pyvenv.cfg 或含本机路径的控制台启动器。每个运行时实际分发包版本写入 runtime-locks.json。FFmpeg/ffprobe 使用 BtbN LGPL shared 构建，Node 使用官方 24.15.0，KaTeX 与离线 Markdown 解析器均内置。Microsoft 官方 CRT 仅提取为 app-local DLL，不安装系统软件。为兼容依赖中的原生窄字符文件接口，仅给独立 Python 启动器的应用清单启用 Windows UTF-8 activeCodePage；不改变解释器、模型权重或识别参数。此兼容方式需要 Windows 10 1903 或更新系统。

准备好三个开发依赖环境与前端构建后，运行 scripts/build_portable.py 指定 dist-release 下的候选目录。构建归档的来源与 SHA-256 记录于 scripts/runtime-downloads.json，下载文件先校验再使用。源码白名单和打包由 scripts/package_release.py 实施；不从工作目录直接 git add 全部内容。

模型首次准备清单在 scripts/model-manifest.json，覆盖 Qwen ASR、对齐、VL、版面、YOLOX，以及运行时自带的 RapidOCR/Silero 文件。模型权重不进入源码包。下载部分约 8.1 GiB，还需预留续传/写入临时空间与课程成果空间。取消保留 .part，校验失败的下载会丢弃重下。已有就绪标记在文件大小或修改时间变化后作废。

## 启停和迁移

解压到可写目录，双击 notes.cmd。端口 8765 固定用于本地应用；遇到另一目录或版本占用必须先关闭对应实例。停止入口通过本目录实例令牌发出停止请求，不按名称结束所有 Python。没有本目录受管理实例时会报明原因。

目录迁移后再启动，运行时和程序内相对资源保持可用；桌面快捷方式指向绝对路径，迁移后应重新创建。Windows 账户变化需要重新填写 DPAPI 密钥，不能因密钥解密问题阻止资料浏览。原视频是路径引用，若文件移动需要重新导入。

## 源码与分卷

源码白名单包含程序、公开自制夹具、文档、CI、六角色与公开装饰资源。排除所有私人课程、QA 原图、字幕、PPT、笔记、配置、密钥、模型、大文件缓存与日志。

打包入口会先验证运行时和工具已构建，缺失时退出，不创建貌似完整的交付包。源码只归档当前白名单，历史暂存文件不自动继承；前端构建中已废弃的哈希文件会清除。独立系统待办见 [干净 Windows 验收](CLEAN_WINDOWS_ACCEPTANCE.md)。

便携完整 ZIP 可在本机直接解压。超过 1.8 GiB 时同时生成按二进制切分的 .partNNN 分卷；分卷必须全部下载到同一个目录，使用附带 PowerShell 合并脚本按 manifest 校验后合并和解压。单个 GitHub Release 附件必须小于 2 GiB，因此不上传超限完整 ZIP。

源码包包含安装环境.ps1；核心安装及CI均用requirements-lock.txt作约束，保证与主要求一致。便携Python文件缺失表示包不完整，应保留已有数据并重新解压完整包；源码安装脚本用于开发环境。

## 发布顺序

1. 冻结源码与运行时、生成每文件清单和 SHA-256。
2. 自动回归、真机 GPU/CPU、中文与空格路径迁移、故障恢复与生命周期验证。
3. 准备公开自制示例与真实验收结论；私有视频不打包，三节整课无需全部完成。
4. 清点已知限制和未满足门槛。当前以 1.0.0-rc.1 公开测试版交付，不将待验收项写成通过。
5. 项目维护者已于2026-10-23确认公开发布，目标为 Chenwt-max/notes。GitHub 远端 CI 的结果以仓库 Actions 实际执行为准。


### 开发环境构建入口

```powershell
python -m venv .venv-asr
.venv-asr\Scripts\python.exe -m pip install -r requirements-asr.txt
python -m venv .venv-formula
.venv-formula\Scripts\python.exe -m pip install -r requirements-formula.txt
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/启用显卡加速.ps1
.venv\Scripts\python.exe scripts/build_portable.py --destination dist-release/notes-portable-rc1
.venv\Scripts\python.exe scripts/package_release.py
```

独立运行时以本地锁定安装为输入，输出 runtime-locks.json 明确实际软件包版本；构建不会把开发虚拟环境启动器复制过去。CPU 版开发环境可单独运行，但完整便携候选按已验证的 GPU 依赖集重建，CPU/GPU 推理在程序中选择。
