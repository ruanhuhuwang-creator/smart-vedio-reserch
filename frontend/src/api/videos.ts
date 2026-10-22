import { apiUrl, request, responseError } from './client'
import type { AnalysisContract, AnalysisOptions, EventPage, Task, Video, VideoPage } from '@/types/api'

export const listVideos = (offset = 0, limit = 8, signal?: AbortSignal) => request<VideoPage>(`/api/videos?offset=${offset}&limit=${limit}`, { signal })
export const getVideo = (id: number, signal?: AbortSignal) => request<Video>(`/api/videos/${id}`, { signal })
export function uploadVideo(file: File, signal?: AbortSignal) {
  const form = new FormData(); form.append('file', file)
  return request<Video>('/api/videos', { method: 'POST', body: form, timeout: 300000, signal })
}
export const analyzeVideo = (id: number, body: AnalysisOptions) => request<Task>(`/api/videos/${id}/analysis`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})
export const getEvents = (id: number, category: string, signal?: AbortSignal) => request<EventPage>(
  `/api/videos/${id}/events${category ? `?category=${encodeURIComponent(category)}` : ''}`, { signal },
)
// 读取正在运行的服务 OpenAPI，使用其默认置信度及许可范围。
export async function getAnalysisContract(): Promise<AnalysisContract> {
  const schema = await request<{ components: { schemas: { AnalysisRequest: { properties: Record<string, { default: number | boolean; minimum?: number; maximum?: number; enum?: number[] }> } } } }>('/openapi.json')
  const p = schema.components.schemas.AnalysisRequest.properties
  if (!p.sample_fps || !p.imgsz || !p.confidence || !p.imgsz.enum) throw new Error('后端分析参数定义不完整')
  return {
    defaults: { sample_fps: Number(p.sample_fps.default), imgsz: Number(p.imgsz.default) as AnalysisOptions['imgsz'], confidence: Number(p.confidence.default), force_rebuild: false },
    fpsMin: p.sample_fps.minimum!, fpsMax: p.sample_fps.maximum!, confidenceMin: p.confidence.minimum!, confidenceMax: p.confidence.maximum!, sizes: p.imgsz.enum,
  }
}
// 原生 video 的错误事件不提供 HTTP 状态；发生错误时用一字节 Range 请求诊断。
export async function diagnoseStream(path: string, signal: AbortSignal) {
  const response = await fetch(apiUrl(path), { headers: { Range: 'bytes=0-0' }, signal })
  if (!response.ok) throw await responseError(response)
  await response.body?.cancel()
}
