import { describe, expect, it } from 'vitest'
import { positionSyncSummary, taskProgress } from './recruitmentJobs'

describe('recruitment job sync helpers', () => {
  it('formats persisted sync counts', () => {
    expect(positionSyncSummary({ sync: { created: 2, updated: 1, unchanged: 4, total: 7 } }))
      .toBe('新增 2 · 更新 1 · 未变化 4 · 共 7 个职位')
  })

  it('returns an empty summary for an invalid result', () => {
    expect(positionSyncSummary({})).toBe('')
  })

  it('maps worker states to stable progress', () => {
    expect(taskProgress('pending')).toEqual({ label: '等待执行', percent: 12 })
    expect(taskProgress('running')).toEqual({ label: '正在读取 BOSS 职位', percent: 62 })
    expect(taskProgress('cancel_requested')).toEqual({ label: '正在取消', percent: 80 })
    expect(taskProgress('succeeded')).toEqual({ label: '同步完成', percent: 100 })
  })
})
