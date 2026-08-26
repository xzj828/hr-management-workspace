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

function planFixture({
  state = 'running',
  id = 301,
  job = 51,
  kind = 'active_resume_search',
  controlVersion = 4,
  runId = 'run-77',
  config = {
    source: 'search',
    keyword: 'Python 后端',
    target_resume_count: 5,
    max_scan_count: 30,
    core: ['3 年 Python 经验'],
    bonus: ['AI 项目经验'],
  },
  workflowVersion = null,
  workflowMode,
  isManagedWorkflow,
  revision = 2,
  revisionId = 401,
} = {}) {
  const runStatus = { completed: 'succeeded', stopped: 'cancelled' }[state] || state
  const currentRevision = {
    id: revisionId,
    revision,
    config,
    workflow_version: workflowVersion,
  }
  if (workflowMode !== undefined) currentRevision.workflow_mode = workflowMode
  if (isManagedWorkflow !== undefined) currentRevision.is_managed_workflow = isManagedWorkflow
  return {
    id,
    job,
    kind,
    desired_state: state === 'stopping' ? 'stopped' : state,
    effective_state: state,
    control_version: controlVersion,
    current_revision: currentRevision,
    current_run: runId ? { id: runId, status: runStatus } : null,
  }
}

function baseApi(path) {
  if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [readyAccount] })
  if (path === 'recruitment/automation/summary/') return Promise.resolve({
    worker: { hostname: 'WIN-HR', status: 'online' },
    cli_available: true,
  })
  if (path === 'recruitment/job-documents/?job=51') return Promise.resolve({ results: [] })
  if (path === 'recruitment/job-documents/?job=52') return Promise.resolve({ results: [] })
  if (path === 'recruitment/automation-plans/?job=51') return Promise.resolve({ results: [] })
  if (path === 'recruitment/automation-plans/?job=52') return Promise.resolve({ results: [] })
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
    vi.useRealTimers()
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

    router.back()
    await flushPromises()
    expect(wrapper.find('[data-test="workbench-step-context"]').exists()).toBe(true)
    router.forward()
    await flushPromises()
    expect(wrapper.find('[data-test="workbench-step-standard"]').exists()).toBe(true)

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

  it('rejects an unavailable job query instead of silently restoring another job draft', async () => {
    let router
    ;({ wrapper } = await mountView())
    await goToPlan(wrapper, { core: '职位 51 的草稿', bonus: '职位 51 的加分项' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('原岗位关键词')
    await wrapper.get('[data-test="target-resume-count"]').setValue('8')
    wrapper.unmount()
    wrapper = null

    ;({ wrapper, router } = await mountView({ job: '999', step: 'plan' }))
    expect(wrapper.find('[data-test="workbench-step-context"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="workbench-step-plan"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="workbench-job"]').element.value).toBe('')
    expect(wrapper.text()).toContain('职位 999 已失效、不再开放或无权访问')
    expect(router.currentRoute.value.query.job).toBeUndefined()
    expect(router.currentRoute.value.query.step).toBe('context')

    await wrapper.get('[data-test="workbench-job"]').setValue('51')
    await flushPromises()
    await goToStandard(wrapper)
    expect(wrapper.get('[data-test="core-requirements"]').element.value).toBe('职位 51 的草稿')
    expect(wrapper.get('[data-test="bonus-requirements"]').element.value).toBe('职位 51 的加分项')
    await wrapper.get('[data-test="complete-standard-step"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="scheme-active"]').element.checked).toBe(true)
    expect(wrapper.get('[data-test="active-keyword"]').element.value).toBe('原岗位关键词')
    expect(wrapper.get('[data-test="target-resume-count"]').element.value).toBe('8')
  })

  it('synchronizes a valid job query change and restarts that job at the context step', async () => {
    let router
    ;({ wrapper, router } = await mountView())
    await goToPlan(wrapper, { core: '职位 51 的草稿' })

    await router.push({ name: 'recruitment-workbench', query: { job: '52', step: 'plan' } })
    await flushPromises()

    expect(wrapper.find('[data-test="workbench-step-context"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="workbench-job"]').element.value).toBe('52')
    expect(router.currentRoute.value.query).toMatchObject({ job: '52', step: 'context' })
    await goToStandard(wrapper)
    expect(wrapper.get('[data-test="core-requirements"]').element.value).toBe('')
  })

  it('normalizes an invalid step to context with an explanation even when plan was restored', async () => {
    let router
    ;({ wrapper, router } = await mountView())
    await goToPlan(wrapper, { core: '已完成标准' })

    await router.push({ name: 'recruitment-workbench', query: { job: '51', step: 'unknown-step' } })
    await flushPromises()

    expect(wrapper.find('[data-test="workbench-step-context"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="workbench-step-plan"]').exists()).toBe(false)
    expect(router.currentRoute.value.query.step).toBe('context')
    expect(wrapper.text()).toContain('步骤参数无效，已安全返回第一步')
  })

  it('continues to the next step when session storage rejects draft writes', async () => {
    ;({ wrapper } = await mountView())
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('storage blocked', 'SecurityError')
    })

    try {
      await wrapper.get('[data-test="complete-context-step"]').trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-test="workbench-step-standard"]').exists()).toBe(true)
      expect(wrapper.text()).toContain('浏览器临时存储不可用')
    } finally {
      setItem.mockRestore()
    }
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

  it('removes a schema-invalid wizard draft and never treats a legacy operation receipt as truth', async () => {
    const wizardKey = 'ximing-hr:recruitment-workbench-draft:v1:9:51'
    const operationKey = 'ximing-hr:recruitment-operation:9:51'
    sessionStorage.setItem(wizardKey, JSON.stringify({
      version: 1,
      jobId: '51',
      step: 'plan',
      completed: { context: true, standard: true },
      documentCategory: 'persona',
      draft: { schemeKind: 'active_resume_search' },
    }))
    sessionStorage.setItem(operationKey, JSON.stringify({
      jobId: 51,
      fingerprint: 'stored-operation',
      requestId: '11111111-1111-4111-8111-111111111111',
      versionId: 21,
      enabledId: 21,
      receipt: null,
      draft: {
        schemeKind: 'active_resume_search',
        workflowChoice: 'standard',
        coreText: '来自可恢复的执行草稿',
        bonusText: '执行草稿加分项',
        interval: 2,
        source: 'search',
        keyword: 'Python',
        targetResumeCount: 4,
        maxScanCount: 20,
      },
    }))
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem')

    try {
      ;({ wrapper } = await mountView({ job: '51', step: 'context' }))
      expect(removeItem).toHaveBeenCalledWith(wizardKey)
      await goToStandard(wrapper)
      expect(wrapper.get('[data-test="core-requirements"]').element.value).toBe('')
      expect(wrapper.get('[data-test="bonus-requirements"]').element.value).toBe('')
    } finally {
      removeItem.mockRestore()
    }
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

  it('keeps the original job selected when the route changes during an upload', async () => {
    let router
    let resolveUpload
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/job-documents/' && options?.method === 'POST') {
        return new Promise((resolve) => { resolveUpload = resolve })
      }
      return baseApi(path)
    })
    ;({ wrapper, router } = await mountView())
    await goToStandard(wrapper)
    const input = wrapper.get('[data-test="workbench-file-input"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['persona'], '画像.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })],
    })
    await input.trigger('change')
    await flushPromises()

    await router.push({ name: 'recruitment-workbench', query: { job: '52', step: 'context' } })
    await flushPromises()
    expect(useRecruitmentContextStore().selectedJobId).toBe('51')
    expect(router.currentRoute.value.query).toMatchObject({ job: '51', step: 'standard' })

    resolveUpload({ id: 1 })
    await flushPromises()
    const uploadCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/job-documents/')
    expect(uploadCall[1].body.get('job')).toBe('51')
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
    const oversized = new File(['large'], '超大文件.doc', { type: 'application/msword' })
    Object.defineProperty(oversized, 'size', { value: 25 * 1024 * 1024 + 1 })

    await wrapper.get('[data-test="workbench-drop-zone"]').trigger('drop', {
      dataTransfer: { files: [valid, failed, invalid, empty, oversized] },
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
    expect(wrapper.text()).toContain('超大文件.doc')
    expect(wrapper.text()).toContain('单个文件不能超过 25MB')
  })

  it('starts an active search with one atomic command containing the complete revision config', async () => {
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') return Promise.resolve(planFixture())
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

    const startCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/automation-plans/start/')
    const command = JSON.parse(startCall[1].body)
    expect(command).toMatchObject({
      request_id: expect.any(String),
      job: 51,
      kind: 'active_resume_search',
      expected_control_version: 0,
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
    expect(writePaths).toEqual(['recruitment/automation-plans/start/'])
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('运行中')
    expect(wrapper.get('[data-test="operation-results"]').attributes('href')).toContain('run=run-77')
    expect(wrapper.find('[data-test="start-execution"]').exists()).toBe(false)
  })

  it('guards the atomic start command against double clicks', async () => {
    let resolveStart
    const startPending = new Promise((resolve) => { resolveStart = resolve })
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') return startPending
      return baseApi(path)
    })
    ;({ wrapper } = await mountView())
    await goToPlan(wrapper, { core: 'Python' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('Python')

    const start = wrapper.get('[data-test="start-execution"]')
    await start.trigger('click')
    await start.trigger('click')
    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/automation-plans/start/')).toHaveLength(1)

    resolveStart(planFixture({ runId: 'run-once' }))
    await flushPromises()
    expect(wrapper.get('[data-test="operation-control"]').text()).toContain('run-once')
  })

  it('freezes the atomic start snapshot and rejects a job route change while it is pending', async () => {
    let router
    let resolveStart
    const startPending = new Promise((resolve) => { resolveStart = resolve })
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') return startPending
      return baseApi(path)
    })
    ;({ wrapper, router } = await mountView())
    await goToPlan(wrapper, { core: '原始核心要求', bonus: '原始加分项' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('原始关键词')
    await wrapper.get('[data-test="target-resume-count"]').setValue('6')
    await wrapper.get('[data-test="max-scan-count"]').setValue('30')

    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="active-keyword"]').setValue('等待期间被修改')
    await wrapper.get('[data-test="scheme-passive"]').setValue(true)
    await router.push({ name: 'recruitment-workbench', query: { job: '52', step: 'context' } })
    await flushPromises()

    expect(useRecruitmentContextStore().selectedJobId).toBe('51')
    expect(router.currentRoute.value.query).toMatchObject({ job: '51', step: 'plan' })
    expect(wrapper.text()).toContain('任务处理中，暂不能切换职位')

    const startCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/automation-plans/start/')
    expect(JSON.parse(startCall[1].body)).toMatchObject({
      job: 51,
      kind: 'active_resume_search',
      config: {
        keyword: '原始关键词',
        target_resume_count: 6,
        max_scan_count: 30,
        core: ['原始核心要求'],
        bonus: ['原始加分项'],
      },
    })

    resolveStart(planFixture({ runId: 'run-snapshot' }))
    await flushPromises()
    expect(wrapper.get('[data-test="operation-control"]').text()).toContain('run-snapshot')
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

  it('passes an enabled custom workflow to the same atomic start command', async () => {
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/workflows/' && !options?.method) return Promise.resolve({ results: [{ id: 90, name: '研发定向寻访' }] })
      if (path === 'recruitment/workflow-versions/' && !options?.method) return Promise.resolve({ results: [{ id: 91, template: 90, boss_account: 7, version: 4, status: 'enabled' }] })
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') {
        return Promise.resolve(planFixture({ runId: 'run-custom', workflowVersion: 91 }))
      }
      return baseApi(path)
    })
    ;({ wrapper } = await mountView())
    await goToPlan(wrapper, { core: 'Python' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('Python')
    await wrapper.get('[data-test="workflow-choice"]').setValue('custom:91')

    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()

    const startCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/automation-plans/start/')
    expect(JSON.parse(startCall[1].body)).toMatchObject({ workflow_version: 91 })
    expect(apiMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
    expect(wrapper.get('[data-test="operation-control"]').text()).toContain('run-custom')
  })

  it('restores a managed standard revision as editable config without reusing its old workflow graph', async () => {
    const managed = planFixture({
      state: 'stopped',
      workflowVersion: 91,
      workflowMode: 'managed',
    })
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') return Promise.resolve({ results: [managed] })
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') {
        return Promise.resolve(planFixture({ state: 'running', revision: 3, revisionId: 402 }))
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51' }))
    expect(wrapper.get('[data-test="workflow-choice"]').element.value).toBe('standard')
    expect(wrapper.text()).not.toContain('当前任务使用的高级流程')
    await wrapper.get('[data-test="modify-operation"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="core-requirements"]').setValue('修改后的托管标准')
    await wrapper.get('[data-test="complete-standard-step"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="restart-operation"]').trigger('click')
    await flushPromises()

    const startBody = JSON.parse(apiMock.mock.calls.find(([path]) => path === 'recruitment/automation-plans/start/')[1].body)
    expect(startBody.config.core).toEqual(['修改后的托管标准'])
    expect(startBody).not.toHaveProperty('workflow_version')
  })

  it('restores an explicitly custom revision and keeps its workflow version on restart', async () => {
    const custom = planFixture({
      state: 'stopped',
      workflowVersion: 91,
      isManagedWorkflow: false,
    })
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') return Promise.resolve({ results: [custom] })
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') {
        return Promise.resolve(planFixture({ state: 'running', workflowVersion: 91, isManagedWorkflow: false }))
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51' }))
    expect(wrapper.get('[data-test="workflow-choice"]').element.value).toBe('custom:91')
    expect(wrapper.text()).toContain('当前任务使用的高级流程')
    await wrapper.get('[data-test="restart-operation"]').trigger('click')
    await flushPromises()

    const startBody = JSON.parse(apiMock.mock.calls.find(([path]) => path === 'recruitment/automation-plans/start/')[1].body)
    expect(startBody.workflow_version).toBe(91)
  })

  it('excludes plan-managed enabled versions and fallback while keeping genuine custom choices', async () => {
    const plan = planFixture({
      state: 'stopped',
      workflowVersion: { id: 91 },
      workflowMode: 'custom',
    })
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/automation-plans/?job=51') return Promise.resolve({ results: [plan] })
      if (path === 'recruitment/workflows/') return Promise.resolve({ results: [
        { id: 90, name: '系统托管标准图', is_plan_managed: true },
        { id: 92, name: 'HR 自定义图', is_plan_managed: false },
      ] })
      if (path === 'recruitment/workflow-versions/') return Promise.resolve({ results: [
        { id: 91, template: 90, boss_account: 7, version: 2, status: 'enabled' },
        { id: 93, template: 92, boss_account: 7, version: 1, status: 'enabled', is_plan_managed: false },
      ] })
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51' }))
    const choice = wrapper.get('[data-test="workflow-choice"]')
    const values = choice.findAll('option').map((option) => option.attributes('value'))
    expect(values).toEqual(['standard', 'custom:93'])
    expect(choice.element.value).toBe('standard')
    expect(wrapper.text()).not.toContain('当前任务使用的高级流程')

    await choice.setValue('custom:93')
    expect(choice.element.value).toBe('custom:93')
    expect(wrapper.get('[data-test="precheck-scheme"]').text()).toContain('HR 自定义图 · V1')
  })

  it('keeps edited draft criteria across remount after an atomic start failure', async () => {
    const requestIds = []
    let startAttempts = 0
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') {
        startAttempts += 1
        requestIds.push(JSON.parse(options.body).request_id)
        return startAttempts === 1
          ? Promise.reject(new Error('network lost'))
          : Promise.resolve(planFixture({ runId: 'run-new-draft' }))
      }
      return baseApi(path)
    })
    ;({ wrapper } = await mountView())
    await goToPlan(wrapper, { core: '旧核心要求', bonus: '旧加分项' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('Python')
    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('network lost')

    await wrapper.get('[data-test="previous-step"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="core-requirements"]').setValue('更新后的核心要求')
    await wrapper.get('[data-test="bonus-requirements"]').setValue('更新后的加分项')
    wrapper.unmount()
    wrapper = null

    ;({ wrapper } = await mountView({ job: '51', step: 'standard' }))
    expect(wrapper.get('[data-test="core-requirements"]').element.value).toBe('更新后的核心要求')
    expect(wrapper.get('[data-test="bonus-requirements"]').element.value).toBe('更新后的加分项')
    await wrapper.get('[data-test="complete-standard-step"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()

    const startCalls = apiMock.mock.calls.filter(([path]) => path === 'recruitment/automation-plans/start/')
    expect(startCalls).toHaveLength(2)
    expect(JSON.parse(startCalls[1][1].body).config).toMatchObject({
      core: ['更新后的核心要求'],
      bonus: ['更新后的加分项'],
    })
    expect(requestIds[1]).not.toBe(requestIds[0])
    expect(wrapper.get('[data-test="operation-control"]').text()).toContain('run-new-draft')
  })

  it('reuses an in-memory idempotency key when the same atomic command is retried', async () => {
    const requestIds = []
    let startAttempts = 0
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') {
        startAttempts += 1
        requestIds.push(JSON.parse(options.body).request_id)
        return startAttempts === 1
          ? Promise.reject(new Error('network lost'))
          : Promise.resolve(planFixture({ runId: 'run-recovered' }))
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

    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()

    expect(requestIds).toHaveLength(2)
    expect(requestIds[1]).toBe(requestIds[0])
    expect(wrapper.get('[data-test="operation-control"]').text()).toContain('run-recovered')
  })

  it('loads a running plan from the server and stops it with optimistic concurrency', async () => {
    const running = planFixture()
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') return Promise.resolve({ results: [running] })
      if (path === 'recruitment/automation-plans/301/stop/' && options?.method === 'POST') {
        return Promise.resolve(planFixture({ state: 'stopping', controlVersion: 5 }))
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51' }))
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('运行中')
    expect(wrapper.find('[data-test="start-execution"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="stop-and-modify-operation"]').exists()).toBe(true)

    await wrapper.get('[data-test="stop-operation"]').trigger('click')
    await flushPromises()

    const stopCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/automation-plans/301/stop/')
    expect(JSON.parse(stopCall[1].body)).toMatchObject({
      request_id: expect.any(String),
      expected_control_version: 4,
    })
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('正在停止')
    expect(wrapper.text()).toContain('安全收尾')
  })

  it('stops before editing and preserves the current per-job draft on step two', async () => {
    sessionStorage.setItem('ximing-hr:recruitment-workbench-draft:v1:9:51', JSON.stringify({
      version: 1,
      jobId: '51',
      selectedAccountId: '7',
      step: 'plan',
      completed: { context: true, standard: true },
      documentCategory: 'persona',
      draft: {
        schemeKind: 'active_resume_search',
        workflowChoice: 'standard',
        coreText: 'HR 尚未提交的修改',
        bonusText: '本地加分项',
        interval: 2,
        source: 'search',
        keyword: 'Python',
        targetResumeCount: 4,
        maxScanCount: 20,
      },
    }))
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') return Promise.resolve({ results: [planFixture()] })
      if (path === 'recruitment/automation-plans/301/stop/' && options?.method === 'POST') {
        return Promise.resolve(planFixture({ state: 'stopping', controlVersion: 5 }))
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51', step: 'plan' }))
    await wrapper.get('[data-test="stop-and-modify-operation"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="workbench-step-standard"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="core-requirements"]').element.value).toBe('HR 尚未提交的修改')
    expect(wrapper.get('[data-test="bonus-requirements"]').element.value).toBe('本地加分项')
    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/automation-plans/301/stop/')).toHaveLength(1)
  })

  it('resumes a paused plan and refreshes a 409 conflict to the latest server state', async () => {
    let planReads = 0
    const conflict = Object.assign(new Error('version conflict'), { status: 409 })
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') {
        planReads += 1
        return Promise.resolve({ results: [planFixture({ state: planReads === 1 ? 'running' : 'paused', controlVersion: 5 })] })
      }
      if (path === 'recruitment/automation-plans/301/stop/' && options?.method === 'POST') return Promise.reject(conflict)
      if (path === 'recruitment/automation-plans/301/resume/' && options?.method === 'POST') {
        return Promise.resolve(planFixture({ state: 'running', controlVersion: 6 }))
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51' }))
    await wrapper.get('[data-test="stop-operation"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('已暂停')
    expect(wrapper.text()).toContain('已为你刷新')

    await wrapper.get('[data-test="resume-operation"]').trigger('click')
    await flushPromises()
    const resumeCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/automation-plans/301/resume/')
    expect(JSON.parse(resumeCall[1].body).expected_control_version).toBe(5)
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('运行中')
  })

  it('restarts a terminal plan as a new revision with its latest control version', async () => {
    const stopped = planFixture({
      state: 'stopped',
      kind: 'passive_resume',
      config: { interval_minutes: 5, reply_message: '请发送简历', core: [], bonus: [] },
    })
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') return Promise.resolve({ results: [stopped] })
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') {
        return Promise.resolve(planFixture({ kind: 'passive_resume', controlVersion: 5 }))
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51' }))
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('已停止')
    await wrapper.get('[data-test="restart-operation"]').trigger('click')
    await flushPromises()

    const startCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/automation-plans/start/')
    expect(JSON.parse(startCall[1].body)).toMatchObject({
      kind: 'passive_resume',
      expected_control_version: 4,
      config: { interval_minutes: 5 },
    })
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('运行中')
  })

  it('keeps the restored edit baseline when polling discovers a newer server revision', async () => {
    const draftKey = 'ximing-hr:recruitment-workbench-draft:v1:9:51'
    sessionStorage.setItem(draftKey, JSON.stringify({
      version: 1,
      jobId: '51',
      selectedAccountId: '7',
      step: 'plan',
      completed: { context: true, standard: true },
      documentCategory: 'persona',
      draft: {
        schemeKind: 'active_resume_search',
        workflowChoice: 'standard',
        coreText: 'A 基于 V2 的修改',
        bonusText: '',
        interval: 2,
        source: 'search',
        keyword: 'Python',
        targetResumeCount: 4,
        maxScanCount: 20,
      },
      editBase: {
        jobId: '51',
        controlVersion: 4,
        revisionId: 401,
        revision: 2,
      },
    }))
    const latest = planFixture({ state: 'stopped', controlVersion: 5, revision: 3, revisionId: 402 })
    const startBodies = []
    let startAttempts = 0
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') return Promise.resolve({ results: [latest] })
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') {
        startAttempts += 1
        startBodies.push(JSON.parse(options.body))
        if (startAttempts === 1) return Promise.reject(Object.assign(new Error('version conflict'), { status: 409 }))
        return Promise.resolve(planFixture({ state: 'running', controlVersion: 6, revision: 4, revisionId: 403 }))
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51', step: 'plan' }))
    expect(wrapper.get('[data-test="plan-version-notice"]').text()).toContain('V2 更新为 V3')
    await wrapper.get('[data-test="restart-operation"]').trigger('click')
    await flushPromises()

    expect(startBodies[0].expected_control_version).toBe(4)
    expect(wrapper.text()).toContain('已为你刷新')
    expect(wrapper.get('[data-test="plan-version-notice"]').text()).toContain('当前草稿仍基于原版本')

    await wrapper.get('[data-test="rebase-edit-draft"]').trigger('click')
    expect(wrapper.find('[data-test="plan-version-notice"]').exists()).toBe(false)
    await wrapper.get('[data-test="restart-operation"]').trigger('click')
    await flushPromises()
    expect(startBodies[1].expected_control_version).toBe(5)
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('运行中')
  })

  it('invalidates a pending stop-and-modify response when the workbench unmounts', async () => {
    let router
    let resolveStop
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') return Promise.resolve({ results: [planFixture()] })
      if (path === 'recruitment/automation-plans/301/stop/' && options?.method === 'POST') {
        return new Promise((resolve) => { resolveStop = resolve })
      }
      return baseApi(path)
    })

    ;({ wrapper, router } = await mountView({ job: '51', step: 'plan' }))
    const push = vi.spyOn(router, 'push')
    await wrapper.get('[data-test="stop-and-modify-operation"]').trigger('click')
    await flushPromises()
    push.mockClear()
    wrapper.unmount()
    wrapper = null

    resolveStop(planFixture({ state: 'stopping', controlVersion: 5 }))
    await flushPromises()
    expect(push).not.toHaveBeenCalled()
    push.mockRestore()
  })

  it('disables terminal restart when status polling failed and reenables it after refresh', async () => {
    vi.useFakeTimers()
    let planReads = 0
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') {
        planReads += 1
        if (planReads === 2) return Promise.reject(new Error('status offline'))
        return Promise.resolve({ results: [planFixture({ state: 'stopped', controlVersion: 4 })] })
      }
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') {
        return Promise.resolve(planFixture())
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51' }))
    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(wrapper.get('[data-test="restart-operation"]').attributes()).toHaveProperty('disabled')
    expect(wrapper.text()).toContain('任务状态同步失败，请等待自动刷新后再试')
    await wrapper.get('[data-test="restart-operation"]').trigger('click')
    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/automation-plans/start/')).toHaveLength(0)

    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(wrapper.get('[data-test="restart-operation"]').attributes()).not.toHaveProperty('disabled')
  })

  it('does not let an older poll overwrite a newer stop response', async () => {
    vi.useFakeTimers()
    let planReads = 0
    let resolveStalePoll
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') {
        planReads += 1
        if (planReads === 2) return new Promise((resolve) => { resolveStalePoll = resolve })
        return Promise.resolve({ results: [planFixture()] })
      }
      if (path === 'recruitment/automation-plans/301/stop/' && options?.method === 'POST') {
        return Promise.resolve(planFixture({ state: 'stopping', controlVersion: 5 }))
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51' }))
    vi.advanceTimersByTime(5000)
    await flushPromises()
    await wrapper.get('[data-test="stop-operation"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('正在停止')

    resolveStalePoll({ results: [planFixture({ state: 'running', controlVersion: 4 })] })
    await flushPromises()
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('正在停止')
  })

  it('does not let an older terminal poll overwrite a newer restart response', async () => {
    vi.useFakeTimers()
    let planReads = 0
    let resolveStalePoll
    const stopped = planFixture({ state: 'stopped' })
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') {
        planReads += 1
        if (planReads === 2) return new Promise((resolve) => { resolveStalePoll = resolve })
        return Promise.resolve({ results: [stopped] })
      }
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') {
        return Promise.resolve(planFixture({ state: 'running', controlVersion: 5, runId: 'run-restarted' }))
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51' }))
    vi.advanceTimersByTime(5000)
    await flushPromises()
    await wrapper.get('[data-test="restart-operation"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('运行中')

    resolveStalePoll({ results: [stopped] })
    await flushPromises()
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('运行中')
    expect(wrapper.get('[data-test="operation-control"]').text()).toContain('run-restarted')
  })

  it('polls every five seconds without overlapping an unfinished status request', async () => {
    vi.useFakeTimers()
    let planReads = 0
    let resolvePoll
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/automation-plans/?job=51') {
        planReads += 1
        if (planReads === 2) return new Promise((resolve) => { resolvePoll = resolve })
        return Promise.resolve({ results: [planFixture({ controlVersion: planReads + 3 })] })
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51' }))
    expect(planReads).toBe(1)
    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(planReads).toBe(2)
    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(planReads).toBe(2)

    resolvePoll({ results: [planFixture({ controlVersion: 5 })] })
    await flushPromises()
    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(planReads).toBe(3)
  })
})
