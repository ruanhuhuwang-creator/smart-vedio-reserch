import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DashboardView from '@/views/DashboardView.vue'
import * as videos from '@/api/videos'
import { getTask } from '@/api/tasks'
import { ApiError } from '@/api/client'
import { writeLocal } from '@/utils/storage'
import { video, event, task, contract } from './fixtures'
vi.mock('@/api/videos', () => ({ listVideos: vi.fn(), getVideo: vi.fn(), getEvents: vi.fn(), getAnalysisContract: vi.fn(), analyzeVideo: vi.fn(), uploadVideo: vi.fn(), diagnoseStream: vi.fn() }))
vi.mock('@/api/tasks', () => ({ getTask: vi.fn() }))
vi.mock('@/api/client', async importOriginal => ({ ...await importOriginal<typeof import('@/api/client')>(), request: vi.fn().mockResolvedValue({ status: 'ok' }) }))
let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear()
  vi.mocked(videos.listVideos).mockResolvedValue({ total: 1, offset: 0, limit: 8, items: [video] })
  vi.mocked(videos.getVideo).mockResolvedValue(video)
  vi.mocked(videos.getAnalysisContract).mockResolvedValue(contract)
  vi.mocked(videos.getEvents).mockResolvedValue({ video_id: 1, analysis_status: 'completed', index_available: true, using_previous_index: false, events: [event] })
  vi.mocked(getTask).mockResolvedValue({ ...task, status: 'succeeded', progress: 100 })
})
afterEach(() => { wrapper?.unmount(); localStorage.clear() })
it('连接分页列表、详情、person/car 查询；初次打开不提交任务', async () => {
  wrapper = mount(DashboardView); await flushPromises()
  expect(videos.listVideos).toHaveBeenCalledWith(0, 8, expect.any(AbortSignal))
  expect(videos.getVideo).toHaveBeenCalledWith(1, expect.any(AbortSignal))
  expect(wrapper.text()).toContain('unit-test.mp4')
  expect(videos.getEvents).toHaveBeenCalledWith(1, 'person', expect.any(AbortSignal))
  await wrapper.findAll('.category-options button').find(button => button.text().includes('car'))!.trigger('click'); await flushPromises()
  expect(videos.getEvents).toHaveBeenLastCalledWith(1, 'car', expect.any(AbortSignal))
  expect(videos.analyzeVideo).not.toHaveBeenCalled()
})
it('刷新恢复已保存任务，仅 GET 不重复 POST', async () => {
  writeLocal('selected-video', '1'); writeLocal('video:1:task', task.task_id)
  wrapper = mount(DashboardView); await flushPromises()
  expect(getTask).toHaveBeenCalledWith(task.task_id, expect.any(AbortSignal))
  expect(wrapper.text()).toContain('分析成功'); expect(videos.analyzeVideo).not.toHaveBeenCalled()
})
it('从服务端 active_task_id 恢复活动任务', async () => {
  vi.mocked(videos.getVideo).mockResolvedValue({ ...video, active_task_id: 'server-task', analysis_status: 'running' })
  vi.mocked(getTask).mockResolvedValue({ ...task, task_id: 'server-task', status: 'running', progress: null, total_frames: null })
  wrapper = mount(DashboardView); await flushPromises()
  expect(getTask).toHaveBeenCalledWith('server-task', expect.any(AbortSignal)); expect(wrapper.text()).toContain('任务进行中')
})
it.each([409, 429])('提交错误 %s 明确展示且不自动重试', async status => {
  vi.mocked(videos.analyzeVideo).mockRejectedValue(new ApiError(status, status === 429 ? '分析队列已满，请稍后手动重试' : '已有活动分析任务'))
  wrapper = mount(DashboardView); await flushPromises()
  await wrapper.get('.analysis-panel button.primary').trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain(status === 429 ? '分析队列已满' : '已有活动分析任务')
  expect(videos.analyzeVideo).toHaveBeenCalledTimes(1)
})
it('提交成功保存 task_id，由轮询独立取得结果', async () => {
  vi.mocked(videos.analyzeVideo).mockResolvedValue(task)
  wrapper = mount(DashboardView); await flushPromises()
  await wrapper.get('.analysis-panel button.primary').trigger('click'); await flushPromises()
  expect(getTask).toHaveBeenCalledWith(task.task_id, expect.any(AbortSignal))
  expect(videos.analyzeVideo).toHaveBeenCalledWith(1, contract.defaults)
  expect(wrapper.text()).toContain('分析成功')
})
