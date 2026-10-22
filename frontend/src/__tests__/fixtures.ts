// 仅供单元测试的确定性输入；产品界面没有演示数据分支。
import type { Task, Video, VideoEvent, AnalysisContract } from '@/types/api'
export const video: Video = { video_id: 1, filename: 'unit-test.mp4', duration: 10, fps: 25, width: 640, height: 480, resolution: '640x480', analysis_status: 'completed', created_at: '2026-10-21T00:00:00+00:00', index_available: true, active_task_id: null, video_codec: 'h264', browser_compatible: true, compatibility_message: null, stream_url: '/api/videos/1/stream' }
export const task: Task = { task_id: 'test-task', video_id: 1, status: 'queued', progress: 0, progress_is_estimate: true, processed_frames: 0, total_frames: 250, index_reused: false, created_at: '2026-10-21T00:00:00+00:00', started_at: null, finished_at: null, error_message: null }
export const event: VideoEvent = { event_id: 1, video_id: 1, category: 'person', start_time: 2, end_time: 4, duration: 2, max_count: 3 }
export const contract: AnalysisContract = { defaults: { imgsz: 640, sample_fps: 2, confidence: .42, force_rebuild: false }, fpsMin: .25, fpsMax: 30, confidenceMin: .05, confidenceMax: 1, sizes: [416, 640, 960] }
