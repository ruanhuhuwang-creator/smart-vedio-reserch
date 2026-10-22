# SmartVision 第五阶段：Windows onedir 实施与验收

日期：2026-10-21，Asia/Shanghai。此次仅进行发布适配，没有新增视频业务功能，没有更换 YOLO、重写索引/查询算法或调整任务并发限制。

## 1. 交付物

最终应用目录（完整分发，必须保留 _internal）：

`F:\数图期末作业\smart-video-search\release\20261021-111002\dist\SmartVision`

EXE：

`F:\数图期末作业\smart-video-search\release\20261021-111002\dist\SmartVision\SmartVision.exe`

最终分发 ZIP：

`F:\数图期末作业\smart-video-search\release\20261021-111002\SmartVision-win64-validated.zip`

该 ZIP 对应的 .json/.sha256 记录精确大小和校验值；已做 ZIP64 全量 CRC 校验。
目录约 **4.99 GB / 4.65 GiB**，ZIP 约 **3.09 GB / 2.88 GiB**，EXE 为 **46,004,600 字节**。
最终加入验收报告和补全源码资料后，精确总大小以归档旁的 JSON 为准。
主要体积为 CUDA 版 PyTorch DLL；只携带 yolo26n.pt 一份预训练权重，没有用户视频、数据库或私人数据。
release 下更早的目录和未带 validated 的归档属于构建/诊断中间产物，不作为最终交付入口。

目录还包含：使用说明.md、构建说明.md、源码与许可.md、PHASE5_VALIDATION.md。
项目中的对应文档为 packaging/USER_GUIDE.md、packaging/README_PACKAGING.md、packaging/DISTRIBUTION_LICENSE.md。

## 2. 检查、基线和实际环境

实施前已阅读 README、PHASE4_VALIDATION、FastAPI 路由、Schema、配置、模型、视频时间戳、任务和数据库路径。
检查 Git：main 尚无正式提交，原文件均未跟踪；保存工作区状态，没有提交或推送 GitHub。
已有视频、数据库和模型保留，没有自动迁移开发数据。

| 项目 | 结果 |
| --- | --- |
| 原后端基线 | **68 passed**，14.78 秒 |
| 原前端基线 | **38 passed / 5 files**，17.13 秒 |
| 最终后端回归 | **82 passed**，含原 68 项及 14 项发布边界测试，15.57 秒 |
| 最终前端回归 | **38 passed / 5 files**，15.46 秒 |
| TypeScript/Vite | 多次真实构建通过；最终 EXE 内页面也已验证 |
| Python | 3.11.17，x64 |
| PyTorch | 2.9.1+cu128，torchvision 0.24.1+cu128 |
| CUDA/GPU | CUDA runtime 12.8，RTX 5060 Laptop GPU；实际 EXE 使用 cuda:0 |
| Ultralytics | 8.4.175；随包 yolo26n.pt 离线加载 |
| PyInstaller | 6.22.3，hooks-contrib 2026.9 |
| FFprobe | 8.0.1 essentials，来自现有 Gyan 构建 |
| Node/npm | 构建端沿用 Node 24.19.0/npm 12.2.0；应用不带 Node，不在运行时调用 npm |

保留 1 条原有 Starlette TestClient/httpx 弃用警告，没有为消除警告替换后端包。
只安装 PyInstaller 构建依赖，没有盲目重装或替换 CUDA 版 PyTorch。

## 3. 文件变更与架构

新增：

- packaging/launcher.py：标准库 Tkinter 控制窗口、路径、日志、独占 socket、服务就绪检查、浏览器启动、关闭和诊断入口。
- packaging/smartvision.spec：windowed onedir，收集 Python/Torch/OpenCV/Ultralytics/Tcl/Tk、模型、SQL 和静态资源。
- packaging/build_windows.ps1、prepare_release.py、finish_release.py、requirements-build.txt：可重复构建、白名单资源、许可证/源码、ZIP64 和校验。
- packaging/USER_GUIDE.md、README_PACKAGING.md、DISTRIBUTION_LICENSE.md。
- backend/api/static.py：可选生产静态页面及安全 SPA fallback。
- backend/core/subprocess_utils.py：窗口版 FFprobe 的无控制台子进程选项。
- tests/test_packaging.py、tests/validate_packaged_runtime.py、frontend/e2e/packaged.mjs。
- 本报告。

修改：backend/config.py、main.py、core/detector.py、core/timestamps.py、services/videos.py；
frontend/src/api/client.ts、views/DashboardView.vue；README.md、.gitignore。
改动限于资源/数据路径、同源页面、离线文档、许可证入口、设备日志及 FFprobe 进程句柄。
检测、采样、合并、SQL 查询及单 GPU/单工作者/有界队列算法不变。

## 4. 启动与退出

用户双击 EXE → 创建用户数据子目录并验证可写 → 检查权重/网页/SQL/FFprobe → 桌面实例锁 →
独占 bind 127.0.0.1 → 在同一进程的线程运行单个 Uvicorn → 初始化 SQLite/工作者 → 校验本实例 /health →
打开默认浏览器，保留控制窗口。

Windows socket 使用 SO_EXCLUSIVEADDRUSE；先 bind 再把同一 socket 交给 Uvicorn，端口冲突时选空闲端口。
健康检查使用随机实例响应标记，拒绝误认别人的服务，不用“发现端口已有响应就直接打开”的方式。
首选端口默认 8765，成功端口保存在用户配置中以便重启尽量稳定。
同一数据目录保留桌面实例锁及后端数据库锁；没有增加进程/工作者。

控制窗口包含打开网页、日志目录和停止退出按钮。关闭标签页不结束后台服务，控制窗口仍存在。
普通关闭遇到活动任务时先询问；用户确认后停止接受服务并通过原 lifespan/TaskManager.stop 退出。
UI 等待服务和分析工作线程真正结束后才销毁；不会因为 30 秒 join 超时就丢下无法管理的线程。
有分析任务时停止导致任务 failed/索引回滚，不覆盖此前成功索引。

PE 检查 Subsystem=2（Windows GUI）、asInvoker 构建，不请求管理员权限，不创建常驻 Windows 服务。
FFprobe 子进程显式 CREATE_NO_WINDOW、DEVNULL stdin，避免窗口版无效标准句柄及黑框。

## 5. 资源与数据

只读内容在 _internal：Python、PyTorch、动态库、模型、frontend/dist、SQL 模板、许可证。
发布默认数据路径为 `%LOCALAPPDATA%\SmartVision`，开发模式仍使用项目 data。
没有把数据库、视频、输出、配置或日志写入 _internal；不依赖 EXE 启动时的当前目录。
发布启动器显式构造 APIConfig，不采用可能遗留的开发 SMARTVISION_DATABASE/VIDEO_DIR 路径。

用户目录：videos、outputs、smartvision.sqlite3、logs、config、cache、tmp。
主要日志 logs/smartvision.log 自动轮转；第三方标准输出写入 console.log。
记录启动、模式、资源/数据路径、端口、数据库、CUDA/CPU、模型加载、任务异常及关闭。
严重资源缺失会返回错误并保存 startup-error.txt/日志；普通 GUI 启动会显示可理解提示。
run-state.json 仅用于本机诊断，记录当前实例及 stopped 状态，不是业务 API。

Ultralytics、matplotlib、torch 缓存均指定到用户目录；配置目录父级预先存在，避免第三方退回临时目录。
配置关闭 Ultralytics 自动装包及联网检查，权重显式使用 _internal/models/yolo26n.pt。
发布版权重缺失直接报错，不默默下载。

## 6. 同源网页与依赖

Vite 生产构建强制使用 window.location.origin，页面、API、视频流位于同一动态端口。
不依赖 localhost:5173/127.0.0.1:8000；开发模式仍支持原环境变量。
FastAPI 保留 /health、/api、/openapi.json、/docs 及原生 Range。
生产 /docs 使用本地 Swagger JS/CSS/图标，无需访问 CDN；/redoc 是 FastAPI 原有可选文档，未单独离线化。
静态 fallback 不吞掉未知 /api 路径，缺失 JS 返回 404，普通页面刷新可返回 index.html。
发布实例不添加通配符 CORS，默认同源使用；原开发 CORS 配置保持。

运行时只需要 FFprobe 做解码校验与 PTS 扫描，因此只捆绑 ffprobe.exe，没有额外携带 ffmpeg.exe/ffplay.exe。
Torch 的官方 PyInstaller hook 收集 CUDA 所需 DLL；未额外收集 TensorFlow、JAX、ONNX runtime、Qt、测试框架或 Node。
模型仅一份 YOLO26n；没有训练、其他权重、用户视频或运行数据库。

## 7. 从实际 EXE 的验收结果

最终可重复验收证据：

`F:\数图期末作业\smart-video-search\data\outputs\phase5_runtime\1792552445463328400`

acceptance-report.json 有 **10 项进程/持久化检查**，gpu-report.json 与 cpu-report.json 各有 **8 项真实浏览器检查**，
additional-report.json 另记录资源缺失日志和真实默认 AppData 路径检查。
gpu-desktop.png/cpu-desktop.png 为 EXE 服务的页面截图，已实际查看。
没有 API 拦截、模拟模型或用源码 Uvicorn 替代产物运行。

| 验收项 | 实际结果 |
| --- | --- |
| EXE 启动、控制窗口 | 最终 EXE 实际启动，Windows 窗口列表出现“SmartVision · 应用控制” |
| 自动打开浏览器 | 默认 Chrome 出现 SmartVision 页面；启动日志记录 webbrowser 返回 True |
| 不启动开发服务 | EXE 进程 PATH 仅 C:\Windows\System32;C:\Windows，无 Vite/npm/外部 Uvicorn；已确认监听自己的动态端口 |
| 无虚拟环境依赖 | 清除 PYTHONPATH/PYTHONHOME/VIRTUAL_ENV；进程映射 python311.dll 在 _internal，无 .venv 模块 |
| 无管理员权限 | 测试进程运行时 IsUserAnAdmin=False；EXE asInvoker，不调用提权 |
| 中文/空格与移动 | 首次从中文/空格工作目录启动，随后整包复制到“复制后 中文 空格/SmartVision”再启动成功 |
| 同源网页/静态资源 | 页面、Vite assets、health、OpenAPI、源码 ZIP、本地 Swagger 资源成功；没有固定开发端口请求 |
| 真实上传 | 24 秒 H.264 片段，768×576、10 FPS，FFprobe 校验后 201 |
| GPU 分析 | 打包 yolo26n.pt 加载，日志 selected=cuda:0，任务成功扫描 240/240 原视频帧 |
| CPU 回退 | 设置 CUDA_VISIBLE_DEVICES=-1，重启后 selected=cpu，真实强制重建成功，模型 CPU 推理有日志 |
| 检索 | person/car 真实查询 SQLite，返回目标事件（模型预测，不视为人工真值） |
| 播放 | 原生 video 元数据加载，点击事件定位、播放和高亮；Range 0-127 返回 206 和 128 字节 |
| 故障日志 | 对隔离上传副本临时追加字节，真实任务失败并保留旧索引；副本随后恢复 |
| 运行中退出 | 强制重建状态 running 后请求诊断退出，原关闭处理器/worker 实际执行，记录 AnalysisInterrupted/failed，旧索引回滚保留 |
| 服务清理 | 两轮 EXE 均正常返回 0，run-state=stopped，原端口不能再连接，没有 SmartVision 残留进程 |
| 持久化 | 复制后重启继续读取同一数据目录的视频和索引；刷新/重启不自动提交任务 |
| 端口冲突 | 驱动先占一个端口，EXE 选其他端口，没有向占用者发送就绪请求 |
| 资源只读 | 启动/退出前后比对包内文件大小/mtime，无新增或修改；原始素材 SHA256 不变 |
| 缺失权重 | 仅对验收复制品暂时移开权重，--diagnostics 退出 1，startup-error.txt/日志保存清晰原因，随后恢复权重 |
| 默认真实 AppData | 无 --data-dir 覆盖时，实际创建 C:\Users\Lenovo\AppData\Local\SmartVision，正常停止且数据保留 |

网络验证通过不可用的外网代理和 YOLO_OFFLINE 配置约束外联；浏览器/模型使用本地资源。
没有物理断开系统网络，不能把此测试表述为断网操作系统实测。
源片段 SHA256：d5f009ed17df73106071fe8bf0f43bde50a0e3596effd9ed439ce317ae64f054；原文件未改动。
测试生成的重复片段、上传副本和数据库均在 data/outputs，不进入分发包。

## 8. 明确未验证的项目

- **真实鼠标双击 EXE、控制窗口按钮及人工确认对话框点击未验证。** Windows 电脑使用工具分别返回
  “Computer Use was not approved to use explorer/smartvision”。用户的开发权限与该工具独立授权不同，未绕过限制。
- 关闭验收通过显式 --smoke-exit-file/--smoke-interrupt 调用与窗口关闭相同的处理器；普通启动不启用诊断控制，未新增 HTTP 关闭接口。
  忙碌退出的确认/取消分支另有单元测试，但这不能冒充实际鼠标操作或对话框点击。
- 未在第二台完全没有 Python、Node 的干净 Windows 系统实测。当前只证实 EXE 在清理开发环境变量/PATH 后自带运行库可工作。
- CPU 回退是在本机有 NVIDIA 驱动的情况下禁用可见 GPU，不等同于物理无 GPU/无驱动电脑测试。
- 未逐项测试 Windows 10、其他驱动/GPU/CPU、其他浏览器、只读介质及 SmartScreen 交互。EXE 未做商业代码签名。
- 无法据此宣称已在全部干净系统实现完全独立分发；交付包为本机实际验证的便携候选版本。

## 9. 构建过程遇到的问题

1. windowed 运行没有标准输出/输入句柄：应用写日志，FFprobe 显式无窗口和 DEVNULL stdin，实际上传/索引通过。
2. 第一次诊断发现 Ultralytics 配置父目录不存在会退回临时目录：调整到已存在的用户 config，最终实际检查配置文件位置及输出目录。
3. 新设备日志最初假设测试替身有 torch 版本字段，导致 3 个旧测试失败：改为容错读取元数据，原测试未删改，最终 82 项通过。
4. 一次 PyInstaller 构建进程发生原生 Python 0x80000003 异常，Windows 事件记录保留；启用 faulthandler 后重试成功。
   根因尚未确定，脚本保留日志并允许一次重试，没有用替换 CUDA PyTorch 掩盖问题；最终产物运行未复现该崩溃。
5. 首次发布验收脚本把实际 analysis_tasks 表误写为 tasks，读取校验失败；修正驱动查询后完整 GPU/CPU/持久化验收通过，未修改应用数据库算法。
6. 完整包接近 5GB：采用 ZIP64，完整解压 CRC 校验，并生成 SHA256；不强塞入 onefile，不裁减必要 CUDA DLL。

## 10. 使用、许可与后续验收

普通用户：完整解压最终 ZIP → 双击 SmartVision.exe → 浏览器使用 → 从控制窗口停止退出。
无需安装 Python/Node/CUDA Toolkit；需 Windows 10/11 x64、现代浏览器，建议 16GB RAM 与至少 12GB 空间并另留视频空间。
GPU 为可选项；使用 CUDA 需兼容 NVIDIA GPU/驱动，驱动不在包内。默认 CPU 回退会明确记录日志。
日常检测/检索使用随包权重和本地资源，无需首次联网下载模型。

开发构建：`./packaging/build_windows.ps1`，先按 requirements-build.txt 安装构建工具，保留已验证 CUDA 环境。
日志、重建、源码 ZIP 权重复制及诊断参数见 packaging/README_PACKAGING.md。

许可证、原始声明及依赖版本在 _internal/licenses，源码在 _internal/frontend/dist/source-code.zip，并可经同源页面下载。
Ultralytics/模型按 AGPL-3.0 提供，此分发版应用源码一起提供；FFprobe 为 GPLv3，保留构建配置与 FFmpeg 8.0.1 源码归档。
许可参考：[Ultralytics 官方说明](https://www.ultralytics.com/license)、[Gyan 构建说明](https://www.gyan.dev/ffmpeg/builds/)、[PyInstaller 官方说明](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)。
FFprobe 静态构建外部库的完整对应源码/构建资料是公开再分发者需持续维护的事项，不能只分发本项目源码并删除第三方声明。
此交付不是 Ultralytics Enterprise 闭源商业许可，也不是对许可证合规的法律认证。
后续仅需补充已列出的真实鼠标/干净系统/实际无 GPU 验收；没有增加本阶段禁止的业务功能。
