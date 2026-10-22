// Real browser + already-running EXE. No route interception or mock responses.
import { chromium } from 'playwright'
import { strict as assert } from 'node:assert'
import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'

const output = process.env.SMARTVISION_FEATURE_OUTPUT
const data = process.env.SMARTVISION_FEATURE_DATA
const source = process.env.SMARTVISION_FEATURE_SOURCE
const queuedSource = process.env.SMARTVISION_FEATURE_QUEUED_SOURCE
const state = JSON.parse(await readFile(path.join(data, 'run-state.json'), 'utf8'))
assert.equal(state.mode, 'frozen')
const base = state.url
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1500, height: 1100 }, locale: 'zh-CN' })
const report = { state, checks: [], tasks: [], events: {}, errors: [] }
let submissions = 0
page.on('pageerror', error => report.errors.push(error.message))
page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/analysis')) submissions++ })
const pass = message => { report.checks.push(message); console.log('PASS', message) }
async function json(method, route, data) {
  const response = await page.request.fetch(base + route, { method, data })
  assert.ok(response.ok(), `${response.status()} ${await response.text()}`)
  return response.json()
}
async function waitTask(id, expected) {
  const deadline = Date.now() + 600000
  while (Date.now() < deadline) {
    const task = await json('GET', '/api/tasks/' + id)
    if (task.status === expected) return task
    assert.ok(!['failed', 'succeeded', 'cancelled'].includes(task.status), JSON.stringify(task))
    await page.waitForTimeout(250)
  }
  throw new Error('Task timeout ' + id)
}
async function waitForFrames(id) {
  const deadline = Date.now() + 60000
  while (Date.now() < deadline) {
    const task = await json('GET', '/api/tasks/' + id)
    assert.equal(task.status, 'running', JSON.stringify(task))
    if (task.processed_frames > 0) return
    await page.waitForTimeout(250)
  }
  throw new Error('No decoded/inferred frames before stop test')
}
async function analyze() {
  const pending = page.waitForResponse(response => response.request().method() === 'POST' && /\/analysis$/.test(response.url()))
  await page.locator('.analysis-panel .primary').click()
  const response = await pending
  assert.equal(response.status(), 202)
  return response.json()
}
try {
  await page.goto(base, { waitUntil: 'networkidle' })
  await page.getByText('服务已连接', { exact: true }).waitFor()
  await page.locator('.event-card').first().waitFor()
  assert.equal(submissions, 0)
  const listing = await json('GET', '/api/videos')
  const video = listing.items[0], vid = video.video_id
  assert.equal(video.index_available, true)
  report.video_id = vid
  for (const category of ['person', 'car']) {
    report.events[category] = (await json('GET', `/api/videos/${vid}/events?category=${category}`)).events
    assert.ok(report.events[category].length > 0)
    assert.ok(report.events[category].every(event => Number.isInteger(event.max_count) && event.max_count >= 1))
  }
  const people = report.events.person
  assert.equal(await page.locator('.event-count').count(), people.length)
  for (let index = 0; index < people.length; index++) {
    assert.ok((await page.locator('.event-count').nth(index).innerText()).includes(`最多 ${people[index].max_count} 人`))
  }
  await page.getByRole('tab', { name: '出现时间段', exact: true }).click()
  assert.equal(await page.locator('.event-count').count(), 0)
  await page.getByRole('tab', { name: '数量统计', exact: true }).click()
  await page.locator('.event-card').first().click()
  await page.waitForFunction(start => {
    const video = document.querySelector('video')
    return video && !video.paused && video.currentTime >= start
  }, people[0].start_time)
  await page.locator('video').evaluate(video => video.pause())
  assert.equal(await page.locator('.event-card.active').count(), 1)
  await page.locator('.category-options button', { hasText: '汽车' }).click()
  await page.waitForFunction(() => document.querySelector('.event-count')?.textContent.includes('个'))
  await page.locator('.category-options button', { hasText: '行人' }).click()
  await page.waitForFunction(() => document.querySelector('.event-count')?.textContent.includes('人'))
  await page.screenshot({ path: path.join(output, 'counts-desktop.png'), fullPage: true })
  pass('旧索引直接返回每段 person/car 峰值数量；菜单、类别切换与播放跳转正常')

  // Complete a real GPU rebuild, then interrupt a slower rebuild.
  await page.getByLabel('强制重建索引').check()
  await page.locator('.mode-options label').filter({ hasText: '快速' }).click()
  await page.getByLabel('分析帧率').fill('2')
  const first = await analyze()
  report.tasks.push(await waitTask(first.task_id, 'succeeded'))
  await page.waitForFunction(() => !document.querySelector('.analysis-panel .primary')?.disabled)
  const oldEvents = (await json('GET', `/api/videos/${vid}/events`)).events
  report.publishedEvents = oldEvents
  await page.locator('.mode-options label').filter({ hasText: '精细' }).click()
  await page.getByLabel('分析帧率').fill('30')
  const task = await analyze()
  await waitTask(task.task_id, 'running')
  await waitForFrames(task.task_id)
  const stopping = page.waitForResponse(response => response.url().endsWith(`/api/tasks/${task.task_id}/cancel`))
  await page.locator('.stop-analysis').click()
  assert.equal((await stopping).status(), 202)
  const cancelled = await waitTask(task.task_id, 'cancelled')
  assert.ok(cancelled.processed_frames > 0)
  assert.equal(cancelled.cancel_requested, true)
  assert.ok(cancelled.progress < 100)
  report.tasks.push(cancelled)
  assert.deepEqual((await json('GET', `/api/videos/${vid}/events`)).events, oldEvents)
  await page.getByText('分析已停止，本次未完成索引已丢弃', { exact: false }).waitFor()
  await page.waitForFunction(() => !document.querySelector('.analysis-panel .primary')?.disabled)
  const beforeReload = submissions
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForFunction(() => document.querySelector('video')?.readyState >= 2)
  await page.getByText('分析已停止，本次未完成索引已丢弃', { exact: false }).waitFor()
  assert.equal(submissions, beforeReload)
  await page.screenshot({ path: path.join(output, 'cancelled-desktop.png'), fullPage: true })
  pass('真实 CUDA 重建成功；按钮停止运行任务，旧索引不变，刷新恢复已停止且不重复提交')

  // Queue a second distinct video while the long video is running.
  const busy = await json('POST', `/api/videos/${vid}/analysis`, { imgsz: 960, sample_fps: 30, force_rebuild: true })
  await waitTask(busy.task_id, 'running')
  await waitForFrames(busy.task_id)
  const queuedBytes = await readFile(queuedSource)
  const upload = await page.request.post(base + '/api/videos', { multipart: { file: { name: 'queue-cancel.mp4', mimeType: 'video/mp4', buffer: queuedBytes } } })
  assert.equal(upload.status(), 201)
  const other = await upload.json()
  const queued = await json('POST', `/api/videos/${other.video_id}/analysis`, {})
  assert.equal(queued.status, 'queued')
  await page.getByRole('button', { name: '刷新视频列表' }).click()
  await page.locator('.video-item').filter({ hasText: 'queue-cancel.mp4' }).click()
  await page.waitForFunction(() => !document.querySelector('.stop-analysis')?.disabled)
  const queueCancel = page.waitForResponse(response => response.url().endsWith(`/api/tasks/${queued.task_id}/cancel`))
  await page.locator('.stop-analysis').click()
  assert.equal((await queueCancel).status(), 202)
  report.tasks.push(await waitTask(queued.task_id, 'cancelled'))
  assert.equal((await json('GET', '/api/tasks/' + busy.task_id)).status, 'running')
  assert.equal((await page.request.get(base + `/api/videos/${other.video_id}/events`)).status(), 409)
  await json('POST', `/api/tasks/${busy.task_id}/cancel`)
  await waitTask(busy.task_id, 'cancelled')
  assert.equal((await json('GET', '/health')).status, 'ok')
  const reused = await json('POST', `/api/videos/${vid}/analysis`, { imgsz: 416, sample_fps: 2 })
  assert.equal((await waitTask(reused.task_id, 'succeeded')).index_reused, true)
  pass('界面停止排队任务，未影响另一个运行任务；无索引返回 409，工作者仍可接受后续任务')
  assert.deepEqual(report.errors, [])
  pass('浏览器没有未捕获脚本错误')
} catch (error) {
  report.failure = String(error.stack || error)
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true })
  throw error
} finally {
  await writeFile(path.join(output, 'browser-report.json'), JSON.stringify(report, null, 2))
  await browser.close()
}
