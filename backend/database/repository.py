"""SQLite access boundary. Detection/model code never knows about SQL."""
from contextlib import contextmanager, nullcontext
import logging
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

from backend.core.analyzer import FrameResult, ScanSummary
from backend.core.video_io import VideoInfo


class IndexBusyError(RuntimeError):
    pass


class IndexRepository:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise RuntimeError(f"不支持的 SQLite 数据库版本: {version}")
            if version in (1, 2):
                backup = self.path.with_name(self.path.name + f".pre-v3.{uuid4().hex[:8]}.sqlite3")
                with sqlite3.connect(backup) as destination:
                    conn.backup(destination)
                logging.getLogger(__name__).info("数据库升级前备份已保存: %s", backup)
            if conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
            if version == 0:
                schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
                conn.executescript("BEGIN IMMEDIATE;\n" + schema + "\nCOMMIT;")
                version = 1
            if version == 1:
                migration = Path(__file__).with_name("migration_v2.sql").read_text(encoding="utf-8")
                conn.executescript("BEGIN IMMEDIATE;\n" + migration + "\nCOMMIT;")
                version = 2
            if version == 2:
                migration = Path(__file__).with_name("migration_v3.sql").read_text(encoding="utf-8")
                conn.executescript("BEGIN IMMEDIATE;\n" + migration + "\nCOMMIT;")

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def get_video(self, video_id: int):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
            return dict(row) if row else None

    def claim(self, content_hash: str, info: VideoInfo, key: str, *, force: bool = False):
        """Atomically claim a video, or return a reusable completed index."""
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM videos WHERE content_sha256=?", (content_hash,)).fetchone()
            if row:
                if row["status"] == "analyzing":
                    raise IndexBusyError("该视频正在分析；若上次进程被强制关闭，请用 recover 恢复状态后重试")
                if row["status"] == "completed" and row["analysis_key"] == key and not force:
                    # Same content at a new path is still one indexed video.
                    conn.execute("UPDATE videos SET name=CASE WHEN is_uploaded=1 THEN name ELSE ? END,"
                                 "path=CASE WHEN is_uploaded=1 THEN path ELSE ? END WHERE id=?",
                                 (info.path.name, str(info.path), row["id"]))
                    return row["id"], True
                conn.execute("UPDATE videos SET status='analyzing',last_error=NULL WHERE id=?", (row["id"],))
                return row["id"], False
            cursor = conn.execute(
                "INSERT INTO videos(content_sha256,name,path,duration,fps,width,height,total_frames,status) "
                "VALUES(?,?,?,?,?,?,?,?,'analyzing')",
                (content_hash, info.path.name, str(info.path), info.duration_seconds, info.fps,
                 info.width, info.height, info.total_frames))
            return cursor.lastrowid, False

    def fail(self, video_id: int, error: str):
        with self.transaction() as conn:
            conn.execute("UPDATE videos SET status=CASE WHEN analysis_key IS NULL THEN 'failed' "
                         "ELSE 'completed' END,last_error=? WHERE id=?", (error[:2000], video_id))

    def recover(self, video_id: int):
        """Explicit recovery only: caller must ensure the old worker is stopped."""
        with self.transaction() as conn:
            row = conn.execute("SELECT status FROM videos WHERE id=?", (video_id,)).fetchone()
            if not row or row[0] != "analyzing":
                raise ValueError("视频不存在或不处于 analyzing 状态")
            conn.execute("UPDATE videos SET status=CASE WHEN analysis_key IS NULL THEN 'failed' "
                         "ELSE 'completed' END,last_error='已手动恢复中断任务' WHERE id=?", (video_id,))

    @contextmanager
    def replace_index(self, video_id: int, *, publish_guard=None):
        # Analysis writes to disk staging, leaving the main DB free to commit
        # task progress. Only publication locks the main DB; it remains atomic.
        staging_root = self.path.parent / ".index-staging"
        staging_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=staging_root) as folder:
            stage = sqlite3.connect(Path(folder) / "stage.sqlite3")
            stage.row_factory = sqlite3.Row
            try:
                stage.execute("ATTACH DATABASE ? AS source", (str(self.path),))
                for table in ("videos", "detections", "events"):
                    stage.execute(f"CREATE TABLE {table} AS SELECT * FROM source.{table} WHERE 0")
                stage.execute("CREATE INDEX stage_detection_times ON detections(video_id,class_name,timestamp)")
                stage.execute("INSERT INTO videos SELECT * FROM source.videos WHERE id=?", (video_id,))
                stage.commit()
                stage.execute("DETACH DATABASE source")
                yield IndexWriter(stage, video_id)
                stage.commit()
                with (publish_guard() if publish_guard else nullcontext()), self.transaction() as conn:
                    conn.execute("DELETE FROM events WHERE video_id=?", (video_id,))
                    conn.execute("DELETE FROM detections WHERE video_id=?", (video_id,))
                    conn.executemany(
                        "INSERT INTO detections(video_id,frame_index,timestamp,class_id,class_name,confidence,x1,y1,x2,y2) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)", stage.execute(
                        "SELECT video_id,frame_index,timestamp,class_id,class_name,confidence,x1,y1,x2,y2 FROM detections"))
                    conn.executemany("INSERT INTO events(video_id,class_name,start_time,end_time,sample_count) VALUES(?,?,?,?,?)",
                                     stage.execute("SELECT video_id,class_name,start_time,end_time,sample_count FROM events"))
                    columns = ("name", "path", "duration", "fps", "width", "height", "total_frames", "status",
                               "analysis_key", "analysis_fps", "image_size", "confidence", "sampled_frames",
                               "merge_gap", "min_samples", "timestamp_source", "estimated_tail", "last_error", "analyzed_at")
                    row = stage.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
                    conn.execute("UPDATE videos SET " + ",".join(c + "=?" for c in columns) + " WHERE id=?",
                                 (*[row[c] for c in columns], video_id))
            finally:
                stage.close()

    def rebuild_events(self, video_id: int, merge_gap: float, min_samples: int, merger):
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
            if not row or row["status"] != "completed":
                raise ValueError("仅能重新合并已完成的视频索引")
            writer = IndexWriter(conn, video_id)
            conn.execute("DELETE FROM events WHERE video_id=?", (video_id,))
            writer.merge_events(row["duration"], merge_gap, min_samples, merger)
            conn.execute("UPDATE videos SET merge_gap=?,min_samples=? WHERE id=?",
                         (merge_gap, min_samples, video_id))

    def search(self, class_name: str | None, video_id: int | None = None, start_time=None, end_time=None,
               *, include_counts=False):
        counts = (",(SELECT COALESCE(MAX(n),0) FROM (SELECT COUNT(*) AS n FROM detections d "
                  "WHERE d.video_id=e.video_id AND d.class_name=e.class_name "
                  "AND d.timestamp BETWEEN e.start_time AND e.end_time "
                  "GROUP BY d.frame_index,d.timestamp)) AS max_count" if include_counts else "")
        sql = ("SELECT e.id AS event_id,v.id AS video_id,v.name AS video_name,e.class_name,e.start_time,e.end_time,"
               "e.end_time-e.start_time AS duration,e.sample_count" + counts + " FROM events e "
               "JOIN videos v ON v.id=e.video_id WHERE v.analysis_key IS NOT NULL")
        params = []
        if class_name is not None:
            sql += " AND e.class_name=?"
            params.append(class_name)
        if video_id is not None:
            sql += " AND v.id=?"
            params.append(video_id)
        if start_time is not None:
            sql += " AND e.end_time>=?"
            params.append(start_time)
        if end_time is not None:
            sql += " AND e.start_time<=?"
            params.append(end_time)
        sql += " ORDER BY e.start_time,e.end_time,v.id"
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    def raw_detections(self, video_id: int):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM detections WHERE video_id=? ORDER BY timestamp,id", (video_id,))]

    def counts(self, video_id: int):
        with self.connection() as conn:
            detections = conn.execute("SELECT COUNT(*) FROM detections WHERE video_id=?", (video_id,)).fetchone()[0]
            events = conn.execute("SELECT COUNT(*) FROM events WHERE video_id=?", (video_id,)).fetchone()[0]
            return {"detections": detections, "events": events}


class IndexWriter:
    def __init__(self, conn, video_id):
        self.conn, self.video_id = conn, video_id

    def add_frame(self, result: FrameResult):
        if not result.analyzed:
            return
        self.conn.executemany(
            "INSERT INTO detections(video_id,frame_index,timestamp,class_id,class_name,confidence,x1,y1,x2,y2) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(self.video_id, result.frame_index, result.timestamp_seconds, item.class_id,
              item.class_name, item.confidence, *item.xyxy) for item in result.detections])

    def merge_events(self, duration: float, gap: float, minimum: int, merger):
        # DISTINCT ensures several people in one frame count as one observation,
        # rather than falsely turning a single-frame false positive into an event.
        rows = self.conn.execute(
            "SELECT DISTINCT class_name,timestamp FROM detections WHERE video_id=? "
            "ORDER BY class_name,timestamp", (self.video_id,))
        self.conn.executemany(
            "INSERT INTO events(video_id,class_name,start_time,end_time,sample_count) VALUES(?,?,?,?,?)",
            ((self.video_id, e.class_name, e.start_time, e.end_time, e.sample_count)
             for e in merger(rows, duration=duration, merge_gap=gap, min_samples=minimum)))

    def complete(self, summary: ScanSummary, key: str, detector_config, index_config):
        info = summary.input_info
        self.conn.execute(
            "UPDATE videos SET name=CASE WHEN is_uploaded=1 THEN name ELSE ? END,"
            "path=CASE WHEN is_uploaded=1 THEN path ELSE ? END,duration=?,fps=?,width=?,height=?,total_frames=?,"
            "status='completed',analysis_key=?,analysis_fps=?,image_size=?,confidence=?,sampled_frames=?,"
            "merge_gap=?,min_samples=?,timestamp_source='ffprobe_pts',estimated_tail=?,last_error=NULL,"
            "analyzed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (info.path.name, str(info.path), summary.duration_seconds, info.fps, info.width, info.height,
             summary.processed_frames, key, index_config.analysis_fps, detector_config.image_size,
             detector_config.confidence, summary.analyzed_frames, index_config.merge_gap,
             index_config.min_samples, int(summary.estimated_tail), self.video_id))
