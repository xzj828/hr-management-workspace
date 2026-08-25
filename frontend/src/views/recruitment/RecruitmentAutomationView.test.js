import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentAutomationView from './RecruitmentAutomationView.vue'
import AppIcon from '@/components/AppIcon.vue'


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
        last_checked_at: '2026-08-24T08:00:00Z',
        active: true,
      }] })
      if (path === 'recruitment/rpa-tasks/') return Promise.resolve({ results: [{
        id: 'task-1', account_name: '主招聘账号', action: 'check_status', status: 'succeeded',
        created_at: '2026-08-22T12:00:00Z', events: [],
      }] })
      if (path === 'recruitment/execution-batches/') return Promise.resolve({ results: [] })
      if (path === 'recruitment/workflows/') return Promise.resolve({ results: [] })
      if (path === 'recruitment/workflow-versions/') return Promise.resolve({ results: [] })
      if (path === 'recruitment/boss-accounts/1/archive/') return Promise.resolve({ id: 1, archived_at: '2026-08-24T10:00:00Z' })
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
    expect(wrapper.text()).toContain('立即检查')
    expect(wrapper.text()).not.toContain('发送消息')
    expect(wrapper.text()).not.toContain('打招呼')
    expect(wrapper.text()).not.toContain('采集候选人')
    const menuTrigger = wrapper.get('button[aria-label="账号操作"]')
    expect(menuTrigger.findComponent(AppIcon).props('name')).toBe('more-horizontal')
    expect(menuTrigger.text()).not.toContain('•••')
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

  it('shows honest login state and checks it immediately without creating an RPA task', async () => {
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/boss-accounts/1/check-status/' && options?.method === 'POST') {
        return Promise.resolve({ id: 1, login_status: 'ready', status: 'ready' })
      }
      if (path === 'recruitment/automation/summary/') return Promise.resolve({ worker: null, cli_available: true, task_counts: {} })
      if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [{
        id: 1, name: '主招聘账号', browser_type: 'edge', browser_profile: 'boss-main', cdp_port: 53470,
        login_status: 'ready', verification_status: '', last_checked_at: '2026-08-24T08:00:00Z', active: true,
      }] })
      if (['recruitment/rpa-tasks/', 'recruitment/execution-batches/', 'recruitment/workflows/', 'recruitment/workflow-versions/'].includes(path)) return Promise.resolve({ results: [] })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    wrapper = mount(RecruitmentAutomationView, { attachTo: document.body })
    await flushPromises()

    expect(wrapper.text()).toContain('登录成功')
    expect(wrapper.text()).toContain('最近检查')
    await wrapper.get('button[aria-label="账号操作"]').trigger('click')
    const checkButton = [...document.body.querySelectorAll('.automation-menu-popover button')]
      .find((button) => button.textContent.includes('立即检查'))
    expect(checkButton).toBeTruthy()
    checkButton.click()
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/boss-accounts/1/check-status/', { method: 'POST' })
    expect(apiMock).not.toHaveBeenCalledWith('recruitment/rpa-tasks/', expect.objectContaining({ method: 'POST' }))
  })

  it('offers re-login for a remembered ready session', async () => {
    wrapper = mount(RecruitmentAutomationView, { attachTo: document.body })
    await flushPromises()

    await wrapper.get('button[aria-label="账号操作"]').trigger('click')
    const labels = [...document.body.querySelectorAll('.automation-menu-popover button')].map((button) => button.textContent.trim())

    expect(labels).toContain('重新登录')
    expect(labels).toContain('立即检查')
  })

  it('removes a saved account through a confirmed lifecycle action', async () => {
    wrapper = mount(RecruitmentAutomationView, {
      attachTo: document.body,
      global: { stubs: { teleport: { template: '<div><slot /></div>' } } },
    })
    await flushPromises()
    await wrapper.get('button[aria-label="账号操作"]').trigger('click')
    const removeButton = [...document.body.querySelectorAll('.automation-menu-popover button')]
      .find((button) => button.textContent.includes('移除账号'))
    expect(removeButton).toBeTruthy()
    removeButton.click()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('移除 BOSS 账号')
    await wrapper.get('[data-test="confirm-archive"]').trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/boss-accounts/1/archive/', { method: 'POST' })
  })

  it('opens a saved workflow version as a rearrangeable new-version draft', async () => {
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/automation/summary/') return Promise.resolve({ worker: null, cli_available: false, task_counts: {} })
      if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [{ id: 1, name: '主招聘账号' }] })
      if (path === 'recruitment/rpa-tasks/' || path === 'recruitment/execution-batches/') return Promise.resolve({ results: [] })
      if (path === 'recruitment/workflows/') return Promise.resolve({ results: [{ id: 9, name: '标准流程' }] })
      if (path === 'recruitment/workflow-versions/') return Promise.resolve({ results: [{
        id: 21, template: 9, boss_account: 1, version: 3, status: 'enabled',
        nodes: [
          { key: 'source-x', type: 'search', label: '常规搜索', position: { x: 20, y: 40 } },
          { key: 'end-x', type: 'end', label: '结束', position: { x: 300, y: 40 } },
        ],
        edges: [{ source: 'source-x', target: 'end-x' }],
      }] })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    wrapper = mount(RecruitmentAutomationView, { global: { stubs: { teleport: true } } })
    await flushPromises()

    await wrapper.get('.automation-workspace-tabs button:nth-child(3)').trigger('click')
    await wrapper.get('[data-test="edit-workflow-version-21"]').trigger('click')

    expect(wrapper.get('[data-test="workflow-name"]').element.value).toBe('标准流程')
    expect(wrapper.find('[data-node-key="source-x"]').exists()).toBe(true)
  })

  it('runs a saved workflow in dry mode and guards formal execution with confirmation', async () => {
    const version = {
      id: 21, template: 9, boss_account: 1, version: 3, status: 'enabled',
      nodes: [{ key: 'source-x', type: 'search', label: '常规搜索', position: { x: 20, y: 40 } }, { key: 'gate-x', type: 'human_screen', label: '人工筛选', position: { x: 220, y: 40 } }],
      edges: [{ source: 'source-x', target: 'gate-x' }],
    }
    const run = {
      id: 'run-1', template_name: '标准流程', account_name: '主招聘账号', mode: 'dry_run', status: 'waiting_human',
      node_runs: [{ id: 31, node_key: 'source-x', status: 'succeeded', attempt: 0 }, { id: 32, node_key: 'gate-x', status: 'waiting_human', attempt: 0 }], events: [],
    }
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation/summary/') return Promise.resolve({ worker: null, cli_available: true, task_counts: {} })
      if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [{ id: 1, name: '主招聘账号', login_status: 'ready' }] })
      if (path === 'recruitment/rpa-tasks/' || path === 'recruitment/execution-batches/') return Promise.resolve({ results: [] })
      if (path === 'recruitment/workflows/') return Promise.resolve({ results: [{ id: 9, name: '标准流程' }] })
      if (path === 'recruitment/workflow-versions/') return Promise.resolve({ results: [version] })
      if (path === 'recruitment/jobs/') return Promise.resolve({ results: [{ id: 51, title: 'Vue 工程师', boss_account: 1, status: 'open' }] })
      if (path === 'recruitment/workflow-versions/21/run/' && options?.method === 'POST') return Promise.resolve({ ...run, mode: JSON.parse(options.body).mode })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    wrapper = mount(RecruitmentAutomationView, { global: { stubs: { teleport: { template: '<div><slot /></div>' } } } })
    await flushPromises()
    await wrapper.get('.automation-workspace-tabs button:nth-child(3)').trigger('click')
    await wrapper.get('[data-test="dry-run-21"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('试运行 · 不会操作 BOSS')
    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-versions/21/run/', expect.objectContaining({ method: 'POST' }))

    await wrapper.get('[data-test="formal-run-21"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('确认正式运行')
    expect(wrapper.get('[data-test="formal-run-job"]').element.value).toBe('51')
    await wrapper.get('[data-test="confirm-formal-run"]').trigger('click')
    await flushPromises()
    const runCalls = apiMock.mock.calls.filter(([path]) => path === 'recruitment/workflow-versions/21/run/')
    expect(JSON.parse(runCalls.at(-1)[1].body)).toMatchObject({ mode: 'formal', job: 51, confirm: true })
  })

  it('presents the two standard outcomes before the advanced canvas', async () => {
    wrapper = mount(RecruitmentAutomationView, { global: { stubs: { teleport: true } } })
    await flushPromises()

    expect(wrapper.text()).toContain('同步消息并获取简历')
    expect(wrapper.text()).toContain('搜索并拉取在线简历')
    expect(wrapper.text()).toContain('当前没有人工介入事项')
    await wrapper.get('.automation-scheme-card.is-passive').trigger('click')
    expect(wrapper.text()).toContain('运行被动咨询方案')
    expect(wrapper.text()).toContain('消息同步间隔')
  })
})
