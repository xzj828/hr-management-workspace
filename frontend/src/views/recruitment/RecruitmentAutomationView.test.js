import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentAutomationView from './RecruitmentAutomationView.vue'


describe('RecruitmentAutomationView', () => {
  let wrapper

  beforeEach(() => {
    apiMock.mockReset()
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/automation/summary/') return Promise.resolve({
        worker: { hostname: 'WIN-HR', version: '@joohw/boss-cli 0.6.6', status: 'online' },
        cli_available: true,
        task_counts: { succeeded: 2 },
        has_active_task: false,
      })
      if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [{
        id: 1,
        name: '主招聘账号',
        browser_type: 'edge',
        browser_profile: 'boss-main',
        cdp_port: 53470,
        login_status: 'ready',
        verification_status: '',
        active: true,
      }] })
      if (path === 'recruitment/rpa-tasks/') return Promise.resolve({ results: [{
        id: 'task-1', account_name: '主招聘账号', action: 'check_status', status: 'succeeded',
        created_at: '2026-08-22T12:00:00Z', events: [],
      }] })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ''
  })

  it('renders worker, account and read-only task state without outbound actions', async () => {
    wrapper = mount(RecruitmentAutomationView, {
      global: { stubs: { teleport: true } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('WIN-HR')
    expect(wrapper.text()).toContain('@joohw/boss-cli 0.6.6')
    expect(wrapper.text()).toContain('主招聘账号')
    expect(wrapper.text()).toContain('Edge')
    expect(wrapper.text()).toContain('检查状态')
    expect(wrapper.text()).not.toContain('发送消息')
    expect(wrapper.text()).not.toContain('打招呼')
    expect(wrapper.text()).not.toContain('采集候选人')
  })

  it('uses larger workspace panels and teleports the account menu outside the table', async () => {
    wrapper = mount(RecruitmentAutomationView, { attachTo: document.body })
    await flushPromises()

    expect(wrapper.find('.automation-panel--accounts').exists()).toBe(true)
    expect(wrapper.find('.automation-panel--tasks').exists()).toBe(true)

    await wrapper.get('button[aria-label="账号操作"]').trigger('click')

    const popover = document.body.querySelector('.automation-menu-popover')
    expect(popover).not.toBeNull()
    expect(popover.style.position).toBe('fixed')
    expect(wrapper.find('.table-scroll .automation-menu-popover').exists()).toBe(false)
  })
})
