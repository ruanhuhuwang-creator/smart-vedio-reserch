from dataclasses import replace
import sqlite3
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import DetectionConfig, IndexConfig
from backend.core.analyzer import FrameResult, ScanSummary
from backend.core.detector import Detection
from backend.core.video_io import VideoInfo
from backend.database.repository import IndexRepository
from backend.services.events import merge_observations
from backend.services.search import SearchService
from backend.main import create_app
from tests.test_api import settings, video, api, Controller, upload, submit, terminal


def wait_cancelled(client, task_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = client.get(f'/api/tasks/{task_id}').json()
        if task['status'] == 'cancelled':
            return task
        time.sleep(.02)
    raise AssertionError(task)


def cancel(client, task_id):
    response = client.post(f'/api/tasks/{task_id}/cancel')
    assert response.status_code == 202, response.text
    return response.json()


def test_peak_counts_group_by_frame_not_total_boxes(tmp_path):
    repo = IndexRepository(tmp_path / 'counts.sqlite3')
    info = VideoInfo(tmp_path / 'unused.mp4', 10, 96, 64, 50)
    vid, _ = repo.claim('hash', info, 'key')
    person = Detection(0, 'person', .9, (1, 1, 20, 30))
    car = Detection(2, 'car', .9, (1, 1, 20, 30))
    with repo.replace_index(vid) as writer:
        for index, (stamp, n) in enumerate([(0, 2), (.5, 3), (1, 1), (3, 1), (3.5, 2)]):
            writer.add_frame(FrameResult(index, stamp, [person] * n + [car], True))
        writer.merge_events(5, 1, 2, merge_observations)
        writer.complete(ScanSummary(info, 5, 50, 5, 14, 0, 0, False), 'key', DetectionConfig(), IndexConfig())
    rows = SearchService(repo).search('PERSON', vid, include_counts=True)
    assert [r['max_count'] for r in rows] == [3, 2]
    assert [r['start_time'] for r in rows] == [0, 3]
    assert SearchService(repo).search('car', vid, include_counts=True)[0]['max_count'] == 1
    assert SearchService(repo).search('bicycle', vid, include_counts=True) == []
    assert len(repo.raw_detections(vid)) == 14


def test_running_cancel_no_partial_index_and_can_restart(api, video):
    client, app, control = api
    vid = upload(client, video)['video_id']
    control.block_at = 1
    task = submit(client, vid)
    assert control.started.wait(4)
    stopped = cancel(client, task['task_id'])
    assert stopped['status'] == 'running' and stopped['cancel_requested']
    assert cancel(client, task['task_id'])['cancel_requested']
    control.release.set()
    done = wait_cancelled(client, task['task_id'])
    assert done['finished_at'] and done['error_message'] is None and done['progress'] < 100
    assert client.get(f'/api/videos/{vid}').json()['analysis_status'] == 'cancelled'
    assert client.get(f'/api/videos/{vid}/events').status_code == 409
    assert app.state.index.counts(vid) == {'detections': 0, 'events': 0}
    assert terminal(client, submit(client, vid)['task_id'])['status'] == 'succeeded'
    assert client.get('/health').json()['status'] == 'ok' and control.max_active == 1


def test_rebuild_cancel_keeps_previous_index_and_counts(api, video):
    client, app, control = api
    vid = upload(client, video)['video_id']
    done = terminal(client, submit(client, vid)['task_id'])
    before = client.get(f'/api/videos/{vid}/events').json()['events']
    raw = app.state.index.raw_detections(vid)
    assert all(row['max_count'] == 1 for row in before)
    control.block_at = control.calls + 1
    task = submit(client, vid, force_rebuild=True)
    assert control.started.wait(4)
    cancel(client, task['task_id'])
    control.release.set()
    wait_cancelled(client, task['task_id'])
    response = client.get(f'/api/videos/{vid}/events').json()
    assert response['using_previous_index'] and response['events'] == before
    assert app.state.index.raw_detections(vid) == raw
    assert client.post(f"/api/tasks/{done['task_id']}/cancel").status_code == 409
    assert client.post('/api/tasks/unknown/cancel').status_code == 404
    assert terminal(client, submit(client, vid)['task_id'])['index_reused']


def test_cancel_queued_releases_queue_slot(settings, video):
    control = Controller(); control.block_at = 1
    app = create_app(replace(settings, queue_capacity=1), detector_loader=control.loader)
    with TestClient(app) as client:
        try:
            ids = [upload(client, video, extra=b'\0' * n)['video_id'] for n in (8, 16, 24)]
            first = submit(client, ids[0]); assert control.started.wait(4)
            queued = submit(client, ids[1])
            assert client.post(f'/api/videos/{ids[2]}/analysis', json={}).status_code == 429
            assert cancel(client, queued['task_id'])['status'] == 'cancelled'
            assert cancel(client, queued['task_id'])['status'] == 'cancelled'
            third = submit(client, ids[2])
            control.release.set()
            assert terminal(client, first['task_id'])['status'] == 'succeeded'
            assert terminal(client, third['task_id'])['status'] == 'succeeded'
            assert app.state.index.counts(ids[1]) == {'detections': 0, 'events': 0}
            assert app.state.tasks.queue.unfinished_tasks == 0
        finally:
            control.release.set()


def test_stop_after_publication_is_rejected(api, video, monkeypatch):
    client, app, _ = api
    vid = upload(client, video)['video_id']
    original = app.state.tasks.indexing.analyze
    published, release = threading.Event(), threading.Event()
    def gated(*args, **kwargs):
        result = original(*args, **kwargs)
        published.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(app.state.tasks.indexing, 'analyze', gated)
    try:
        task = submit(client, vid)
        assert published.wait(4)
        assert client.post(f"/api/tasks/{task['task_id']}/cancel").status_code == 409
        assert client.get(f'/api/videos/{vid}').json()['index_available']
    finally:
        release.set()
    assert terminal(client, task['task_id'])['status'] == 'succeeded'


def test_stop_before_publication_does_not_replace_existing_index(api, video, monkeypatch):
    client, app, _ = api
    vid = upload(client, video)['video_id']
    terminal(client, submit(client, vid)['task_id'])
    old = app.state.index.raw_detections(vid)
    from backend.database.repository import IndexWriter
    original = IndexWriter.merge_events
    at_merge, release = threading.Event(), threading.Event()
    def gated(self, *args):
        original(self, *args)
        at_merge.set()
        assert release.wait(5)
    monkeypatch.setattr(IndexWriter, 'merge_events', gated)
    try:
        task = submit(client, vid, force_rebuild=True)
        assert at_merge.wait(4)
        assert cancel(client, task['task_id'])['cancel_requested']
    finally:
        release.set()
    wait_cancelled(client, task['task_id'])
    assert app.state.index.raw_detections(vid) == old


def test_cancel_before_cached_event_remerge_keeps_old_events(api, video, monkeypatch):
    client, app, _ = api
    vid = upload(client, video)['video_id']
    terminal(client, submit(client, vid)['task_id'])
    app.state.tasks.indexing.rebuild_events(vid, .1)
    assert app.state.index.search('person', vid) == []
    original = app.state.index.claim
    claimed, release = threading.Event(), threading.Event()
    def gated(*args, **kwargs):
        result = original(*args, **kwargs)
        claimed.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(app.state.index, 'claim', gated)
    try:
        task = submit(client, vid)
        assert claimed.wait(4)
        cancel(client, task['task_id'])
    finally:
        release.set()
    wait_cancelled(client, task['task_id'])
    assert app.state.index.search('person', vid) == []
    assert app.state.index.get_video(vid)['merge_gap'] == .1


def test_v2_upgrade_backups_and_preserves_tasks(tmp_path):
    db = tmp_path / 'v2.sqlite3'
    with sqlite3.connect(db) as conn:
        conn.executescript(Path('backend/database/schema.sql').read_text(encoding='utf-8'))
        conn.executescript(Path('backend/database/migration_v2.sql').read_text(encoding='utf-8'))
        conn.execute("INSERT INTO videos(id,content_sha256,name,path,duration,fps,width,height,status,analysis_key) "
                     "VALUES(1,'hash','old.mp4','old.mp4',2,12,96,64,'completed','key')")
        conn.execute("INSERT INTO analysis_tasks(task_id,video_id,status,parameters_json,created_at) "
                     "VALUES('history',1,'succeeded','{}','2026-10-21')")
    repo = IndexRepository(db)
    IndexRepository(db)
    backups = list(tmp_path.glob('*.pre-v3.*.sqlite3'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute('PRAGMA user_version').fetchone()[0] == 2
        assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert backup.execute('SELECT status FROM analysis_tasks').fetchone()[0] == 'succeeded'
    with repo.connection() as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 3
        assert conn.execute('SELECT status,cancel_requested FROM analysis_tasks').fetchone()[:] == ('succeeded', 0)
