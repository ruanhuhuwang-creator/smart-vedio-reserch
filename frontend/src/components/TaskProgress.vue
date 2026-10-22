<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { Task } from '@/types/api'
import { statusLabel, time } from '@/utils/format'
const props = defineProps<{ task: Task | null; taskId: string | null; error: string }>()
defineEmits<{ retry: [] }>()
const now = ref(Date.now())
const clock = setInterval(() => { now.value = Date.now() }, 1000)
onBeforeUnmount(() => clearInterval(clock))
const elapsed = computed(() => props.task?.started_at ? Math.max(0, ((props.task.finished_at ? Date.parse(props.task.finished_at) : now.value) - Date.parse(props.task.started_at)) / 1000) : 0)
</script>
<template>
  <section class="panel task-panel" aria-live="polite">
    <div class="section-heading"><h2>任务进度</h2><span class="tiny-label">02 / ANALYZE</span></div>
    <p v-if="!taskId" class="hint">提交分析后，进度将在此显示。</p>
    <template v-else>
      <div class="task-heading"><span class="status" :data-status="task?.status">{{ task ? statusLabel[task.status] : '正在读取任务' }}</span><strong>{{ task?.progress == null ? '—' : `${Math.round(task.progress)}%` }}</strong></div>
      <div class="progress-track" role="progressbar" :aria-valuenow="task?.progress ?? undefined" aria-valuemin="0" aria-valuemax="100" aria-label="分析进度"><div :style="{ width: `${Math.min(100, Math.max(0, task?.progress || 0))}%` }" :class="{ failed: task?.status === 'failed' }"></div></div>
      <p v-if="task?.status === 'queued'" class="hint">排队中，等待分析工作者空闲。</p>
      <p v-if="task?.status === 'running'" class="hint">正在扫描视频；首次加载模型可能需要一些时间。</p>
      <p v-if="task?.status === 'succeeded'" class="success">{{ task.index_reused ? '已复用现有索引，可以立即检索。' : '索引已保存，可以开始检索。' }}</p>
      <p v-if="task?.error_message" class="error" role="alert">{{ task.error_message }}</p>
      <div v-if="task" class="task-metrics"><div><small>已扫描原视频帧</small><strong>{{ task.processed_frames.toLocaleString() }} <small>/ {{ task.total_frames?.toLocaleString() ?? '未知' }}</small></strong></div><div><small>执行时间</small><strong>{{ time(elapsed) }}</strong></div></div>
      <small v-if="task?.progress_is_estimate" class="footnote">进度为估计值，最终状态以任务结果为准。</small>
      <p v-if="error" class="error" role="alert">进度获取已暂停：{{ error }} <button class="text-button" @click="$emit('retry')">重试获取</button></p>
      <p class="task-id" :title="taskId">任务 {{ taskId.slice(0, 12) }}</p>
    </template>
  </section>
</template>
