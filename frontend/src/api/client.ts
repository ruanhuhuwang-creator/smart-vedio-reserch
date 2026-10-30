// 发布页面始终同源；开发模式继续允许 Vite 单独连接后端。
export const API_BASE = (import.meta.env.PROD ? window.location.origin :
  (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000')).replace(/\/$/, '')

// 统一的错误对象：status 是 HTTP 状态码，code 是后端业务错误标记，message 给用户看。
export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string, public detail?: unknown) {
    super(message); this.name = 'ApiError'
  }
}
export function apiUrl(path: string) {
  const url = new URL(path, `${API_BASE}/`)
  if (url.origin !== new URL(API_BASE).origin || !['http:', 'https:'].includes(url.protocol)) {
    throw new Error('视频地址与已配置的 API 来源不一致')
  }
  return url.href
}
export async function responseError(response: Response) {
  const body = await response.json().catch(() => null)
  const detail = body?.detail
  let message = typeof detail === 'string' ? detail : detail?.message
  if (Array.isArray(detail)) message = detail.map(item => `${item.loc?.slice(1).join('.') || '参数'}：${item.msg}`).join('；')
  if (response.status === 415 && detail?.code === 'unsupported_browser_codec') message = '当前视频编码不受浏览器支持'
  if (response.status === 429) message = `分析队列已满，请稍后手动重试。${message || ''}`
  return new ApiError(response.status, message || `请求失败（HTTP ${response.status}）`, detail?.code, detail)
}
export async function request<T>(path: string, options: RequestInit & { timeout?: number } = {}): Promise<T> {
  const { timeout = 15000, signal, ...init } = options
  // AbortController 像请求的停止开关：超时或切换页面时中断请求，并在 finally 清理定时器。
  const controller = new AbortController()
  let timedOut = false
  const abort = () => controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) abort()
  const timer = setTimeout(() => { timedOut = true; controller.abort() }, timeout)
  try {
    const response = await fetch(apiUrl(path), { ...init, signal: controller.signal })
    if (!response.ok) throw await responseError(response)
    // T 帮 TypeScript 检查调用代码，但不会在运行时验证 JSON；字段仍必须遵守真实后端协议。
    return await response.json() as T
  } catch (error) {
    if (timedOut) throw new ApiError(0, '请求超时，请检查服务状态后重试')
    if (error instanceof ApiError || controller.signal.aborted) throw error
    throw new ApiError(0, '无法连接后端，请检查服务、API 地址和 CORS 配置')
  } finally {
    clearTimeout(timer); signal?.removeEventListener('abort', abort)
  }
}
export function errorMessage(error: unknown) { return error instanceof Error ? error.message : '发生未知错误' }
