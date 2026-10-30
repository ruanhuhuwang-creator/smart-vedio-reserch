"""Upload registry and durable task state; each call owns its SQLite connection."""
# API 数据存取：补充视频列表、上传登记和任务状态；检测索引本身由 IndexRepository 管理。
from datetime import datetime, timezone
import json
import sqlite3
from uuid import uuid4

from backend.database.repository import IndexRepository, IndexBusyError


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class APIRepository:
    def __init__(self, index: IndexRepository):
        self.index = index

    def register_upload(self, digest, filename, path, info, duration, codec, compatible, message):
        with self.index.transaction() as conn:
            row = conn.execute("SELECT * FROM videos WHERE content_sha256=?", (digest,)).fetchone()
            if row and row["is_uploaded"]:
                return row["id"], False
            if row and row["status"] == "analyzing":
                raise IndexBusyError("相同视频正被 CLI 分析，请等待结束后上传")
            if row:
                video_id = row["id"]
                conn.execute("UPDATE videos SET name=?,path=?,is_uploaded=1,created_at=?,video_codec=?,"
                             "browser_compatible=?,compatibility_message=? WHERE id=?",
                             (filename, str(path), utc_now(), codec, int(compatible), message, video_id))
            else:
                video_id = conn.execute(
                    "INSERT INTO videos(content_sha256,name,path,duration,fps,width,height,total_frames,status,"
                    "is_uploaded,created_at,video_codec,browser_compatible,compatibility_message) "
                    "VALUES(?,?,?,?,?,?,?,?,'failed',1,?,?,?,?)",
                    (digest, filename, str(path), duration, info.fps, info.width, info.height, info.total_frames,
                     utc_now(), codec, int(compatible), message)).lastrowid
            return video_id, True

    @staticmethod
    def _video_query():
        return ("SELECT v.*, (SELECT status FROM analysis_tasks t WHERE t.video_id=v.id "
                "ORDER BY created_at DESC,task_id DESC LIMIT 1) AS latest_task_status,"
                "(SELECT task_id FROM analysis_tasks t WHERE t.video_id=v.id AND status IN ('queued','running') "
                "LIMIT 1) AS active_task_id FROM videos v WHERE is_uploaded=1")

    def video(self, video_id):
        with self.index.connection() as conn:
            row = conn.execute(self._video_query() + " AND v.id=?", (video_id,)).fetchone()
            return dict(row) if row else None

    def videos(self, offset, limit):
        with self.index.connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM videos WHERE is_uploaded=1").fetchone()[0]
            rows = conn.execute(self._video_query() + " ORDER BY v.created_at DESC,v.id DESC LIMIT ? OFFSET ?",
                                (limit, offset))
            return total, [dict(row) for row in rows]

    def create_task(self, video_id, parameters):
        task_id = uuid4().hex
        try:
            with self.index.transaction() as conn:
                conn.execute("INSERT INTO analysis_tasks(task_id,video_id,status,parameters_json,progress,created_at) "
                             "VALUES(?,?,'queued',?,0,?)", (task_id, video_id, json.dumps(parameters), utc_now()))
        except sqlite3.IntegrityError as exc:
            raise IndexBusyError("该视频已有排队或执行中的任务") from exc
        return self.task(task_id)

    def task(self, task_id):
        with self.index.connection() as conn:
            row = conn.execute("SELECT * FROM analysis_tasks WHERE task_id=?", (task_id,)).fetchone()
            return dict(row) if row else None

    def start(self, task_id):
        with self.index.transaction() as conn:
            return conn.execute("UPDATE analysis_tasks SET status='running',started_at=? "
                                "WHERE task_id=? AND status='queued'", (utc_now(), task_id)).rowcount == 1

    def progress(self, task_id, processed, total):
        total = total if total and total > 0 else None
        percentage = min(99.0, max(0.0, 100 * processed / total)) if total else None
        with self.index.transaction() as conn:
            conn.execute("UPDATE analysis_tasks SET processed_frames=?,total_frames=?,progress=?,"
                         "progress_is_estimate=1 WHERE task_id=? AND status='running'",
                         (processed, total, percentage, task_id))

    def succeeded(self, task_id, total, reused):
        with self.index.transaction() as conn:
            conn.execute("UPDATE analysis_tasks SET status='succeeded',progress=100,progress_is_estimate=0,"
                         "processed_frames=?,total_frames=?,index_reused=?,finished_at=? "
                         "WHERE task_id=? AND status='running'", (total, total, int(reused), utc_now(), task_id))

    def failed(self, task_id, error):
        with self.index.transaction() as conn:
            conn.execute("UPDATE analysis_tasks SET status='failed',error_message=?,finished_at=? "
                         "WHERE task_id=? AND status IN ('queued','running')", (error[:2000], utc_now(), task_id))

    def request_cancel(self, task_id):
        with self.index.transaction() as conn:
            conn.execute("UPDATE analysis_tasks SET cancel_requested=1 WHERE task_id=? "
                         "AND status IN ('queued','running')", (task_id,))

    def cancelled(self, task_id):
        with self.index.transaction() as conn:
            conn.execute("UPDATE analysis_tasks SET status='cancelled',cancel_requested=1,"
                         "error_message=NULL,finished_at=? WHERE task_id=? AND status IN ('queued','running')",
                         (utc_now(), task_id))

    def recover_interrupted(self):
        message = "服务上次停止时任务未完成，已标记失败；请重新提交分析任务"
        with self.index.transaction() as conn:
            videos = conn.execute("SELECT DISTINCT video_id FROM analysis_tasks WHERE status IN ('queued','running')").fetchall()
            for row in videos:
                conn.execute("UPDATE videos SET status=CASE WHEN analysis_key IS NULL THEN 'failed' ELSE 'completed' END,"
                             "last_error=? WHERE id=? AND status='analyzing'", (message, row[0]))
            conn.execute("UPDATE analysis_tasks SET status=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'failed' END,"
                         "error_message=CASE WHEN cancel_requested=1 THEN NULL ELSE ? END,finished_at=? "
                         "WHERE status IN ('queued','running')", (message, utc_now()))
