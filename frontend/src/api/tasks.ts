import { request } from './client'
import type { Task } from '@/types/api'
export const getTask = (id: string, signal?: AbortSignal) => request<Task>(`/api/tasks/${encodeURIComponent(id)}`, { signal })
