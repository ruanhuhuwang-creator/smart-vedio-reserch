# Windows 开发者构建说明

构建工具为 PyInstaller onedir + Python 标准库 Tkinter；不使用 Electron 或单文件自解压。
先在已验证的项目 CUDA 虚拟环境中安装 `packaging/requirements-build.txt`，不要重装 torch/torchvision。
当前构建版本为 Python 3.11.17、torch 2.9.1+cu128、PyInstaller 6.22.3。

```powershell
# 项目根目录，现有虚拟环境没有 pip 时用 uv
python -m uv pip install --python .venv/Scripts/python.exe -r packaging/requirements-build.txt
.\packaging\build_windows.ps1
```

需要现有 frontend/node_modules 或先运行 frontend/run.ps1 install；需要本地 models/yolo26n.pt，
从分发包源码 ZIP 重建时，可将 `_internal/models/yolo26n.pt` **复制**到源码 models 目录，保留分发包中的原文件。
以及 PATH 中 FFprobe 8.0.1 essentials 及其上级目录原版 LICENSE/README。
首次准备许可源码资料时会下载 FFmpeg 8.0.1 源码到 data/outputs/packaging-downloads，后续复用。
运行时不下载模型、不自动装包。构建产物从明确白名单收集，没有遍历用户 data。

每次构建生成全新的 release/时间戳目录，保留旧产物；可显式指定：

```powershell
.\packaging\build_windows.ps1 -OutputRoot 'F:\我的交付目录\SmartVision-构建一'
# 开发人员诊断用控制台版本，不用于普通用户交付
.\packaging\build_windows.ps1 -Console
```

步骤：检查现有 CUDA Python → Vite 生产构建/类型检查 → 检查资源 → 收集许可证和源码 → PyInstaller → 检查关键文件 → ZIP64 全量 CRC 核验及 SHA256。
同源生产 API 使用 window.location.origin，不能依赖 5173/8000；FastAPI 最后挂载静态路由，保留 /api、/health、/docs 与 Range。
ZIP64 必须保留完整 `_internal`，不能用 2GB 文件受限的归档工具替代。
build.log、build-work/warn-SmartVision.txt 可诊断动态模块或 DLL 缺失。

发布模式使用 `%LOCALAPPDATA%\SmartVision`；源码运行 launcher 默认仍用项目 data。
发布配置显式构造 APIConfig，忽略开发环境遗留 SMARTVISION_DATABASE/SMARTVISION_VIDEO_DIR，不会自动迁移旧数据。
启动器预先独占 socket 后传给同进程 Uvicorn，健康检查含随机实例标记；不采用先探端口、再另起服务的竞态流程。
单桌面实例锁和原后端数据库锁均保留。关闭窗口会等待 Uvicorn lifespan 和分析工作线程结束。

## 调试发布产物

```powershell
.\SmartVision.exe --debug
.\SmartVision.exe --no-browser --data-dir 'F:\独立验收数据'
.\SmartVision.exe --diagnostics --data-dir 'F:\独立模型诊断'
# 模拟无可见 NVIDIA GPU，验证自动 CPU 回退；不要修改系统驱动
$env:CUDA_VISIBLE_DEVICES='-1'
.\SmartVision.exe --diagnostics --data-dir 'F:\独立CPU诊断'
```

GUI 版不输出控制台，结果写入数据目录日志/diagnostics.json。--data-dir 是开发验收选项，不建议普通用户使用。
无人值守验收可指定 `--smoke-exit-file 路径`，文件出现后调用与关闭窗口相同的处理器；默认等待任务空闲。
同时明确指定 `--smoke-interrupt` 可验证任务中断和回滚，会跳过人工对话框。普通启动不启用这些诊断控制，也不添加 HTTP 关闭接口。
诊断回调验证不能替代实际鼠标双击/窗口按钮验收，报告须分别注明。
实际产物必须验证：真实上传/分析、CUDA 日志、CPU 回退、Range、查询/跳转、重新启动持久化、移动目录、中文/空格路径、正常关闭和异常日志。
源代码测试或只检查 EXE 文件存在均不能替代这些验收。
没有第二台干净 Windows 电脑时必须明确记录未验证项。

项目环境中可重复执行真实 EXE 验收（不启动源码服务）：

```powershell
.\.venv\Scripts\python.exe -m tests.validate_packaged_runtime --exe '你的分发目录\SmartVision.exe' --source '含行人的本地MP4.mp4'
```

该驱动使用开发环境的 Python/Node 控制测试，EXE 子进程的 PATH 仅包含 Windows 系统目录，Python/虚拟环境变量被清除。
它复制程序到中文/空格目录，验证 GPU、禁用 CUDA 的 CPU 重建、旧索引保留和诊断关闭；不伪装为鼠标双击测试。

## 许可与源码

见 DISTRIBUTION_LICENSE.md。同包提供 SmartVision/Ultralytics 源码和许可，页面可访问 source-code.zip。
FFprobe 是必要探测程序，不额外携带 FFmpeg/FFplay 转码或播放器命令。
对外公开再分发前需维护全部 GPL 静态外部库的对应源码/构建资料；不能删除第三方声明。
