"""SmartVision windowed entry point. One process owns the UI, socket and worker."""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import socket
import sys
import tempfile
import threading
import time
from urllib.request import build_opener, ProxyHandler
from uuid import uuid4
import webbrowser

log = logging.getLogger('smartvision.desktop')


@dataclass(frozen=True)
class AppPaths:
    resources: Path
    data: Path

    @classmethod
    def resolve(cls, override=None):
        frozen = bool(getattr(sys, 'frozen', False))
        resources = Path(sys._MEIPASS) if frozen else Path(__file__).resolve().parent.parent
        default = (Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'SmartVision'
                   if frozen else resources / 'data')
        return cls(resources.resolve(), Path(override).resolve() if override else default.resolve())

    def initialize(self):
        for child in ('videos', 'outputs', 'logs', 'config', 'cache', 'tmp'):
            (self.data / child).mkdir(parents=True, exist_ok=True)
        probe = self.data / 'tmp' / f'.write-check-{uuid4().hex}'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()

    def verify(self):
        required = ['frontend/dist/index.html', 'models/yolo26n.pt',
                    'backend/database/schema.sql', 'backend/database/migration_v2.sql',
                    'backend/database/migration_v3.sql']
        if getattr(sys, 'frozen', False):
            required.append('bin/ffprobe.exe')
        missing = [name for name in required if not (self.resources / name).is_file()]
        if missing:
            raise RuntimeError('应用资源缺失，请完整解压并保留 _internal 文件夹：' + ', '.join(missing))


def configure_environment(paths):
    # Set before importing Ultralytics/matplotlib/torch. No cache in _internal/CWD.
    os.environ.update({
        'YOLO_CONFIG_DIR': str(paths.data / 'config'),
        'MPLCONFIGDIR': str(paths.data / 'cache' / 'matplotlib'),
        'TORCH_HOME': str(paths.data / 'cache' / 'torch'),
        'TORCHINDUCTOR_CACHE_DIR': str(paths.data / 'cache' / 'inductor'),
        'YOLO_AUTOINSTALL': 'false', 'YOLO_OFFLINE': 'true',
        'TEMP': str(paths.data / 'tmp'), 'TMP': str(paths.data / 'tmp'),
    })
    tempfile.tempdir = str(paths.data / 'tmp')
    if getattr(sys, 'frozen', False):
        os.environ['PATH'] = str(paths.resources / 'bin') + os.pathsep + os.environ.get('PATH', '')


def configure_logging(paths, debug=False):
    handler = RotatingFileHandler(paths.data / 'logs' / 'smartvision.log', maxBytes=5 * 1024 * 1024,
                                  backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s'))
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=[handler], force=True)
    if sys.stdout is None or sys.stderr is None:
        stream = (paths.data / 'logs' / 'console.log').open('a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stderr = stream
    def exception_hook(kind, value, trace):
        log.critical('未处理的异常', exc_info=(kind, value, trace))
    sys.excepthook = exception_hook
    threading.excepthook = lambda args: exception_hook(args.exc_type, args.exc_value, args.exc_traceback)


def reserve_socket(preferred):
    if not isinstance(preferred, int) or not 0 <= preferred <= 65535:
        raise ValueError('preferred_port 必须为 0～65535 的整数')
    for port in dict.fromkeys((preferred, 0)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Windows exclusive bind prevents another process hijacking readiness.
            if os.name == 'nt':
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(('127.0.0.1', port))
            sock.listen(128)
            return sock
        except OSError:
            sock.close()
            if port == 0:
                raise


def runtime_device():
    import torch
    available = torch.cuda.is_available()
    device = 'cuda:0' if available else 'cpu'
    log.info('PyTorch=%s CUDA runtime=%s available=%s selected=%s', torch.__version__, torch.version.cuda, available, device)
    if available:
        log.info('NVIDIA GPU: %s', torch.cuda.get_device_name(0))
    else:
        log.warning('CUDA 不可用，自动使用 CPU；没有兼容 GPU、驱动不可用或 CUDA_VISIBLE_DEVICES 禁用均可能导致此情况')
    return device


def configure_model_settings(paths):
    from ultralytics import settings
    values = {'datasets_dir': str(paths.data / 'cache' / 'datasets'),
              'weights_dir': str(paths.data / 'cache' / 'models'),
              'runs_dir': str(paths.data / 'outputs'), 'sync': False}
    settings.update({key: value for key, value in values.items() if key in settings})
    log.info('Ultralytics 使用用户配置目录，离线模式启用，自动安装关闭')


class DesktopApp:
    def __init__(self, paths, args):
        import tkinter as tk
        from tkinter import ttk
        self.paths, self.args = paths, args
        self.token = uuid4().hex
        self.messages = queue.Queue()
        self.state_lock = threading.Lock()
        self.state = {'pid': os.getpid(), 'instance': self.token, 'status': 'starting',
                      'mode': 'frozen' if getattr(sys, 'frozen', False) else 'development',
                      'data_dir': str(paths.data), 'started_at': datetime.now(timezone.utc).isoformat()}
        self.server = self.application = self.sock = None
        self.closing = False
        self.root = tk.Tk()
        self.root.title('SmartVision · 应用控制')
        self.root.geometry('540x365')
        self.root.resizable(False, False)
        self.root.configure(bg='#101925')
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('SV.TButton', font=('Microsoft YaHei UI', 10), padding=9)
        tk.Label(self.root, text='SmartVision', font=('Segoe UI', 25, 'bold'), fg='#46d9b6', bg='#101925').pack(pady=(22, 4))
        tk.Label(self.root, text='智能视频分析与检索 · 本地便携版', font=('Microsoft YaHei UI', 10), fg='#9cafc7', bg='#101925').pack()
        self.status = tk.StringVar(value='正在检查资源并启动服务，请稍候…')
        tk.Label(self.root, textvariable=self.status, font=('Microsoft YaHei UI', 10), wraplength=485,
                 fg='#e2eaf4', bg='#101925').pack(pady=(23, 8))
        self.address = tk.StringVar(value='仅监听 127.0.0.1 · 不向局域网开放')
        tk.Label(self.root, textvariable=self.address, font=('Segoe UI', 10), fg='#8ba6c5', bg='#101925').pack()
        frame = tk.Frame(self.root, bg='#101925')
        frame.pack(pady=20)
        self.open_button = ttk.Button(frame, text='打开 SmartVision', command=self.open_browser, state='disabled', style='SV.TButton')
        self.open_button.pack(side='left', padx=5)
        ttk.Button(frame, text='打开日志目录', command=self.open_logs, style='SV.TButton').pack(side='left', padx=5)
        self.stop_button = ttk.Button(frame, text='停止并退出', command=self.close, style='SV.TButton')
        self.stop_button.pack(side='left', padx=5)
        tk.Label(self.root, text=f'数据与日志：{paths.data}', font=('Microsoft YaHei UI', 9), wraplength=495,
                 fg='#7189a5', bg='#101925').pack(padx=15)
        tk.Label(self.root, text='关闭浏览器不会停止分析；关闭本窗口将停止服务，数据会保留。',
                 font=('Microsoft YaHei UI', 9), fg='#7189a5', bg='#101925').pack(pady=9)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.report_callback_exception = self.ui_exception
        self.worker = threading.Thread(target=self.serve, name='SmartVision-server', daemon=False)
        self.worker.start()
        self.root.after(150, self.tick)

    def write_state(self, **updates):
        with self.state_lock:
            self.state.update(updates)
            destination = self.paths.data / 'run-state.json'
            partial = destination.with_suffix('.tmp')
            partial.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')
            partial.replace(destination)

    def serve(self):
        try:
            self.paths.verify()
            import shutil
            from backend.core.subprocess_utils import hidden_process_options
            import subprocess
            executable = shutil.which('ffprobe')
            if not executable:
                raise RuntimeError('缺少 FFprobe；请完整解压分发包，开发模式请配置 FFprobe')
            subprocess.run([executable, '-version'], capture_output=True, check=True, timeout=15, **hidden_process_options())
            settings_file = self.paths.data / 'config' / 'settings.json'
            settings = json.loads(settings_file.read_text(encoding='utf-8')) if settings_file.is_file() else {}
            self.sock = reserve_socket(self.args.port if self.args.port is not None else settings.get('preferred_port', 8765))
            port = self.sock.getsockname()[1]
            self.write_state(port=port, url=f'http://127.0.0.1:{port}')
            log.info('端口已独占绑定: 127.0.0.1:%s', port)
            device = runtime_device()
            configure_model_settings(self.paths)
            self.write_state(device=device)
            if self.closing:
                return
            from backend.config import APIConfig
            from backend.main import create_app
            import uvicorn
            config = APIConfig(database=self.paths.data / 'smartvision.sqlite3', video_dir=self.paths.data / 'videos',
                               weights=self.paths.resources / 'models' / 'yolo26n.pt', cors_origins=())
            self.application = create_app(config, frontend_dir=self.paths.resources / 'frontend' / 'dist')
            @self.application.middleware('http')
            async def identify(request, call_next):
                response = await call_next(request)
                if request.url.path == '/health':
                    response.headers['X-SmartVision-Instance'] = self.token
                return response
            self.server = uvicorn.Server(uvicorn.Config(self.application, host='127.0.0.1', port=port,
                workers=1, loop='asyncio', http='h11', lifespan='on', log_config=None,
                timeout_graceful_shutdown=10, access_log=True))
            if self.closing:
                return
            # Socket is already owned; never probe/connect to an unrelated service.
            monitor = threading.Thread(target=self.wait_ready, name='SmartVision-ready', daemon=True)
            monitor.start()
            self.server.run(sockets=[self.sock])
        except BaseException as error:
            log.exception('服务启动或运行失败')
            self.write_state(status='failed', error=str(error))
            self.messages.put(('error', str(error)))
        finally:
            if self.sock:
                self.sock.close()
            log.info('本次服务线程已退出')

    def wait_ready(self):
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and not self.closing:
            if self.server.started:
                try:
                    with opener.open(self.state['url'] + '/health', timeout=2) as response:
                        body = json.load(response)
                        if response.headers.get('X-SmartVision-Instance') != self.token:
                            raise RuntimeError('服务实例校验失败，拒绝打开其他进程的页面')
                        if body.get('status') == 'ok':
                            settings = self.paths.data / 'config' / 'settings.json'
                            settings.write_text(json.dumps({'preferred_port': self.state['port']}, indent=2), encoding='utf-8')
                            self.write_state(status='ready')
                            log.info('服务就绪: %s', self.state['url'])
                            self.messages.put(('ready', self.state['url']))
                            return
                except OSError:
                    pass
                except Exception as error:
                    log.exception('服务身份检查失败')
                    self.messages.put(('error', str(error)))
                    self.server.should_exit = True
                    return
            time.sleep(.2)
        if not self.closing:
            log.error('服务未能在规定时间内就绪')
            self.messages.put(('error', '服务启动超时，请查看日志'))
            self.server.should_exit = True

    def open_browser(self):
        def open_page():
            try:
                result = webbrowser.open(self.state['url'])
                log.info('请求默认浏览器打开 %s，返回 %s', self.state['url'], result)
                if not result:
                    self.messages.put(('browser-error', '无法自动打开浏览器，请手动访问窗口显示的网址'))
            except Exception:
                log.exception('打开浏览器失败')
                self.messages.put(('browser-error', '无法自动打开浏览器，请手动访问窗口显示的网址'))
        threading.Thread(target=open_page, name='SmartVision-browser', daemon=True).start()

    def open_logs(self):
        os.startfile(str(self.paths.data / 'logs'))

    def ui_exception(self, kind, error, trace):
        log.error('控制窗口异常', exc_info=(kind, error, trace))
        self.show_error(str(error))

    def show_error(self, message):
        from tkinter import messagebox
        self.status.set('发生错误，请查看日志；可关闭窗口后重新启动。')
        messagebox.showerror('SmartVision', f'{message}\n\n日志目录：{self.paths.data / "logs"}', parent=self.root)

    def close(self, confirm=True):
        if self.closing:
            return
        manager = getattr(getattr(self.application, 'state', None), 'tasks', None)
        if manager and manager.queue.unfinished_tasks and confirm:
            from tkinter import messagebox
            if not messagebox.askyesno('退出 SmartVision', '仍有正在分析或排队的任务。\n退出将中断这些任务，已保存的有效索引会保留。\n\n确定停止并退出吗？', parent=self.root):
                return
        self.closing = True
        log.info('用户请求关闭；等待服务及分析工作线程安全退出')
        self.write_state(status='stopping')
        self.status.set('正在停止服务并安全保存状态，请稍候…')
        self.open_button.configure(state='disabled')
        self.stop_button.configure(state='disabled')
        if self.server:
            self.server.should_exit = True

    def tick(self):
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == 'ready' and not self.closing:
                    self.status.set(f'服务已就绪 · 推理设备 {self.state["device"]}')
                    self.address.set(value)
                    self.open_button.configure(state='normal')
                    if not self.args.no_browser:
                        self.open_browser()
                elif kind in ('error', 'browser-error') and not self.closing:
                    self.show_error(value)
        except queue.Empty:
            pass
        # Unattended release QA can exercise the very same close handler without
        # adding an HTTP shutdown endpoint or requiring Windows UI automation.
        if self.args.smoke_exit_file and not self.closing and Path(self.args.smoke_exit_file).is_file():
            manager = getattr(getattr(self.application, 'state', None), 'tasks', None)
            if not manager or not manager.queue.unfinished_tasks or self.args.smoke_interrupt:
                log.info('诊断退出文件已就绪，调用正常关闭处理器')
                self.close(confirm=not self.args.smoke_interrupt)
        if self.closing and not self.worker.is_alive():
            manager = getattr(getattr(self.application, 'state', None), 'tasks', None)
            if not manager or not manager.worker.is_alive():
                self.write_state(status='stopped', stopped_at=datetime.now(timezone.utc).isoformat())
                log.info('服务与分析工作线程已全部停止，应用正常关闭')
                self.root.destroy()
                return
            self.status.set('正在等待当前推理安全退出，请勿强制结束进程…')
        self.root.after(150, self.tick)


def main():
    parser = argparse.ArgumentParser(description='SmartVision Windows 应用控制器')
    parser.add_argument('--data-dir', help='诊断专用：显式指定独立数据目录')
    parser.add_argument('--port', type=int, help='首选 loopback 端口，冲突时自动选择空闲端口')
    parser.add_argument('--no-browser', action='store_true', help='诊断专用：不自动打开浏览器')
    parser.add_argument('--debug', action='store_true', help='记录详细调试日志')
    parser.add_argument('--smoke-exit-file', help='无人值守验收：指定文件出现且任务空闲时，调用正常关闭处理器')
    parser.add_argument('--smoke-interrupt', action='store_true', help='仅验收：允许诊断退出中断任务，跳过人工确认对话框')
    parser.add_argument('--diagnostics', action='store_true', help='离线加载模型并推理一帧，将结果写入 diagnostics.json 后退出')
    args = parser.parse_args()
    paths = AppPaths.resolve(args.data_dir)
    instance_lock = None
    try:
        sys.dont_write_bytecode = True
        paths.initialize()
        configure_logging(paths, args.debug)
        configure_environment(paths)
        log.info('SmartVision 启动 pid=%s mode=%s data=%s resources=%s cwd=%s', os.getpid(),
                 'frozen' if getattr(sys, 'frozen', False) else 'development', paths.data, paths.resources, Path.cwd())
        paths.verify()
        from backend.services.process_lock import ProcessLock
        instance_lock = ProcessLock(paths.data / 'desktop-instance')
        instance_lock.acquire()
        if args.diagnostics:
            import numpy as np
            from backend.core.detector import YOLODetector
            from backend.config import DetectionConfig
            device = runtime_device()
            configure_model_settings(paths)
            model = YOLODetector(DetectionConfig(weights=paths.resources / 'models' / 'yolo26n.pt'))
            detections = model.detect(np.zeros((480, 640, 3), dtype=np.uint8))
            (paths.data / 'diagnostics.json').write_text(json.dumps({'device': device, 'detections': len(detections),
                'weights': str(model.config.weights), 'frozen': bool(getattr(sys, 'frozen', False)),
                'executable': sys.executable}, indent=2), encoding='utf-8')
            log.info('离线模型诊断通过 device=%s', model.device)
            return 0
        app = DesktopApp(paths, args)
        app.root.mainloop()
        return 0
    except BaseException as error:
        log.exception('SmartVision 严重启动错误')
        try:
            (paths.data / 'startup-error.txt').write_text(str(error), encoding='utf-8')
        except OSError:
            pass
        if os.name == 'nt' and not args.diagnostics:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f'{error}\n\n日志：{paths.data / "logs"}', 'SmartVision 启动失败', 0x10)
        return 1
    finally:
        if instance_lock:
            instance_lock.release()


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
