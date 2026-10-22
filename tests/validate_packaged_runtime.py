"""Real frozen EXE acceptance. The driver uses Python/Node; the EXE's environment does not.

Window gestures are deliberately not emulated. Diagnostic exit invokes the same
application close handler; actual mouse clicks require separately approved UI tools.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.request import build_opener, ProxyHandler, Request

import psutil

ROOT = Path(__file__).resolve().parents[1]
opener = build_opener(ProxyHandler({}))


def http(url, body=None):
    headers = {'Content-Type': 'application/json'} if body is not None else {}
    request = Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with opener.open(request, timeout=20) as response:
        return json.load(response)


def ready(process, state_file):
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'EXE exited {process.returncode} before ready')
        try:
            state = json.loads(state_file.read_text(encoding='utf-8'))
            if state.get('pid') == process.pid and state['status'] == 'ready':
                assert http(state['url'] + '/health')['status'] == 'ok'
                return state
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        time.sleep(.25)
    raise RuntimeError('Frozen EXE startup timeout')


def package_snapshot(folder):
    return {str(file.relative_to(folder)): (file.stat().st_size, file.stat().st_mtime_ns)
            for file in folder.rglob('*') if file.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    executable = args.exe.resolve(strict=True)
    source = args.source.resolve(strict=True)
    original_hash = sha256(source.read_bytes()).hexdigest()
    folder = ROOT / 'data' / 'outputs' / 'phase5_runtime' / str(time.time_ns())
    folder.mkdir(parents=True)
    cwd = folder / '从 中文 空格 工作目录 启动'
    cwd.mkdir()
    profile = folder / '模拟用户 LocalAppData'
    data = profile / 'SmartVision'
    state_file = data / 'run-state.json'
    marker = folder / 'normal-close.flag'
    node = shutil.which('node')
    assert node
    fixture = folder / 'packaged-pedestrians.mp4'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-stream_loop', '3', '-i', str(source),
                    '-t', '24', '-an', '-c', 'copy', str(fixture)], check=True)
    clean = os.environ.copy()
    for name in ('VIRTUAL_ENV', 'PYTHONPATH', 'PYTHONHOME', 'CONDA_PREFIX'):
        clean.pop(name, None)
    clean['PATH'] = os.environ['SystemRoot'] + r'\System32;' + os.environ['SystemRoot']
    clean['LOCALAPPDATA'] = str(profile)
    clean['HTTP_PROXY'] = clean['HTTPS_PROXY'] = 'http://127.0.0.1:9'
    clean['NO_PROXY'] = '127.0.0.1,localhost'
    report = {'original_exe': str(executable), 'output': str(folder), 'checks': [], 'cycles': [],
              'source_sha256': original_hash, 'driver_executable': sys.executable,
              'app_environment': {'PATH': clean['PATH'], 'LOCALAPPDATA': str(profile), 'external_http_proxy': 'blocked localhost:9'},
              'physical_ui_clicks': 'not tested: Windows UI application permission unavailable'}
    process = None
    dummy = socket.socket()
    dummy.bind(('127.0.0.1', 0)); dummy.listen(4); dummy.settimeout(.2)
    occupied = dummy.getsockname()[1]
    unexpected_requests = []
    done = threading.Event()
    def dummy_service():
        while not done.is_set():
            try:
                connection, address = dummy.accept()
                with connection:
                    connection.settimeout(.2)
                    try:
                        unexpected_requests.append(connection.recv(1024).decode(errors='replace'))
                    except OSError:
                        pass
            except socket.timeout:
                continue
            except OSError:
                return
    threading.Thread(target=dummy_service, daemon=True).start()
    def passed(name):
        report['checks'].append(name)
        print('PASS ' + name, flush=True)
    initial_snapshot = package_snapshot(executable.parent)
    try:
        for phase in ('gpu', 'cpu'):
            marker.unlink(missing_ok=True)
            if phase == 'cpu':
                destination = folder / '复制后 中文 空格' / 'SmartVision'
                shutil.copytree(executable.parent, destination)
                executable = destination / 'SmartVision.exe'
                clean['CUDA_VISIBLE_DEVICES'] = '-1'
            else:
                clean.pop('CUDA_VISIBLE_DEVICES', None)
            command = [str(executable), '--smoke-exit-file', str(marker), '--smoke-interrupt']
            if phase == 'gpu':
                command += ['--port', str(occupied)]
            else:
                command += ['--no-browser']
            process = subprocess.Popen(command, cwd=cwd, env=clean, creationflags=subprocess.CREATE_NO_WINDOW)
            state = ready(process, state_file)
            assert state['device'] == ('cuda:0' if phase == 'gpu' else 'cpu')
            assert state['port'] != occupied
            assert state['data_dir'] == str(data.resolve())
            modules = [region.path for region in psutil.Process(process.pid).memory_maps()]
            assert not any('.venv' in item.lower() for item in modules)
            assert any('python311.dll' in item.lower() and '_internal' in item for item in modules)
            report['cycles'].append({'phase': phase, 'state': state, 'exe': str(executable),
                                      'python_dll': [item for item in modules if 'python311.dll' in item.lower()]})
            passed(f'{phase}: frozen EXE normal-user startup with clean PATH and no virtualenv modules')
            if phase == 'gpu':
                assert unexpected_requests == []
                passed('occupied port avoided; no readiness request sent to the other process')
            driver_env = os.environ.copy()
            driver_env.update({'SMARTVISION_PACKAGED_DATA': str(data), 'SMARTVISION_PACKAGED_REPORT': str(folder),
                               'SMARTVISION_PACKAGED_SOURCE': str(fixture), 'SMARTVISION_PACKAGED_PHASE': phase})
            subprocess.run([node, 'e2e/packaged.mjs'], cwd=ROOT / 'frontend', env=driver_env, check=True, timeout=180)
            settings = json.loads((data / 'config' / 'Ultralytics' / 'settings.json').read_text(encoding='utf-8'))
            assert settings['runs_dir'].startswith(str(data))
            passed(f'{phase}: real browser workflow passed; Ultralytics settings remain in user data')
            if phase == 'gpu':
                # Start a deliberate rebuild, then exercise close -> lifespan -> worker cancellation.
                video = http(state['url'] + '/api/videos')['items'][0]
                existing = http(f"{state['url']}/api/videos/{video['video_id']}/events?category=person")['events']
                submitted = http(f"{state['url']}/api/videos/{video['video_id']}/analysis",
                                 {'sample_fps': 30, 'imgsz': 960, 'confidence': .35, 'force_rebuild': True})
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    task = http(state['url'] + '/api/tasks/' + submitted['task_id'])
                    if task['status'] == 'running':
                        break
                    time.sleep(.02)
                assert task['status'] == 'running'
                report['interrupted_task_id'] = submitted['task_id']
                report['previous_person_events'] = existing
            marker.write_text('diagnostic close through normal handler', encoding='utf-8')
            process.wait(timeout=50)
            assert process.returncode == 0
            stopped = json.loads(state_file.read_text(encoding='utf-8'))
            assert stopped['status'] == 'stopped'
            with socket.socket() as check:
                check.settimeout(.3)
                assert check.connect_ex(('127.0.0.1', state['port'])) != 0
            passed(f'{phase}: normal application close handler stopped its service and worker; port released')
            if phase == 'gpu':
                # Read-only validation of persistence, never modify rows to fake a result.
                import sqlite3
                with sqlite3.connect((data / 'smartvision.sqlite3').as_uri() + '?mode=ro', uri=True) as connection:
                    row = connection.execute('SELECT status,error_message FROM analysis_tasks WHERE task_id=?', (submitted['task_id'],)).fetchone()
                    assert row[0] == 'failed', row
                    report['interruption_error'] = row[1]
                passed('running rebuild interrupted and recorded failed before exit; old index retained for restart')
            process = None
        assert package_snapshot(args.exe.resolve().parent) == initial_snapshot
        passed('read-only package resources unchanged after launches; source video hash unchanged')
        assert sha256(source.read_bytes()).hexdigest() == original_hash
        passed('moved EXE in Chinese/space path reused persisted database; CPU rebuild completed')
    except Exception as error:
        report['failure'] = repr(error)
        raise
    finally:
        done.set(); dummy.close()
        if process and process.poll() is None:
            marker.write_text('diagnostic cleanup', encoding='utf-8')
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate(); process.wait(timeout=10)
                report['forced_cleanup'] = True
        (folder / 'acceptance-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Acceptance evidence: {folder}', flush=True)


if __name__ == '__main__':
    main()
