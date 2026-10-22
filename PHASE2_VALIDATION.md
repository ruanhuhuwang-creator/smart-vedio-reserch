# SmartVision 第二阶段实施与实测

日期：2026-10-11（Asia/Shanghai）。在现有项目中继续开发，保留第一阶段代码、权重和测试数据。
开始时第一阶段 15 项测试通过；Python 3.11.17、PyTorch 2.9.1+cu128、Ultralytics 8.4.175、
OpenCV 4.14.0、FFmpeg/FFprobe 8.0.1 和 RTX 5060 Laptop CUDA 均可用，没有重新安装依赖。

## 实际文件变更

新增：

- `backend/core/timestamps.py`：流式原始 PTS 与视频时长读取。
- `backend/index_cli.py`：分析入库、搜索、重建事件、中断状态恢复。
- `backend/database/schema.sql`、`repository.py`：三张表、索引与原子数据访问。
- `backend/services/indexing.py`、`events.py`、`search.py`：索引协调、合并、类别检索。
- `tests/test_indexing.py`、`validate_index_runtime.py`：单元/集成测试与实际模型验证。
- `PHASE2_VALIDATION.md`：本报告。

修改：

- `backend/config.py`：2 FPS 默认配置、合并参数和默认数据库路径。
- `backend/core/analyzer.py`：独立的 `scan` 原始 PTS 采样路径，不写输出视频。
- `backend/core/video_io.py`：允许索引路径将容器帧数视为参考值；由双解码器交叉验证实际帧数。
- `backend/cli.py`：保留第一阶段导出，增加 `--imgsz`。
- `backend/database/__init__.py`、`backend/services/__init__.py`：更新模块说明。
- `.gitignore`：忽略 SQLite 数据和日志。
- `README.md`、`frontend/README.md`：更新当前能力、命令与后续前端安排。

检测器及 FastAPI 入口沿用第一阶段；requirements.txt 未改变。没有完整 Vue 页面、上传接口、视频剪辑、
大模型、Gradio、Redis 或复杂任务队列。Git 远程地址保留，本次未提交或推送代码。

## 数据流

`index_cli analyze → IndexingService → 内容 SHA256/参数签名 → videos 认领状态`

`VideoReader/OpenCV 逐帧画面 + VideoTimestamps/FFprobe 显示顺序 PTS → 时间网格采样 → YOLO → FrameResult`

`IndexWriter.add_frame → detections（逐帧事务写入）→ 类别观测合并 → events → videos.completed → 提交事务`

同内容同推理参数完成后，重复分析直接复用，不重新加载模型。更改合并参数只重新合并。
更改采样率/置信度/imgsz/权重/模型版本或使用 force 会原子替换原有检测及事件，不追加重复记录。
失败回滚，保留上一次成功的原始记录和事件；首次失败标记 failed。强制终止后可明确 recover。
默认数据库为 `data/smartvision.sqlite3`。测试使用单独数据库，未污染默认库。

## 三张表与合并规则

| 表 | 主要数据 |
| --- | --- |
| videos | 内容指纹、名称/路径、时长/FPS/分辨率/帧数、分析状态、推理参数、采样数、时间戳来源、错误 |
| detections | 视频 ID、原始帧号、真实相对 PTS、类别 ID/名称、置信度、xyxy 坐标；每个框一条 |
| events | 视频 ID、类别、首末观测时间、不同采样时间的支持次数 |

索引：视频/类别/时间的 detections 索引、类别/开始时间的 events 索引、视频/类别/开始时间的 events 索引。
内容指纹唯一约束去重，外键启用，SQLite WAL；初始化与每次索引替换都是事务。
SQL 全部位于 database/，查询由 SearchService 调用 Repository；查询结果按时间排序。

合并按 `(类别, 时间)` 排序，同类别相邻时间差 ≤ merge_gap（默认 1 秒）连接为一段。
默认 2 FPS 时可容忍一次中间漏检。同帧多个同类框去重计数，默认至少两个不同时间的采样支持。
孤立误检仍保存在 detections，但不发布为可靠事件；事件只取首末实际观测，不延长、不越过视频时长。
这些是类别出现的估计区间，不表示同一个人的身份，也不保证检测正确。

## 实际验证结果

最终自动化测试：**39 passed in 3.51s**，无失败、无跳过。包括原有 15 项与新增 24 项。

| 测试 | 实际结果 |
| --- | --- |
| 第一阶段回归 | 原 CLI CUDA 逐帧导出 24 帧、120 个框；FPS 12、640×480；全量解码验证通过 |
| 默认 2 FPS | 现有 2 秒、24 帧视频采样 4 帧，PTS 为 0、0.5、1.0、1.5 秒；保存 20 条检测及 2 个类别事件 |
| person 查询 | 视频 1/example_clip.mp4，0.0–1.5 秒，长度 1.5 秒，4 次不同时间观测支持 |
| 重复分析/重复查询 | 同一视频 ID 不变，检测/事件数不变；日志明确复用索引，未加载模型；服务耗时从首次 5.52 秒降至复用 0.04 秒 |
| 3 FPS / imgsz 416 | 采样 6 帧，PTS 为 0、0.333333、0.666667、1、1.333333、1.666667；30 条检测、2 个类别事件 |
| 强制重新分析 | 同一 ID、记录数仍为 30，不重复追加 |
| 逐帧 / imgsz 960 | 采样全部 24 帧，保存 120 条检测、2 个类别事件 |
| 事件重建 | gap=0.1 时无 person 连续事件，gap=1 时恢复；原始检测记录未变，没有模型推理 |
| 负例黑色视频 | 2 次采样，0 检测、0 事件；person 查询返回空列表 |
| 源视频保护 | 分析前后 SHA256 一致；索引扫描不生成标注 MP4 |
| 检索与模型隔离 | 查询进程未导入 torch，多个搜索不重新分析视频 |
| 短暂漏检 | 模拟 person 在 0、0.5、1.5 秒出现，gap=1 合并成一段；gap=0.6 不跨过缺口 |
| 孤立检测 | 同帧两个/多个框不构成两次支持，不生成连续事件；原始框保留 |
| 失败重跑 | 模拟推理中途异常，事务回滚，旧 detections 和 events 完整保留，last_error 有记录 |
| 非整数帧率 | 29.97 FPS 源视频在原始第 0、15、30 帧采样，记录真实 PTS，尾部不越界 |
| VFR / B 帧 | 原始 PTS 为 0、0.1、0.2、0.3、0.7、1.1 秒；2 FPS 选取 0、0.7、1.1，并未使用帧号/平均 FPS |
| 错误时间戳 | 缺失 PTS、重复 PTS 明确失败，非零原始 PTS 正确归一到视频相对时间 |
| FFprobe 缺失 | 清晰报告依赖缺失，视频状态 failed，无错误检测/事件残留 |
| 数据库检索 | 空结果、类别过滤、指定视频、时间排序、参数化 SQL 查询均通过 |
| /health 回归 | 原有自动化 HTTP 测试继续通过，FastAPI 入口未修改 |

变帧率测试曾发现容器声明 0.6 秒，但最后一帧 PTS 为 1.1 秒，帧持续 0.1 秒。
现在时长结合实际解码 PTS + 帧时长，避免将尾部有效帧错误排除；该回归测试已通过。

### 实测产物

实际模型验证使用已有的 `data/outputs/validation/example_clip.mp4`（官方图片生成的合成视频）。
完整第二阶段证据保存在：

```text
data/outputs/phase2_validation/1791691314754705300/
  index.sqlite3
  report.json
  cli.log
  black.mp4
```

数据库中视频 ID 1 已恢复为默认 2 FPS/640 索引；视频 ID 2 是黑色负例。
兼容导出回归位于 `data/outputs/phase2_export_regression/legacy_detected.mp4`。
全部运行产物及数据库被 Git 忽略。

## 直接运行命令

在项目根目录运行已有示例，无需下载新视频或模型：

```powershell
.\.venv\Scripts\python.exe -m backend.index_cli analyze "data/outputs/validation/example_clip.mp4"
.\.venv\Scripts\python.exe -m backend.index_cli search person --video-id 1 --json
```

查看本次已经生成的验证数据库，无需重新推理：

```powershell
.\.venv\Scripts\python.exe -m backend.index_cli search person --video-id 1 --json --db "data/outputs/phase2_validation/1791691314754705300/index.sqlite3"
```

复现自动化与实际模型验证：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tests.validate_index_runtime
```

## 限制与未验证项

- 没有真实监控录像。本次实际 YOLO 数据来自现有合成短片和生成的黑色视频；真实进出场景与真实漏检未验证，规则使用可控模拟序列测试。
- 2 FPS 边界存在约 0.5 秒采样量化误差，另有原视频帧间距和漏检误差；事件是近似观测边界。
- 短于采样间隔的出现可能完全漏掉，单次出现被保留为原始记录但不形成事件；持续误检仍可能形成事件。
- 不跟踪人员身份，不输出物理剪辑文件。用户需保持原视频路径和内容可用。
- 低采样率应配合更大的 merge_gap。高于源帧率时每帧最多分析一次。
- 原始 PTS 不可用时失败；缺失帧时长时尾部使用平均帧率估计并标记 estimated_tail。FFprobe 与 OpenCV 双解码增加 CPU/I/O 消耗。
- SQLite 当前为单写入者，索引任务期间长事务写入；没有复杂并发调度。多小时/多 GB 视频与真实显存耗尽未专项验证。
