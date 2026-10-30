<script setup lang="ts">
// 选择或拖入文件 → 初步检查 → 调上传 API → emit 通知工作台刷新。
// 扩展名检查只是提前提示，最终文件能否解码由后端验证。
import { onBeforeUnmount, ref } from 'vue'
import { uploadVideo } from '@/api/videos'
import { errorMessage } from '@/api/client'
import { bytes } from '@/utils/format'
import type { Video } from '@/types/api'
const emit = defineEmits<{ uploaded: [video: Video] }>()
const input = ref<HTMLInputElement>()
const file = ref<File | null>(null), busy = ref(false), dragging = ref(false), error = ref(''), success = ref('')
const configuredMax = Number(import.meta.env.VITE_MAX_UPLOAD_BYTES || 536870912)
const maxBytes = Number.isFinite(configuredMax) && configuredMax > 0 ? configuredMax : 536870912
let controller: AbortController | undefined
function choose(files: FileList | null) {
  if (busy.value) return
  error.value = ''; success.value = ''; file.value = files?.[0] || null
  if (!file.value) return
  if (files && files.length > 1) { error.value = '请一次选择一个视频'; file.value = null; return }
  if (!/\.(mp4|mov|avi)$/i.test(file.value.name)) error.value = '请选择 MP4、MOV 或 AVI 视频'
  else if (!file.value.size) error.value = '文件为空'
  else if (file.value.size > maxBytes) error.value = `文件超过 ${bytes(maxBytes)} 限制`
}
function drop(event: DragEvent) { dragging.value = false; choose(event.dataTransfer?.files || null) }
async function upload() {
  if (!file.value || error.value || busy.value) return
  busy.value = true; success.value = ''; controller = new AbortController()
  try {
    const video = await uploadVideo(file.value, controller.signal)
    success.value = `已上传：${video.filename}`; file.value = null
    if (input.value) input.value.value = ''
    emit('uploaded', video)
  } catch (reason) { if (!controller.signal.aborted) error.value = errorMessage(reason) }
  finally { busy.value = false }
}
onBeforeUnmount(() => controller?.abort())
</script>
<template>
  <section class="panel upload-panel">
    <div class="section-heading"><h2>导入视频</h2><span class="tiny-label">01 / IMPORT</span></div>
    <button class="drop-zone" :class="{ dragging }" :disabled="busy" @click="input?.click()" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="drop">
      <span class="upload-symbol" aria-hidden="true">↥</span><strong>拖拽视频到这里</strong><span>或点击选择本地文件</span>
      <small>MP4 / MOV / AVI · 最大 {{ bytes(maxBytes) }}</small>
    </button>
    <input ref="input" class="visually-hidden" type="file" accept=".mp4,.mov,.avi" aria-label="选择视频文件" :disabled="busy" @change="choose(($event.target as HTMLInputElement).files)">
    <div v-if="file" class="selected-file"><span>{{ file.name }}</span><small>{{ bytes(file.size) }}</small></div>
    <button v-if="file" class="primary wide" :disabled="busy || !!error" @click="upload">{{ busy ? '正在上传并验证…' : '上传视频' }}</button>
    <p v-if="busy" role="status" class="hint">服务端正在接收、解码并验证文件，请稍候。</p>
    <p v-if="error" role="alert" class="error">{{ error }} <button class="text-button" @click="error = ''; input?.click()">重新选择</button></p>
    <p v-if="success" role="status" class="success">{{ success }}</p>
    <p class="footnote">保留原始视频，文件可用性由服务端验证。</p>
  </section>
</template>
