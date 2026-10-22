# SmartVision Vue 控制台

Vue 3 Composition API + Vite + TypeScript，官方 create-vue 最小模板，不引入路由、状态管理或 UI 组件库。
所有业务结果来自真实 FastAPI；测试夹具只在 `src/__tests__` 使用。

## 启动

先在项目根目录启动 `.venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`。
本目录运行 `npm ci`、`npm run dev`，打开 http://localhost:5173。
若当前 Codex 环境找不到 npm，从项目根目录运行 `./frontend/run.ps1 install`、`./frontend/run.ps1 dev`。
Vite strictPort 保证开发端口不漂移。Node 版本要求以 package.json engines 为准。

复制 `.env.example` 为 `.env.local` 可配置 VITE_API_BASE_URL 和 VITE_MAX_UPLOAD_BYTES。
VITE_* 配置公开在浏览器中，不能放密钥。API 地址应为后端 HTTP 来源，不填写磁盘路径。
后端默认只允许两个本机 Vite 来源，不配置通配符 CORS。

## 组件与数据流

`DashboardView` 维护当前视频、分页、查询类别、事件和任务 ID，通过明确 props/emits 协调：

- `VideoUploader`：点击/拖拽选择，显示大小，FormData.file 上传，上传成功更新列表和详情。
- `VideoList`：offset/limit 分页，视频元数据、上传时间、状态，选择触发详情读取。
- `VideoPlayer`：原生 HTML5 video 与 Range，使用服务提供的 stream_url；错误时诊断 HTTP 状态。
- `AnalysisPanel`：读取 OpenAPI 默认值与允许范围，只提交许可字段；相同参数缓存、参数变化重建、显式强制重建。
- `TaskProgress` + `useTaskPolling`：2 秒无重叠轮询，取消旧请求，终态停止，网络错误暂停并可手动重试。
- `EventSearch`：六类或全部查询，按时间排序，区分未就绪、旧索引、空结果和错误。
- `EventTimeline`：按视频时长定位，相交事件独立轨道，点击通过播放器暴露的 seek 方法定位并尝试播放。

`api/client.ts` 统一 URL、Fetch、超时、取消与错误解析，`videos.ts`/`tasks.ts` 负责具体 REST 操作。
422 字段错误、409 冲突/未就绪、429 队列满、415 编码不兼容分别展示后端语义。
Fetch 上传显示真实的等待状态，不伪造上传百分比；最终由后端解码验证。
任务恢复优先使用服务端 active_task_id，再用按 API 来源和 video_id 隔离的 localStorage task_id。
刷新仅发 GET。服务重启留下的 failed 任务由用户决定是否重新提交。

数据流：FormData 上传 → video_id/元数据 → stream_url 播放；点击分析 → POST 返回 task_id → 独立 GET 轮询 → succeeded 后刷新详情/列表/事件 → 点击事件定位原视频。
失败重建可以继续显示旧有效索引，并标明使用旧结果。只有 succeeded 表示分析成功。

## 验证

```powershell
npm run type-check
npm run test:unit
npm run build
```

单元测试使用可控模拟输入覆盖异步和错误状态；不把它们作为真实联调证据。
实际浏览器测试不拦截 API，在独立目录启动 Vue、FastAPI 和真实 YOLO：

```powershell
# 从项目根目录，先停止占用 8000/5173 的服务
.\.venv\Scripts\python.exe -m tests.validate_frontend_runtime --source "你的本地视频.mp4"
```

默认使用已安装 Edge 的 headless 浏览器；SMARTVISION_BROWSER_CHANNEL 可改为 chrome。
仅为测试创建独立短 H.264、AVI、黑视频副本；不改变输入和正式库。
测试在隔离上传副本中临时追加数据以触发真实内容校验失败，随后恢复副本，验证失败及旧索引保留。
素材应有足够明显的行人，脚本会断言实际 person 事件非空；模型结果不作为标注真值。
报告、浏览器截图、数据库和日志在 data/outputs/phase4_browser 下，不纳入 Git。

本阶段没有剪辑/导出、自然语言检索、自动转码、用户账户或云部署。
