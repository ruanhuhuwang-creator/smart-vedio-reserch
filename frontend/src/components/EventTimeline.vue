<script setup lang="ts">
import { computed } from 'vue'
import type { VideoEvent } from '@/types/api'
import { categoryColor, categoryName, time } from '@/utils/format'
const props = defineProps<{ events: VideoEvent[]; duration: number; currentTime: number; activeId: number | null; ready: boolean }>()
defineEmits<{ select: [event: VideoEvent] }>()
// 同类事件也按重叠区间分配独立轨道，避免相互遮挡。
const lanes = computed(() => {
  const result: { category: string; events: VideoEvent[]; end: number }[] = []
  for (const event of [...props.events].sort((a, b) => a.start_time - b.start_time)) {
    let lane = result.find(row => row.category === event.category && row.end < event.start_time)
    if (!lane) { lane = { category: event.category, events: [], end: -1 }; result.push(lane) }
    lane.events.push(event); lane.end = event.end_time
  }
  return result
})
const percent = (seconds: number) => Math.min(100, Math.max(0, props.duration > 0 ? seconds / props.duration * 100 : 0))
</script>
<template>
  <section class="panel timeline-panel">
    <div class="section-heading"><h2>检测时间轴</h2><span class="tiny-label">{{ events.length }} 个片段</span></div>
    <div class="timeline-scale"><span v-for="part in [0, 1, 2, 3, 4]" :key="part">{{ time(duration * part / 4) }}</span></div>
    <div class="timeline-lanes">
      <p v-if="!lanes.length" class="timeline-empty">{{ ready ? '当前查询没有事件片段' : '索引就绪后在此显示目标出现的时间段' }}</p>
      <div v-for="(lane, index) in lanes" :key="index" class="timeline-lane"><span class="lane-label" :style="{ color: categoryColor(lane.category) }">{{ categoryName(lane.category) }}</span><div class="lane-track"><button v-for="event in lane.events" :key="event.event_id" class="timeline-event" :class="{ active: activeId === event.event_id }" :style="{ left: `${percent(event.start_time)}%`, width: `${Math.max(.25, percent(event.end_time) - percent(event.start_time))}%`, background: categoryColor(event.category) }" :aria-label="`${categoryName(event.category)} ${time(event.start_time, true)} 至 ${time(event.end_time, true)}`" :title="`${categoryName(event.category)} ${time(event.start_time, true)} — ${time(event.end_time, true)}`" @click="$emit('select', event)"></button><span class="playhead" :style="{ left: `${percent(currentTime)}%` }"></span></div></div>
    </div>
    <p class="footnote">点击色块跳转 · 时间段根据原视频时间戳定位</p>
  </section>
</template>
