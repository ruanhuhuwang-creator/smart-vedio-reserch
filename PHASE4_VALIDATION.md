# SmartVision 第四阶段：Vue 可视化前端实施与验收

日期：2026-10-21（Asia/Shanghai）。基于现有前三阶段继续开发，没有替换 YOLO、SQLite 索引、事件合并或后台任务算法。

## 1. 实施前检查与文件清单

已阅读 README、PHASE3_VALIDATION、FastAPI 路由、Pydantic Schema、视频管理及任务/索引服务；
运行时前端还读取真实 `/openapi.json` 的分析默认值与参数范围。
原 frontend 仅有预留 README。Git main 尚无正式提交，现有代码均未跟踪；保留 origin 配置，没有提交或推送。
没有删除已有本地视频、数据库或模型权重。验证使用独立输出目录，不连接正式数据库。

新增：

```text
frontend/
  .env.example
  env.d.ts
  index.html
  package.json
  package-lock.json
  run.ps1
  vite.config.ts
  vitest.config.ts
  tsconfig.json
  tsconfig.app.json
  tsconfig.node.json
  tsconfig.vitest.json
  public/.gitkeep
  e2e/real-backend.mjs
  src/
    App.vue
    main.ts
    style.css
    api/client.ts
    api/videos.ts
    api/tasks.ts
    types/api.ts
    utils/format.ts
    utils/storage.ts
    composables/useTaskPolling.ts
    views/DashboardView.vue
    components/
      VideoUploader.vue
      VideoList.vue
      VideoPlayer.vue
      AnalysisPanel.vue
      TaskProgress.vue
      EventSearch.vue
      EventTimeline.vue
    __tests__/
      fixtures.ts
      client.spec.ts
      polling.spec.ts
      components.spec.ts
      dashboard.spec.ts
      presentation.spec.ts
tests/validate_frontend_runtime.py
pytest.ini
PHASE4_VALIDATION.md
```

修改：根 README.md、frontend/README.md、.gitignore。
pytest.ini 仅将收集范围限制为 tests，防止误扫描历史输出目录和 node_modules，不改变已有测试行为。
.gitignore 保留虚拟环境、模型、视频、运行数据库及输出排除规则，新增前端产物/测试报告/本地环境配置规则；`.env.example` 可纳入 Git。

## 2. 组件关系与界面

`App → DashboardView`，Dashboard 管理选择、请求状态和事件，通过 props/emits 连接七个展示/操作组件。
左侧为上传与分页视频库，中间为原视频播放器和事件时间轴，右侧为分析设置与任务，底部为类别结果。
深蓝灰背景、青绿色强调色，中文界面；窄屏改为纵向布局。

- VideoUploader：点击/拖拽选择、文件名/大小、上传等待与错误，成功通知 Dashboard。
- VideoList：展示 API 元数据，发出 video_id 和分页 offset。
- VideoPlayer：原生 controls/Range，按视频 ID 重建元素，通过 seek 暴露定位/播放能力。
- AnalysisPanel：快速 416、均衡 640、精细 960，采样 FPS、置信度及强制重建。
- TaskProgress：展示后端任务状态、进度是否估计、原视频帧计数、执行耗时及错误。
- EventSearch：六类别/全部查询，显示时间范围与持续时间，结果点击带回完整事件。
- EventTimeline：按时长比例绘制，同类重叠区间也独立分轨，点击调用同一跳转逻辑。

## 3. API 封装与任务恢复

Fetch 统一封装在 api/client.ts：环境变量 API_BASE、来源校验、超时、AbortController、FastAPI 错误解析。
videos.ts/tasks.ts 只提供真实 REST 调用，types/api.ts 对应 backend/schemas/api.py。
没有业务模拟数据、没有直接读取服务器本地路径。

| 操作 | 契约 |
| --- | --- |
| 上传 | FormData 的 file 字段，POST /api/videos，201 VideoResponse |
| 列表 | GET /api/videos?offset=...&limit=8，total/offset/limit/items |
| 详情 | GET /api/videos/{id}，index_available/active_task_id/stream_url 等 |
| 参数 | GET /openapi.json，读取 AnalysisRequest 默认值和边界 |
| 分析 | POST /api/videos/{id}/analysis，202 TaskResponse，立即记录 task_id |
| 进度 | GET /api/tasks/{task_id}，每 2 秒，单个请求完成后再调度 |
| 检索 | GET /api/videos/{id}/events?category=person，events 包络 |
| 播放 | 原生 video 指向 API 返回的 stream_url，浏览器自行发送 Range |

sample_fps 0.25～30、imgsz 416/640/960、confidence 0.05～1，实际默认值来自运行后端。
相同内容/参数可复用索引；参数变化自动重新分析；force_rebuild=true 可强制忽略缓存。
没有改动后端单工作者和队列容量。

轮询只在 queued/running 继续，只有 succeeded 是成功，failed 展示原因；不按 progress=100 判定成功。
切换任务、卸载时取消旧请求及定时器，迟到响应不会覆盖新任务；切换视频也取消旧详情和检索。
请求超时/网络错误暂停轮询并提供手动重试，429 明确提示队列满，不无限自动重试。
409 冲突后只刷新详情并恢复已有任务，不重复提交。
服务端 active_task_id 优先，localStorage 按 API 来源和视频 ID 保存任务；刷新只发 GET，不自动 POST。

409/index_not_ready 与空结果区分；旧有效索引用 using_previous_index/实际状态标记。
415 显示“当前视频编码不受浏览器支持”，保留分析和检索入口；原生播放错误时发一字节 Range 诊断 HTTP 原因。
没有转码功能。Fetch 上传显示真实等待状态，不伪造百分比。
CORS 保持后端现有的 localhost:5173、127.0.0.1:5173 两个来源，没有开放通配符。

## 4. 完整数据流

选择/拖入视频 → 本地初步校验 → FormData 上传 → 后端探测/登记 → 返回 video_id → 更新列表与详情。
播放器使用 stream_url；开始分析发送许可 JSON 参数 → 后端返回排队任务 → 独立轮询 → 成功后刷新详情、列表与事件。
类别查询只读取已建立的 SQLite 索引，不重复运行 YOLO；点击事件/时间轴 → video.currentTime=start_time → 尝试播放并高亮。
重建失败时仍展示此前有效索引并标明来源。采样边界与模型检测都有误差，界面不将结果表述为真值。

## 5. 实际环境与运行命令

验证环境：Node 24.19.0、npm 12.2.0、Vue 3.5.44、Vite 8.3.4、TypeScript 6.0.3、Vitest 4.1.12、Playwright 1.64.1。
本机 Node 来自 Codex 便携运行时，npm 未在 PATH。run.ps1 优先正常 npm，缺少时复用其已有 pnpm 临时运行 npm。
没有全局安装 Node，也没有改动 Python/PyTorch/CUDA 环境。
后端仍为 Python 3.11.17、PyTorch 2.9.1+cu128、CUDA 12.8 可用、Ultralytics 8.4.175，RTX 5060 Laptop GPU。
真实任务日志确认 cuda:0，本地复用 models/yolo26n.pt。

```powershell
# 项目根目录，终端一
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 项目根目录，终端二（本机兼容方式）
.\frontend\run.ps1 install
.\frontend\run.ps1 dev

# 标准 Node/npm 环境也可使用
cd frontend
npm ci
npm run dev
npm run type-check
npm run test:unit
npm run build
```

打开 http://localhost:5173。配置修改方式：复制 frontend/.env.example 为 frontend/.env.local，再重启 Vite。
VITE_MAX_UPLOAD_BYTES 默认 536870912，需与服务端配置保持一致，后端仍作最终校验。
VITE_* 在浏览器公开，不填写密钥。

## 6. 自动化检查结果

| 检查 | 实际结果 |
| --- | --- |
| 后端原有回归 | **68 passed**，13.01 秒；1 条原有 Starlette/httpx 弃用警告 |
| 前端 Vitest | **38 passed / 5 files**，2.46 秒 |
| TypeScript | vue-tsc --build 通过，包含应用、配置和测试代码 |
| 完整 npm build | type-check 与 Vite 生产打包均通过 |
| 生产资源 | JS 95.35 kB（gzip 36.75 kB），CSS 14.60 kB（gzip 4.01 kB） |
| 本机 run.ps1 | build 与 test:unit 已实际执行通过 |

单元测试涵盖 FormData、HTTP 错误、超时/网络、非法来源、任务状态流、progress=100/running、失败停止、手动重试、切换/卸载取消、迟到响应、刷新恢复不重复 POST、上传状态、415、跳转播放、旧索引、空结果、重叠轨道、参数范围、分页边界和时间进位。
这些模拟输入仅用于单元测试，不作为真实联调结果。

开发时首次 npm 下载发生 ECONNRESET，使用缓存重试后成功。首次 pytest 自动收集误入旧输出目录，加入 testpaths 后全部通过。
首次浏览器脚本错误预期“参数变化会失败”，实际后端自动重建；已纠正脚本与界面说明，最终完整实测通过。
没有把这些早期失败计入最终成功结果，也未为适配测试修改后端算法。

## 7. 真实浏览器联调结果

使用已安装 Microsoft Edge 的 headless 浏览器，访问真实 localhost:5173 和 127.0.0.1:8000。
独立 SQLite/上传目录启动真实 API，使用本地 OpenCV 行人录像片段（前阶段已验证来源）和生成的黑视频。
未拦截 API、未使用模拟 detector。最终一次完整测试 **16 项检查通过**，无未捕获 JavaScript 错误。

证据目录：`data/outputs/phase4_browser/1792547428703136400/`。
其中 browser-report.json 保存真实响应、任务与事件；backend.log 保存 CUDA 和 HTTP 日志，desktop.png/mobile.png 保存截图。
原始输入 SHA256 `d5f009ed17df73106071fe8bf0f43bde50a0e3596effd9ed439ce317ae64f054`，测试后校验未改变。

- 无效视频上传真实返回 422，界面显示解码验证错误；有效 H.264 视频上传 201，列表/详情正常。
- HTML5 video 加载真实 768×576、10 FPS、6 秒视频；Range bytes=0-127 返回 206 和正确 Content-Range。
- 后台任务真实经历 queued/running/succeeded；首次分析约 5.98 秒，扫描 60 帧，CUDA 推理。
- person 与 car 均实际查询成功，各返回 0～5.5 秒事件；这是模型预测，不是人工标注准确率结论。
- 点击结果和时间轴完成定位、原生播放及高亮。
- 页面刷新恢复 task_id，没有多发分析 POST；同参数任务 index_reused=true。
- 只对隔离上传副本临时追加字节，真实内容校验导致 failed，界面展示错误且仍可查询旧索引；副本随后恢复。
- 改成 3 FPS 自动重新分析，index_reused=false；显式强制重建也成功。
- 3 秒黑视频实际分析 30 帧，person events=[]，显示空结果。
- AVI/mpeg4 副本上传成功，真实 stream 返回 415，界面显示编码不支持，没有伪装为不存在。
- 1500 像素桌面、390 像素窄屏均完成截图并人工查看，窄屏无横向溢出。

409 活动任务冲突、429 队列满、超时、慢响应切换等在前端可控测试及现有后端测试中覆盖；
本次浏览器完整链路没有人为填满 GPU 队列来制造真实 429，也未额外制造多标签同时提交的真实 409。
真实 409/index_not_ready 已在上传后检索验证。未宣称所有浏览器或所有编码均已验证。
隔离服务在验证脚本完成后已关闭，运行时锁和数据留在输出目录作为证据。

重现：先停止占用 8000/5173 的服务，再在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m tests.validate_frontend_runtime --source "data/outputs/phase3_http_validation/1792545430917977200/browser_fixture.mp4"
```

脚本会创建独立测试视频，检查原始哈希，完成后关闭自己的服务；不同素材需有可识别行人，否则非空事件断言会失败。

## 8. 范围与限制

未开发剪辑导出、自然语言检索、模型训练、账户、转码或云部署。
支持现有 API 的六类及全部类别查询；事件接口没有分页，前端结果区域可滚动，特别大的索引可能需要后续增加服务端分页。
任务恢复依赖服务端 active_task_id 和本机保存的最近 task_id；后端尚无历史任务列表接口，因此不能跨浏览器恢复所有历史任务。
上传超时为 5 分钟，请求超时不代表服务端一定未完成；应先刷新列表核对，后端按内容指纹去重。
仅验证本机 Edge；Chrome/Firefox/Safari 与更多容器/编码组合未逐项测试。
稀疏采样时间边界、误检和漏检来自现有检测/合并机制，前端不额外推断或补造事件。
