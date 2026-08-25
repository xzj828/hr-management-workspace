import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())
const routeState = vi.hoisted(() => ({ name: 'recruitment-admin', query: {} }))
const routerReplace = vi.hoisted(() => vi.fn(() => Promise.resolve()))

vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ replace: routerReplace }),
}))

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentAdminView from './RecruitmentAdminView.vue'
import { useAuthStore } from '@/stores/auth'

const account = {
  id: 1,
  name: '北京招聘账号',
  browser_type: 'edge',
  browser_profile: 'boss-beijing',
  cdp_port: 53470,
  login_status: 'browser_stopped',
  verification_status: '',
  last_checked_at: '2026-08-25T08:00:00Z',
  active: true,
}

function modelConfig() {
  return { api_url: 'https://models.example/v1', model: 'glm-5', has_api_key: true, key_last4: '1234' }
}

function modelProfiles() {
  return { results: [{ id: 3, name: '日常招聘', ...modelConfig(), is_active: true }] }
}

function baseApi({ ready = false, workerOnline = false, workflowVersion = null } = {}) {
  let loginQueued = false
  let synced = false
  apiMock.mockImplementation((path, options = {}) => {
    if (path === 'recruitment/automation/summary/') return Promise.resolve({
      worker: workerOnline ? { hostname: 'WIN-HR', version: 'boss-cli 0.6.6', status: 'online', last_seen_at: '2026-08-25T08:30:00Z' } : null,
      cli_available: workerOnline,
      task_counts: {},
      has_active_task: loginQueued,
    })
    if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [{ ...account, login_status: ready ? 'ready' : 'browser_stopped' }] })
    if (path === 'recruitment/jobs/') return Promise.resolve({ results: synced ? [{
      id: 31, boss_account: 1, title: '高级前端工程师', department: '研发中心', headcount: 2,
      status: 'open', updated_at: '2026-08-25T09:00:00Z',
    }] : [] })
    if (path === 'recruitment/rpa-tasks/' && !options.method) return Promise.resolve({ results: loginQueued ? [{
      id: 'task-login', boss_account: 1, account_name: account.name, action: 'check_status', status: 'pending', created_at: '2026-08-25T09:00:00Z', events: [],
    }] : [] })
    if (path === 'recruitment/rpa-tasks/' && options.method === 'POST') {
      loginQueued = true
      return Promise.resolve({ id: 'task-login', boss_account: 1, action: 'check_status', status: 'pending' })
    }
    if (path === 'recruitment/workflows/') return Promise.resolve({ results: workflowVersion ? [{ id: 9, name: '标准主动寻访' }] : [] })
    if (path === 'recruitment/workflow-versions/') return Promise.resolve({ results: workflowVersion ? [workflowVersion] : [] })
    if (path === 'account/model-profiles/') return Promise.resolve(modelProfiles())
    if (path === 'recruitment/jobs/sync/' && options.method === 'POST') {
      synced = true
      return Promise.resolve({ task_id: 'sync-1', status: 'pending' })
    }
    if (path === 'recruitment/rpa-tasks/sync-1/') return Promise.resolve({
      id: 'sync-1',
      status: 'succeeded',
      result: { sync: { created: 1, updated: 0, unchanged: 2, total: 3 } },
    })
    if (path === 'recruitment/workflow-versions/21/enable/' && options.method === 'POST') return Promise.resolve({ ...workflowVersion, status: 'enabled' })
    return Promise.reject(new Error(`unexpected path: ${path}`))
  })
}

describe('RecruitmentAdminView', () => {
  let wrapper

  beforeEach(() => {
    setActivePinia(createPinia())
    useAuthStore().user = { id: 9, username: 'hr', role: 'hr' }
    apiMock.mockReset()
    routerReplace.mockClear()
    routeState.query = {}
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ''
  })

  it('turns a stopped browser into a visible, traceable login task', async () => {
    baseApi({ ready: false, workerOnline: false })
    wrapper = mount(RecruitmentAdminView, {
      global: {
        stubs: {
          teleport: true,
          WorkflowCanvas: true,
          ModelProfileDrawer: { template: '<aside data-test="model-drawer-stub">model</aside>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('隔离浏览器未启动')
    expect(wrapper.text()).toContain('浏览器尚未启动，职位同步与正式执行暂不可用')
    await wrapper.get('[data-test="start-browser-1"]').trigger('click')
    await flushPromises()

    const loginCall = apiMock.mock.calls.find(([path, options]) => path === 'recruitment/rpa-tasks/' && options?.method === 'POST')
    expect(JSON.parse(loginCall[1].body)).toEqual({
      boss_account: 1,
      action: 'check_status',
      request_payload: { open_login: true },
    })
    expect(wrapper.text()).toContain('启动任务已排队')
    expect(wrapper.text()).toContain('等待执行')

    await wrapper.get('[data-test="admin-tab-jobs"]').trigger('click')
    expect(wrapper.text()).toContain('同步条件未满足')
    expect(wrapper.text()).toContain('去启动并登录')
  })

  it('syncs published positions from a ready account and shows persisted counts', async () => {
    baseApi({ ready: true, workerOnline: true })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true } } })
    await flushPromises()
    await wrapper.get('[data-test="admin-tab-jobs"]').trigger('click')
    await wrapper.get('[data-test="admin-sync-positions"]').trigger('click')
    await flushPromises()

    const syncCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/jobs/sync/')
    const payload = JSON.parse(syncCall[1].body)
    expect(payload.boss_account).toBe(1)
    expect(payload.request_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(wrapper.text()).toContain('新增 1 · 更新 0 · 未变化 2 · 共 3 个职位')
    expect(wrapper.text()).toContain('高级前端工程师')
  })

  it('keeps advanced workflow editing behind the workflow governance tab', async () => {
    const version = {
      id: 21,
      template: 9,
      boss_account: 1,
      version: 3,
      status: 'draft',
      nodes: [{ key: 'source', type: 'search', label: '常规搜索', position: { x: 20, y: 40 } }],
      edges: [],
    }
    baseApi({ ready: true, workerOnline: true, workflowVersion: version })
    wrapper = mount(RecruitmentAdminView, {
      global: {
        stubs: {
          teleport: true,
          WorkflowCanvas: { name: 'WorkflowCanvas', template: '<div data-test="workflow-canvas-stub"></div>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.find('[data-test="workflow-canvas-stub"]').exists()).toBe(false)
    await wrapper.get('[data-test="admin-tab-workflows"]').trigger('click')
    expect(wrapper.text()).toContain('标准主动寻访')
    expect(wrapper.text()).toContain('草稿')
    await wrapper.get('[data-test="edit-admin-workflow-21"]').trigger('click')
    expect(wrapper.find('[data-test="workflow-canvas-stub"]').exists()).toBe(true)

    const enableButton = wrapper.findAll('button').find((button) => button.text().includes('校验并启用'))
    await enableButton.trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-versions/21/enable/', { method: 'POST' })
  })

  it('lists saved models and opens the custom model form', async () => {
    baseApi({ ready: true, workerOnline: true })
    wrapper = mount(RecruitmentAdminView, {
      global: {
        stubs: {
          teleport: true,
          WorkflowCanvas: true,
          ModelProfileDrawer: { template: '<aside data-test="model-drawer-stub">model</aside>' },
        },
      },
    })
    await flushPromises()
    await wrapper.get('[data-test="admin-tab-models"]').trigger('click')

    expect(wrapper.text()).toContain('日常招聘')
    expect(wrapper.text()).toContain('glm-5')
    expect(wrapper.text()).toContain('当前使用')
    await wrapper.get('[data-test="open-model-config"]').trigger('click')
    expect(wrapper.find('[data-test="model-drawer-stub"]').exists()).toBe(true)
  })

  it('opens the requested administration section from a compatibility deep link', async () => {
    routeState.query = { section: 'jobs' }
    baseApi({ ready: true, workerOnline: true })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true } } })
    await flushPromises()

    expect(wrapper.get('[data-test="admin-tab-jobs"]').classes()).toContain('active')
    expect(wrapper.text()).toContain('从 BOSS 同步职位')
  })

  it('does not load or expose management actions to viewer roles', async () => {
    useAuthStore().user = { id: 10, username: 'viewer', role: 'viewer' }
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true } } })
    await flushPromises()

    expect(wrapper.get('[data-test="admin-permission"]').text()).toContain('没有管理权限')
    expect(wrapper.find('.admin-tabs').exists()).toBe(false)
    expect(wrapper.find('[data-test="start-browser-1"]').exists()).toBe(false)
    expect(apiMock).not.toHaveBeenCalled()
  })
})
