import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import VideoUploader from '@/components/VideoUploader.vue'
import VideoPlayer from '@/components/VideoPlayer.vue'
import EventSearch from '@/components/EventSearch.vue'
import EventTimeline from '@/components/EventTimeline.vue'
import AnalysisPanel from '@/components/AnalysisPanel.vue'
import TaskProgress from '@/components/TaskProgress.vue'
import { diagnoseStream, uploadVideo } from '@/api/videos'
import { ApiError } from '@/api/client'
import { video, event, contract, task } from './fixtures'
vi.mock('@/api/videos', () => ({ uploadVideo: vi.fn(), diagnoseStream: vi.fn() }))
const wrappers: { unmount: () => void }[] = []
beforeEach(() => { vi.clearAllMocks(); Element.prototype.scrollIntoView = vi.fn(); vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(); vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {}) })
afterEach(() => { wrappers.splice(0).forEach(item => item.unmount()); vi.restoreAllMocks() })
function track<T extends { unmount: () => void }>(wrapper: T) { wrappers.push(wrapper); return wrapper }
describe('上传', () => {
  it.each([true, false])('后端验证上传成功/失败：%s', async success => {
    if (success) vi.mocked(uploadVideo).mockResolvedValueOnce(video)
    else vi.mocked(uploadVideo).mockRejectedValueOnce(new ApiError(422, '文件没有视频画面'))
    const wrapper = track(mount(VideoUploader)); const input = wrapper.get('input')
    Object.defineProperty(input.element, 'files', { value: [new File(['not a real video'], 'test.mp4')], configurable: true })
    await input.trigger('change'); expect(wrapper.text()).toContain('test.mp4')
    await wrapper.get('button.primary').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain(success ? '已上传' : '文件没有视频画面')
    expect(wrapper.emitted('uploaded')?.length || 0).toBe(success ? 1 : 0)
  })
  it('拖入不支持的扩展名不提交', async () => {
    const wrapper = track(mount(VideoUploader))
    await wrapper.get('.drop-zone').trigger('drop', { dataTransfer: { files: [new File(['x'], 'bad.txt')] } })
    expect(wrapper.text()).toContain('请选择 MP4'); expect(uploadVideo).not.toHaveBeenCalled()
  })
})
describe('播放器', () => {
  it('不兼容编码显示 415 语义，且不请求本地路径', () => {
    const wrapper = track(mount(VideoPlayer, { props: { video: { ...video, browser_compatible: false, compatibility_message: '需要 H264' } } }))
    expect(wrapper.text()).toContain('当前视频编码不受浏览器支持'); expect(wrapper.find('video').exists()).toBe(false)
  })
  it('播放失败诊断能保留后端 415', async () => {
    vi.mocked(diagnoseStream).mockRejectedValueOnce(new ApiError(415, '当前视频编码不受浏览器支持'))
    const wrapper = track(mount(VideoPlayer, { props: { video } })); await wrapper.get('video').trigger('error'); await flushPromises()
    expect(wrapper.text()).toContain('当前视频编码不受浏览器支持')
  })
  it('事件跳转设定 currentTime 并尝试播放，切换视频清空旧状态', async () => {
    const wrapper = track(mount(VideoPlayer, { props: { video } })); await wrapper.get('video').trigger('loadedmetadata')
    await wrapper.vm.seek(2.5); expect((wrapper.get('video').element as HTMLVideoElement).currentTime).toBe(2.5); expect(HTMLMediaElement.prototype.play).toHaveBeenCalled()
    await wrapper.setProps({ video: { ...video, video_id: 2, stream_url: '/api/videos/2/stream' } })
    expect(wrapper.get('video').attributes('src')).toContain('/api/videos/2/stream'); expect(wrapper.text()).not.toContain('已定位')
  })
})
describe('结果与参数语义', () => {
  const searchProps = { video, category: 'person', events: [], loading: false, error: '', notReady: false, previous: false, searched: true, activeId: null }
  it('空索引结果与分析尚未完成显示不同信息', async () => {
    const wrapper = track(mount(EventSearch, { props: searchProps })); expect(wrapper.text()).toContain('未检测到行人事件')
    await wrapper.setProps({ notReady: true, video: { ...video, index_available: false, analysis_status: 'running' } })
    expect(wrapper.text()).toContain('尚无可用索引'); expect(wrapper.text()).not.toContain('未检测到行人事件')
  })
  it('结果点击带回真实事件，旧索引提示明确', async () => {
    const wrapper = track(mount(EventSearch, { props: { ...searchProps, events: [event], previous: true } }))
    await wrapper.get('.event-card').trigger('click'); expect(wrapper.emitted('select')?.[0]).toEqual([event]); expect(wrapper.text()).toContain('上一次成功建立的索引')
  })
  it('数量菜单显示采样最大数量，切换时间段不重新分析', async () => {
    const wrapper = track(mount(EventSearch, { props: { ...searchProps, events: [event] } }))
    expect(wrapper.get('.event-count').text()).toContain('最多 3 人')
    expect(wrapper.text()).toContain('不是去重累计数量')
    await wrapper.findAll('[role=tab]').find(button => button.text() === '出现时间段')!.trigger('click')
    expect(wrapper.find('.event-count').exists()).toBe(false)
    await wrapper.findAll('[role=tab]').find(button => button.text() === '数量统计')!.trigger('click')
    await wrapper.get('.event-card').trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual([event])
    await wrapper.setProps({ events: [{ ...event, category: 'car', max_count: 2 }] })
    expect(wrapper.get('.event-count').text()).toContain('最多 2 个')
  })
  it('停止按钮位于开始按钮下方，停止中禁用并说明安全退出', async () => {
    const wrapper = track(mount(AnalysisPanel, { props: { video: { ...video, active_task_id: task.task_id }, contract, contractError: '', submitting: false, error: '', canStop: true } }))
    await wrapper.get('.stop-analysis').trigger('click')
    expect(wrapper.emitted('stop')).toHaveLength(1)
    await wrapper.setProps({ stopping: true })
    expect(wrapper.get('.stop-analysis').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('正在停止')
  })
  it('取消任务显示已停止，不能显示成功或分析失败', () => {
    const wrapper = track(mount(TaskProgress, { props: { task: { ...task, status: 'cancelled', cancel_requested: true }, taskId: task.task_id, error: '' } }))
    expect(wrapper.text()).toContain('已停止')
    expect(wrapper.text()).not.toContain('索引已保存')
    expect(wrapper.text()).not.toContain('分析失败')
  })
  it('重叠事件分轨且点击返回事件', async () => {
    const wrapper = track(mount(EventTimeline, { props: { events: [event, { ...event, event_id: 2, start_time: 3, end_time: 5 }, { ...event, event_id: 3, category: 'car' }], duration: 10, currentTime: 0, activeId: null, ready: true } }))
    expect(wrapper.findAll('.timeline-lane')).toHaveLength(3)
    expect(wrapper.get('.timeline-event').attributes('style')).toContain('left: 20%')
    await wrapper.get('.timeline-event').trigger('click'); expect(wrapper.emitted('select')?.[0]).toEqual([event])
  })
  it('使用后端默认置信度并限制许可范围', async () => {
    const wrapper = track(mount(AnalysisPanel, { props: { video, contract, contractError: '', submitting: false, error: '' } }))
    expect((wrapper.get('#confidence').element as HTMLInputElement).value).toBe('0.42')
    await wrapper.get('#fps').setValue('31'); expect(wrapper.get('button.primary').attributes('disabled')).toBeDefined()
    await wrapper.get('#fps').setValue('2'); await wrapper.get('button.primary').trigger('click')
    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({ confidence: .42, sample_fps: 2, imgsz: 640 })
  })
  it.each(['queued', 'running', 'succeeded', 'failed'] as const)('任务 %s 按状态展示', status => {
    const wrapper = track(mount(TaskProgress, { props: { task: { ...task, status, progress: 100, error_message: status === 'failed' ? '推理失败' : null }, taskId: task.task_id, error: '' } }))
    expect(wrapper.get('.status').attributes('data-status')).toBe(status)
    expect(wrapper.text().includes('索引已保存')).toBe(status === 'succeeded')
    if (status === 'failed') expect(wrapper.text()).toContain('推理失败')
  })
})
