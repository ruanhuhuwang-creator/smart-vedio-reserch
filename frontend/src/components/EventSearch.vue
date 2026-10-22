<script setup lang="ts">
import type { VideoEvent, Video } from '@/types/api'
import { categories, categoryName, categoryColor, time } from '@/utils/format'
defineProps<{ video: Video | null; category: string; events: VideoEvent[]; loading: boolean; error: string; notReady: boolean; previous: boolean; searched: boolean; activeId: number | null }>()
defineEmits<{ 'update:category': [category: string]; select: [event: VideoEvent]; refresh: [] }>()
</script>
<template>
  <section class="panel search-panel">
    <div class="section-heading"><div><h2>事件检索 <span v-if="searched && !notReady && !loading && !error" class="count">{{ events.length }}</span></h2><p class="hint">按目标类别，快速定位视频片段</p></div><button class="secondary" :disabled="!video || loading" @click="$emit('refresh')">重新查询</button></div>
    <div class="category-options" role="group" aria-label="目标类别"><button :class="{ active: category === '' }" :disabled="!video" @click="$emit('update:category', '')">全部类别</button><button v-for="item in categories" :key="item.key" :class="{ active: category === item.key }" :disabled="!video" :style="{ '--category-color': item.color }" @click="$emit('update:category', item.key)"><i></i>{{ item.name }} <small>{{ item.key }}</small></button></div>
    <p v-if="previous" class="notice">当前显示上一次成功建立的索引；新任务完成后将刷新结果。</p>
    <p v-if="loading" class="empty" role="status">正在查询视频索引…</p>
    <p v-else-if="error" class="error" role="alert">{{ error }}</p>
    <p v-else-if="!video" class="empty">选择视频后可检索目标事件</p>
    <p v-else-if="notReady" class="empty">{{ ['running', 'queued'].includes(video.analysis_status) ? '视频正在分析，尚无可用索引，请等待任务成功。' : '尚无可用索引，请先完成视频分析。' }}</p>
    <p v-else-if="searched && !events.length" class="empty">当前索引中未检测到{{ category ? categoryName(category) : '目标' }}事件<small>检测可能存在漏检，结果不代表绝对真值。</small></p>
    <div v-else class="event-results"><button v-for="(event, index) in events" :key="event.event_id" class="event-card" :class="{ active: event.event_id === activeId }" :style="{ '--category-color': categoryColor(event.category) }" @click="$emit('select', event)"><span class="event-number">{{ String(index + 1).padStart(2, '0') }}</span><div><strong><i></i>{{ categoryName(event.category) }} <small>{{ event.category }}</small></strong><span>{{ time(event.start_time, true) }} <span class="subtle">→</span> {{ time(event.end_time, true) }}</span></div><div class="event-duration"><strong>{{ event.duration.toFixed(1) }}<small> 秒</small></strong><small>▷ 跳转播放</small></div></button></div>
  </section>
</template>
