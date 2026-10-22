// Drives only an already-running frozen EXE; never starts Python, Vite or Uvicorn.
import { chromium } from 'playwright'
import { strict as assert } from 'node:assert'
import { readFile, writeFile, readdir, appendFile, mkdir } from 'node:fs/promises'
import path from 'node:path'

const data = process.env.SMARTVISION_PACKAGED_DATA
const output = process.env.SMARTVISION_PACKAGED_REPORT
const source = process.env.SMARTVISION_PACKAGED_SOURCE
const mode = process.env.SMARTVISION_PACKAGED_PHASE || 'gpu'
if (!data || !output || !source) throw new Error('Set SMARTVISION_PACKAGED_DATA/REPORT/SOURCE')
await mkdir(output, { recursive: true })
const state = JSON.parse(await readFile(path.join(data, 'run-state.json'), 'utf8'))
assert.equal(state.mode, 'frozen'); assert.equal(state.status, 'ready')
const base = state.url
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1500, height: 1080 }, locale: 'zh-CN' })
const report = { mode, state, checks: [], tasks: [], events: {}, errors: [], requests: [] }
let submissions = 0
page.on('pageerror', error => report.errors.push(error.message))
page.on('request', request => {
  report.requests.push(request.url())
  if (request.method() === 'POST' && request.url().endsWith('/analysis')) submissions++
})
const pass = message => { report.checks.push(message); console.log(`PASS ${message}`) }
const visible = locator => locator.waitFor({ state: 'visible', timeout: 120000 })
async function analyze(expected = 'succeeded') {
  const promise = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/analysis'))
  await page.getByRole('button', { name: /开始分析/ }).click()
  const response = await promise; assert.equal(response.status(), 202)
  const submitted = await response.json()
  await visible(page.locator('.task-id').filter({ hasText: submitted.task_id.slice(0, 12) }))
  await visible(page.locator('.task-panel .status').filter({ hasText: expected === 'succeeded' ? '分析成功' : '分析失败' }))
  const final = await (await page.request.get(`${base}/api/tasks/${submitted.task_id}`)).json()
  assert.equal(final.status, expected); report.tasks.push(final)
  return final
}
try {
  const health = await page.request.get(base + '/health')
  assert.equal(health.headers()['x-smartvision-instance'], state.instance)
  assert.equal((await health.json()).status, 'ok')
  assert.equal((await page.request.get(base + '/openapi.json')).status(), 200)
  const docs = await (await page.request.get(base + '/docs')).text()
  assert.ok(docs.includes('/assets/swagger-ui-bundle.js'))
  for (const resource of ['/assets/swagger-ui-bundle.js', '/assets/swagger-ui.css', '/assets/swagger-favicon.png', '/source-code.zip']) {
    assert.equal((await page.request.get(base + resource)).status(), 200)
  }
  assert.equal((await page.request.get(base + '/api/does-not-exist')).status(), 404)
  assert.equal((await page.request.get(base + '/workspace/refresh-check')).status(), 200)
  pass('EXE 同源 health、OpenAPI、离线 docs、源码与页面刷新，未知 API 仍为 404')
  await page.goto(base, { waitUntil: 'networkidle' })
  await visible(page.getByText('服务已连接', { exact: true }))
  assert.equal(submissions, 0)
  assert.equal(report.requests.some(url => url.includes('localhost:5173') || url.includes('127.0.0.1:8000')), false)
  pass('生产 Vue 资源加载，无 Vite/固定 API 端口，无启动时 POST')
  let video
  if (mode === 'gpu') {
    await page.getByLabel('选择视频文件').setInputFiles(source)
    const response = page.waitForResponse(response => response.url().endsWith('/api/videos') && response.request().method() === 'POST')
    await page.getByRole('button', { name: '上传视频', exact: true }).click()
    const uploaded = await response; assert.equal(uploaded.status(), 201); video = await uploaded.json()
    await visible(page.getByText('尚无可用索引，请先完成视频分析。', { exact: true }))
    pass('打包 FFprobe 校验真实 MP4 上传与 SQLite 登记')
    await analyze()
    pass('打包 YOLO 完成真实视频分析')
    await writeFile(path.join(output, 'video.json'), JSON.stringify(video, null, 2))
  } else {
    const pageResult = await (await page.request.get(base + '/api/videos')).json()
    assert.ok(pageResult.total > 0); video = pageResult.items[0]
    assert.equal(video.index_available, true)
    await visible(page.locator('.event-card').first())
    assert.equal(submissions, 0)
    pass('关闭重启后视频、索引和任务仍保留，未重复提交')
    if (mode === 'cpu') {
      await page.getByLabel('强制重建索引').check()
      const task = await analyze(); assert.equal(task.index_reused, false)
      pass('禁用 CUDA 后 EXE 实际重建分析成功（设备以应用日志核验）')
    }
  }
  await page.waitForFunction(() => document.querySelector('video')?.readyState >= 1)
  const range = await page.request.get(base + video.stream_url, { headers: { Range: 'bytes=0-127' } })
  assert.equal(range.status(), 206); assert.equal((await range.body()).length, 128)
  pass('原生视频加载及 Range 206')
  for (const category of ['person', 'car']) {
    const response = await page.request.get(`${base}/api/videos/${video.video_id}/events?category=${category}`)
    assert.equal(response.status(), 200)
    const result = await response.json(); assert.ok(result.events.length > 0)
    report.events[category] = result.events
  }
  await visible(page.locator('.event-card').first())
  await page.locator('.event-card').first().click()
  await page.waitForFunction(() => { const element = document.querySelector('video'); return element && !element.paused && element.currentTime > 0 })
  await page.locator('video').evaluate(element => element.pause())
  assert.equal(await page.locator('.event-card.active').count(), 1)
  pass('真实 person/car 检索和事件跳转播放')
  await page.screenshot({ path: path.join(output, `${mode}-desktop.png`), fullPage: true })
  if (mode === 'gpu') {
    const copies = (await readdir(path.join(data, 'videos'))).filter(file => file.endsWith('.mp4'))
    assert.equal(copies.length, 1)
    const copy = path.join(data, 'videos', copies[0]), original = await readFile(copy)
    try {
      await appendFile(copy, Buffer.from('controlled-packaging-integrity-test'))
      await analyze('failed')
      await visible(page.getByText('当前显示上一次成功建立的索引', { exact: false }))
    } finally { await writeFile(copy, original) }
    const logs = await readFile(path.join(data, 'logs', 'smartvision.log'), 'utf8')
    assert.ok(logs.includes('cuda:0') && logs.includes('YOLO 模型已加载') && logs.includes('分析任务失败'))
    pass('真实 CUDA 模型日志、故障日志及失败时保留旧索引')
  }
  if (mode === 'cpu') {
    const logs = await readFile(path.join(data, 'logs', 'smartvision.log'), 'utf8')
    assert.ok(logs.includes('selected=cpu') && logs.includes('YOLO 模型已加载，设备 cpu'))
    pass('应用日志证实 CPU 回退与 CPU YOLO 推理')
  }
  assert.deepEqual(report.errors, [])
  pass('浏览器无未捕获脚本错误')
} catch (error) {
  report.failure = String(error.stack || error)
  await page.screenshot({ path: path.join(output, `${mode}-failure.png`), fullPage: true })
  throw error
} finally {
  await writeFile(path.join(output, `${mode}-report.json`), JSON.stringify(report, null, 2))
  await browser.close()
}
