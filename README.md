# SmartVision 智能视频分析与检索

片尾时间戳容错修复与新版本验收见 [PTS_HOTFIX_VALIDATION.md](PTS_HOTFIX_VALIDATION.md)。

前后端分离：Vue 3 + Vite 前端通过 REST API 调用 Python 3.11 + FastAPI 后端。
当前支持视频上传、后台分析任务、持久化进度、SQLite 索引、类别检索和原视频 Range 播放，
并保留第一、第二阶段 CLI。第四阶段已实现 Vue 可视化控制台；片段剪辑和大模型检索留待后续阶段，没有 Gradio 依赖。

## Windows 便携版（第五阶段）

已实际构建 PyInstaller onedir 发布版，并从 EXE 验证真实上传、CUDA/CPU 分析、检索、Range 播放、数据持久化和正常关闭。
完整解压发布 ZIP 后运行 `SmartVision.exe`，无需安装 Python/Node 或手动启动服务。
默认用户数据和日志在 `%LOCALAPPDATA%\SmartVision`，不会使用或迁移开发目录中的 data。

最新片尾 PTS 修复版：`release/20261021-pts-hotfix/dist/SmartVision/`；归档：`release/20261021-pts-hotfix/SmartVision-win64-pts-fixed.zip`。
首版交付 `release/20261021-111002/` 保留；修复版真实 EXE 验证及测试结果见 `PTS_HOTFIX_VALIDATION.md`。
目录约 4.99 GB、ZIP 约 3.09 GB，主要体积来自保留的 CUDA 版 PyTorch 运行库。
完整验证及未验证项见 `PHASE5_VALIDATION.md`，普通用户说明见 `packaging/USER_GUIDE.md`，构建说明见 `packaging/README_PACKAGING.md`。
Windows 界面工具未获应用授权，实际鼠标双击与窗口按钮点击尚未验证；未在第二台没有 Python/Node 的干净电脑测试。
自动打开浏览器、真实 EXE 服务运行和诊断方式调用正常退出处理器均已验证，不能将它们等同于上述未执行的鼠标操作。

## 启动可视化控制台（第四阶段）

在项目根目录打开两个 PowerShell 终端：

```powershell
# 终端一：沿用现有 Python 环境，单个后端进程
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 终端二：安装前端依赖并启动
cd frontend
npm ci
npm run dev
```

浏览器打开 http://localhost:5173。依次导入视频 → 开始分析 → 选择类别 → 点击结果或时间轴跳转播放。
默认 2 FPS、640 输入尺寸，置信度等默认值读取当前后端 OpenAPI。
任务只在点击按钮时提交；刷新恢复本机保存的 task_id，不自动创建新任务。
同内容同参数复用索引，参数变化自动重新分析，勾选强制重建可跳过缓存。

本机 Codex 提供的 Node 24.19.0 未将 npm 加入 PATH。可在项目根目录使用兼容启动脚本：

```powershell
.\frontend\run.ps1 install
.\frontend\run.ps1 dev
.\frontend\run.ps1 build
.\frontend\run.ps1 test:unit
```

脚本优先使用 npm；缺少时复用当前 Node 环境的 pnpm 临时运行 npm，不安装全局软件或更改 Python/CUDA。
普通开发环境请使用带 npm 的 Node 24 LTS（支持版本见 frontend/package.json）。

API 地址集中在 `frontend/.env.example`，需要修改时复制为 `.env.local` 并重启 Vite。
VITE_MAX_UPLOAD_BYTES 必须与后端上传限制同步；最终有效性、大小和编码由服务端验证。
现有 CORS 仅允许 localhost:5173 与 127.0.0.1:5173；使用其他来源须显式配置 SMARTVISION_CORS_ORIGINS。
MP4/H.264 8-bit yuv420p + AAC/MP3 或无音轨可播放；其他编码显示兼容性提示，仍可分析检索，本阶段不自动转码。
开发端口严格固定 5173，避免端口自动变化引起 CORS 错误。
完整组件、测试及真实浏览器验证说明见 `frontend/README.md`、`PHASE4_VALIDATION.md`。

## 目录

```text
smart-video-search/
  frontend/               Vue 3 + Vite + TypeScript 可视化控制台
  backend/
    config.py              模型路径、设备、置信度、推理尺寸
    cli.py                 命令行入口
    index_cli.py           分析入库、类别查询、重新合并与中断恢复
    main.py                FastAPI 生命周期、CORS、/health
    api/                   REST 路由与上传请求限额
    schemas/api.py         请求/响应契约
    core/
      video_io.py          流式读取、写入、输出解码校验
      detector.py          一次加载 YOLO、结构化结果、画框
      analyzer.py          编排视频流程、进度及逐帧结果回调
      timestamps.py        FFprobe 原始帧 PTS 与时长，流式读取
    services/
      indexing.py          索引任务、内容指纹、参数缓存与事务协调
      events.py            按类别合并相邻观测
      search.py            独立类别检索服务
      videos.py            上传探测与文件访问
      tasks.py             有界队列、单工作线程、模型缓存
      process_lock.py      API 单进程锁
    database/
      schema.sql           三张表及查询索引
      repository.py        集中管理 SQLite 读写
      api_repository.py    视频登记与任务持久化
      migration_v2.sql     保留旧数据的版本迁移
  data/videos/             输入视频（Git 忽略）
  data/outputs/            输出视频（Git 忽略）
  models/                  yolo26n.pt 本地缓存（Git 忽略）
  tests/test_core.py       无真实 GPU 依赖的自动化测试
  tests/test_indexing.py   采样、合并、查询、回滚及变帧率测试
  tests/test_api.py        上传、任务、迁移与 Range 测试
  requirements.txt
  .gitignore
```

## Windows 环境安装

所有命令在项目根目录执行。先检查现有环境，已有兼容 CUDA PyTorch 时不要盲目覆盖。

```powershell
py -0p
nvidia-smi
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
# RTX 50 系列选择支持 Blackwell 的 CUDA 构建；本项目验证使用 cu128。
.\.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

没有 Python 3.11 时，可以使用 uv 安装独立运行时：

```powershell
python -m pip install uv
python -m uv python install 3.11
python -m uv venv --python 3.11 .venv
# 如果 uv 创建的环境没有 pip，使用以下命令安装依赖。
python -m uv pip install --python .venv/Scripts/python.exe torch torchvision --index-url https://download.pytorch.org/whl/cu128
python -m uv pip install --python .venv/Scripts/python.exe -r requirements.txt
```

模型名依据 [Ultralytics YOLO26 文档](https://docs.ultralytics.com/models/yolo26/)，
CUDA 安装依据 [PyTorch 官方安装说明](https://pytorch.org/get-started/locally/)。
首次运行需联网下载官方预训练权重至 `models/yolo26n.pt`，之后直接复用本地权重。
也可预先将官方权重放入该路径。本项目不训练模型。

## HTTP API 与后台任务（第三阶段）

当前环境只需增加上传依赖，不需要重装 CUDA PyTorch：

```powershell
python -m uv pip install --python .venv/Scripts/python.exe "python-multipart>=0.0.20,<1"
# 自建含 pip 的 venv 也可用 python -m pip install 安装该依赖。
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

打开 `http://127.0.0.1:8000/docs`：POST /api/videos 选择文件上传，记下 video_id；
POST /api/videos/{video_id}/analysis 提交分析；GET /api/tasks/{task_id} 查询状态。
也可访问 `http://127.0.0.1:8000/openapi.json` 获取契约。

| 方法 | 地址 | 用途 |
| --- | --- | --- |
| GET | /health | 服务与工作者状态 |
| POST | /api/videos | multipart 字段 file 上传，返回 201 |
| GET | /api/videos?offset=0&limit=20 | 已上传视频分页，limit 最大 100 |
| GET | /api/videos/{video_id} | 元数据、状态和播放地址 |
| POST | /api/videos/{video_id}/analysis | 返回 202、task_id，不等待分析 |
| GET | /api/tasks/{task_id} | 持久化状态和进度 |
| GET | /api/videos/{video_id}/events | 按类别/时间检索事件 |
| GET | /api/videos/{video_id}/stream | 原视频，支持 HTTP Range |

请求参数：sample_fps 默认 2、范围 0.25～30；imgsz 为 416/640/960；confidence 默认 0.35、
范围 0.05～1；force_rebuild 默认 false。多余、非有限或超限参数返回 422。

### PowerShell 完整示例

服务启动后，另开终端；curl.exe 避免 Windows PowerShell 的 curl 别名。
示例路径是本次真实视频验证生成的 H.264 副本，可替换为自己的视频：

```powershell
$smartvisionBaseUrl = "http://127.0.0.1:8000"
$smartvisionVideo = curl.exe -sS -F "file=@data/outputs/phase3_http_validation/1792545430917977200/browser_fixture.mp4" "$smartvisionBaseUrl/api/videos" | ConvertFrom-Json
$smartvisionBody = @{sample_fps=2; imgsz=640; confidence=0.35; force_rebuild=$false} | ConvertTo-Json
$smartvisionTask = Invoke-RestMethod -Method Post -Uri "$smartvisionBaseUrl/api/videos/$($smartvisionVideo.video_id)/analysis" -ContentType "application/json" -Body $smartvisionBody
do {
    $smartvisionStatus = Invoke-RestMethod "$smartvisionBaseUrl/api/tasks/$($smartvisionTask.task_id)"
    $smartvisionStatus | Select-Object status,progress,processed_frames,total_frames,error_message
    if ($smartvisionStatus.status -in @("succeeded", "failed")) { break }
    Start-Sleep -Seconds 1
} while ($true)
Invoke-RestMethod "$smartvisionBaseUrl/api/videos/$($smartvisionVideo.video_id)/events?category=person"
Start-Process "$smartvisionBaseUrl/api/videos/$($smartvisionVideo.video_id)/stream"
```

事件支持 category、start_time、end_time，后两者按区间相交过滤，返回完整事件边界，按开始时间排序。
暂无有效索引返回 409/index_not_ready；已有旧索引时可查询，并通过 using_previous_index 标记。
客户端必须以 status=succeeded 判断完成；运行中进度上限 99%，未知总帧数时 progress/total_frames 为 null。
processed_frames 是扫描源帧数而非 YOLO 采样数，progress_is_estimate 标记估计值；首次加载模型时 running/0% 正常。

### 队列、数据与重启

有界队列默认 4 个等待名额，仅一个独立工作线程执行推理，模型按权重缓存并串行使用。
同视频 queued/running 返回 409，队列满返回 429。相同内容/参数的有效索引仍复用。
检测数据流式写入磁盘临时索引库，成功后短事务发布，正式库可以随时持久化进度；失败保留旧索引。
迁移自动将 SQLite v1 升级为 v2，不删除旧表记录，增加上传元数据和 analysis_tasks。
只有上传登记的受管理文件可经 API 播放，客户端不能指定服务器本地路径。
旧 CLI 索引不会自动暴露；上传同内容后可接管为受管理文件并复用兼容索引。

必须单 API 进程，OS 锁拒绝同一数据库的第二个进程；不要与 CLI 推理或其他 API 实例同时占用 GPU。
正常关闭时 queued 标记 failed，running 在回调检查点中断；重启把遗留 queued/running 标为 failed，
恢复旧索引状态，不自动重新执行，请显式重新提交。原生推理 30 秒仍未退出时保留进程锁到进程结束。
硬结束可能留下未登记文件或 .index-staging 目录，停服后可检查；有效索引不依赖这些临时文件。

上传 MP4/MOV/AVI，UUID 内部文件名，FFprobe/OpenCV 实际探测，1 MiB 分块保存，失败清理不完整文件。
默认最大文件 512 MiB（multipart 额外开销预算 64 KiB）、最大 4K 像素数、最长 6 小时。
浏览器保守支持 MP4/H.264 8-bit yuv420p + AAC/MP3（或无音轨）；其他编码可以分析，
但 browser_compatible=false，播放返回 415，不自动转码。Range 正常返回 206，越界 416，格式错误 400。

启动前可配置：

```powershell
$env:SMARTVISION_MAX_UPLOAD_BYTES = "536870912"
$env:SMARTVISION_QUEUE_CAPACITY = "4"
$env:SMARTVISION_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
# 可选 SMARTVISION_DATABASE、SMARTVISION_VIDEO_DIR：服务端指定数据库与存储位置。
```

CORS 默认仅上述两项，不允许 *；尺寸/时长限制可通过 create_app(APIConfig(...)) 调整。
旧 videos.status 约束保留，上传但未分析的内部占位状态由公共 analysis_status 明确映射为 not_analyzed。
常见错误：413 调整上传限额；422 检查视频、FFprobe 和参数；409 等活动任务结束或先建立索引；
429 等队列释放；415 检查编码；显存不足关闭其他 GPU 程序或选 imgsz=416。
默认本机单进程、无认证，不作为公网服务部署。Swagger UI 使用默认外部 CDN，脚本无法加载时检查浏览器网络。

实际 HTTP 与 CUDA 测试见 PHASE3_VALIDATION.md，可重现：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tests.validate_http_runtime --source "data/outputs/phase3_http_validation/1792545194269396100/vtest.avi"
# 没有素材时使用 --download-sample，从 OpenCV 官方仓库下载并校验测试视频。
```

## 视频索引与类别查询（保留第二阶段 CLI）

默认 2 FPS、imgsz=640、confidence=0.35。视频只读取，不覆盖、不压缩，不生成稀疏标注视频。
FFprobe 必须可从 PATH 调用。使用 FFprobe 的 best_effort_timestamp_time 对应 OpenCV 解码帧，
将第一帧 PTS 作为视频内 0 秒，保存真实相对 PTS；变帧率视频不会用帧号/FPS 假造时间。

```powershell
# 默认 2 FPS 分析入库，数据库默认 data/smartvision.sqlite3
.\.venv\Scripts\python.exe -m backend.index_cli analyze "data/videos/input.mp4"

# 查询不运行 YOLO，按开始时间排序；可限定 video_id
.\.venv\Scripts\python.exe -m backend.index_cli search person
.\.venv\Scripts\python.exe -m backend.index_cli search person --video-id 1 --json
.\.venv\Scripts\python.exe -m backend.index_cli search car --video-id 1

# 自定义采样率、尺寸和设备（416、640、960 均支持）
.\.venv\Scripts\python.exe -m backend.index_cli analyze "data/videos/input.mp4" --analysis-fps 3 --imgsz 416 --device cuda

# 原始逐帧检测能力：逐帧记录入库，仍不生成标注视频
.\.venv\Scripts\python.exe -m backend.index_cli analyze "data/videos/input.mp4" --every-frame

# 重新分析并原子替换，避免追加重复索引
.\.venv\Scripts\python.exe -m backend.index_cli analyze "data/videos/input.mp4" --force

# 只调整事件规则，不重复模型推理，不删除原始检测记录
.\.venv\Scripts\python.exe -m backend.index_cli rebuild-events --video-id 1 --merge-gap 1.5 --min-samples 3
```

所有子命令支持 `--db "数据库路径.sqlite3"`。类别使用模型输出的 COCO 英文名称，例如 person、car、bicycle、bus。
结果包含视频 ID、名称、类别、开始时间、结束时间、长度以及采样支持次数；不是已剪辑的媒体文件。

### 索引与重复分析

视频以流式 SHA256 内容指纹去重，复制或重命名同一内容仍使用同一个视频 ID。
采样率、置信度、imgsz、权重内容和 Ultralytics 版本组成推理参数签名。
同内容且同参数已完成时，直接复用索引，不加载模型；仅改变合并规则时从原始记录重新合并。
改变推理参数会替换该视频的旧索引，`--force` 可以显式重跑相同参数，不会保留多版本历史。
数据库采用 WAL，在临时索引库中流式保存检测记录；成功才事务发布新的检测及事件，失败回滚。
重新分析失败保留旧成功结果，并在 videos.last_error 中记录错误；首次失败标记 failed。

如果进程被强制终止而状态停在 analyzing，先确认旧进程已停止，再运行：

```powershell
.\.venv\Scripts\python.exe -m backend.index_cli recover --video-id 1
```

### 三张表

- `videos`：内容指纹、视频名称和路径、时长、原始 FPS、宽高、帧数、分析状态和参数、采样数与错误。
- `detections`：视频 ID、原始帧号、实际 PTS、类别 ID/名称、置信度、xyxy 像素坐标；保留每个检测框。
- `events`：视频 ID、类别、首末观测时间、不同采样时间的支持次数。

索引覆盖视频与类别的原始检测时间查询、类别事件排序查询和指定视频类别查询。
所有 SQL 集中在 database/，模型与检索服务没有 SQL。SQLite 文件及其 WAL/journal 被 Git 忽略。

### 事件合并与时间误差

按类别、时间排序，同类相邻观测时间差不超过 `--merge-gap` 时归为一段；默认 1 秒，
对默认 2 FPS 可容忍一次中间漏检。同一时间多个同类框只计一次支持，
默认至少两次不同时间的观测，孤立检测保留在 detections 中但不发布为事件。
边界取第一、最后一次实际观测时间，不人为延长；裁剪到解码视频时长内。

2 FPS 的规则采样网格为 0、0.5、1.0…秒，每个边界选第一帧 PTS 不早于该边界的帧。
当采样率大于原视频帧率时，每帧最多推理一次；不重复采样、不强制添加尾帧、不越过结尾。
对 CFR，边界量化误差通常最多约一个采样间隔加一帧；VFR 还取决于当地帧间距，
漏检会进一步扩大误差，不能当作精确进入/离开时刻。低于 1 FPS 时应相应增加 merge-gap，
例如 0.5 FPS 配合 4 秒合并间隔；孤立出现和采样间短暂出现可能无法形成事件。
缺少原始 PTS 或双解码器帧数不一致时明确失败，不静默用平均 FPS 替代。
时长优先结合容器声明和最后解码 PTS + 帧时长；缺失帧时长时用原始平均 FPS 估计尾部，
并在 videos.estimated_tail 标记。索引同时解码 OpenCV 与 FFprobe，增加少量 CPU/I/O 成本，内存保持流式。

YOLO 结果是模型预测，连续多个误检仍可能形成事件；空查询也不证明目标绝对不存在。
本阶段只表示类别出现，不跟踪身份。原始文件路径需要由用户保持可用，数据库不保存视频副本。

## 标注视频导出（保留第一阶段逐帧模式）

将视频复制到 `data/videos`，支持包含空格及中文的路径，用引号包裹。

```powershell
.\.venv\Scripts\python.exe -m backend.cli "data/videos/input.mp4" "data/outputs/input_detected.mp4"
.\.venv\Scripts\python.exe -m backend.cli "data/videos/input.mp4" "data/outputs/input_cpu.mp4" --confidence 0.5 --device cpu
.\.venv\Scripts\python.exe -m backend.cli "data/videos/input.mp4" "data/outputs/input_cuda.mp4" --device cuda
```

`auto` 优先 CUDA，否则 CPU；显式指定 `cuda` 不可用时报告错误。
每个 detector 实例只加载一次模型。默认 640、置信度 0.35、batch 1，无并行多路推理。
遇到显存不足给出明确提示，可关闭显存占用程序或改用 CPU。
CLI 显示元数据、设备、处理进度、分析及校验耗时、输出位置。
用本地视频播放器打开输出 MP4。已有输出不会被覆盖；错误退出码 1，取消为 130。

输出以 mp4v 编码、保持解码帧顺序、原始 FPS 与尺寸；逐帧写入并全量解码校验，
验证通过后才发布最终文件，失败清理本次创建的临时文件。
OpenCV 仅处理画面，**输出不保留音轨**；本阶段不做 FFmpeg 音轨复用或剪辑。
该导出路径将变帧率输入按读取到的 FPS 转成恒定帧率；它不建立数据库索引。
第一阶段旧回调时间为 frame_index/FPS，第二阶段索引必须通过 index_cli / IndexingService 走原始 PTS 扫描。
mp4v 对奇数尺寸可能裁剪，因此明确拒绝奇数宽高，避免改变原视频分辨率。
输入总帧数是容器元数据，部分受损/特殊容器可能不准确；提前结束会报告错误。
MP4/mp4v 可由常见本地播放器播放，浏览器兼容的 H.264 转码留给后续 FFmpeg 阶段。

## 后端与测试

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
Invoke-RestMethod http://127.0.0.1:8000/health
# 另一个终端
.\.venv\Scripts\python.exe -m pytest -q
```

健康响应：`{"status":"ok","service":"SmartVision","version":"0.3.0"}`。
API 启动不导入 torch/ultralytics，不下载或加载模型。
实际本机验证证据见 `VALIDATION.md`（第一阶段）和 `PHASE2_VALIDATION.md`（第二阶段）。

第二阶段实际模型与命令行验证可重现：

```powershell
.\.venv\Scripts\python.exe -m tests.validate_index_runtime
```

该脚本复用第一阶段测试视频，测试 2 FPS、3 FPS/416、逐帧/960、重复查询、强制替换和黑色视频。
通用 pytest 测试不需要联网、模型或 GPU；时间戳集成测试需要 FFprobe，VFR 生成测试需要 FFmpeg。

## Vue 接入契约

Vue 用 FormData 的 file 字段 POST /api/videos，保存 video_id 和返回的 stream_url。
提交分析参数后保存 task_id，每 2 秒 GET /api/tasks/{task_id}，按 status 区分排队、执行和成功/失败。
成功后 GET /api/videos/{video_id}/events?category=person 绘制时间轴；点击事件可设置 video.currentTime=start_time。
video 元素的 src 指向服务地址加 stream_url，浏览器自行发送 Range；不把服务器本地路径传入 API。
遇到 409/index_not_ready 显示“待分析”，using_previous_index=true 明确显示旧结果，415 显示编码提示。
未来片段导出还没有 API；本阶段也没有自然语言查询。内部仍由 IndexingService 和 SearchService 复用核心算法。

`on_start(VideoInfo)` 提供元数据，`on_progress(Progress)` 更新任务状态；
核心 `scan` 的 `on_frame(FrameResult)` 已由索引服务连接到 SQLite 写入器，包含真实采样时间与 `Detection` 列表。
`Detection` 含 class_id、class_name、confidence、xyxy 像素坐标；回调可以使用 dataclasses.asdict。
索引服务返回 `IndexSummary`（video_id、是否复用、采样帧数、检测数、耗时）；
旧标注导出返回 `AnalysisSummary`（输出路径、帧数、检测数、耗时）。
分析器不累积整个视频的检测结果，回调异常会中断任务并清理临时视频。
当前通过任务 REST API 轮询进度，后续按需增加推送。
旧 `analyze(frame_interval=...)` 仅属于兼容的导出接口；新索引使用 `scan(analysis_fps=...)`，不调用编码器。
