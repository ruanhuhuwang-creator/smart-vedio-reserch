"""Packaging boundaries; independent of GPU, model downloads and native UI."""
import importlib.util
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from backend.config import APIConfig
from backend.main import create_app

spec = importlib.util.spec_from_file_location('smartvision_launcher', Path(__file__).resolve().parents[1] / 'packaging' / 'launcher.py')
launcher = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = launcher
spec.loader.exec_module(launcher)


def test_frozen_paths_ignore_current_directory(tmp_path, monkeypatch):
    resources = tmp_path / '只读应用' / '_internal'
    resources.mkdir(parents=True)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(resources), raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / '用户 AppData'))
    monkeypatch.chdir(tmp_path)
    paths = launcher.AppPaths.resolve()
    assert paths.resources == resources
    assert paths.data == tmp_path / '用户 AppData' / 'SmartVision'
    paths.initialize()
    assert (paths.data / 'videos').is_dir()
    assert not (resources / 'videos').exists()


def test_development_data_stays_in_project(monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    paths = launcher.AppPaths.resolve()
    assert paths.data == Path(__file__).resolve().parents[1] / 'data'


def test_explicit_data_directory_isolated(tmp_path):
    paths = launcher.AppPaths.resolve(tmp_path / '独立诊断')
    paths.initialize()
    marker = paths.data / 'videos' / 'preserve.mp4'
    marker.write_bytes(b'user-data')
    paths.initialize()
    assert marker.read_bytes() == b'user-data'


def test_missing_resources_fail_clearly(tmp_path):
    with pytest.raises(RuntimeError, match='资源缺失'):
        launcher.AppPaths(tmp_path, tmp_path / 'data').verify()


def test_occupied_port_is_not_reused():
    owned = launcher.reserve_socket(0)
    try:
        port = owned.getsockname()[1]
        new = launcher.reserve_socket(port)
        try:
            assert new.getsockname()[0] == '127.0.0.1'
            assert new.getsockname()[1] != port
            # Second bind cannot hijack either already-owned port.
            attempt = socket.socket()
            try:
                with pytest.raises(OSError):
                    attempt.bind(('127.0.0.1', new.getsockname()[1]))
            finally:
                attempt.close()
        finally:
            new.close()
    finally:
        owned.close()


@pytest.mark.parametrize('port', [-1, 65536, '8000'])
def test_invalid_port_rejected(port):
    with pytest.raises(ValueError):
        launcher.reserve_socket(port)


def test_production_static_does_not_swallow_api(tmp_path):
    static = tmp_path / 'dist'
    (static / 'assets').mkdir(parents=True)
    (static / 'index.html').write_text('<html>SmartVision</html>', encoding='utf-8')
    (static / 'assets' / 'app.js').write_text('console.log(1)', encoding='utf-8')
    (static / 'source-code.zip').write_bytes(b'source-archive')
    config = APIConfig(database=tmp_path / 'data' / 'index.sqlite3', video_dir=tmp_path / 'videos')
    app = create_app(config, frontend_dir=static)
    with TestClient(app) as client:
        assert client.get('/').text == '<html>SmartVision</html>'
        assert client.get('/workspace/1').text == '<html>SmartVision</html>'
        assert client.get('/assets/app.js').status_code == 200
        assert client.get('/assets/missing.js').status_code == 404
        assert client.get('/missing.js').status_code == 404
        assert client.get('/source-code.zip').content == b'source-archive'
        assert client.get('/health').json()['status'] == 'ok'
        assert client.get('/docs').status_code == 200
        assert client.get('/openapi.json').status_code == 200
        assert client.get('/api/videos').json()['items'] == []
        assert client.get('/api/unknown').status_code == 404
        assert client.get('/api/videos/123').status_code == 404


def test_invalid_frontend_fails_before_service_start(tmp_path):
    with pytest.raises(RuntimeError, match='Vue 生产资源不完整'):
        create_app(APIConfig(database=tmp_path / 'db.sqlite3'), frontend_dir=tmp_path / 'missing')


def test_windowed_ffprobe_does_not_inherit_console():
    import subprocess
    from backend.core.subprocess_utils import hidden_process_options
    options = hidden_process_options()
    assert options['stdin'] == subprocess.DEVNULL
    if sys.platform == 'win32':
        assert options['creationflags'] & subprocess.CREATE_NO_WINDOW


def test_yolo_config_parent_exists_in_user_directory(tmp_path, monkeypatch):
    import os
    import tempfile
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    monkeypatch.setattr(tempfile, 'tempdir', tempfile.tempdir)
    paths = launcher.AppPaths(tmp_path / 'resources', tmp_path / '用户 数据')
    paths.initialize()
    launcher.configure_environment(paths)
    parent = Path(os.environ['YOLO_CONFIG_DIR'])
    assert parent == paths.data / 'config'
    assert parent.is_dir()
    assert os.environ['YOLO_OFFLINE'] == 'true'
    assert os.environ['YOLO_AUTOINSTALL'] == 'false'


@pytest.mark.parametrize('confirmed', [False, True])
def test_busy_close_requires_user_decision(tmp_path, monkeypatch, confirmed):
    from tkinter import messagebox
    from unittest.mock import Mock
    monkeypatch.setattr(messagebox, 'askyesno', Mock(return_value=confirmed))
    app = object.__new__(launcher.DesktopApp)
    app.closing = False
    app.application = SimpleNamespace(state=SimpleNamespace(tasks=SimpleNamespace(queue=SimpleNamespace(unfinished_tasks=1))))
    app.server = SimpleNamespace(should_exit=False)
    app.root = None
    app.status = SimpleNamespace(set=Mock())
    app.open_button = SimpleNamespace(configure=Mock())
    app.stop_button = SimpleNamespace(configure=Mock())
    app.write_state = Mock()
    app.close()
    assert app.closing is confirmed
    assert app.server.should_exit is confirmed
    messagebox.askyesno.assert_called_once()
    if not confirmed:
        app.write_state.assert_not_called()
