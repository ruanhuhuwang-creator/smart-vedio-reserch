ALTER TABLE videos ADD COLUMN is_uploaded INTEGER NOT NULL DEFAULT 0;
ALTER TABLE videos ADD COLUMN created_at TEXT;
ALTER TABLE videos ADD COLUMN video_codec TEXT;
ALTER TABLE videos ADD COLUMN browser_compatible INTEGER NOT NULL DEFAULT 0;
ALTER TABLE videos ADD COLUMN compatibility_message TEXT;

CREATE TABLE analysis_tasks (
    task_id TEXT PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id),
    status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed')),
    parameters_json TEXT NOT NULL,
    progress REAL CHECK(progress BETWEEN 0 AND 100),
    progress_is_estimate INTEGER NOT NULL DEFAULT 1,
    processed_frames INTEGER NOT NULL DEFAULT 0,
    total_frames INTEGER,
    index_reused INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT
);
CREATE UNIQUE INDEX ix_tasks_active_video ON analysis_tasks(video_id)
    WHERE status IN ('queued','running');
CREATE INDEX ix_tasks_status_created ON analysis_tasks(status,created_at);
CREATE INDEX ix_uploaded_created ON videos(is_uploaded,created_at,id);
PRAGMA user_version=2;
