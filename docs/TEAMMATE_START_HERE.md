# 队友从这里开始读源码

这是“先知道程序在做什么，再读代码”的入口。不需要先懂 YOLO 的数学原理。
普通使用软件只需解压 EXE 包；下面是想学习或修改源码时的路线。

## 先认清几个词

| 代码中的词 | 通俗解释 |
| --- | --- |
| 前端 / frontend | 浏览器里看到的按钮、视频和结果列表，用 Vue 写 |
| 后端 / backend | 接收请求、管理视频、安排分析、查询数据库，用 Python 写 |
| API / 路由 | 前后端约好的服务地址，例如 `/api/videos` |
| 帧 / frame | 视频中的一张图片；30 FPS 表示每秒约 30 张画面 |
| 推理 / inference | 让已经训练好的模型看一张图，返回检测结果；这里不训练模型 |
| 检测框 / Detection | 一个目标的类别、置信度和矩形坐标 |
| 索引 / index | 提前保存“哪个视频、第几秒、有什么目标”，方便以后直接查 |
| PTS | 每帧真正的播放时间，防止变帧率视频按帧号计算时跳错位置 |
| 回调 / callback | 把函数作为参数传进去；内部有进度或结果时调用它通知外部 |
| 事务 / transaction | 一组数据库操作，要么全成功，要么撤销，避免只更新一半 |
| 轮询 / polling | 浏览器每隔一段时间问后端“任务现在怎样了” |
| ref / computed / watch | Vue 的可更新变量、由变量计算的值、变量变化时执行的动作 |

## 文件夹怎么分工

```text
frontend/src/
  views/DashboardView.vue        页面总协调，建议前端从这里读
  components/                   上传、播放器、分析面板、结果列表等小部件
  api/                          把 HTTP 请求集中封装起来
  composables/useTaskPolling.ts  定期查询任务状态
backend/
  main.py                       组装后端、启动和关闭资源
  config.py                     参数默认值和文件路径
  api/routes.py                 哪个 URL 调哪个服务
  schemas/api.py                请求/响应有哪些字段、哪些值合法
  core/                         读视频、取时间戳、检测单帧、协调读帧循环
  services/                     上传、建索引、合并事件、搜索、后台任务
  database/                     SQLite 表结构和 SQL 读写
tests/                          用例：看输入什么、预期得到什么
packaging/                      Windows EXE 启动器和构建流程，最后再读
```

路径均相对于项目根目录。不需要照着某台电脑的 D/F 盘路径修改代码。

## 顺着一次真实操作读下去

### 1. 点击上传

`VideoUploader.vue` 选择文件 → `api/videos.ts` 用 FormData 发到 `POST /api/videos`
→ `api/routes.py` → `services/videos.py` → `database/api_repository.py`。

前端检查大小和扩展名只是提前提示。后端还会分块接收、计算内容指纹、用 FFprobe/OpenCV 检查真实画面。
上传登记后返回 `video_id`，工作台据此刷新列表和详情。浏览器只拿视频流 URL，不读取服务器磁盘路径。

### 2. 点击开始分析

`AnalysisPanel.vue` 提交参数 → `DashboardView.vue` 的 `submit`
→ `api/videos.ts` 的 `analyzeVideo` → `POST /api/videos/{id}/analysis`
→ `TaskManager.submit` 返回 `task_id`。

HTTP 202 只代表“接单成功”，不是“分析完成”。后台只有一个分析工作线程，依次处理队列中的任务。
同一视频已有任务时返回 409，队列满时返回 429，网页应提示而不是无限重发。

### 3. 后台看视频并存结果

`TaskManager._execute` → `IndexingService.analyze` → `VideoAnalyzer.scan`。

`VideoReader` 用 OpenCV 逐帧解码，`VideoTimestamps` 用 FFprobe 取每帧对应的秒数。
默认 2 FPS 是“每秒约选两帧送模型”，不是把原视频变成 2 FPS。所有画面仍需顺序解码；原视频不改动。
`YOLODetector.detect` 返回检测框，`on_frame` 回调交给 `IndexWriter.add_frame` 写临时数据库。
模型通过检测器缓存复用，不是每读一帧就加载一次权重。

完成后合并事件，再在一个事务里发布到正式数据库。失败或停止时，不用半成品覆盖以前成功的索引。
相同内容和检测参数可以复用已有检测；只调整合并参数时，可从原始检测重新合并，不必重跑模型。

### 4. 网页更新进度

`useTaskPolling.ts` 用 `GET /api/tasks/{task_id}` 初始每 2 秒查询一次。

| 状态 | 含义 |
| --- | --- |
| queued | 排队中 |
| running | 正在执行 |
| succeeded | 成功，只有这个状态代表本次分析成功 |
| failed | 失败，需查看原因 |
| cancelled | 用户停止，本次未完成索引未发布 |

进度是估算，不能只看 100%。切换任务时会停止旧轮询，并丢弃旧请求的迟到响应。
刷新页面只恢复已有任务 ID 并 GET 查询，不重新 POST 创建任务。

### 5. 查询行人并跳转

选 person → `DashboardView.search` → `GET /api/videos/{id}/events?category=person`
→ `SearchService.search` → `IndexRepository.search` 从 SQLite 查结果。

搜索不再读视频或跑 YOLO。点击结果会调用 `jump` → `VideoPlayer.seek(start_time)`，
设置 HTML5 video 的 `currentTime` 并尝试播放。视频数据通过 `/stream` 获取；Range 支持浏览器分段读取。
415 是视频编码不适合浏览器播放，不代表文件不存在。没有可用索引时的 409 也不等于“没有目标”。

## 数据库和数量统计，用例子理解

| 表 | 一行表示什么 |
| --- | --- |
| videos | 一份视频资料：名称、路径、时长、尺寸、分析信息等 |
| detections | 某一采样帧中的一个检测框，含类别、秒数、坐标和置信度 |
| events | 某一类别连续出现的一段时间 |
| tasks | 一次分析任务的参数、进度、状态和错误等；这是 API 阶段新增的表 |

假设 120、120.5、121 秒分别检测到 2、3、2 个人：

- 原始检测保存 7 条框记录，方便后续重新计算。
- 合并器看见的是三个“person 出现时刻”，同一秒多个框不会变成多次时间证据。
- 默认允许相邻出现时刻相差最多 1 秒，且至少两个不同采样时刻支持一段事件。
- 因而得到约 `[120,121]` 秒事件，数量显示 **最多 3 人**，不是 7 人。
- 不追踪身份，无法判断三次画面是否是同一批人；“最多 3 人”不是去重总人数。

事件边界是首次和末次检测到的采样时间，不向两边猜测扩展。2 FPS 的理想采样间隔是 0.5 秒，
边界存在采样误差；变帧率、漏检和合并容忍间隔还会影响精度，不能视为精确的进出场时刻。
只有一次的孤立检测仍保留在 detections，但默认不会形成事件。

## 为什么停止分析不是立即杀进程

`cancelTask` 发请求 → 后台设置当前任务的停止信号 → 运行流程到检查点才抛出取消异常并回滚。
正在模型加载、单次推理或解码时需要等调用返回，所以“正在停止”与“已停止”不是同一个状态。
最终提交和接受取消共用一把锁；若结果已提交，迟到的停止会返回 409，不能显示已取消却悄悄替换索引。
停止一个任务不会关闭整个服务，也不会清空其他任务。

## 建议怎么学和改

1. 先读 `core/detector.py` 的 `Detection` 和 `detect`，看“一张图怎样变成列表”。
2. 读 `core/analyzer.py` 的 `scan`，看结果怎样通过回调逐帧流出。
3. 读 `services/events.py` 和 `tests/test_indexing.py`，拿纸模拟两三条时间记录。
4. 读 `database/repository.py` 的 `replace_index`、`search`，理解暂存和数量统计。
5. 读 `services/tasks.py` 和 `tests/test_counts_cancel.py`，理解排队与停止。
6. 最后按上文 URL 路线读 `api/routes.py`、`DashboardView.vue` 和子组件。

先修改页面文字或颜色练手，再尝试参数/字段变更。改 API 字段时，同时核对 Pydantic Schema、
前端 types/api.ts、API 调用和组件使用处。不要把 SQL 放进 YOLO 模块，也不要在搜索中重新跑模型。

安装与运行命令以根目录 README 为准；首次安装先确认 PyTorch 的 CUDA/CPU 版本，不要盲目覆盖。
测试方法见 [学习路线](LEARNING_GUIDE.md)，各阶段演进见 [迭代记录](../CHANGELOG.md)。
本次仅增加讲解性注释和文档，不需要重新打包之前发给队友的 EXE。
