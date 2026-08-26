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
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

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

function baseApi({
  ready = false,
  workerOnline = false,
  workflowVersion = null,
  loginStatus = null,
  verificationStatus = '',
  failAccounts = false,
  failRuntimeRefreshAfterLogin = false,
} = {}) {
  let loginQueued = false
  let synced = false
  apiMock.mockImplementation((path, options = {}) => {
    if (path === 'recruitment/automation/summary/') return Promise.resolve({
      worker: workerOnline ? { hostname: 'WIN-HR', version: 'boss-cli 0.6.6', status: 'online', last_seen_at: '2026-08-25T08:30:00Z' } : null,
      cli_available: workerOnline,
      task_counts: {},
      has_active_task: loginQueued,
    })
    if (path === 'recruitment/boss-accounts/') {
      if (failAccounts || (loginQueued && failRuntimeRefreshAfterLogin)) return Promise.reject(new Error('账号状态服务暂不可用'))
      return Promise.resolve({ results: [{
        ...account,
        login_status: loginStatus || (ready ? 'ready' : 'browser_stopped'),
        verification_status: verificationStatus,
      }] })
    }
    if (path === 'recruitment/jobs/' || path === 'recruitment/jobs/?status=open') return Promise.resolve({ results: synced ? [{
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
    vi.useRealTimers()
  })

  it('blocks browser login visibly while the local worker or CLI is offline', async () => {
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
    expect(wrapper.get('[data-test="account-runtime-blocker"]').text()).toContain('启动考勤系统.cmd')
    expect(wrapper.get('[data-test="add-boss-account"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-test="start-browser-1"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="start-browser-1"]').trigger('click')
    await flushPromises()

    const loginCall = apiMock.mock.calls.find(([path, options]) => path === 'recruitment/rpa-tasks/' && options?.method === 'POST')
    expect(loginCall).toBeUndefined()

    await wrapper.get('[data-test="admin-tab-jobs"]').trigger('click')
    expect(wrapper.text()).toContain('同步条件未满足')
    expect(wrapper.text()).toContain('去启动并登录')
  })

  it('blocks position sync when a previously ready account loses the worker runtime', async () => {
    baseApi({ ready: true, workerOnline: false })
    wrapper = mount(RecruitmentAdminView, {
      global: { stubs: { teleport: true, WorkflowCanvas: true, ModelProfileDrawer: true } },
    })
    await flushPromises()

    await wrapper.get('[data-test="admin-tab-jobs"]').trigger('click')
    const syncButton = wrapper.get('[data-test="admin-sync-positions"]')
    expect(syncButton.attributes('disabled')).toBeDefined()
    await syncButton.trigger('click')
    await flushPromises()

    const syncCall = apiMock.mock.calls.find(([path, options]) => path === 'recruitment/jobs/sync/' && options?.method === 'POST')
    expect(syncCall).toBeUndefined()
  })

  it('merges a submitted login task immediately and keeps feedback on the account card', async () => {
    baseApi({ ready: false, workerOnline: true })
    wrapper = mount(RecruitmentAdminView, {
      global: { stubs: { teleport: true, WorkflowCanvas: true, ModelProfileDrawer: true } },
    })
    await flushPromises()

    await wrapper.get('[data-test="start-browser-1"]').trigger('click')
    await flushPromises()

    const loginCall = apiMock.mock.calls.find(([path, options]) => path === 'recruitment/rpa-tasks/' && options?.method === 'POST')
    expect(JSON.parse(loginCall[1].body)).toEqual({
      boss_account: 1,
      action: 'check_status',
      request_payload: { open_login: true },
    })
    expect(wrapper.text()).toContain('等待执行')
    expect(wrapper.get('[data-test="account-feedback-1"]').text()).toContain('正在打开隔离浏览器')
  })

  it('keeps the accepted task visible when the follow-up refresh fails', async () => {
    baseApi({ workerOnline: true, failRuntimeRefreshAfterLogin: true })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true } } })
    await flushPromises()

    await wrapper.get('[data-test="start-browser-1"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('等待执行')
    expect(wrapper.get('[data-test="account-feedback-1"]').text()).toContain('任务已提交，但状态刷新暂时失败')
    expect(apiMock.mock.calls.filter(([path, options]) => path === 'recruitment/rpa-tasks/' && options?.method === 'POST')).toHaveLength(1)
  })

  it('uses state-specific login actions and human guidance', async () => {
    baseApi({ workerOnline: true, loginStatus: 'waiting_login' })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true } } })
    await flushPromises()

    expect(wrapper.get('[data-test="start-browser-1"]').text()).toContain('聚焦登录窗口')
    expect(wrapper.text()).toContain('完成 BOSS 扫码登录')
  })

  it('polls account runtime every five seconds after the previous request settles', async () => {
    vi.useFakeTimers()
    baseApi({ workerOnline: true })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true } } })
    await flushPromises()
    const initialAccountCalls = apiMock.mock.calls.filter(([path]) => path === 'recruitment/boss-accounts/').length

    await vi.advanceTimersByTimeAsync(5000)
    await flushPromises()

    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/boss-accounts/')).toHaveLength(initialAccountCalls + 1)
  })

  it('ignores a late polling response after a newer manual refresh has applied', async () => {
    vi.useFakeTimers()
    baseApi({ workerOnline: true })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true } } })
    await flushPromises()

    const fallback = apiMock.getMockImplementation()
    let accountRefreshCalls = 0
    let resolveSlowPoll
    apiMock.mockImplementation((path, options = {}) => {
      if (path !== 'recruitment/boss-accounts/') return fallback(path, options)
      accountRefreshCalls += 1
      if (accountRefreshCalls === 1) {
        return new Promise((resolve) => { resolveSlowPoll = resolve })
      }
      return Promise.resolve({ results: [{ ...account, login_status: 'ready' }] })
    })

    await vi.advanceTimersByTimeAsync(5000)
    await wrapper.get('.admin-hero .admin-button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('登录成功')

    resolveSlowPoll({ results: [{ ...account, login_status: 'browser_stopped' }] })
    await flushPromises()
    expect(wrapper.text()).toContain('登录成功')
    expect(wrapper.text()).not.toContain('隔离浏览器未启动')
  })

  it('does not render the no-account empty state when the initial account request fails', async () => {
    baseApi({ workerOnline: true, failAccounts: true })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true } } })
    await flushPromises()

    expect(wrapper.get('[data-test="accounts-load-error"]').text()).toContain('账号列表加载失败')
    expect(wrapper.text()).not.toContain('尚未添加 BOSS 账号')
  })

  it('syncs published positions from a ready account and shows persisted counts', async () => {
    baseApi({ ready: true, workerOnline: true })
    const recruitmentContext = useRecruitmentContextStore()
    await recruitmentContext.loadJobs({ userId: 9 })
    expect(recruitmentContext.jobs).toEqual([])

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
    expect(recruitmentContext.jobs).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: 31, title: '高级前端工程师', status: 'open' }),
    ]))
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

  it('archives and restores a BOSS account from the same administration tab', async () => {
    baseApi({ ready: true, workerOnline: true })
    const fallback = apiMock.getMockImplementation()
    apiMock.mockImplementation((path, options = {}) => {
      if (path === 'recruitment/boss-accounts/1/archive/' && options.method === 'POST') return Promise.resolve({ ...account, archived_at: '2026-08-25T10:00:00Z' })
      if (path === 'recruitment/boss-accounts/?archived=1') return Promise.resolve({ results: [{ ...account, active: false, archived_at: '2026-08-25T10:00:00Z' }] })
      if (path === 'recruitment/boss-accounts/1/restore/?archived=1' && options.method === 'POST') return Promise.resolve({ ...account, active: true, archived_at: null })
      return fallback(path, options)
    })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true, ModelProfileDrawer: true } } })
    await flushPromises()

    await wrapper.get('[aria-label="归档账号 北京招聘账号"]').trigger('click')
    expect(wrapper.text()).toContain('归档 BOSS 账号')
    await wrapper.get('[data-test="confirm-archive"]').trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/boss-accounts/1/archive/', { method: 'POST' })
    expect(wrapper.text()).toContain('尚未添加 BOSS 账号')

    await wrapper.get('[data-test="archived-accounts"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('账号已停用')
    await wrapper.get('[data-test="restore-account-1"]').trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/boss-accounts/1/restore/?archived=1', { method: 'POST' })
  })

  it('closes and archives a synced job without implying a BOSS-side deletion', async () => {
    baseApi({ ready: true, workerOnline: true })
    const fallback = apiMock.getMockImplementation()
    apiMock.mockImplementation((path, options = {}) => {
      if (path === 'recruitment/jobs/') return Promise.resolve({ results: [{
        id: 31, boss_account: 1, title: '高级前端工程师', department: '研发中心', headcount: 2,
        status: 'open', updated_at: '2026-08-25T09:00:00Z',
      }] })
      if (path === 'recruitment/jobs/31/archive/' && options.method === 'POST') return Promise.resolve({ id: 31, title: '高级前端工程师', status: 'closed' })
      return fallback(path, options)
    })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true, ModelProfileDrawer: true } } })
    await flushPromises()
    await wrapper.get('[data-test="admin-tab-jobs"]').trigger('click')

    await wrapper.get('[aria-label="关闭并归档职位 高级前端工程师"]').trigger('click')
    expect(wrapper.text()).toContain('不会关闭或删除 BOSS 线上发布的职位')
    await wrapper.get('[data-test="confirm-archive"]').trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/jobs/31/archive/', { method: 'POST' })
    expect(wrapper.text()).toContain('BOSS 线上职位未更改')
  })

  it('permanently deletes a selected model through the masked profile API', async () => {
    baseApi({ ready: true, workerOnline: true })
    const fallback = apiMock.getMockImplementation()
    apiMock.mockImplementation((path, options = {}) => {
      if (path === 'account/model-profiles/3/' && options.method === 'DELETE') return Promise.resolve(null)
      return fallback(path, options)
    })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true, ModelProfileDrawer: true } } })
    await flushPromises()
    await wrapper.get('[data-test="admin-tab-models"]').trigger('click')

    await wrapper.get('[aria-label="永久删除模型 日常招聘"]').trigger('click')
    expect(wrapper.text()).toContain('加密保存的 Key')
    expect(wrapper.text()).toContain('新建 AI 任务将等待配置')
    await wrapper.get('[data-test="confirm-archive"]').trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('account/model-profiles/3/', { method: 'DELETE' })
    expect(wrapper.text()).toContain('API Key 已擦除')
    expect(wrapper.text()).toContain('尚未配置模型')
  })

  it('deletes only workflow drafts and restores archived workflow templates', async () => {
    const version = {
      id: 21, template: 9, boss_account: 1, version: 3, status: 'draft', nodes: [], edges: [],
    }
    baseApi({ ready: true, workerOnline: true, workflowVersion: version })
    const fallback = apiMock.getMockImplementation()
    apiMock.mockImplementation((path, options = {}) => {
      if (path === 'recruitment/workflow-versions/21/' && options.method === 'DELETE') return Promise.resolve(null)
      if (path === 'recruitment/workflows/?archived=1') return Promise.resolve({ results: [{ id: 10, name: '已归档寻访流程' }] })
      if (path === 'recruitment/workflow-versions/?archived=1') return Promise.resolve({ results: [{ id: 22, template: 10, version: 2, status: 'disabled' }] })
      if (path === 'recruitment/workflows/10/restore/?archived=1' && options.method === 'POST') return Promise.resolve({ id: 10, name: '已归档寻访流程' })
      return fallback(path, options)
    })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true, ModelProfileDrawer: true } } })
    await flushPromises()
    await wrapper.get('[data-test="admin-tab-workflows"]').trigger('click')

    const deleteDraft = wrapper.findAll('button').find((button) => button.text() === '删除草稿')
    await deleteDraft.trigger('click')
    await wrapper.get('[data-test="confirm-archive"]').trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-versions/21/', { method: 'DELETE' })
    expect(wrapper.text()).toContain('尚无可用版本')
    expect(wrapper.findAll('button').some((button) => button.text() === '归档方案')).toBe(true)

    await wrapper.get('[data-test="archived-workflows"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已归档寻访流程')
    const restore = wrapper.findAll('button').find((button) => button.text() === '恢复流程')
    await restore.trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/workflows/10/restore/?archived=1', { method: 'POST' })
  })

  it('archives a terminal task from its record and exposes the archived task list', async () => {
    baseApi({ ready: true, workerOnline: true })
    const fallback = apiMock.getMockImplementation()
    const task = { id: 'done-1', boss_account: 1, account_name: account.name, action: 'sync_positions', status: 'succeeded', created_at: '2026-08-25T09:00:00Z', events: [] }
    apiMock.mockImplementation((path, options = {}) => {
      if (path === 'recruitment/rpa-tasks/' && !options.method) return Promise.resolve({ results: [task] })
      if (path === 'recruitment/rpa-tasks/done-1/archive/' && options.method === 'POST') return Promise.resolve({ ...task, archived_at: '2026-08-25T10:00:00Z' })
      if (path === 'recruitment/rpa-tasks/?archived=1') return Promise.resolve({ results: [{ ...task, archived_at: '2026-08-25T10:00:00Z' }] })
      return fallback(path, options)
    })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true, ModelProfileDrawer: true } } })
    await flushPromises()
    await wrapper.get('[data-test="admin-tab-diagnostics"]').trigger('click')

    const viewRecord = wrapper.findAll('button').find((button) => button.text() === '查看记录')
    await viewRecord.trigger('click')
    const archiveRecord = wrapper.findAll('button').find((button) => button.text() === '归档任务记录')
    await archiveRecord.trigger('click')
    await wrapper.get('[data-test="confirm-archive"]').trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/rpa-tasks/done-1/archive/', { method: 'POST' })

    await wrapper.get('[data-test="archived-tasks"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已归档自动化任务')
    expect(wrapper.text()).toContain('北京招聘账号')
  })

  it('treats workflow restore as committed even when the follow-up list refresh fails', async () => {
    baseApi({ ready: true, workerOnline: true })
    const fallback = apiMock.getMockImplementation()
    let restored = false
    apiMock.mockImplementation((path, options = {}) => {
      if (path === 'recruitment/workflows/?archived=1') return Promise.resolve({ results: [{ id: 10, name: '已归档流程' }] })
      if (path === 'recruitment/workflow-versions/?archived=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/workflows/10/restore/?archived=1' && options.method === 'POST') {
        restored = true
        return Promise.resolve({ id: 10, name: '已归档流程' })
      }
      if (restored && path === 'recruitment/workflows/') return Promise.reject(new Error('流程列表暂不可用'))
      return fallback(path, options)
    })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true, ModelProfileDrawer: true } } })
    await flushPromises()
    await wrapper.get('[data-test="admin-tab-workflows"]').trigger('click')
    await wrapper.get('[data-test="archived-workflows"]').trigger('click')
    await flushPromises()

    const restore = wrapper.findAll('button').find((button) => button.text() === '恢复流程')
    await restore.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('已恢复，但列表刷新暂时失败')
    expect(wrapper.text()).toContain('暂无已归档流程')
    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/workflows/10/restore/?archived=1')).toHaveLength(1)
  })

  it('shows a retryable archive error instead of a false empty state', async () => {
    baseApi({ ready: true, workerOnline: true })
    const fallback = apiMock.getMockImplementation()
    apiMock.mockImplementation((path, options = {}) => {
      if (path === 'recruitment/jobs/?archived=1') return Promise.reject(new Error('归档服务暂不可用'))
      if (path === 'recruitment/jobs/') return Promise.resolve({ results: [{
        id: 31, boss_account: 1, title: '高级前端工程师', department: '研发中心', headcount: 2,
        status: 'open', updated_at: '2026-08-25T09:00:00Z',
      }] })
      return fallback(path, options)
    })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true, ModelProfileDrawer: true } } })
    await flushPromises()
    await wrapper.get('[data-test="admin-tab-jobs"]').trigger('click')
    await wrapper.get('[data-test="archived-jobs"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('归档职位加载失败')
    expect(wrapper.text()).toContain('重新加载归档职位')
    expect(wrapper.text()).not.toContain('暂无已归档职位')
    const currentButton = wrapper.findAll('.admin-segmented button').find((button) => button.text() === '当前')
    await currentButton.trigger('click')
    expect(wrapper.text()).toContain('高级前端工程师')
    expect(wrapper.text()).not.toContain('归档职位加载失败')
  })

  it('does not hide task lifecycle actions after the twentieth record', async () => {
    baseApi({ ready: true, workerOnline: true })
    const fallback = apiMock.getMockImplementation()
    const manyTasks = Array.from({ length: 21 }, (_, index) => ({
      id: `done-${index + 1}`, boss_account: 1, account_name: account.name,
      action: 'sync_positions', status: 'succeeded', created_at: '2026-08-25T09:00:00Z', events: [],
    }))
    apiMock.mockImplementation((path, options = {}) => {
      if (path === 'recruitment/rpa-tasks/' && !options.method) return Promise.resolve({ results: manyTasks })
      return fallback(path, options)
    })
    wrapper = mount(RecruitmentAdminView, { global: { stubs: { teleport: true, WorkflowCanvas: true, ModelProfileDrawer: true } } })
    await flushPromises()
    await wrapper.get('[data-test="admin-tab-diagnostics"]').trigger('click')

    expect(wrapper.findAll('.admin-table-shell tbody tr')).toHaveLength(21)
    expect(wrapper.text()).toContain('21 条')
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
