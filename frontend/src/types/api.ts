// 对应 backend/schemas/api.py；不是演示数据。
export interface Video {
  video_id: number; filename: string; duration: number; fps: number
  width: number; height: number; resolution: string; analysis_status: string
  created_at: string; index_available: boolean; active_task_id: string | null
  video_codec: string; browser_compatible: boolean; compatibility_message: string | null
  stream_url: string
}
export interface VideoPage { total: number; offset: number; limit: number; items: Video[] }
export interface AnalysisOptions {
  sample_fps: number; imgsz: 416 | 640 | 960; confidence: number; force_rebuild: boolean
}
export interface Task {
  task_id: string; video_id: number; status: 'queued' | 'running' | 'succeeded' | 'failed'
  progress: number | null; progress_is_estimate: boolean; processed_frames: number
  total_frames: number | null; index_reused: boolean; created_at: string
  started_at: string | null; finished_at: string | null; error_message: string | null
}
export interface VideoEvent {
  event_id: number; video_id: number; category: string
  start_time: number; end_time: number; duration: number
}
export interface EventPage {
  video_id: number; analysis_status: string; index_available: boolean
  using_previous_index: boolean; events: VideoEvent[]
}
export interface AnalysisContract {
  defaults: AnalysisOptions
  fpsMin: number; fpsMax: number; confidenceMin: number; confidenceMax: number
  sizes: number[]
}
