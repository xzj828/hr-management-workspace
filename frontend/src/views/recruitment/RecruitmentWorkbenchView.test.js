import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentWorkbenchView from './RecruitmentWorkbenchView.vue'
import { useAuthStore } from '@/stores/auth'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

const readyAccount = {
  id: 7,
  name: '研发招聘账号',
  active: true,
  archived_at: null,
  browser_type: 'edge',
  cdp_port: 53470,
  login_status: 'ready',
  login_status_label: '已登录',
}

function baseApi(path) {
  if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [readyAccount] })
  if (path === 'recruitment/message-sync-policies/') return Promise.resolve({ results: [] })
  if (path === 'recruitment/automation/summary/') return Promise.resolve({
    worker: { hostname: 'WIN-HR', status: 'online' },
    cli_available: true,
  })
  if (path === 'recruitment/job-documents/?job=51') return Promise.resolve({ results: [] })
  if (path === 'recruitment/job-documents/?job=52') return Promise.resolve({ results: [] })
  return Promise.reject(new Error(`unexpected path: ${path}`))
}

async function mountView(query = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/recruitment/workbench', name: 'recruitment-workbench', component: RecruitmentWorkbenchView },
      { path: '/recruitment/results', name: 'recruitment-results', component: { template: '<div>results</div>' } },
      { path: '/recruitment/admin', name: 'recruitment-admin', component: { template: '<div>admin</div>' } },
    ],
  })
  await router.push({ name: 'recruitment-workbench', query })
  await router.isReady()
  const wrapper = mount(RecruitmentWorkbenchView, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

async function goToStandard(wrapper) {
  await wrapper.get('[data-test="complete-context-step"]').trigger('click')
  await flushPromises()
  expect(wrapper.find('[data-test="workbench-step-standard"]').exists()).toBe(true)
}

async function goToPlan(wrapper, { core = '', bonus = '' } = {}) {
  await goToStandard(wrapper)
  if (core) await wrapper.get('[data-test="core-requirements"]').setValue(core)
  if (bonus) await wrapper.get('[data-test="bonus-requirements"]').setValue(bonus)
  await wrapper.get('[data-test="complete-standard-step"]').trigger('click')
  await flushPromises()
  expect(wrapper.find('[data-test="workbench-step-plan"]').exists()).toBe(true)
}

describe('RecruitmentWorkbenchView', () => {
  let wrapper

  beforeEach(() => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.user = { id: 9, username: 'hr', role: 'hr' }
    auth.loading = false
    const context = useRecruitmentContextStore()
    context.jobs = [
      {
        id: 51,
        title: 'Python 后端工程师',
        department: '研发部',
        boss_account: 7,
        account_name: '研发招聘账号',
        status: 'open',
        jd: '负责招聘平台服务端研发',
      },
      {
        id: 52,
        title: '产品经理',
        department: '产品部',
        boss_account: 7,
        account_name: '研发招聘账号',
        status: 'open',
        jd: '负责企业产品规划',
      },
    ]
    context.selectedJobId = '51'
    context.loaded = true
    context.loadedUserId = '9'
    apiMock.mockReset()
    apiMock.mockImplementation(baseApi)
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    localStorage.clear()
    sessionStorage.clear()
  })

  it('presents the three steps as guarded pages with current-step semantics and previous navigation', async () => {
    let router
    ;({ wrapper, router } = await mountView())

    expect(wrapper.get('[data-test="wizard-step-context"]').attributes('aria-current')).toBe('step')
    expect(wrapper.find('[data-test="workbench-step-context"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="workbench-step-standard"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="workbench-step-plan"]').exists()).toBe(false)
    expect(router.currentRoute.value.query.step).toBe('context')

    await goToStandard(wrapper)
    expect(wrapper.get('[data-test="wizard-step-standard"]').attributes('aria-current')).toBe('step')
    expect(router.currentRoute.value.query).toMatchObject({ job: '51', step: 'standard' })
    expect(wrapper.text()).toContain('岗位依据文件')

    await wrapper.get('[data-test="complete-standard-step"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="wizard-step-plan"]').attributes('aria-current')).toBe('step')
    expect(wrapper.text()).toContain('执行前检查')
    expect(wrapper.findAll('button.primary-button')).toHaveLength(1)

    await wrapper.get('[data-test="previous-step"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="workbench-step-standard"]').exists()).toBe(true)
    await wrapper.get('[data-test="previous-step"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="workbench-step-context"]').exists()).toBe(true)
  })

  it('guards direct deep links and does not auto-skip the first step during hydration', async () => {
    let router
    ;({ wrapper, router } = await mountView({ job: '51', step: 'plan' }))

    expect(wrapper.find('[data-test="workbench-step-context"]').exists()).toBe(true)
    expect(router.currentRoute.value.query.step).toBe('context')
  })

  it('persists a versioned non-file draft per user and job and restores it on the plan page', async () => {
    let router
    ;({ wrapper, router } = await mountView())
    await goToPlan(wrapper, { core: '3 年 Python 经验', bonus: 'AI 项目经验' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('Python 后端')
    await flushPromises()

    const key = Object.keys(sessionStorage).find((item) => item.includes('workbench-draft:v1:9:51'))
    expect(key).toBeTruthy()
    expect(sessionStorage.getItem(key)).not.toContain('File')

    wrapper.unmount()
    wrapper = null
    ;({ wrapper, router } = await mountView({ job: '51', step: 'plan' }))
    expect(router.currentRoute.value.query.step).toBe('plan')
    expect(wrapper.get('[data-test="scheme-active"]').element.checked).toBe(true)
    expect(wrapper.get('[data-test="active-keyword"]').element.value).toBe('Python 后端')

    await wrapper.get('[data-test="previous-step"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="core-requirements"]').element.value).toBe('3 年 Python 经验')
    expect(wrapper.get('[data-test="bonus-requirements"]').element.value).toBe('AI 项目经验')
  })

  it('returns to step one and isolates the draft when the job changes', async () => {
    ;({ wrapper } = await mountView())
    await goToStandard(wrapper)
    await wrapper.get('[data-test="core-requirements"]').setValue('只属于职位 51')
    await wrapper.get('[data-test="previous-step"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="workbench-job"]').setValue('52')
    await flushPromises()

    expect(wrapper.find('[data-test="workbench-step-context"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="wizard-step-context"]').attributes('aria-current')).toBe('step')
    await goToStandard(wrapper)
    expect(wrapper.get('[data-test="core-requirements"]').element.value).toBe('')
  })

  it('uploads multiple requirement files sequentially through click selection', async () => {
    let documentReads = 0
    const uploadOrder = []
    apiMock.mockImplementation(async (path, options) => {
      if (path === 'recruitment/job-documents/?job=51') {
        documentReads += 1
        return { results: documentReads > 1 ? [
          { id: 1, title: '候选人画像', category_label: '岗位需求', current_version: { id: 11, version: 1 } },
          { id: 2, title: '岗位要求', category_label: '岗位需求', current_version: { id: 12, version: 1 } },
        ] : [] }
      }
      if (path === 'recruitment/job-documents/' && options?.method === 'POST') {
        uploadOrder.push(options.body.get('title'))
        return { id: uploadOrder.length }
      }
      return baseApi(path)
    })
    ;({ wrapper } = await mountView())
    await goToStandard(wrapper)
    await wrapper.get('[data-test="document-category"]').setValue('requirement')
    const fileInput = wrapper.get('[data-test="workbench-file-input"]')
    Object.defineProperty(fileInput.element, 'files', {
      configurable: true,
      value: [
        new File(['persona'], '候选人画像.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }),
        new File(['requirement'], '岗位要求.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
      ],
    })

    await fileInput.trigger('change')
    await flushPromises()

    expect(uploadOrder).toEqual(['候选人画像', '岗位要求'])
    const uploadCalls = apiMock.mock.calls.filter(([path, options]) => (
      path === 'recruitment/job-documents/' && options?.method === 'POST'
    ))
    expect(uploadCalls).toHaveLength(2)
    expect(uploadCalls[0][1].body.get('job')).toBe('51')
    expect(uploadCalls[0][1].body.get('category')).toBe('requirement')
    expect(wrapper.text()).toContain('候选人画像')
    expect(wrapper.text()).toContain('岗位要求')
    expect(wrapper.text()).toContain('已上传')
  })

  it('supports drag-and-drop validation and keeps per-file partial-failure status', async () => {
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/job-documents/' && options?.method === 'POST') {
        const title = options.body.get('title')
        return title === '失败文件' ? Promise.reject(new Error('服务端拒绝该文件')) : Promise.resolve({ id: 1 })
      }
      return baseApi(path)
    })
    ;({ wrapper } = await mountView())
    await goToStandard(wrapper)
    const empty = new File([], '空文件.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })
    const valid = new File(['valid'], '成功文件.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })
    const failed = new File(['valid'], '失败文件.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    const invalid = new File(['text'], '错误格式.txt', { type: 'text/plain' })

    await wrapper.get('[data-test="workbench-drop-zone"]').trigger('drop', {
      dataTransfer: { files: [valid, failed, invalid, empty] },
    })
    await flushPromises()

    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/job-documents/')).toHaveLength(2)
    expect(wrapper.text()).toContain('成功文件.docx')
    expect(wrapper.text()).toContain('已上传')
    expect(wrapper.text()).toContain('失败文件.xlsx')
    expect(wrapper.text()).toContain('服务端拒绝该文件')
    expect(wrapper.text()).toContain('错误格式.txt')
    expect(wrapper.text()).toContain('仅支持 DOC、DOCX 或 XLSX')
    expect(wrapper.text()).toContain('空文件.docx')
    expect(wrapper.text()).toContain('文件不能为空')
  })

  it('writes active core and bonus criteria into the standard workflow, enables it, then runs it formally', async () => {
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/workflows/standard/' && options?.method === 'POST') {
        return Promise.resolve({ template: { id: 13 }, version: { id: 21 } })
      }
      if (path === 'recruitment/workflow-versions/21/enable/' && options?.method === 'POST') {
        return Promise.resolve({ id: 21, status: 'enabled' })
      }
      if (path === 'recruitment/workflow-versions/21/run/' && options?.method === 'POST') {
        return Promise.resolve({ id: 'run-77', status: 'running' })
      }
      return baseApi(path)
    })
    ;({ wrapper } = await mountView())
    await goToPlan(wrapper, { core: '3 年 Python 经验\n熟悉 Django', bonus: 'AI 项目经验\nToB 经验' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('Python 后端')
    await wrapper.get('[data-test="target-resume-count"]').setValue('5')
    await wrapper.get('[data-test="max-scan-count"]').setValue('30')

    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()

    const standardCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/workflows/standard/')
    expect(JSON.parse(standardCall[1].body)).toEqual({
      kind: 'active_resume_search',
      boss_account: 7,
      config: {
        source: 'search',
        keyword: 'Python 后端',
        target_resume_count: 5,
        max_scan_count: 30,
        core: ['3 年 Python 经验', '熟悉 Django'],
        bonus: ['AI 项目经验', 'ToB 经验'],
      },
    })
    const writePaths = apiMock.mock.calls
      .filter(([, options]) => options?.method === 'POST')
      .map(([path]) => path)
    expect(writePaths).toEqual([
      'recruitment/workflows/standard/',
      'recruitment/workflow-versions/21/enable/',
      'recruitment/workflow-versions/21/run/',
    ])
    const runCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/workflow-versions/21/run/')
    expect(JSON.parse(runCall[1].body)).toMatchObject({
      mode: 'formal',
      job: 51,
      confirm: true,
      input: {
        scheme: 'active_resume_search',
        core: ['3 年 Python 经验', '熟悉 Django'],
        bonus: ['AI 项目经验', 'ToB 经验'],
      },
    })
    expect(wrapper.get('[data-test="execution-receipt"]').text()).toContain('run-77')
    expect(wrapper.get('[data-test="view-results"]').attributes('href')).toContain('/recruitment/results?')
    expect(wrapper.get('[data-test="view-results"]').attributes('href')).toContain('run=run-77')
    expect(wrapper.get('[data-test="view-results"]').attributes('href')).toContain('job=51')
    expect(wrapper.get('[data-test="view-results"]').attributes('href')).toContain('view=tasks')
    expect(wrapper.get('[data-test="start-execution"]').attributes()).toHaveProperty('disabled')

    await wrapper.get('[data-test="start-execution"]').trigger('click')
    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/workflows/standard/')).toHaveLength(1)
    await wrapper.get('[data-test="new-task"]').trigger('click')
    expect(wrapper.get('[data-test="start-execution"]').attributes()).not.toHaveProperty('disabled')
  })

  it('guards the multi-step submission against double clicks', async () => {
    let resolveStandard
    const standardPending = new Promise((resolve) => { resolveStandard = resolve })
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/workflows/standard/' && options?.method === 'POST') return standardPending
      if (path === 'recruitment/workflow-versions/21/enable/' && options?.method === 'POST') return Promise.resolve({ id: 21 })
      if (path === 'recruitment/workflow-versions/21/run/' && options?.method === 'POST') return Promise.resolve({ id: 'run-once', status: 'running' })
      return baseApi(path)
    })
    ;({ wrapper } = await mountView())
    await goToPlan(wrapper, { core: 'Python' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('Python')

    const start = wrapper.get('[data-test="start-execution"]')
    await start.trigger('click')
    await start.trigger('click')
    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/workflows/standard/')).toHaveLength(1)

    resolveStandard({ template: { id: 13 }, version: { id: 21 } })
    await flushPromises()
    expect(wrapper.get('[data-test="execution-receipt"]').text()).toContain('run-once')
  })

  it('blocks execution with an explicit repair path when the isolated browser is stopped', async () => {
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [{
        ...readyAccount,
        login_status: 'browser_stopped',
        login_status_label: '浏览器未启动',
      }] })
      return baseApi(path)
    })
    ;({ wrapper } = await mountView())
    await goToPlan(wrapper)

    expect(wrapper.get('[data-test="start-execution"]').attributes()).toHaveProperty('disabled')
    expect(wrapper.get('[data-test="precheck-browser"]').text()).toContain('隔离浏览器尚未启动')
    expect(wrapper.get('[data-test="precheck-browser"]').text()).toContain('处理')
    expect(wrapper.text()).toContain('请先处理：隔离浏览器')
  })

  it('runs an enabled custom workflow without creating another standard version', async () => {
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/workflows/' && !options?.method) return Promise.resolve({ results: [{ id: 90, name: '研发定向寻访' }] })
      if (path === 'recruitment/workflow-versions/' && !options?.method) return Promise.resolve({ results: [{ id: 91, template: 90, boss_account: 7, version: 4, status: 'enabled' }] })
      if (path === 'recruitment/workflow-versions/91/run/' && options?.method === 'POST') return Promise.resolve({ id: 'run-custom', status: 'running' })
      return baseApi(path)
    })
    ;({ wrapper } = await mountView())
    await goToPlan(wrapper, { core: 'Python' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('Python')
    await wrapper.get('[data-test="workflow-choice"]').setValue('custom:91')

    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()

    expect(apiMock.mock.calls.some(([path]) => path === 'recruitment/workflows/standard/')).toBe(false)
    expect(apiMock.mock.calls.some(([path]) => path === 'recruitment/workflow-versions/91/enable/')).toBe(false)
    expect(wrapper.get('[data-test="execution-receipt"]').text()).toContain('run-custom')
  })

  it('reuses the persisted version and request id when a run response fails and the page is retried', async () => {
    const runRequestIds = []
    let runAttempts = 0
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/workflows/standard/' && options?.method === 'POST') return Promise.resolve({ template: { id: 13 }, version: { id: 21 } })
      if (path === 'recruitment/workflow-versions/21/enable/' && options?.method === 'POST') return Promise.resolve({ id: 21, status: 'enabled' })
      if (path === 'recruitment/workflow-versions/21/run/' && options?.method === 'POST') {
        runAttempts += 1
        runRequestIds.push(JSON.parse(options.body).request_id)
        return runAttempts === 1 ? Promise.reject(new Error('network lost')) : Promise.resolve({ id: 'run-recovered', status: 'running' })
      }
      return baseApi(path)
    })
    ;({ wrapper } = await mountView())
    await goToPlan(wrapper, { core: 'Python' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('Python')

    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('network lost')

    wrapper.unmount()
    wrapper = null
    ;({ wrapper } = await mountView({ job: '51', step: 'plan' }))
    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()

    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/workflows/standard/')).toHaveLength(1)
    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/workflow-versions/21/enable/')).toHaveLength(1)
    expect(runRequestIds).toHaveLength(2)
    expect(runRequestIds[1]).toBe(runRequestIds[0])
    expect(wrapper.get('[data-test="execution-receipt"]').text()).toContain('run-recovered')
  })
})
