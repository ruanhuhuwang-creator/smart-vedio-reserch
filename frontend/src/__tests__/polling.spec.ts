import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { getTask } from '@/api/tasks'
import { useTaskPolling } from '@/composables/useTaskPolling'
import { task } from './fixtures'
vi.mock('@/api/tasks', () => ({ getTask: vi.fn() }))
const scopes: ReturnType<typeof effectScope>[] = []
function start() { const scope = effectScope(); scopes.push(scope); const id = ref<string | null>('a'); return { id, ...scope.run(() => useTaskPolling(id))! } }
beforeEach(() => { vi.useFakeTimers(); vi.mocked(getTask).mockReset() })
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.useRealTimers() })
describe('任务轮询生命周期', () => {
  it('排队 → 运行 → 成功，终态停止', async () => {
    vi.mocked(getTask).mockResolvedValueOnce(task).mockResolvedValueOnce({ ...task, status: 'running', progress: 50 }).mockResolvedValueOnce({ ...task, status: 'succeeded', progress: 100 })
    const state = start(); await flushPromises(); expect(state.task.value?.status).toBe('queued')
    await vi.advanceTimersByTimeAsync(2000); expect(state.task.value?.status).toBe('running')
    await vi.advanceTimersByTimeAsync(2000); expect(state.task.value?.status).toBe('succeeded')
    await vi.advanceTimersByTimeAsync(10000); expect(getTask).toHaveBeenCalledTimes(3)
  })
  it('progress=100 的 running 不被误判成功', async () => {
    vi.mocked(getTask).mockResolvedValue({ ...task, status: 'running', progress: 100 })
    const state = start(); await flushPromises(); await vi.advanceTimersByTimeAsync(2000)
    expect(state.task.value?.status).toBe('running'); expect(getTask).toHaveBeenCalledTimes(2)
  })
  it('失败停止，保留后端原因', async () => {
    vi.mocked(getTask).mockResolvedValue({ ...task, status: 'failed', error_message: '显存不足' })
    const state = start(); await flushPromises(); await vi.advanceTimersByTimeAsync(6000)
    expect(state.task.value?.error_message).toBe('显存不足'); expect(getTask).toHaveBeenCalledTimes(1)
  })
  it('网络错误暂停，手动重试', async () => {
    vi.mocked(getTask).mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce(task)
    const state = start(); await flushPromises(); await vi.advanceTimersByTimeAsync(10000)
    expect(state.error.value).toBe('网络中断'); expect(getTask).toHaveBeenCalledTimes(1)
    state.retry(); await flushPromises(); expect(state.error.value).toBe(''); expect(getTask).toHaveBeenCalledTimes(2)
  })
  it('任务切换取消旧请求，迟到响应不会覆盖新任务', async () => {
    let complete!: (value: typeof task) => void
    vi.mocked(getTask).mockImplementationOnce(() => new Promise(resolve => { complete = resolve })).mockResolvedValueOnce({ ...task, task_id: 'b', status: 'succeeded' })
    const state = start(); const oldSignal = vi.mocked(getTask).mock.calls[0]?.[1]
    state.id.value = 'b'; await nextTick(); await flushPromises()
    expect(oldSignal?.aborted).toBe(true)
    complete({ ...task, task_id: 'a' }); await flushPromises(); expect(state.task.value?.task_id).toBe('b')
  })
  it('卸载与清除任务都停止旧轮询', async () => {
    vi.mocked(getTask).mockResolvedValue(task)
    const state = start(); await flushPromises(); state.id.value = null; await nextTick(); await vi.advanceTimersByTimeAsync(8000)
    expect(getTask).toHaveBeenCalledTimes(1); expect(state.task.value).toBeNull()
    state.id.value = 'b'; await nextTick(); await flushPromises(); scopes[0]!.stop(); await vi.advanceTimersByTimeAsync(8000)
    expect(getTask).toHaveBeenCalledTimes(2)
  })
})
