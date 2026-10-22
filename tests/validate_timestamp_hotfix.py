"""Real EXE acceptance on an anomalous MP4, with isolated data and normal exit.

Run as a module. Diagnostic exit is not a native mouse-click test.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

import httpx


def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    for name in ('exe', 'input', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    exe, source, out = args.exe.resolve(), args.input.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    data, marker = out / 'appdata', out / 'stop.marker'
    env = os.environ.copy()
    for name in ('VIRTUAL_ENV', 'PYTHONPATH', 'PYTHONHOME'):
        env.pop(name, None)
    env['PATH'] = str(Path(env.get('SystemRoot', 'C:/Windows')) / 'System32')
    before = digest(source)
    process = subprocess.Popen([str(exe), '--data-dir', str(data), '--no-browser',
                                '--port', '0', '--smoke-exit-file', str(marker)], cwd=out, env=env)
    result = {'exe': str(exe), 'source_sha256': before}
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            assert process.poll() is None, 'EXE exited during startup'
            try:
                state = json.loads((data / 'run-state.json').read_text(encoding='utf-8'))
                if state.get('status') == 'ready':
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        else:
            raise TimeoutError('EXE readiness timed out')
        assert state['mode'] == 'frozen'
        result['state'] = state
        with httpx.Client(base_url=state['url'], trust_env=False, timeout=120) as client:
            def request(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()

            def wait(task):
                deadline = time.monotonic() + 600
                while task['status'] not in ('succeeded', 'failed') and time.monotonic() < deadline:
                    time.sleep(2)
                    task = request('GET', '/api/tasks/' + task['task_id'])
                assert task['status'] == 'succeeded', task
                return task

            result['health'] = request('GET', '/health')
            with source.open('rb') as file:
                video = request('POST', '/api/videos', files={'file': (source.name, file, 'video/mp4')})
            vid = video['video_id']
            parameters = {'sample_fps': 2, 'imgsz': 416, 'confidence': 0.35}
            result['task'] = wait(request('POST', f'/api/videos/{vid}/analysis', json=parameters))
            result['events'] = {category: request('GET', f'/api/videos/{vid}/events',
                                                params={'category': category})
                                for category in ('person', 'car')}
            for response in result['events'].values():
                assert response['index_available']
                assert all(0 <= event['start_time'] <= event['end_time'] <= video['duration'] + 0.01
                           for event in response['events'])
            ranged = client.get(f'/api/videos/{vid}/stream', headers={'Range': 'bytes=0-127'})
            assert ranged.status_code == 206 and len(ranged.content) == 128
            result['reused'] = wait(request('POST', f'/api/videos/{vid}/analysis', json=parameters))
            assert result['reused']['index_reused']
        marker.touch()
        assert process.wait(timeout=60) == 0
        with sqlite3.connect((data / 'smartvision.sqlite3').as_uri() + '?mode=ro', uri=True) as conn:
            row = conn.execute('SELECT total_frames,sampled_frames,estimated_tail,status FROM videos WHERE id=?',
                               (vid,)).fetchone()
        assert row[2:] == (1, 'completed'), row
        result['stored_index'] = dict(zip(('total_frames', 'sampled_frames', 'estimated_tail', 'status'), row))
        log = (data / 'logs/smartvision.log').read_text(encoding='utf-8')
        assert log.count('跳过异常尾帧索引') == 2 and 'cuda:0' in log
        assert before == digest(source)
        result.update(source_unchanged=True, gpu_verified=True, skipped_tail_frames=2,
                      range_verified=True, exit_code=process.returncode)
    finally:
        marker.touch(exist_ok=True)
        (out / 'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
