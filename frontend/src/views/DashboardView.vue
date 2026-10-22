<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, errorMessage, request } from '@/api/client'
import { analyzeVideo, getAnalysisContract, getEvents, getVideo, listVideos } from '@/api/videos'
import { useTaskPolling } from '@/composables/useTaskPolling'
import { readLocal, writeLocal } from '@/utils/storage'
import type { AnalysisContract, AnalysisOptions, EventPage, Video, VideoEvent, VideoPage } from '@/types/api'
import VideoUploader from '@/components/VideoUploader.vue'
import VideoList from '@/components/VideoList.vue'
import VideoPlayer from '@/components/VideoPlayer.vue'
import AnalysisPanel from '@/components/AnalysisPanel.vue'
import TaskProgress from '@/components/TaskProgress.vue'
import EventSearch from '@/components/EventSearch.vue'
import EventTimeline from '@/components/EventTimeline.vue'

const page = ref<VideoPage | null>(null), selected = ref<Video | null>(null)
const production = import.meta.env.PROD
const offset = ref(0), listLoading = ref(false), listError = ref(''), detailLoading = ref(false), detailError = ref('')
const contract = ref<AnalysisContract | null>(null), contractError = ref(''), service = ref('连接中')
const submitting = ref(false), analysisError = ref(''), taskId = ref<string | null>(null)
const { task, error: taskError, retry: retryTask } = useTaskPolling(taskId)
const category = ref('person'), eventPage = ref<EventPage | null>(null), eventLoading = ref(false), eventError = ref(''), notReady = ref(false), searched = ref(false)
const activeId = ref<number | null>(null), currentTime = ref(0), player = ref<InstanceType<typeof VideoPlayer>>()
const events = computed(() => eventPage.value?.events || [])
const previous = computed(() => !!selected.value?.index_available && (eventPage.value?.using_previous_index || ['queued', 'running', 'failed'].includes(selected.value.analysis_status)))
let listController: AbortController | undefined, detailController: AbortController | undefined, eventController: AbortController | undefined
let disposed = false
let selectionVersion = 0

async function loadContract() {
  contractError.value = ''
  try { const value = await getAnalysisContract(); if (!disposed) contract.value = value }
  catch (error) { if (!disposed) contractError.value = `无法读取后端分析参数：${errorMessage(error)}` }
}
async function health() {
  try { const result = await request<{ status: string }>('/health'); if (!disposed) service.value = result.status === 'ok' ? '服务已连接' : '服务状态异常' }
  catch { if (!disposed) service.value = '服务未连接' }
}
async function loadList(nextOffset = offset.value) {
  listController?.abort(); const controller = new AbortController(); listController = controller
  listLoading.value = true; listError.value = ''; offset.value = nextOffset
  try {
    const result = await listVideos(nextOffset, 8, controller.signal)
    if (controller.signal.aborted) return
    page.value = result
    if (!selected.value && !detailLoading.value && result.items[0]) {
      const saved = Number(readLocal('selected-video'))
      void selectVideo(Number.isSafeInteger(saved) && saved > 0 ? saved : result.items[0].video_id)
    }
  } catch (error) { if (!controller.signal.aborted) listError.value = errorMessage(error) }
  finally { if (listController === controller) listLoading.value = false }
}
function restoreTask(video: Video) {
  taskId.value = video.active_task_id || readLocal(`video:${video.video_id}:task`)
}
async function selectVideo(id: number) {
  selectionVersion++
  detailController?.abort(); eventController?.abort()
  const controller = new AbortController(); detailController = controller
  taskId.value = null; selected.value = null; eventPage.value = null; activeId.value = null
  eventError.value = ''; notReady.value = false; searched.value = false; eventLoading.value = false
  detailError.value = ''; analysisError.value = ''; detailLoading.value = true
  try {
    const video = await getVideo(id, controller.signal)
    if (controller.signal.aborted) return
    selected.value = video; writeLocal('selected-video', String(id)); restoreTask(video)
    void search()
  } catch (error) {
    if (!controller.signal.aborted) { detailError.value = errorMessage(error); writeLocal('selected-video', null) }
  } finally { if (detailController === controller) detailLoading.value = false }
}
async function refreshSelected() {
  const id = selected.value?.video_id
  const version = selectionVersion, previousTaskId = taskId.value
  if (!id) return
  try {
    const video = await getVideo(id)
    if (!disposed && selectionVersion === version && taskId.value === previousTaskId && selected.value?.video_id === id) { selected.value = video; if (video.active_task_id && taskId.value !== video.active_task_id) restoreTask(video) }
  } catch (error) { if (!disposed && selected.value?.video_id === id) detailError.value = errorMessage(error) }
}
async function search() {
  eventController?.abort(); const controller = new AbortController(); eventController = controller
  const id = selected.value?.video_id
  eventPage.value = null; activeId.value = null; eventError.value = ''; notReady.value = false; searched.value = false
  if (!id) return
  eventLoading.value = true
  try {
    const result = await getEvents(id, category.value, controller.signal)
    if (!controller.signal.aborted && selected.value?.video_id === id) {
      result.events.sort((a, b) => a.start_time - b.start_time || a.end_time - b.end_time)
      eventPage.value = result; searched.value = true
    }
  } catch (error) {
    if (!controller.signal.aborted) {
      if (error instanceof ApiError && error.status === 409 && error.code === 'index_not_ready') notReady.value = true
      else eventError.value = errorMessage(error)
    }
  } finally { if (eventController === controller) eventLoading.value = false }
}
async function submit(options: AnalysisOptions) {
  if (!selected.value || submitting.value) return
  const id = selected.value.video_id
  submitting.value = true; analysisError.value = ''
  try {
    const result = await analyzeVideo(id, options)
    writeLocal(`video:${id}:task`, result.task_id)
    if (disposed || selected.value?.video_id !== id) return
    taskId.value = result.task_id
    selected.value = { ...selected.value, active_task_id: result.task_id, analysis_status: result.status }
    void loadList(); void search()
  } catch (error) {
    if (!disposed && selected.value?.video_id === id) {
      analysisError.value = errorMessage(error)
      // 重复请求 409 时读取已有活动任务，绝不自动重新提交。
      if (error instanceof ApiError && error.status === 409) await refreshSelected()
    }
  } finally { submitting.value = false }
}
watch(category, () => void search())
watch(task, (value, old) => {
  if (!value || value.video_id !== selected.value?.video_id) return
  writeLocal(`video:${value.video_id}:task`, value.task_id)
  if (value.status === 'queued' || value.status === 'running') selected.value = { ...selected.value, active_task_id: value.task_id, analysis_status: value.status }
  else if (value.status !== old?.status || value.task_id !== old?.task_id) {
    void (async () => { await refreshSelected(); if (!disposed && selected.value?.video_id === value.video_id) void search() })()
    void loadList()
  }
})
function jump(event: VideoEvent) { activeId.value = event.event_id; void player.value?.seek(event.start_time) }
async function uploaded(video: Video) { offset.value = 0; await selectVideo(video.video_id); void loadList(0) }
function reconnect() { void health(); void loadContract(); void loadList() }
onMounted(reconnect)
onBeforeUnmount(() => { disposed = true; listController?.abort(); detailController?.abort(); eventController?.abort() })
</script>
<template>
  <div class="app-shell">
    <header class="app-header"><a class="brand" href="./" aria-label="SmartVision 首页"><span class="brand-mark" aria-hidden="true"><i></i></span><span>Smart<span class="brand-accent">Vision</span><small>智能视频检索工作台</small></span></a><div class="header-right"><span class="workspace-label">本地工作空间</span><button class="connection" :class="{ connected: service === '服务已连接' }" title="点击重新检查后端连接" @click="reconnect"><i></i>{{ service }}</button></div></header>
    <main>
      <div class="page-heading"><div><p class="eyebrow">VIDEO INTELLIGENCE WORKSPACE</p><h1>让每一段视频，都可被检索<span>。</span></h1><p>导入监控视频，用 AI 定位目标出现的关键时刻。</p></div><div class="workflow"><span>01 导入</span><i>→</i><span>02 分析</span><i>→</i><span>03 检索</span></div></div>
      <div class="dashboard-grid">
        <aside class="left-column"><VideoUploader @uploaded="uploaded" /><VideoList :page="page" :selected-id="selected?.video_id" :loading="listLoading" :error="listError" @select="selectVideo" @page="loadList" @refresh="loadList()" /></aside>
        <div class="center-column"><p v-if="detailLoading" class="notice" role="status">正在加载视频详情…</p><p v-if="detailError" class="error panel" role="alert">视频详情：{{ detailError }}</p><VideoPlayer ref="player" :video="selected" @time="currentTime = $event" /><EventTimeline :events="events" :duration="selected?.duration || 0" :current-time="currentTime" :active-id="activeId" :ready="searched" @select="jump" /></div>
        <aside class="right-column"><AnalysisPanel :video="selected" :contract="contract" :contract-error="contractError" :submitting="submitting" :error="analysisError" @submit="submit" @retry-contract="loadContract" /><TaskProgress :task="task" :task-id="taskId" :error="taskError" @retry="retryTask" /></aside>
        <EventSearch v-model:category="category" :video="selected" :events="events" :loading="eventLoading" :error="eventError" :not-ready="notReady" :previous="previous" :searched="searched" :active-id="activeId" @refresh="search" @select="jump" />
      </div>
    </main>
    <footer><span>SmartVision <span class="subtle">/</span> 从画面到线索 <a v-if="production" href="/source-code.zip"> · 源码与许可</a></span><span>本地分析 · 原始视频保留 · YOLO26n</span></footer>
  </div>
</template>
