"""Run the real Vue + FastAPI + YOLO browser smoke test in an isolated workspace.

Requires Node, frontend dependencies, FFmpeg, an installed Edge/Chrome channel,
and a real local video. Never changes the supplied source or production database.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from backend.config import PROJECT_ROOT


def wait_ready(url, process, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited: {url}")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(.25)
    raise RuntimeError(f"Server did not start: {url}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    for host, port in [('127.0.0.1', 8000), ('localhost', 5173)]:
        try:
            connection = socket.create_connection((host, port), timeout=1)
        except OSError:
            continue
        connection.close()
        raise RuntimeError(f'{host}:{port} is already in use; stop the existing server before this isolated test')
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output = PROJECT_ROOT / 'data' / 'outputs' / 'phase4_browser' / str(time.time_ns())
    output.mkdir(parents=True)
    # Encoding here only prepares independent test fixtures; no product transcoding.
    for filename, options in [
        ('pedestrians.mp4', ['-i', str(source), '-t', '6', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p']),
        ('black.mp4', ['-f', 'lavfi', '-i', 'color=c=black:s=640x480:r=10:d=3', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p']),
        ('incompatible.avi', ['-i', str(source), '-t', '2', '-an', '-c:v', 'mpeg4']),
    ]:
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', *options, str(output / filename)], check=True)
    (output / 'invalid.mp4').write_bytes(b'This is deliberately not a video.')
    env = os.environ.copy()
    env['SMARTVISION_DATABASE'] = str(output / 'api.sqlite3')
    env['SMARTVISION_VIDEO_DIR'] = str(output / 'uploads')
    env['VITE_API_BASE_URL'] = 'http://127.0.0.1:8000'
    env['SMARTVISION_E2E_OUTPUT'] = str(output)
    env['SMARTVISION_BROWSER_CHANNEL'] = env.get('SMARTVISION_BROWSER_CHANNEL', 'msedge')
    env['SMARTVISION_SOURCE_HASH'] = original_hash
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js is not on PATH')
    processes = []
    logs = []
    try:
        for filename, command, cwd, url in [
            ('backend.log', [sys.executable, '-X', 'utf8', '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000'], PROJECT_ROOT, 'http://127.0.0.1:8000/health'),
            ('frontend.log', [node, 'node_modules/vite/bin/vite.js', '--host', 'localhost', '--port', '5173', '--strictPort'], PROJECT_ROOT / 'frontend', 'http://localhost:5173'),
        ]:
            log = (output / filename).open('w', encoding='utf-8')
            logs.append(log)
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
            processes.append(process)
            wait_ready(url, process)
        subprocess.run([node, 'e2e/real-backend.mjs'], cwd=PROJECT_ROOT / 'frontend', env=env, check=True, timeout=300)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash, 'Source video changed'
        print(f'Browser evidence: {output}')
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()
