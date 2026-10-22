<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { AnalysisContract, AnalysisOptions, Video } from '@/types/api'
const props = defineProps<{ video: Video | null; contract: AnalysisContract | null; contractError: string; submitting: boolean; error: string }>()
defineEmits<{ submit: [options: AnalysisOptions]; retryContract: [] }>()
const options = ref<AnalysisOptions>({ sample_fps: 2, imgsz: 640, confidence: .35, force_rebuild: false })
watch(() => props.contract, value => { if (value) options.value = { ...value.defaults } }, { immediate: true })
watch(() => props.video?.video_id, () => { options.value.force_rebuild = false })
const active = computed(() => !!props.video?.active_task_id || ['queued', 'running'].includes(props.video?.analysis_status || ''))
const valid = computed(() => props.contract && Number.isFinite(options.value.sample_fps) && options.value.sample_fps >= props.contract.fpsMin && options.value.sample_fps <= props.contract.fpsMax && Number.isFinite(options.value.confidence) && options.value.confidence >= props.contract.confidenceMin && options.value.confidence <= props.contract.confidenceMax && props.contract.sizes.includes(options.value.imgsz))
const modes = [{ size: 416, name: '快速', note: '更低开销' }, { size: 640, name: '均衡', note: '日常分析' }, { size: 960, name: '精细', note: '更多细节' }] as const
</script>
<template>
  <section class="panel analysis-panel">
    <div class="section-heading"><h2>目标分析</h2><span class="model-tag">YOLO26n</span></div>
    <p class="hint">选择分析精度，为视频建立可检索索引。</p>
    <fieldset :disabled="submitting || active || !contract || !video">
      <legend>推理模式</legend><div class="mode-options"><label v-for="mode in modes" :key="mode.size" :class="{ chosen: options.imgsz === mode.size }"><input v-model="options.imgsz" type="radio" name="mode" :value="mode.size"><strong>{{ mode.name }}</strong><small>{{ mode.size }} px</small></label></div>
      <div class="parameter-row"><label for="fps">分析帧率 <small>FPS</small></label><input id="fps" v-model.number="options.sample_fps" type="number" :min="contract?.fpsMin" :max="contract?.fpsMax" step="0.25"></div>
      <div class="parameter-row"><label for="confidence">置信度阈值</label><input id="confidence" v-model.number="options.confidence" type="number" :min="contract?.confidenceMin" :max="contract?.confidenceMax" step="0.01"></div>
      <p class="footnote">默认值来自当前后端。原始视频与帧率保持不变。</p>
      <label class="checkbox"><input v-model="options.force_rebuild" type="checkbox">强制重建索引</label>
      <p v-if="video?.index_available" class="hint">已有可用索引；参数相同将复用，参数变化会重新分析。勾选重建可忽略缓存，分析期间仍可检索旧索引。</p>
    </fieldset>
    <p v-if="contractError" class="error" role="alert">{{ contractError }} <button class="text-button" @click="$emit('retryContract')">重新读取参数</button></p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <button class="primary wide" :disabled="!video || !valid || active || submitting" @click="$emit('submit', { ...options })">{{ submitting ? '正在提交…' : active ? '任务进行中' : '▷  开始分析' }}</button>
    <p class="footnote">稀疏采样的事件边界存在误差；检测结果仅供辅助判断。</p>
  </section>
</template>
