import { describe, expect, it } from 'vitest'
import { moduleForRoute, navigationForModule } from './navigation'

describe('HR platform navigation', () => {
  it('maps recruitment routes to the recruitment module', () => {
    expect(moduleForRoute({ meta: { module: 'recruitment' } })).toBe('recruitment')
  })

  it('keeps six recruitment side-navigation items', () => {
    expect(navigationForModule('recruitment').map((item) => item.label)).toEqual([
      '招聘看板', '职位管理', '候选人', '招聘流程', '自动化任务', '简历中心',
    ])
  })

  it('keeps the existing six attendance entries', () => {
    expect(navigationForModule('attendance')).toHaveLength(6)
  })
})
