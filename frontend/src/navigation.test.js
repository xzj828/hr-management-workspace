import { describe, expect, it } from 'vitest'
import {
  modules,
  moduleDestination,
  moduleForRoute,
  navigationForModule,
  rememberModuleRoute,
  resetRememberedModuleRoutes,
} from './navigation'

describe('HR platform navigation', () => {
  it('maps modules and pages to semantic icon names', () => {
    expect(modules.map(({ id, icon }) => [id, icon])).toEqual([
      ['recruitment', 'briefcase'],
      ['attendance', 'calendar-check'],
    ])
    expect(navigationForModule('recruitment').map((item) => item.icon)).toEqual([
      'dashboard', 'briefcase', 'check-circle', 'sliders',
    ])
    expect(navigationForModule('attendance').map((item) => item.icon)).toEqual([
      'dashboard', 'users', 'upload', 'calculator-check', 'alert-circle', 'sliders',
    ])
  })

  it('maps recruitment routes to the recruitment module', () => {
    expect(moduleForRoute({ meta: { module: 'recruitment' } })).toBe('recruitment')
  })

  it('keeps a global dashboard before the three task workspaces', () => {
    expect(navigationForModule('recruitment').map((item) => item.label)).toEqual([
      '招聘看板', '招聘作业台', '结果中心', '管理后台',
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
    rememberModuleRoute({ name: 'recruitment-results', meta: { module: 'recruitment' } })
    rememberModuleRoute({ name: 'employees', meta: { module: 'attendance' } })

    expect(moduleDestination('recruitment')).toBe('recruitment-results')
    expect(moduleDestination('attendance')).toBe('employees')
  })

  it('ignores route names that do not belong to the declared module', () => {
    resetRememberedModuleRoutes()
    rememberModuleRoute({ name: 'employees', meta: { module: 'recruitment' } })
    expect(moduleDestination('recruitment')).toBe('recruitment-dashboard')
  })

  it('falls back to the restored dashboard when a removed recruitment page was remembered', () => {
    resetRememberedModuleRoutes()
    sessionStorage.setItem('ximing-hr:last-route:recruitment', 'recruitment-automation')
    expect(moduleDestination('recruitment')).toBe('recruitment-dashboard')
  })
})
