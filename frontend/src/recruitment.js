export const stageColumns = [
  { key: 'new', label: '新候选人' },
  { key: 'to_screen', label: '初筛' },
  { key: 'communicating', label: '沟通' },
  { key: 'interviewing', label: '面试' },
  { key: 'to_offer', label: 'Offer' },
  { key: 'hired', label: '已入职' },
  { key: 'rejected', label: '淘汰' },
]

export function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

export function formatRecruitmentDate(value) {
  return value
    ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(value))
    : '—'
}
