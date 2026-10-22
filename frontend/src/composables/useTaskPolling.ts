import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { getTask } from '@/api/tasks'
import { errorMessage } from '@/api/client'
import type { Task } from '@/types/api'

export function useTaskPolling(taskId: Ref<string | null>) {
  const task = ref<Task | null>(null)
  const error = ref('')
  let generation = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | undefined
  function stop() { generation++; clearTimeout(timer); controller?.abort() }
  async function poll(id: string, version: number) {
    controller = new AbortController()
    try {
      const result = await getTask(id, controller.signal)
      if (version !== generation) return
      task.value = result; error.value = ''
      // progress=100 仍可能是 running；仅终态停止。
      if (result.status === 'queued' || result.status === 'running') timer = setTimeout(() => void poll(id, version), 2000)
    } catch (reason) {
      if (version !== generation) return
      error.value = errorMessage(reason)
      // 网络错误暂停，由用户显式重试；不无限轰击服务。
    }
  }
  function retry() { stop(); error.value = ''; if (taskId.value) void poll(taskId.value, generation) }
  watch(taskId, () => { stop(); task.value = null; error.value = ''; if (taskId.value) void poll(taskId.value, generation) }, { immediate: true })
  onScopeDispose(stop)
  return { task, error, retry }
}
