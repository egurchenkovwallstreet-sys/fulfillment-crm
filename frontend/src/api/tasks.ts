import { apiFetch } from './client'

export type TaskState = 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE' | 'RETRY' | string

export interface TaskStatus<T = unknown> {
  task_id: string
  state: TaskState
  ready: boolean
  result?: T
  error?: string
}

export function fetchTaskStatus<T = unknown>(taskId: string) {
  return apiFetch<TaskStatus<T>>(`/api/integrations/tasks/${taskId}/`)
}

export async function waitForTask<T>(
  taskId: string,
  opts?: { intervalMs?: number; timeoutMs?: number; onProgress?: (state: TaskState) => void },
): Promise<T> {
  const intervalMs = opts?.intervalMs ?? 2000
  const timeoutMs = opts?.timeoutMs ?? 600_000
  const started = Date.now()

  while (Date.now() - started < timeoutMs) {
    const status = await fetchTaskStatus<T>(taskId)
    opts?.onProgress?.(status.state)
    if (status.ready) {
      if (status.state === 'SUCCESS') {
        return status.result as T
      }
      throw new Error(status.error || 'Ошибка фоновой задачи')
    }
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs))
  }
  throw new Error('Таймаут ожидания фоновой задачи')
}
