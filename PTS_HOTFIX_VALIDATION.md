# 片尾 PTS 异常修复记录

日期：2026-10-21。此修复不转码、不修改用户视频，不修改数据库结构和任务并发。

## 原因与处理边界

用户的 300.033333 秒、1920×1080、30 FPS 监控视频包含 9,001 帧。
FFprobe 完整解码确认第 8,999、9,000 帧（从零计数）的 PTS 分别为 299.9 和 300.0 秒，
而此前最大 PTS 已达 300.0 秒，原程序严格拒绝导致整个索引回滚。

现在仅容忍连续末尾的最多 3 帧重复/倒退 PTS；每帧回退不得超过 0.2 秒，
位置须在容器声明的最后 0.5 秒内且不超过总时长最后 10%。未知时长、缺失/非有限时间戳、
视频中途倒退、大幅倒退、异常之后又出现递增帧、超过帧数预算仍失败并回滚。
异常尾帧不做推理、不写检测记录；仍逐帧消费 OpenCV 和 FFprobe 输出、统计扫描进度，
因此不会把下一帧画面与错误时间配对。不修改正常帧 PTS，不用 frame_index/FPS 补造时间。
每个跳过帧均写 WARNING；数据库沿用 estimated_tail 标记。极短片尾的检测覆盖会少最多 3 帧。

## 修改文件

- backend/core/timestamps.py：FrameTimestamp.indexable、末尾容错边界、警告与跳过计数。
- backend/core/analyzer.py：跳过对应帧的索引推理，保留扫描计数；ScanSummary 返回计数。
- tests/test_timestamp_tail.py：真实失败序列、非零起点、边界拒绝、帧对应与稀疏/逐帧测试。
- tests/validate_timestamp_hotfix.py：从 EXE 上传、真实 CUDA 分析、检索、复用、Range 和退出验收。
- 本记录及 README。

## 已完成验证

- 后端 **93 passed**，1 条原有 Starlette/httpx 弃用警告。
- 完整扫描问题视频副本，9,001/9,001 帧，跳过 2 个异常尾帧；分析 601 帧，cuda:0，约 49.87 秒。
- SQLite 成功保存 665 条检测、3 个事件；person 为 2 段，car 为 1 段（仅模型预测）。
- 输入 SHA256 af715f14a1fb6364004d37b54ef0aefc59d13f9149df077c9e53c90c8851c115，分析前后不变。
- 证据在 data/outputs/pts_hotfix/1792592202442482600，均不进入交付包。

## 新 EXE 验收与交付

- 新产物：release/20261021-pts-hotfix/dist/SmartVision/SmartVision.exe。
- 最终 ZIP：release/20261021-pts-hotfix/SmartVision-win64-pts-fixed.zip，大小和 SHA256 见相邻 JSON。
- 从实际 EXE 启动独立数据目录，无 Vite、无开发虚拟环境 PATH，真实上传同一问题视频。
- 任务 cfc19d23af8c4a0d9e0bc8be8142baeb 成功，扫描 9,001/9,001 帧，耗时约 80.98 秒；
  CUDA:0，索引采样 601 帧，2 条片尾警告，数据库 completed/estimated_tail=1。
- person 事件 126–132.5、281.5–300 秒；car 事件 0–300 秒，均为模型预测。
- 再次提交相同参数返回成功并复用索引；Range 0–127 返回 206/128 字节。
- 输入哈希不变，诊断退出正常返回 0；证据在上述目录下 frozen-validation/acceptance.json。
- 前端 38 项测试通过，类型检查及 Vite 生产构建通过；后端 93 项通过。
- 打包首次发生 CPython/PyInstaller 原生 access violation（-1073741819），保留 build.log，
  脚本重试成功，日志为 build.log.retry.log。根因未确定；新 EXE 分析过程未复现。
- 本轮未重新测试 CPU/干净电脑/原生鼠标操作；首版 CPU 验证和其他限制见 PHASE5_VALIDATION.md。
  该历史报告指向首版交付物；本记录指向修复版。未自动推送 GitHub。

升级时先从旧版控制窗口停止服务，完整解压新版并运行其 EXE。
默认仍使用同一个 %LOCALAPPDATA%/SmartVision，现有上传和索引不迁移、不删除。
选择此前失败的视频重新分析即可；不需要重新上传或转码。
