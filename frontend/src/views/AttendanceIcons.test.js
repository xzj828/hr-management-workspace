import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => payload?.results || payload || [],
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))

import AppIcon from '@/components/AppIcon.vue'
import DashboardView from './DashboardView.vue'
import EmployeesView from './EmployeesView.vue'
import ImportsView from './ImportsView.vue'
import ResultsView from './ResultsView.vue'
import SettingsView from './SettingsView.vue'
import SuspicionsView from './SuspicionsView.vue'

const global = {
  stubs: {
    EChart: true,
    RouterLink: { template: '<a><slot /></a>' },
    ToastMessage: true,
  },
}

function iconNames(wrapper) {
  return wrapper.findAllComponents(AppIcon).map((icon) => icon.props('name'))
}

describe('attendance page icons', () => {
  beforeEach(() => apiMock.mockReset())

  it('uses add and search icons in personnel management', async () => {
    apiMock.mockResolvedValue({ results: [] })
    const wrapper = mount(EmployeesView, { global })
    await flushPromises()

    expect(iconNames(wrapper)).toEqual(expect.arrayContaining(['plus', 'search']))
    expect(wrapper.text()).not.toContain('＋')
    expect(wrapper.text()).not.toContain('⌕')
  })

  it('uses an upload icon for file selection', async () => {
    apiMock.mockResolvedValue({ results: [] })
    const wrapper = mount(ImportsView, { global })
    await flushPromises()

    expect(iconNames(wrapper)).toContain('upload')
    expect(wrapper.text()).not.toContain('⇧')
  })

  it('uses download and search icons in attendance results', async () => {
    apiMock.mockResolvedValue({ results: [] })
    const wrapper = mount(ResultsView, { global })
    await flushPromises()

    expect(iconNames(wrapper)).toEqual(expect.arrayContaining(['download', 'search']))
    expect(wrapper.text()).not.toContain('↓')
    expect(wrapper.text()).not.toContain('⌕')
  })

  it('uses distinct clock and upload icons for dashboard empty states', async () => {
    apiMock.mockResolvedValueOnce({ batches: [], available_periods: [{ value: '2026-08' }] })
    const noRange = mount(DashboardView, { global })
    await flushPromises()
    expect(iconNames(noRange)).toContain('clock')
    expect(noRange.text()).not.toContain('◷')

    apiMock.mockResolvedValueOnce({ batches: [], available_periods: [] })
    const noData = mount(DashboardView, { global })
    await flushPromises()
    expect(iconNames(noData)).toContain('upload')
    expect(noData.text()).not.toContain('⇧')
  })

  it('uses policy and permission icons in settings', async () => {
    apiMock.mockImplementation((path) => Promise.resolve(path === 'policies/' ? {
      results: [{ id: 1, name: '标准考勤', mode: 'standard', mode_label: '标准考勤', employee_count: 3, cross_day_cutoff_minutes: 180 }],
    } : { results: [] }))
    const wrapper = mount(SettingsView, { global })
    await flushPromises()

    expect(iconNames(wrapper)).toEqual(expect.arrayContaining(['sliders', 'shield']))
    expect(wrapper.text()).not.toContain('⌘')
  })

  it('uses alert, timeline and completed-state icons in review flows', async () => {
    const batch = { id: 1, year: 2026, month: 8, suspicion_count: 1 }
    const row = {
      id: 2,
      employee_name: '测试员工',
      employee_no: 'E001',
      department: '研发部',
      previous_date: '2026-08-01',
      previous_raw_value: '23:40',
      work_date: '2026-08-02',
      punch_text: '00:20',
      reason: '凌晨单条记录',
      status: 'pending',
    }
    apiMock.mockImplementation((path) => Promise.resolve(path === 'imports/' ? { results: [batch] } : { results: [row] }))
    const withRow = mount(SuspicionsView, { global })
    await flushPromises()
    expect(iconNames(withRow)).toEqual(expect.arrayContaining(['alert-circle', 'arrow-right']))

    apiMock.mockImplementation((path) => Promise.resolve(path === 'imports/' ? { results: [batch] } : { results: [] }))
    const completed = mount(SuspicionsView, { global })
    await flushPromises()
    expect(iconNames(completed)).toEqual(expect.arrayContaining(['alert-circle', 'check-circle']))
  })
})
