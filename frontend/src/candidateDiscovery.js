import { createRequestId, terminalTaskStatuses } from '@/recruitmentJobs'

export const discoveryModes = [
  { key: 'recommend', label: '智能推荐', hint: '读取当前职位的推荐候选人' },
  { key: 'search', label: '关键词搜索', hint: '按关键词读取常规搜索结果' },
  { key: 'deep_search', label: '深度匹配', hint: '确认后消耗 1 次立即匹配额度' },
]

export function discoveryPayload({ accountId, jobId, mode, keyword = '' }) {
  return {
    boss_account: Number(accountId),
    job: Number(jobId),
    mode,
    keyword: keyword.trim(),
    request_id: createRequestId(),
  }
}

export function discoveryTaskDone(status) {
  return terminalTaskStatuses.has(status)
}

export function discoverySyncMessage(result) {
  const sync = result?.sync
  if (!sync) return ''
  return `新增 ${sync.created || 0} · 更新 ${sync.updated || 0} · 共 ${sync.total || 0} 位候选人`
}
