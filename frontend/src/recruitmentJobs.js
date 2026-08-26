const TASK_PROGRESS = {
  pending: { label: '等待执行', percent: 12 },
  leased: { label: 'Worker 已领取任务', percent: 34 },
  running: { label: '正在读取 BOSS 职位', percent: 62 },
  cancel_requested: { label: '正在取消', percent: 80 },
  waiting_human: { label: '等待人工完成验证', percent: 72 },
  succeeded: { label: '同步完成', percent: 100 },
  failed: { label: '同步失败', percent: 100 },
  cancelled: { label: '任务已取消', percent: 100 },
}

export const terminalTaskStatuses = new Set(['waiting_human', 'succeeded', 'failed', 'cancelled'])

export function taskProgress(status) {
  return TASK_PROGRESS[status] || { label: '正在准备', percent: 4 }
}

export function positionSyncSummary(result) {
  const sync = result?.sync
  if (!sync || !Number.isFinite(sync.total)) return ''
  return `新增 ${sync.created || 0} · 更新 ${sync.updated || 0} · 未变化 ${sync.unchanged || 0} · 共 ${sync.total} 个职位`
}

export function createRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  const bytes = new Uint8Array(16)
  globalThis.crypto?.getRandomValues?.(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
