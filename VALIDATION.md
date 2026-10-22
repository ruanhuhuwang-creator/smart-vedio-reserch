# 第一阶段实际验证报告

验证日期：2026-10-11（Asia/Shanghai）。初始工作目录为空且不是 Git 仓库，无旧代码或用户视频被覆盖。

## 环境

| 项目 | 实际状态 |
| --- | --- |
| 原有 Python | 系统 Python 3.12.10，无 torch / ultralytics / fastapi |
| 项目 Python | `.venv/Scripts/python.exe`，CPython 3.11.17 |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU，8151 MiB |
| 驱动 | 610.47；nvidia-smi 显示驱动支持 CUDA 13.3 |
| PyTorch | 2.9.1+cu128，CUDA runtime 12.8，`cuda.is_available() == True` |
| TorchVision | 0.24.1+cu128 |
| GPU 架构 | compute capability 12.0；PyTorch 包含 sm_120 |
| Ultralytics | 8.4.175，真实 yolo26n.pt 预训练检测模型 |
| OpenCV | 4.14.0（包版本 4.14.0.94） |
| FastAPI / Uvicorn | 0.143.0 / 0.54.0 |
| FFmpeg | 8.0.1，ffprobe 与 ffmpeg 解码均执行成功 |

没有修改全局 PyTorch/CUDA 环境。全局安装了 uv，用它下载 Python 3.11 并创建项目独立环境。
CUDA PyTorch 下载较慢并有中断，最终分段获取官方安装包并校验官方 SHA256 后安装。
示例图片首次下载因 IncompleteRead 中断，加入重试后成功；模型官方 GitHub 下载重试后成功。
本地权重 SHA256 与官方 GitHub Release 元数据一致：
`9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef`。

## 最终测试结果

| 测试 | 结果 | 证据 |
| --- | --- | --- |
| 模型加载及图片推理 | 通过 | GPU cuda:0 和 CPU 均识别公交车及 4 人，共 5 个结果 |
| 视频读写 | 通过 | 6 帧亮度递增合成视频，12 FPS、96×64，检查帧序、尺寸、FPS、释放资源 |
| 完整 YOLO 视频分析 | 通过 | 官方示例图片生成 24 帧视频，640×480、12 FPS、2 秒，逐帧分析、画框、编码、解码验证 |
| 视频检测进度 | 通过 | CLI 从 1/24 (4.2%) 到 24/24 (100.0%)，报告 cuda:0、元数据、耗时和输出位置 |
| 输出播放数据校验 | 通过 | ffprobe 确认 mpeg4、24 帧、12/1 FPS、640×480、2.000000 秒；ffmpeg 全量解码退出码 0 |
| 画框检查 | 通过 | 人工查看实际输出视频首帧，公交车与人物有类别、置信度及绿色检测框 |
| 后端健康检查 | 通过 | 真正启动 Uvicorn 子进程，通过 HTTP 调用 /health 返回 200 和预期 JSON，测试后终止服务 |
| 自动化测试 | 通过 | 最终安装环境中 pytest：15 passed in 1.20s，无警告 |
| 环境依赖检查 | 通过 | uv pip check：54 packages，All installed packages are compatible |
| HTTP 与模型隔离 | 通过 | 导入 backend.main 后 torch 不在 sys.modules；PyTorch 安装前健康接口也可启动 |
| CLI 缺失输入错误 | 通过 | 退出码 1；自动化测试另覆盖损坏文件、提前结束、编码器失败、已有输出保护、临时文件清理 |

当前测试没有失败项。首次真实验证曾因示例图片网络下载中断而退出，修复重试后全流程通过。

真实监控视频测试**未执行**，因为当前目录没有用户提供的视频。
真实硬件显存耗尽**未触发**，提示逻辑使用模拟异常验证，实际单路 CUDA 推理成功。
8GB GPU 图片测试峰值 allocated memory 为 76,976,640 bytes（约 73.4 MiB）；
此数值是 PyTorch 当前测试进程的已分配峰值，不代表全 GPU 占用或 CLI 子进程峰值。
长视频稳定性、多编码格式覆盖、变帧率原始 PTS 保真、浏览器 H.264 播放及音轨保留不在本次验证范围。

## 本次真实 CLI 结果

```text
视频: example_clip.mp4 | 时长: 2.00s | FPS: 12.000 | 分辨率: 640x480 | 帧数: 24
推理设备: cuda:0
进度: 1/24 (4.2%) | 2.0s
进度: 24/24 (100.0%) | 2.3s
完成: 24 帧，120 个检测结果 | 总耗时: 5.30s | 分析及输出验证: 2.29s | 推理: 2.21s
```

120 是每帧检测数的总和，并非 120 个独立目标，本阶段没有目标跟踪。

本次产物位于 `data/outputs/validation/`（被 Git 忽略）：

- `report.json`：实际模型结果、环境及输出视频路径。
- `cli.log`：完整命令行日志。
- `bus.jpg`、`bus_detected.jpg`：官方示例及图片检测结果。
- `example_clip.mp4`：合成输入视频。
- `detected_1791688823327056200.mp4`：实际检测后视频。
- `video_first_frame.jpg`：输出视频首帧预览。

## 重现验证

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tests.validate_runtime
```

真实运行脚本首次下载官方示例图片；权重存在时直接复用。每次视频输出使用唯一文件名。
通用自动化测试不需要真实模型、CUDA、联网或 GPU，使用生成视频和模拟检测结果。
