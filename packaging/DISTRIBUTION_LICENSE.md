# SmartVision 便携分发：源码与第三方许可

本课程项目的便携分发版本按所含 Ultralytics AGPL-3.0 组件的要求提供应用完整对应源码、构建脚本和依赖版本。
SmartVision 此分发版本的应用代码按 GNU AGPL v3 提供；原作者保留著作权。各第三方组件仍适用各自许可证。
同源页面 `/source-code.zip` 及安装目录 `_internal/frontend/dist/source-code.zip` 提供源码，无需联网。
AGPL 全文在源码 ZIP 的 AGPL-3.0.txt 和 `_internal/licenses/ultralytics/` 中。

- Ultralytics 及 yolo26n.pt：AGPL-3.0，https://www.ultralytics.com/license 。本包包含准确版本的 Python/YAML 源码；未训练或修改模型。
- PyTorch / torchvision：BSD 系列许可；CUDA/cuDNN 等 NVIDIA 可再分发运行库适用随 PyTorch 附带的 NVIDIA 条款。没有包含 NVIDIA 显卡驱动，驱动须由用户或设备厂商安装。
- OpenCV：Apache-2.0，所带 FFmpeg 解码组件亦保留 opencv-python 的第三方声明。
- NumPy、FastAPI、Starlette、Uvicorn、Vue、Vite 等：许可证与版本见 `_internal/licenses` 和 DEPENDENCIES.json。
- FFprobe 8.0.1 essentials / Gyan：GPL v3，单独外部进程，只执行探测。保留 LICENSE、原版 README/构建配置、版本及 FFmpeg 8.0.1 源码归档。
  对应上游提交：https://github.com/FFmpeg/FFmpeg/commit/894da5ca7d 。Gyan 构建说明及外部库资料：https://www.gyan.dev/ffmpeg/builds/ 。
  静态构建还包含原版构建说明列出的外部库；进行公开再分发时，分发者应持续向接收者提供这些库的完整对应源码/构建资料，不能仅提供本程序的源码。
- Python、Tcl/Tk、PyInstaller bootloader：保留各自声明；PyInstaller 的 bootloader 例外允许分发打包程序。

本项目没有购买或声称拥有 Ultralytics Enterprise 许可。本包并非闭源商业许可交付；不得删除第三方许可、源码访问方式或声称模型预测保证准确。
完整源代码随离线 ZIP 分发，不自动上传任何代码、用户视频或数据库。
