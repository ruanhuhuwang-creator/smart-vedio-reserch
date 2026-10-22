PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    content_sha256 TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    duration REAL NOT NULL CHECK(duration >= 0),
    fps REAL NOT NULL CHECK(fps > 0),
    width INTEGER NOT NULL CHECK(width > 0),
    height INTEGER NOT NULL CHECK(height > 0),
    total_frames INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK(status IN ('analyzing', 'completed', 'failed')),
    analysis_key TEXT,
    analysis_fps REAL,
    image_size INTEGER,
    confidence REAL,
    sampled_frames INTEGER NOT NULL DEFAULT 0,
    merge_gap REAL,
    min_samples INTEGER,
    timestamp_source TEXT,
    estimated_tail INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    analyzed_at TEXT
);

CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    frame_index INTEGER NOT NULL CHECK(frame_index >= 0),
    timestamp REAL NOT NULL CHECK(timestamp >= 0),
    class_id INTEGER NOT NULL,
    class_name TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    x1 REAL NOT NULL, y1 REAL NOT NULL, x2 REAL NOT NULL, y2 REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    class_name TEXT NOT NULL,
    start_time REAL NOT NULL CHECK(start_time >= 0),
    end_time REAL NOT NULL CHECK(end_time >= start_time),
    sample_count INTEGER NOT NULL CHECK(sample_count >= 2),
    UNIQUE(video_id, class_name, start_time, end_time)
);

CREATE INDEX IF NOT EXISTS ix_detections_video_class_time
    ON detections(video_id, class_name, timestamp);
CREATE INDEX IF NOT EXISTS ix_events_class_time
    ON events(class_name, start_time, video_id);
CREATE INDEX IF NOT EXISTS ix_events_video_class_time
    ON events(video_id, class_name, start_time);
