# 时间段数量统计与停止分析

日期：2026-10-22。只实现用户批准的两个功能，不增加目标跟踪、去重或跨镜头识别。

## 使用

事件检索的类别下新增“出现时间段 / 数量统计”菜单，默认显示数量统计。
选择行人会显示每段“最多 N 人”，其他类别显示“最多 N 个”，点击仍跳转原视频。
数量是该事件内采样帧的检测框数量最大值，不是累计去重人数。采样间隙、漏检/误检会影响结果。
已有检测索引直接聚合，不需要重新运行 YOLO。

开始分析下新增停止按钮。排队任务直接取消并释放队列容量，运行任务返回到安全检查点后停止，
过程中显示“正在停止”，结束显示“已停止”。服务和其他任务继续运行；原视频和上次有效索引保留。
再次分析从头开始。正在单次推理、解码、模型加载或哈希计算时需要等待该调用返回。
索引原子发布开始后拒绝迟到的停止请求（409），防止“显示已停止却替换了旧索引”的竞态。

## 接口与数据

- GET /api/videos/{id}/events 在原有每条事件上增加 max_count；前端同一数据更新卡片和时间轴。
- POST /api/tasks/{id}/cancel 返回 202；新增 cancelled 终态和 cancel_requested 标记。
- 停止未知任务返回 404；已成功/失败/已发布任务返回 409；重复停止已取消任务幂等返回。
- GET /api/tasks/{id} 继续轮询，cancelled 后停止；刷新只恢复 GET，不重复提交。
- 数量查询按视频、类别、事件时间范围分组原始检测，先按 frame_index/timestamp 数框再取最大值。
- SQLite v3 扩展任务状态约束，保留所有原始行；已有 v1/v2 数据库升级前使用 SQLite backup 生成独立备份。
  新数据库不生成空备份，重复启动不重复迁移。用户视频不移动、不修改，不触碰旧版验收数据原件。

## 主要修改

backend/database/migration_v3.sql、repository.py、api_repository.py；services/tasks.py、indexing.py、search.py、videos.py；
schemas/api.py、api/routes.py。停止令牌、队列位置回收和发布锁保持单进程/单 GPU 工作者及原队列上限。

frontend 的 EventSearch、AnalysisPanel、TaskProgress、DashboardView、任务 API、类型、轮询、状态文案与样式。
补充后端 counts/cancel 测试、前端组件/页面/轮询测试，以及真实 EXE + Edge 验收驱动。
packaging 加入 v3 SQL 资源校验和可选 SkipArchive，便于先验收再打最终包。

## 自动化结果

- 后端 **101 passed**（原有 PTS 修复测试保留），1 条原有 Starlette/httpx 弃用警告。
- 前端 **44 passed**；TypeScript 和 Vite 生产构建通过。
- 覆盖逐帧峰值而非总和、空类别、运行/排队取消、旧索引保留、重新分析、队列容量释放、
  取消与发布先后顺序、缓存事件重新合并的取消保护、v2 备份迁移、终态轮询和停止错误展示。

## 真实 EXE 与浏览器验收

交付目录：`F:\数图期末作业\smart-video-search\release\20261022-counts-cancel\dist\SmartVision`。
EXE 为其中的 SmartVision.exe；最终 ZIP 为同一 release 目录的 SmartVision-win64-counts-cancel.zip。
完整文件夹约 4.99 GB、ZIP 约 3.09 GB，精确大小/文件数/SHA256 见 ZIP 相邻 JSON。

证据：`data/outputs/counts_cancel_validation/1792646362213825400`，含 acceptance.json、browser-report.json、
counts-desktop.png、cancelled-desktop.png、独立数据和日志。截图已实际查看；验收数据不进入分发包。

- 从实际 windowed EXE 启动，独立中文/空格数据目录、动态 loopback 端口；不启动源码后端或 Vite。
- 复制旧 v2 验收数据库后启动新版，自动备份和升级至 v3，SQLite integrity_check=ok；旧数据库原件哈希不变。
- Edge 真实浏览器读取已有索引，无模拟 API；person 两段各最多 1 人，car 一段最多 2 个。
  用数据库原始检测的独立分组查询核对 API 峰值，未将跨帧检测结果相加。
- 类别切换、数量/时间段菜单、事件跳转播放和高亮成功。
- 新 EXE 使用 cuda:0 完成 5 分钟真实视频的强制重建（9,001 帧）；片尾 PTS 容错仍工作。
- 另一轮 960/30 FPS 强制重建在已有实际处理帧后点击停止，任务成为 cancelled；旧 events（含 ID/数量）逐项不变。
- 页面刷新恢复已停止状态，没有重复 POST 分析；开始按钮恢复可用。
- 运行任务存在时对第二段黑色视频排队，再通过页面停止排队任务；第一个任务仍 running。
  无有效索引仍返回 409，随后工作者可以接受并成功完成缓存复用任务。
- 两轮专项验收均通过，无未捕获浏览器脚本错误；EXE 正常退出 0，服务及工作线程停止。
- 最终 EXE SHA256：51b02c2cb7d5e37a6b801dfd0367b5dc7c44d899161c6bf88b0c94875233119f。
  PyInstaller 内嵌的 10 个关键模块已逐个与当前源码编译结果核对一致，source-match.json 保留在 release。

## 构建问题与限制

本机 CPython/PyInstaller 构建中再次发生原生异常，日志保留；重试可完成。
实施期间修改了源码后，旧工作目录复用了 PYZ 缓存，产物核对及时发现一处旧模块，未作为最终交付。
最终使用全新 build-work-final-clean 构建，通过代码一致性检查及上述实际验收。
新增 packaging/verify_sources.py，构建脚本今后默认执行该检查，避免把旧缓存误当成新代码。

本轮未重新验证 CPU、第二台无 Python/Node 的电脑、原生鼠标双击/启动器窗口按钮；兼容性边界沿用 PHASE5_VALIDATION.md。
网页中的菜单与停止按钮已由真实 Edge 浏览器点击验证；不是原生窗口鼠标操作测试。
没有自动推送 GitHub，没有打包用户视频、数据库或私密配置。

## 升级与运行

先从旧版控制窗口停止服务，完整解压新版 ZIP，再运行 SmartVision.exe，保留 _internal。
默认继续使用 %LOCALAPPDATA%/SmartVision；无需重新上传或为数量统计重建索引。
旧数据库升级前有独立备份；旧 EXE 不支持 v3，请使用新版，勿交替启动旧版本。
完整源码与许可继续随包提供，所有旧交付目录保留。
