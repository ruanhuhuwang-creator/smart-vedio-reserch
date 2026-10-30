<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { Video } from '@/types/api'
import { apiUrl, errorMessage } from '@/api/client'
import { diagnoseStream } from '@/api/videos'
import { time } from '@/utils/format'
const props = defineProps<{ video: Video | null }>()
const emit = defineEmits<{ time: [seconds: number] }>()
const element = ref<HTMLVideoElement>(), root = ref<HTMLElement>(), error = ref(''), notice = ref(''), ready = ref(false)
const source = computed(() => props.video?.browser_compatible ? apiUrl(props.video.stream_url) : undefined)
// 用户可能先点事件、后等到视频加载；先记住跳转秒数，loaded 后再执行。
let pendingSeek: number | null = null, controller: AbortController | undefined
watch(() => props.video?.video_id, () => {
  controller?.abort(); error.value = ''; notice.value = ''; ready.value = false; pendingSeek = null; emit('time', 0)
}, { flush: 'sync' })
async function failed() {
  const video = props.video
  if (!video || !video.browser_compatible) return
  controller?.abort(); controller = new AbortController()
  const current = controller
  const timeout = setTimeout(() => current.abort(), 10000)
  try { await diagnoseStream(video.stream_url, current.signal); if (props.video?.video_id === video.video_id) error.value = '浏览器无法解码此视频；文件可能损坏或当前浏览器不支持此格式' }
  catch (reason) { if (props.video?.video_id === video.video_id && controller === current) error.value = current.signal.aborted ? '视频连接超时，请重新加载' : errorMessage(reason) }
  finally { clearTimeout(timeout) }
}
async function seek(seconds: number) {
  root.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  if (!props.video?.browser_compatible) { notice.value = '当前视频无法在浏览器播放，事件时间仍可查看'; return }
  if (!element.value || !ready.value) { pendingSeek = seconds; notice.value = '视频加载后将跳转到所选事件'; return }
  element.value.currentTime = Math.min(Math.max(0, seconds), props.video.duration)
  notice.value = `已定位 ${time(seconds, true)}`
  try { await element.value.play() } catch { notice.value = `已定位 ${time(seconds, true)}，请点击播放` }
}
function loaded() { ready.value = true; if (pendingSeek !== null) { const seconds = pendingSeek; pendingSeek = null; void seek(seconds) } }
function reload() { error.value = ''; element.value?.load() }
onBeforeUnmount(() => controller?.abort())
// 把 seek 暴露给父页面，父页面不必直接操作本组件内部的 video 元素。
defineExpose({ seek })
</script>
<template>
  <section ref="root" class="panel player-panel">
    <div class="section-heading"><h2>视频预览</h2><span class="tiny-label">ORIGINAL VIDEO</span></div>
    <div class="player-stage">
      <div v-if="!video" class="player-empty"><span class="empty-play">▷</span><strong>选择一个视频</strong><p>导入视频，探索每一个关键时刻</p></div>
      <template v-else>
        <video v-if="source" :key="video.video_id" ref="element" :src="source" controls playsinline preload="metadata" :aria-label="video.filename" @loadedmetadata="loaded" @error="failed" @timeupdate="emit('time', element?.currentTime || 0)"></video>
        <div v-if="!video.browser_compatible || error" class="player-message" role="alert"><span class="empty-play">!</span><strong>{{ !video.browser_compatible ? '当前视频编码不受浏览器支持' : error }}</strong><p>{{ !video.browser_compatible ? video.compatibility_message : '请确认后端服务正常；可以尝试重新加载。' }}</p><button v-if="video.browser_compatible" @click="reload">重新加载视频</button><small v-else>仍可执行目标分析与事件检索 · 本阶段不提供转码</small></div>
      </template>
    </div>
    <div class="player-caption"><div><strong>{{ video?.filename || '等待导入视频' }}</strong><small v-if="video">{{ video.resolution }} · {{ video.fps.toFixed(2) }} FPS · {{ video.video_codec.toUpperCase() }}</small></div><span>{{ video ? time(video.duration) : '--:--' }}</span></div>
    <p v-if="notice" class="hint" role="status">{{ notice }}</p>
  </section>
</template>
