-- Preserve all existing tasks while extending the SQLite CHECK constraint.
CREATE TABLE analysis_tasks_v3 (
    task_id TEXT PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id),
    status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
    parameters_json TEXT NOT NULL,
    progress REAL CHECK(progress BETWEEN 0 AND 100),
    progress_is_estimate INTEGER NOT NULL DEFAULT 1,
    processed_frames INTEGER NOT NULL DEFAULT 0,
    total_frames INTEGER,
    index_reused INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1))
);
INSERT INTO analysis_tasks_v3
    (task_id,video_id,status,parameters_json,progress,progress_is_estimate,processed_frames,
     total_frames,index_reused,created_at,started_at,finished_at,error_message)
SELECT task_id,video_id,status,parameters_json,progress,progress_is_estimate,processed_frames,
       total_frames,index_reused,created_at,started_at,finished_at,error_message FROM analysis_tasks;
DROP TABLE analysis_tasks;
ALTER TABLE analysis_tasks_v3 RENAME TO analysis_tasks;
CREATE UNIQUE INDEX ix_tasks_active_video ON analysis_tasks(video_id) WHERE status IN ('queued','running');
CREATE INDEX ix_tasks_status_created ON analysis_tasks(status,created_at);
PRAGMA user_version=3;
