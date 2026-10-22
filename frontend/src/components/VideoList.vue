<script setup lang="ts">
import type { VideoPage } from '@/types/api'
import { statusLabel, time } from '@/utils/format'
defineProps<{ page: VideoPage | null; selectedId?: number; loading: boolean; error: string }>()
defineEmits<{ select: [id: number]; page: [offset: number]; refresh: [] }>()
</script>
<template>
  <section class="panel library">
    <div class="section-heading"><h2>视频库 <span class="count">{{ page?.total ?? '—' }}</span></h2><button class="icon-button" :disabled="loading" aria-label="刷新视频列表" @click="$emit('refresh')">↻</button></div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载视频…</p>
    <p v-if="page && !page.items.length && !loading" class="empty">视频库还是空的<br><small>导入第一个视频，开始分析</small></p>
    <div class="video-items">
      <button v-for="video in page?.items" :key="video.video_id" class="video-item" :class="{ selected: video.video_id === selectedId }" :aria-pressed="video.video_id === selectedId" @click="$emit('select', video.video_id)">
        <span class="video-icon" aria-hidden="true">▷</span>
        <span class="video-item-body"><strong :title="video.filename">{{ video.filename }}</strong><small>{{ time(video.duration) }} <span>·</span> {{ video.resolution }}</small><span class="status" :data-status="video.analysis_status">{{ statusLabel[video.analysis_status] || video.analysis_status }}</span><time class="uploaded-at" :datetime="video.created_at">{{ new Date(video.created_at).toLocaleString('zh-CN') }}</time></span>
      </button>
    </div>
    <div v-if="page && page.total > page.limit" class="pagination"><button :disabled="loading || page.offset === 0" @click="$emit('page', Math.max(0, page.offset - page.limit))">上一页</button><small>{{ Math.floor(page.offset / page.limit) + 1 }} / {{ Math.ceil(page.total / page.limit) }}</small><button :disabled="loading || page.offset + page.limit >= page.total" @click="$emit('page', page.offset + page.limit)">下一页</button></div>
  </section>
</template>
