# SmartVision 第三阶段：实施与验收

日期：2026-10-21（Asia/Shanghai）。在现有项目上开发，没有重新创建项目或删除前两阶段成果。
开发前阅读 README、第二阶段报告、核心/索引/检索/数据库及 CLI，实际基线为 **39 passed in 5.91s**。
Git main 仍无提交，已有文件均未跟踪；远程配置保留，本次没有自动提交或推送。

## 1. 文件变更

新增：

- `backend/api/routes.py`：七项 REST 操作。
- `backend/api/upload_limit.py`：在 multipart 落盘前限制原始请求体。
- `backend/schemas/api.py`、`__init__.py`：请求/响应结构及参数边界。
- `backend/services/videos.py`：安全上传、元数据探测、编码判断、文件访问。
- `backend/services/tasks.py`：有界队列、独立工作线程、模型缓存、异常处理。
- `backend/services/process_lock.py`：防止同一数据库的多进程 API 并发。
- `backend/database/api_repository.py`：上传登记、任务与进度持久化。
- `backend/database/migration_v2.sql`：非破坏性迁移。
- `tests/test_api.py`：29 项新测试。
- `tests/validate_http_runtime.py`：实际网络、视频、CUDA 联调。
- 本报告。

修改：main.py、config.py、database/repository.py、services/search.py、api/database 包说明、
requirements.txt、.gitignore、README.md。YOLODetector、采样器、事件合并算法和旧 CLI 算法未重写。

## 2. API

| 方法 | 路径 | 结果 |
| --- | --- | --- |
| GET | /health | 服务/工作者健康状态 |
| POST | /api/videos | UploadFile 上传，201 + video_id/元数据 |
| GET | /api/videos | offset/limit 分页 |
| GET | /api/videos/{video_id} | 元数据、分析/编码状态、播放 URL |
| POST | /api/videos/{video_id}/analysis | 202 + task_id |
| GET | /api/tasks/{task_id} | 持久化任务状态、帧进度、时间、错误 |
| GET | /api/videos/{video_id}/events | category、start_time、end_time；返回 event_id/时间段 |
| GET | /api/videos/{video_id}/stream | 受管理视频，原生字节 Range |

Swagger `/docs` 与 `/openapi.json` 已通过真实 HTTP 请求验证。
公共响应不含服务器绝对路径；视频播放仅用登记 ID，不接受路径参数。
未知视频/任务/文件 404，未形成有效索引 409，重复活动任务 409，队列满 429，
超大上传 413，参数/无效视频 422，扩展名或浏览器编码不支持 415。
Range 满足时 206，语法错误 400，合法但越界 416。

请求 sample_fps=0.25～30（默认 2），imgsz=416/640/960（默认 640），confidence=0.05～1（默认 0.35），
force_rebuild 严格布尔值。拒绝 NaN/Infinity、未知字段和资源过大的参数。
事件窗口采用区间相交语义，不截短原始事件，也不剪辑媒体。

## 3. 后台任务与进度

单个有界 Queue（默认 4 个等待名额）+ 单个 daemon 工作线程，独立于 HTTP 请求和事件循环。
提交返回快照 queued；工作者设置 running，再调用原 IndexingService 和 VideoAnalyzer.scan。
同一视频的活动任务由检查和 SQLite 部分唯一索引共同保护。

状态流为 queued → running → succeeded/failed，时间均持久化为 UTC ISO 字符串。
processed_frames 指扫描的原视频帧；未知总量时 progress/total_frames 为 null。
估计值显式 progress_is_estimate=true，运行中至多 99%；只有正式索引提交完毕才 succeeded/100。
初次加载模型时 running/0% 正常，前端必须依据 status 而不是百分比判断成功。

关键调整：第二阶段扫描期间长期占用 SQLite 写事务，会妨碍第三阶段进度持久化。
现在检测结果流式写入磁盘临时 SQLite 库，扫描/合并成功后用正式库事务原子替换。
这样保留旧索引/失败回滚，同时允许进度和其他短写入提交。没有把结果累计进内存。
发布大量记录时仍会短暂占用正式库写锁，可能出现短时等待。

任务异常写入 failed 和 error_message，工作者继续处理后续任务。
正常关闭停止接收、清空 queued 并标记失败，running 在回调检查点中断回滚。
启动将遗留 queued/running 标记 failed，恢复相应旧索引状态，要求客户端重新提交；不自动重跑。
原生调用 30 秒仍未退出时保留 OS 锁至进程结束，避免启动第二个工作者；硬结束后启动恢复。

## 4. 数据库兼容与上传

SQLite user_version 从 1 事务迁移到 2，可重复初始化。
保留 videos/detections/events；videos 新增 is_uploaded、created_at、video_codec、
browser_compatible、compatibility_message；analysis_tasks 保存状态、参数、进度、错误与时间。
每次调用独立连接，线程间不共享连接；WAL 允许读者在分析时继续查看已提交索引。

原 videos.status CHECK 约束不重建：上传未分析的内部占位记录通过 API 映射为 not_analyzed。
旧 CLI 索引不自动开放文件访问；上传同内容可接管为受管理副本并保留原 ID/有效索引。
同内容上传去重，UUID 内部文件名，客户端原名只作为展示名；分析不会把展示名改为 UUID。

上传文件以 1 MiB 分块落盘，SHA256 同步计算，失败清理自己创建的部分文件。
先 FFprobe 获取视频流，再实际解码首帧；后续损坏帧由完整分析验证。
默认最大文件 512 MiB、multipart 额外开销 64 KiB、4K 像素数、时长 6 小时。
不压缩上传原文件；支持 MP4/MOV/AVI，但播放保守要求 MP4/H.264 8-bit 420 + AAC/MP3/无音轨。
不兼容编码仍可上传分析，播放 415；本阶段不自动转码。

## 5. 8GB 显存与进程限制

所有 YOLO 调用仅由同一线程串行执行，一次一段视频，batch=1。
按权重缓存模型；只变置信度或 imgsz 时调整推理配置，不再复制一份 GPU 模型。
API 限制 imgsz 最大 960、采样率最大 30；CUDA 不可用时继续沿用核心 CPU 回退规则。
上传/查询/播放不加载模型，导入 API 也未导入 torch。
OS 文件锁拒绝同一数据库的第二个服务，明确 --workers 1；不管理外部 CLI/其他应用显存。
未通过同时占满显存来压力测试 OOM，已有核心提示逻辑与异常测试保留。

## 6. 自动化测试

最终 **68 passed, 1 warning in 13.32s**：原有 39 项通过，新增 29 项通过，无失败、无跳过。
警告来自已安装 Starlette TestClient 对 httpx 的弃用提示，不影响业务/断言；没有为消除警告额外更换依赖。

覆盖上传/非法文件/空文件/大小限制/无 Content-Length 超大体、列表详情分页、路径与不存在文件、
202 非阻塞、queued/running/succeeded、持久化中间进度、未知进度、进度不等于成功、
同视频冲突、队列满与单路执行、模型复用、失败后继续工作、强制重建回滚、
重启 queued/running 失败且保留旧索引、旧 CLI 索引接管、v1 重复迁移、
person/car/时间窗口查询、Range/越界、编码提示、CORS、OS 锁及非法非有限参数。
新测试使用模拟检测器，不依赖 GPU 或联网。FFprobe/FFmpeg 时间戳/视频测试需要本地工具。
全部已安装的 55 个包通过 uv pip check。

首次接口测试曾将反向范围 bytes=20-10 误预期为 416；框架正确返回格式错误 400，修正测试后通过。

## 7. 真实视频 HTTP 与 CUDA 联调

来源：[OpenCV 官方 vtest.avi](https://github.com/opencv/opencv/blob/4.10.0/samples/data/vtest.avi)，
实际动态录像而非静态图生成视频；8,131,690 bytes、79.5 秒、10 FPS、768×576。
下载经 GitHub blob 内容摘要校验；SHA256 为
`45cddc9490be69345cbdab64ca583be65987e864ca408038e648db99e10516cf`。
raw 下载域名最初 TLS 中断，改用同一官方仓库 blob API 后下载并校验成功。

独立准备前 6 秒 H.264 测试副本，不改变原 AVI；不是 API 自动转码。
实际启动临时单进程 Uvicorn，通过 loopback HTTP 调用接口和真实 YOLO26n，测试后关闭服务。

| 验收项 | 实测 |
| --- | --- |
| 上传 H.264 | 201，463,819 bytes，6 秒，10 FPS，768×576，browser_compatible=true |
| 提交分析 | 202，约 0.032 秒返回 task_id；实际任务约 5.34 秒完成 |
| 推理设备 | server.log 确认为 cuda:0，RTX 5060 Laptop 8GB，PyTorch 2.9.1+cu128 |
| 进度查询 | 共 53 次状态快照；running 期间可反复查询任务和 /health |
| 索引结果 | 扫描 60 帧，默认 2 FPS 推理 12 帧；73 条原始框、3 个类别事件 |
| person | 0.0～5.5 秒，12 次采样支持 |
| car | 0.0～5.5 秒，12 次采样支持 |
| 重复任务 | succeeded，index_reused=true，约 0.064 秒工作时长 |
| Range | 206，Content-Range: bytes 0-1023/463819；内容与原文件前 1024 bytes 完全一致 |
| 越界范围 | 416 |
| 原 AVI 上传 | 201，超过 1 MiB，msmpeg4v3；不兼容播放明确 415 |
| 原文件 | 联调前后 SHA256 相同 |

第三个类别为模型预测的 truck。以上都是模型输出，未以人工标注评估准确率，不应当成绝对真值。
验证了 HTTP 内容、Range、编码和解码元数据；没有人工浏览器播放画面的验收记录。

最终运行证据：

```text
data/outputs/phase3_http_validation/1792545430917977200/
  report.json           完整请求结果及进度快照
  server.log           Uvicorn 与 CUDA 设备日志
  api.sqlite3          两个上传视频及任务/索引
  browser_fixture.mp4  H.264 测试副本
  uploads/             按字节保存的受管理上传
```

原始样本位于 `data/outputs/phase3_http_validation/1792545194269396100/vtest.avi`。
这些是独立测试库，不影响默认 data/smartvision.sqlite3；全部运行数据、进程锁、缓存及临时索引被 Git 忽略。

## 8. 运行、限制与提交建议

README 已提供 Windows PowerShell 安装、启动、Swagger、curl.exe 上传、提交、轮询、检索和播放命令。
仅增加 python-multipart 0.0.32，没有更换现有 CUDA/PyTorch。

限制：单机单 API 进程/单写入者；发布大索引可能短时等待；未知时长/不可读帧/不支持编码会明确提示。
真实 HTTP 测试为公开视频前 6 秒，未专项验证多小时/多 GB 视频、不同浏览器或真实 GPU OOM。
暂无完整 Vue、认证、公网部署方案、片段剪辑、自然语言/大模型、人脸或跨摄像头功能。
Swagger 默认外部 CDN 需要浏览器网络；可独立使用 OpenAPI/curl。

建议首次提交信息：`feat: implement SmartVision video indexing and background analysis REST API`。
本次未提交或推送，既有未提交成果保留。

## 9. Vue 接入

FormData(file) 上传 → 保存 video_id → 提交分析 → 保存 task_id → 每 0.5～1 秒轮询 →
按 status 显示排队/执行/失败/成功 → 拉取 events 绘制时间轴。
video.src 使用服务器地址 + stream_url，点击事件设置 currentTime；不向 API 提供本地路径。
409/index_not_ready 显示待分析，using_previous_index 显示旧索引，415 显示编码兼容性说明。
开发 CORS 仅 localhost:5173 / 127.0.0.1:5173，可通过环境变量配置。
