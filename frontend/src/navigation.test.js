import { describe, expect, it } from 'vitest'
import {
  moduleDestination,
  moduleForRoute,
  navigationForModule,
  rememberModuleRoute,
  resetRememberedModuleRoutes,
} from './navigation'

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

describe('module destinations', () => {
  it('starts each module on its dashboard', () => {
    resetRememberedModuleRoutes()
    expect(moduleDestination('recruitment')).toBe('recruitment-dashboard')
    expect(moduleDestination('attendance')).toBe('attendance-dashboard')
  })

  it('returns to the last page visited in each module', () => {
    resetRememberedModuleRoutes()
    rememberModuleRoute({ name: 'recruitment-candidates', meta: { module: 'recruitment' } })
    rememberModuleRoute({ name: 'employees', meta: { module: 'attendance' } })

    expect(moduleDestination('recruitment')).toBe('recruitment-candidates')
    expect(moduleDestination('attendance')).toBe('employees')
  })

  it('ignores route names that do not belong to the declared module', () => {
    resetRememberedModuleRoutes()
    rememberModuleRoute({ name: 'employees', meta: { module: 'recruitment' } })
    expect(moduleDestination('recruitment')).toBe('recruitment-dashboard')
  })
})
