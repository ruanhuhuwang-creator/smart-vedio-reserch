// Real browser against the real backend. No route interception or mock responses.
import { chromium } from 'playwright'
import { strict as assert } from 'node:assert'
import { writeFile, readFile, readdir, appendFile } from 'node:fs/promises'
import path from 'node:path'

const output = process.env.SMARTVISION_E2E_OUTPUT
if (!output) throw new Error('Run python -m tests.validate_frontend_runtime --source VIDEO from the project root')
const browser = await chromium.launch({ channel: process.env.SMARTVISION_BROWSER_CHANNEL || 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1500, height: 1100 }, locale: 'zh-CN' })
const report = { source_sha256: process.env.SMARTVISION_SOURCE_HASH, checks: [], tasks: [], events: {}, responses: [], browser_errors: [] }
let posts = 0
page.on('pageerror', error => report.browser_errors.push(error.message))
page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/analysis')) posts++ })
page.on('response', response => {
  if (response.url().includes('/api/')) report.responses.push({ url: response.url(), status: response.status() })
})
const check = name => { report.checks.push(name); console.log(`PASS ${name}`) }
async function visible(locator) { await locator.waitFor({ state: 'visible', timeout: 120000 }) }
async function upload(filename, expectedStatus) {
  await page.getByLabel('选择视频文件').setInputFiles(path.join(output, filename))
  const response = page.waitForResponse(r => r.url().endsWith('/api/videos') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '上传视频', exact: true }).click()
  const result = await response
  assert.equal(result.status(), expectedStatus)
  return result.json()
}
async function analyze(expectedStatus = 'succeeded') {
  const response = page.waitForResponse(r => r.url().endsWith('/analysis') && r.request().method() === 'POST')
  await page.getByRole('button', { name: /开始分析/ }).click()
  const submitted = await response; assert.equal(submitted.status(), 202)
  const task = await submitted.json(); assert.equal(task.status, 'queued')
  const statuses = new Set(['queued'])
  const observe = async response => {
    if (response.url().endsWith(`/api/tasks/${task.task_id}`) && response.ok()) {
      const value = await response.json().catch(() => null)
      if (value) statuses.add(value.status)
    }
  }
  page.on('response', observe)
  const label = expectedStatus === 'succeeded' ? '分析成功' : '分析失败'
  await visible(page.locator('.task-id').filter({ hasText: task.task_id.slice(0, 12) }))
  await visible(page.locator('.task-panel .status').filter({ hasText: label }))
  const final = await (await page.request.get(`http://127.0.0.1:8000/api/tasks/${task.task_id}`)).json()
  assert.equal(final.status, expectedStatus)
  statuses.add(final.status)
  page.off('response', observe)
  report.tasks.push({ ...final, observed_statuses: [...statuses] })
  return final
}
async function query(category) {
  const response = page.waitForResponse(r => r.url().endsWith(`/events?category=${category}`))
  await page.locator('.category-options button').filter({ hasText: new RegExp(`\\b${category}\\b`) }).click()
  const result = await response; assert.equal(result.status(), 200)
  return result.json()
}
try {
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle' })
  await visible(page.getByText('服务已连接', { exact: true }))
  await visible(page.getByText('视频库还是空的', { exact: false }))
  assert.equal(posts, 0); check('真实服务连接、空视频库、页面打开不提交任务')
  await upload('invalid.mp4', 422)
  await visible(page.getByRole('alert').filter({ hasText: /视频|解码/ })); check('无效视频上传返回真实 422 并显示错误')
  const video = await upload('pedestrians.mp4', 201)
  assert.equal(video.browser_compatible, true)
  await visible(page.getByText('尚无可用索引，请先完成视频分析。', { exact: true }))
  await page.waitForFunction(() => document.querySelector('video')?.readyState >= 1)
  assert.equal(await page.locator('video').evaluate(el => el.videoWidth), video.width)
  check('真实视频上传、列表、详情与 HTML5 元数据加载')
  const range = await page.request.get(`http://127.0.0.1:8000${video.stream_url}`, { headers: { Range: 'bytes=0-127' } })
  assert.equal(range.status(), 206); assert.equal((await range.body()).length, 128)
  assert.match(range.headers()['content-range'], /^bytes 0-127\//); check('视频流真实 Range 206')
  await analyze(); check('真实 YOLO 后台分析成功并显示状态')
  await visible(page.locator('.event-card').first())
  const person = await (await page.request.get(`http://127.0.0.1:8000/api/videos/${video.video_id}/events?category=person`)).json()
  assert.ok(person.events.length > 0); report.events.person = person.events
  const car = await query('car'); report.events.car = car.events; check('person/car 查询真实 SQLite 索引')
  await query('person'); await visible(page.locator('.event-card').first())
  await page.locator('.event-card').first().click()
  await page.waitForFunction(() => { const video = document.querySelector('video'); return video && !video.paused && video.currentTime > 0 })
  assert.equal(await page.locator('.event-card.active').count(), 1)
  await page.locator('video').evaluate(el => el.pause())
  await page.locator('.timeline-event').first().click()
  assert.equal(await page.locator('.timeline-event.active').count(), 1)
  check('结果与时间轴点击跳转、原生播放与高亮')
  const countBeforeRefresh = posts
  await page.reload({ waitUntil: 'networkidle' }); await visible(page.locator('.task-panel .status').filter({ hasText: '分析成功' }))
  assert.equal(posts, countBeforeRefresh); check('页面刷新恢复 task_id 且没有重复提交')
  const reused = await analyze(); assert.equal(reused.index_reused, true); check('同参数重新分析复用已有索引')
  // 只对隔离测试目录中的上传副本注入内容校验失败；原始素材始终不变。
  const copies = (await readdir(path.join(output, 'uploads'))).filter(name => name.endsWith('.mp4'))
  assert.equal(copies.length, 1)
  const managedCopy = path.join(output, 'uploads', copies[0])
  const originalCopy = await readFile(managedCopy)
  try {
    await appendFile(managedCopy, Buffer.from('integrity-fault-for-browser-test'))
    await analyze('failed')
  } finally { await writeFile(managedCopy, originalCopy) }
  await visible(page.getByText('当前显示上一次成功建立的索引', { exact: false }))
  await visible(page.locator('.event-card').first())
  check('隔离副本内容校验失败产生真实 failed，仍可检索旧索引')
  await page.getByLabel('分析帧率').fill('3')
  const changed = await analyze(); assert.equal(changed.index_reused, false)
  check('参数变化自动重新分析，符合实际后端规则')
  await page.getByLabel('强制重建索引').check()
  await analyze(); check('显式强制重建后成功刷新索引')
  await visible(page.locator('.event-card').first())
  await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  check('桌面与窄屏布局无横向溢出')
  await page.setViewportSize({ width: 1500, height: 1100 })
  const black = await upload('black.mp4', 201)
  await visible(page.getByText('尚无可用索引，请先完成视频分析。', { exact: true }))
  await analyze()
  await visible(page.getByText('当前索引中未检测到行人事件', { exact: false }))
  const blackEvents = await (await page.request.get(`http://127.0.0.1:8000/api/videos/${black.video_id}/events?category=person`)).json()
  assert.deepEqual(blackEvents.events, []); check('真实黑色视频分析后展示空结果')
  const incompatible = await upload('incompatible.avi', 201)
  await visible(page.getByText('当前视频编码不受浏览器支持', { exact: true }))
  const unsupported = await page.request.get(`http://127.0.0.1:8000${incompatible.stream_url}`)
  assert.equal(unsupported.status(), 415)
  assert.equal(await page.locator('.player-stage video').count(), 0)
  check('真实不兼容视频 415，界面显示编码原因')
  assert.deepEqual(report.browser_errors, [])
  check('浏览器无未捕获 JavaScript 错误')
} catch (error) {
  report.failure = String(error.stack || error)
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true })
  throw error
} finally {
  await writeFile(path.join(output, 'browser-report.json'), JSON.stringify(report, null, 2))
  await browser.close()
}
