import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiUrl, request } from '@/api/client'
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
describe('统一 Fetch 请求', () => {
  it('保留 FormData，让浏览器生成 boundary', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{"video_id":1}', { status: 201 }))
    vi.stubGlobal('fetch', fetch)
    const form = new FormData(); form.append('file', new Blob(['video']), 'test.mp4')
    expect(await request('/api/videos', { method: 'POST', body: form })).toEqual({ video_id: 1 })
    expect(fetch.mock.calls[0]?.[1].body).toBe(form)
    expect(fetch.mock.calls[0]?.[1].headers).toBeUndefined()
  })
  it.each([
    [409, { detail: { code: 'index_not_ready', message: '尚无有效索引' } }, '尚无有效索引'],
    [429, { detail: '稍后重试' }, '分析队列已满'],
    [415, { detail: { code: 'unsupported_browser_codec', message: 'codec' } }, '当前视频编码不受浏览器支持'],
    [422, { detail: [{ loc: ['body', 'sample_fps'], msg: 'too large' }] }, 'sample_fps：too large'],
    [404, { detail: '视频不存在' }, '视频不存在'],
  ])('保留 HTTP %s 的语义', async (status, body, expected) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })))
    await expect(request('/api/videos')).rejects.toMatchObject({ status, message: expect.stringContaining(expected) })
  })
  it('网络失败提供可操作信息', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fetch failed')))
    await expect(request('/health')).rejects.toThrow('无法连接后端')
  })
  it('超时取消请求并报告原因', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn((_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))))
    const result = request('/health', { timeout: 10 }).catch(error => error)
    await vi.advanceTimersByTimeAsync(10)
    expect(await result).toBeInstanceOf(ApiError)
    expect((await result as ApiError).message).toContain('请求超时')
  })
  it('拒绝来自其他来源的视频地址', () => { expect(() => apiUrl('https://untrusted.example/stream')).toThrow('来源不一致') })
})
