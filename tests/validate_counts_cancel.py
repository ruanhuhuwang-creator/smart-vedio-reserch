"""Validate new features from the EXE, upgrading only an isolated old QA database."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

from tests.validate_packaged_runtime import ready

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--old-data', type=Path, required=True)
    args = parser.parse_args()
    old = args.old_data.resolve()
    out = ROOT / 'data/outputs/counts_cancel_validation' / str(time.time_ns())
    data = out / '中文 AppData/SmartVision'
    (data / 'videos').mkdir(parents=True)
    old_db, new_db = old / 'smartvision.sqlite3', data / 'smartvision.sqlite3'
    with sqlite3.connect(old_db.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(new_db) as dst:
        assert src.execute('PRAGMA user_version').fetchone()[0] == 2, 'Use original v2 QA data'
        src.backup(dst)
        rows = dst.execute('SELECT id,path FROM videos').fetchall()
        for vid, name in rows:
            source = Path(name)
            target = data / 'videos' / source.name
            shutil.copy2(source, target)
            dst.execute('UPDATE videos SET path=? WHERE id=?', (str(target), vid))
        dst.commit()
    queued = out / 'queue.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=640x480:r=10:d=3',
                    '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(queued)], check=True)
    source_hash = hashlib.sha256(old_db.read_bytes()).hexdigest()
    marker = out / 'stop.marker'
    env = os.environ.copy()
    for name in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'):
        env.pop(name, None)
    env['PATH'] = os.environ['SystemRoot'] + r'\System32;' + os.environ['SystemRoot']
    process = subprocess.Popen([str(args.exe.resolve()), '--data-dir', str(data), '--port', '0', '--no-browser',
                                '--smoke-exit-file', str(marker), '--smoke-interrupt'], cwd=out, env=env)
    result = {'exe': str(args.exe.resolve()), 'old_database_unchanged': False}
    try:
        state = ready(process, data / 'run-state.json')
        result['state'] = state
        browser_env = os.environ.copy()
        browser_env.update(SMARTVISION_FEATURE_OUTPUT=str(out), SMARTVISION_FEATURE_DATA=str(data),
                           SMARTVISION_FEATURE_SOURCE=str(target), SMARTVISION_FEATURE_QUEUED_SOURCE=str(queued))
        subprocess.run([shutil.which('node'), 'e2e/counts-cancel.mjs'], cwd=ROOT / 'frontend', env=browser_env,
                       check=True, timeout=900)
        browser = json.loads((out / 'browser-report.json').read_text(encoding='utf-8'))
        with sqlite3.connect(new_db.as_uri() + '?mode=ro', uri=True) as conn:
            assert conn.execute('PRAGMA user_version').fetchone()[0] == 3
            assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            for event in browser['publishedEvents']:
                maximum = conn.execute('SELECT MAX(n) FROM (SELECT COUNT(*) n FROM detections WHERE video_id=? '
                                       'AND class_name=? AND timestamp BETWEEN ? AND ? GROUP BY frame_index,timestamp)',
                                       (event['video_id'], event['category'], event['start_time'], event['end_time'])).fetchone()[0]
                assert maximum == event['max_count']
            result['task_states'] = conn.execute('SELECT status,COUNT(*) FROM analysis_tasks GROUP BY status').fetchall()
        backups = list(data.glob('*.pre-v3.*.sqlite3'))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute('PRAGMA user_version').fetchone()[0] == 2
            assert backup.execute('SELECT COUNT(*) FROM detections').fetchone()[0] > 0
        log = (data / 'logs/smartvision.log').read_text(encoding='utf-8')
        assert 'cuda:0' in log and 'YOLO 模型已加载' in log and '已停止' in log
        result.update(migration_verified=True, count_sql_verified=True, gpu_verified=True,
                      browser_checks=browser['checks'], old_database_unchanged=source_hash == hashlib.sha256(old_db.read_bytes()).hexdigest())
        assert result['old_database_unchanged']
    finally:
        marker.touch()
        process.wait(timeout=60)
        result['exit_code'] = process.returncode
        (out / 'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Evidence:', out)
    assert process.returncode == 0
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
