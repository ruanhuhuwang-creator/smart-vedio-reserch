import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { time } from '@/utils/format'
import VideoList from '@/components/VideoList.vue'
import { video } from './fixtures'
describe('时间与分页', () => {
  it('时间舍入正确进位，不显示 00:60.0', () => {
    expect(time(59.96, true)).toBe('01:00.0')
    expect(time(3599.96, true)).toBe('1:00:00.0')
    expect(time(NaN)).toBe('00:00')
    expect(time(-1)).toBe('00:00')
  })
  it('分页按钮发出后端 offset，边界禁用', async () => {
    const wrapper = mount(VideoList, { props: { page: { total: 17, offset: 0, limit: 8, items: [video] }, selectedId: 1, loading: false, error: '' } })
    const buttons = wrapper.findAll('.pagination button')
    expect(buttons[0]!.attributes('disabled')).toBeDefined()
    await buttons[1]!.trigger('click'); expect(wrapper.emitted('page')?.[0]).toEqual([8])
    await wrapper.setProps({ page: { total: 17, offset: 16, limit: 8, items: [video] } })
    expect(buttons[1]!.attributes('disabled')).toBeDefined()
    await buttons[0]!.trigger('click'); expect(wrapper.emitted('page')?.[1]).toEqual([8])
    wrapper.unmount()
  })
  it('列表展示真实字段并返回视频 ID', async () => {
    const wrapper = mount(VideoList, { props: { page: { total: 1, offset: 0, limit: 8, items: [video] }, selectedId: 1, loading: false, error: '' } })
    expect(wrapper.text()).toContain(video.filename); expect(wrapper.text()).toContain(video.resolution)
    expect(wrapper.get('time').attributes('datetime')).toBe(video.created_at)
    await wrapper.get('.video-item').trigger('click'); expect(wrapper.emitted('select')?.[0]).toEqual([1])
    wrapper.unmount()
  })
})
