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
  jobTitle = 'Python 后端工程师',
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
  controlGeneration = 6,
  updatedAt = '2026-08-27T09:30:00+08:00',
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
    job_title: jobTitle,
    kind,
    desired_state: state === 'stopping' ? 'stopped' : state,
    effective_state: state,
    control_version: controlVersion,
    control_generation: controlGeneration,
    current_revision: currentRevision,
    current_run: runId ? { id: runId, status: runStatus } : null,
    updated_at: updatedAt,
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
  if (path === 'recruitment/job-standards/?job=51') return Promise.resolve({ results: [{ id: 61, version: 1, status: 'published' }] })
  if (path === 'recruitment/job-standards/?job=52') return Promise.resolve({ results: [{ id: 62, version: 1, status: 'published' }] })
  if (path === 'recruitment/automation-plans/?job=51') return Promise.resolve({ results: [] })
  if (path === 'recruitment/automation-plans/?job=52') return Promise.resolve({ results: [] })
  if (path === 'recruitment/automation-plans/?job=51&archived=1') return Promise.resolve({ results: [] })
  if (path === 'recruitment/automation-plans/?job=52&archived=1') return Promise.resolve({ results: [] })
  if (path.startsWith('recruitment/automation-approvals/?')) return Promise.resolve({ results: [] })
  return Promise.reject(new Error(`unexpected path: ${path}`))
}

async function mountView(query = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/recruitment/workbench', name: 'recruitment-workbench', component: RecruitmentWorkbenchView },
      { path: '/recruitment/results', name: 'recruitment-results', component: { template: '<div>results</div>' } },
      { path: '/recruitment/details/resumes', name: 'recruitment-resumes', component: { template: '<div>resumes</div>' } },
      { path: '/recruitment/tasks', name: 'recruitment-tasks', component: { template: '<div>tasks</div>' } },
      { path: '/recruitment/tasks/:planId', name: 'recruitment-task-detail', component: { template: '<div>task detail</div>' } },
      { path: '/recruitment/admin', name: 'recruitment-admin', component: { template: '<div>admin</div>' } },
    ],
  })
  await router.push({ name: 'recruitment-workbench', query })
  await router.isReady()
  const wrapper = mount(RecruitmentWorkbenchView, {
    global: {
      plugins: [router],
      stubs: { Teleport: true },
    },
  })
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

async function completePlanAndReview(wrapper) {
  await wrapper.get('[data-test="complete-plan-step"]').trigger('click')
  await flushPromises()
  expect(wrapper.find('[data-test="workbench-step-review"]').exists()).toBe(true)
}

async function goToReview(wrapper, options = {}) {
  await goToPlan(wrapper, options)
  await completePlanAndReview(wrapper)
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

  it('keeps executed task cards out of the workbench', async () => {
    ;({ wrapper } = await mountView({ new: '1' }))

    expect(wrapper.find('[data-test="workspace-task-entry"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="operation-control"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="resume-approval-inbox"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="workbench-step-context"]').exists()).toBe(true)
  })

  it('presents four guarded configuration pages and leaves execution controls to the result task page', async () => {
    let router
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') return Promise.resolve(planFixture())
      return baseApi(path)
    })
    ;({ wrapper, router } = await mountView())

    expect(wrapper.get('[data-test="wizard-step-context"]').attributes('aria-current')).toBe('step')
    expect(wrapper.find('[data-test="workbench-step-context"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="workbench-step-standard"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="workbench-step-plan"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="workbench-step-review"]').exists()).toBe(false)
    expect(router.currentRoute.value.query.step).toBe('context')
    expect(wrapper.text()).not.toContain('完成上一步后开放')
    expect(wrapper.text()).not.toContain('已归档职位描述')
    expect(wrapper.text()).not.toContain('自动化服务已就绪')
    expect(wrapper.text()).not.toContain('确认职位与执行账号后')

    await goToStandard(wrapper)
    expect(wrapper.get('[data-test="wizard-step-standard"]').attributes('aria-current')).toBe('step')
    expect(router.currentRoute.value.query).toMatchObject({ job: '51', step: 'standard' })
    expect(wrapper.text()).toContain('岗位参考资料')

    router.back()
    await flushPromises()
    expect(wrapper.find('[data-test="workbench-step-context"]').exists()).toBe(true)
    router.forward()
    await flushPromises()
    expect(wrapper.find('[data-test="workbench-step-standard"]').exists()).toBe(true)

    await wrapper.get('[data-test="complete-standard-step"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="wizard-step-plan"]').attributes('aria-current')).toBe('step')
    expect(wrapper.find('.workbench-review').exists()).toBe(false)
    expect(wrapper.find('[data-test="start-execution"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="precheck-job"]').exists()).toBe(false)
    expect(wrapper.findAll('button.primary-button')).toHaveLength(1)

    const writesBeforeReview = apiMock.mock.calls.filter(([, options]) => options?.method === 'POST').length
    await completePlanAndReview(wrapper)
    expect(wrapper.get('[data-test="wizard-step-review"]').attributes('aria-current')).toBe('step')
    expect(router.currentRoute.value.name).toBe('recruitment-tasks')
    expect(wrapper.find('.workbench-review').exists()).toBe(true)
    expect(wrapper.find('[data-test="operation-control"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="workspace-task-entry"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="precheck-job"]').exists()).toBe(true)
    expect(apiMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(writesBeforeReview + 1)
  })

  it('resets the persistent work area for every newly selected step', async () => {
    ;({ wrapper } = await mountView())
    expect(wrapper.findAll('.workbench-wizard__step')).toHaveLength(4)
    await goToStandard(wrapper)
    const main = wrapper.get('.workbench-main')
    const mainElement = main.element

    mainElement.scrollTop = 180
    await wrapper.get('[data-test="complete-standard-step"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('.workbench-main').element).toBe(mainElement)
    expect(mainElement.scrollTop).toBe(0)

    mainElement.scrollTop = 240
    await wrapper.get('[data-test="complete-plan-step"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="workbench-step-review"]').exists()).toBe(true)
    expect(wrapper.findAll('.workbench-checks > li')).toHaveLength(7)
    expect(mainElement.scrollTop).toBe(0)

    mainElement.scrollTop = 120
    await wrapper.get('[data-test="wizard-step-standard"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="workbench-step-standard"]').exists()).toBe(true)
    expect(mainElement.scrollTop).toBe(0)
  })

  it('guards direct review deep links and does not auto-skip incomplete prerequisite steps during hydration', async () => {
    let router
    ;({ wrapper, router } = await mountView({ job: '51', step: 'review' }))

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
    await wrapper.get('[data-test="candidate-filter-trigger"]').trigger('click')
    await wrapper.get('[data-test="filter-gender-female"]').trigger('click')
    await wrapper.get('[data-test="filter-school-211"]').trigger('click')
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
    await wrapper.get('[data-test="candidate-filter-trigger"]').trigger('click')
    expect(wrapper.get('[data-test="filter-gender-female"]').classes()).toContain('is-selected')
    expect(wrapper.get('[data-test="filter-school-211"]').classes()).toContain('is-selected')

    await wrapper.get('[data-test="previous-step"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="core-requirements"]').element.value).toBe('3 年 Python 经验')
    expect(wrapper.get('[data-test="bonus-requirements"]').element.value).toBe('AI 项目经验')
  })

  it('restores a legacy three-step draft without completed.plan and gates review until plan is completed', async () => {
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
        coreText: '旧草稿核心要求',
        bonusText: '',
        interval: 2,
        source: 'search',
        keyword: 'Python',
        targetResumeCount: 4,
        maxScanCount: 20,
      },
    }))

    let router
    ;({ wrapper, router } = await mountView({ job: '51', step: 'review' }))

    expect(router.currentRoute.value.query.step).toBe('plan')
    expect(wrapper.find('[data-test="workbench-step-plan"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="workbench-step-review"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="start-execution"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="active-keyword"]').element.value).toBe('Python')

    await completePlanAndReview(wrapper)
    expect(router.currentRoute.value.query.step).toBe('review')
    expect(wrapper.find('[data-test="start-execution"]').exists()).toBe(true)
  })
  it('does not auto-start when a completed review step is restored by a refresh or deep link', async () => {
    sessionStorage.setItem('ximing-hr:recruitment-workbench-draft:v1:9:51', JSON.stringify({
      version: 1,
      jobId: '51',
      selectedAccountId: '7',
      step: 'review',
      completed: { context: true, standard: true, plan: true },
      documentCategory: 'persona',
      draft: {
        schemeKind: 'active_resume_search',
        workflowChoice: 'standard',
        coreText: '刷新后保留的核心要求',
        bonusText: '',
        interval: 2,
        source: 'search',
        keyword: 'Python',
        targetResumeCount: 4,
        maxScanCount: 20,
      },
    }))

    ;({ wrapper } = await mountView({ job: '51', step: 'review' }))

    expect(wrapper.find('[data-test="workbench-step-review"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="start-execution"]').exists()).toBe(true)
    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/automation-plans/start/')).toHaveLength(0)
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

  it('hides the file-purpose selector and uploads reference files with the fixed compatibility category', async () => {
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
    expect(wrapper.find('[data-test="document-category"]').exists()).toBe(false)
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
    expect(uploadCalls[0][1].body.get('category')).toBe('persona')
    expect(uploadCalls[1][1].body.get('category')).toBe('persona')
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

  it('automatically starts an active search with one atomic command after prechecks pass', async () => {
    let router
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') return Promise.resolve(planFixture())
      return baseApi(path)
    })
    ;({ wrapper, router } = await mountView())
    await goToPlan(wrapper, { core: '3 年 Python 经验\n熟悉 Django', bonus: 'AI 项目经验\nToB 经验' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('Python 后端')
    await wrapper.get('[data-test="candidate-filter-trigger"]').trigger('click')
    await wrapper.get('[data-test="filter-activity-today"]').trigger('click')
    await wrapper.get('[data-test="filter-keyword-data_analysis"]').trigger('click')
    await wrapper.get('[data-test="target-resume-count"]').setValue('5')
    await wrapper.get('[data-test="max-scan-count"]').setValue('30')
    expect(wrapper.get('[data-test="complete-plan-step"]').text()).toContain('检查并开始执行')
    await completePlanAndReview(wrapper)
    expect(wrapper.text()).toContain('点击开始执行即授权本方案按冻结条件搜索，并最多查看 30 份在线简历')
    expect(wrapper.text()).toContain('后续不再重复确认')

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
        candidate_filters: {
          activity: 'today',
          talent_keywords: ['data_analysis'],
        },
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
    expect(router.currentRoute.value.name).toBe('recruitment-tasks')
    expect(router.currentRoute.value.params).toEqual({})
    expect(router.currentRoute.value.query).toEqual({})
    expect(wrapper.find('[data-test="operation-control"]').exists()).toBe(false)
    expect(sessionStorage.getItem('ximing-hr:recruitment-workbench-draft:v1:9:51')).toBeNull()
    expect(sessionStorage.getItem('ximing-hr:recruitment-workbench-reset:v1:9')).not.toBeNull()

    wrapper.unmount()
    wrapper = null
    ;({ wrapper, router } = await mountView({ job: '51' }))
    expect(sessionStorage.getItem('ximing-hr:recruitment-workbench-reset:v1:9')).toBeNull()
    expect(router.currentRoute.value.query).toMatchObject({ new: '1', step: 'context' })
    expect(router.currentRoute.value.query.job).toBeUndefined()
    expect(useRecruitmentContextStore().selectedJobId).toBe('')
    expect(wrapper.get('[data-test="workbench-job"]').element.value).toBe('')
  })

  it('uses workbench manual requirements without a separately published scoring standard', async () => {
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/job-standards/?job=51') return Promise.resolve({ results: [] })
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') return Promise.resolve(planFixture())
      return baseApi(path)
    })
    ;({ wrapper } = await mountView())
    await goToPlan(wrapper, { core: '3 年 Python 经验' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('Python 后端')
    await completePlanAndReview(wrapper)

    const startCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/automation-plans/start/')
    expect(JSON.parse(startCall[1].body).config.core).toEqual(['3 年 Python 经验'])
    expect(wrapper.text()).not.toContain('主动寻访需要先发布岗位评分标准')
  })

  it('waits for an uploaded Word or Excel standard to finish generating without asking for another upload', async () => {
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/job-documents/?job=51') {
        return Promise.resolve({ results: [{
          id: 71,
          title: '岗位标准',
          category_label: '岗位需求',
          current_version: { id: 72, version: 1 },
        }] })
      }
      if (path === 'recruitment/job-standards/?job=51') return Promise.resolve({ results: [] })
      return baseApi(path)
    })
    ;({ wrapper } = await mountView())
    await goToPlan(wrapper)
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('Python 后端')
    await completePlanAndReview(wrapper)

    expect(wrapper.text()).toContain('上传的 Word/Excel 正在生成标准')
    expect(wrapper.text()).toContain('不需要重新上传')
    expect(wrapper.get('[data-test="start-execution"]').attributes('disabled')).toBeDefined()
    expect(apiMock.mock.calls.some(([path]) => path === 'recruitment/automation-plans/start/')).toBe(false)
  })

  it('uses the archived plan control version when starting a replacement task', async () => {
    const archived = {
      ...planFixture({
        state: 'stopped',
        controlVersion: 20,
        controlGeneration: 20,
        revision: 10,
        revisionId: 410,
        runId: 'run-archived',
      }),
      archived_at: '2026-08-27T10:05:42+08:00',
    }
    let startBody
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') return Promise.resolve({ results: [] })
      if (path === 'recruitment/automation-plans/?job=51&archived=1') {
        return Promise.resolve({ results: [archived] })
      }
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') {
        startBody = JSON.parse(options.body)
        return Promise.resolve(planFixture({
          state: 'running',
          controlVersion: 21,
          controlGeneration: 21,
          revision: 11,
          revisionId: 411,
        }))
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51' }))
    await goToPlan(wrapper, { core: '3 年 Python 经验' })
    await wrapper.get('[data-test="scheme-active"]').setValue(true)
    await wrapper.get('[data-test="active-keyword"]').setValue('Python 后端')
    await completePlanAndReview(wrapper)

    expect(startBody).toMatchObject({
      job: 51,
      kind: 'active_resume_search',
      expected_control_version: 20,
    })
  })

  it('rebases an old archived-plan draft to the latest control version', async () => {
    sessionStorage.setItem('ximing-hr:recruitment-workbench-draft:v1:9:51', JSON.stringify({
      version: 1,
      jobId: '51',
      selectedAccountId: '7',
      step: 'review',
      completed: { context: true, standard: true, plan: true },
      documentCategory: 'persona',
      draft: {
        schemeKind: 'active_resume_search',
        workflowChoice: 'standard',
        coreText: '3 年 Python 经验',
        bonusText: '',
        interval: 2,
        source: 'search',
        keyword: 'Python 后端',
        targetResumeCount: 5,
        maxScanCount: 30,
      },
      editBase: {
        jobId: '51',
        controlVersion: 0,
        revisionId: null,
        revision: null,
      },
    }))
    const archived = {
      ...planFixture({
        state: 'stopped',
        controlVersion: 20,
        controlGeneration: 20,
        revision: 10,
        revisionId: 410,
        runId: 'run-archived',
      }),
      archived_at: '2026-08-27T10:05:42+08:00',
    }
    let startBody
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/automation-plans/?job=51') return Promise.resolve({ results: [] })
      if (path === 'recruitment/automation-plans/?job=51&archived=1') {
        return Promise.resolve({ results: [archived] })
      }
      if (path === 'recruitment/automation-plans/start/' && options?.method === 'POST') {
        startBody = JSON.parse(options.body)
        return Promise.resolve(planFixture({ controlVersion: 21, revision: 11, revisionId: 411 }))
      }
      return baseApi(path)
    })

    ;({ wrapper } = await mountView({ job: '51', step: 'review' }))
    expect(wrapper.get('[data-test="plan-version-notice"]').text()).toContain('当前草稿仍基于原版本')
    await wrapper.get('[data-test="rebase-edit-draft"]').trigger('click')
    expect(wrapper.find('[data-test="plan-version-notice"]').exists()).toBe(false)
    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()

    expect(startBody.expected_control_version).toBe(20)
  })

  it('opens a blank first step for a fresh task instead of restoring the last job', async () => {
    apiMock.mockImplementation((path) => baseApi(path))
    const context = useRecruitmentContextStore()
    context.selectJob(51, { userId: 9 })

    ;({ wrapper } = await mountView({ new: '1' }))

    expect(context.selectedJobId).toBe('')
    expect(wrapper.get('[data-test="workbench-job"]').element.value).toBe('')
    expect(wrapper.find('[data-test="workbench-step-context"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="complete-context-step"]').attributes()).toHaveProperty('disabled')
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
    await completePlanAndReview(wrapper)

    const start = wrapper.get('[data-test="start-execution"]')
    await start.trigger('click')
    await start.trigger('click')
    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/automation-plans/start/')).toHaveLength(1)

    resolveStart(planFixture({ runId: 'run-once' }))
    await flushPromises()
    expect(wrapper.find('[data-test="operation-control"]').exists()).toBe(false)
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
    await completePlanAndReview(wrapper)

    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()
    await router.push({ name: 'recruitment-workbench', query: { job: '52', step: 'context' } })
    await flushPromises()

    expect(useRecruitmentContextStore().selectedJobId).toBe('51')
    expect(router.currentRoute.value.query).toMatchObject({ job: '51', step: 'review' })
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
    expect(wrapper.find('[data-test="operation-control"]').exists()).toBe(false)
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
    await goToReview(wrapper)

    expect(wrapper.get('[data-test="start-execution"]').attributes()).toHaveProperty('disabled')
    expect(wrapper.get('[data-test="precheck-browser"]').text()).toContain('隔离浏览器尚未启动')
    expect(wrapper.get('[data-test="precheck-browser"]').text()).toContain('处理')
    expect(wrapper.text()).toContain('请先处理：隔离浏览器')
    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/automation-plans/start/')).toHaveLength(0)
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
    await completePlanAndReview(wrapper)

    const startCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/automation-plans/start/')
    expect(JSON.parse(startCall[1].body)).toMatchObject({ workflow_version: 91 })
    expect(apiMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
    expect(wrapper.find('[data-test="operation-control"]').exists()).toBe(false)
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

    ;({ wrapper } = await mountView({ job: '51', editPlan: '301' }))
    expect(wrapper.find('[data-test="workbench-step-standard"]').exists()).toBe(true)
    await wrapper.get('[data-test="core-requirements"]').setValue('修改后的托管标准')
    await wrapper.get('[data-test="complete-standard-step"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="workflow-choice"]').element.value).toBe('standard')
    expect(wrapper.text()).not.toContain('当前任务使用的高级流程')
    await completePlanAndReview(wrapper)

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

    ;({ wrapper } = await mountView({ job: '51', editPlan: '301' }))
    await wrapper.get('[data-test="complete-standard-step"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="workflow-choice"]').element.value).toBe('custom:91')
    expect(wrapper.text()).toContain('当前任务使用的高级流程')
    await completePlanAndReview(wrapper)

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

    ;({ wrapper } = await mountView({ job: '51', editPlan: '301' }))
    await wrapper.get('[data-test="complete-standard-step"]').trigger('click')
    await flushPromises()
    const choice = wrapper.get('[data-test="workflow-choice"]')
    const values = choice.findAll('option').map((option) => option.attributes('value'))
    expect(values).toEqual(['standard', 'custom:93'])
    expect(choice.element.value).toBe('standard')
    expect(wrapper.text()).not.toContain('当前任务使用的高级流程')

    await choice.setValue('custom:93')
    expect(choice.element.value).toBe('custom:93')
    await completePlanAndReview(wrapper)
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
    await completePlanAndReview(wrapper)
    expect(wrapper.text()).toContain('network lost')

    await wrapper.get('[data-test="previous-step"]').trigger('click')
    await flushPromises()
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
    await completePlanAndReview(wrapper)

    const startCalls = apiMock.mock.calls.filter(([path]) => path === 'recruitment/automation-plans/start/')
    expect(startCalls).toHaveLength(2)
    expect(JSON.parse(startCalls[1][1].body).config).toMatchObject({
      core: ['更新后的核心要求'],
      bonus: ['更新后的加分项'],
    })
    expect(requestIds[1]).not.toBe(requestIds[0])
    expect(wrapper.find('[data-test="operation-control"]').exists()).toBe(false)
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
    await completePlanAndReview(wrapper)
    expect(wrapper.text()).toContain('network lost')

    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()

    expect(requestIds).toHaveLength(2)
    expect(requestIds[1]).toBe(requestIds[0])
    expect(wrapper.find('[data-test="operation-control"]').exists()).toBe(false)
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
    await completePlanAndReview(wrapper)
    expect(wrapper.get('[data-test="plan-version-notice"]').text()).toContain('V2 更新为 V3')

    expect(startBodies[0].expected_control_version).toBe(4)
    expect(wrapper.text()).toContain('version conflict')
    expect(wrapper.text()).toContain('已为你刷新')
    expect(wrapper.get('[data-test="plan-version-notice"]').text()).toContain('当前草稿仍基于原版本')

    await wrapper.get('[data-test="rebase-edit-draft"]').trigger('click')
    expect(wrapper.find('[data-test="plan-version-notice"]').exists()).toBe(false)
    await wrapper.get('[data-test="start-execution"]').trigger('click')
    await flushPromises()
    expect(startBodies[1].expected_control_version).toBe(5)
    expect(wrapper.find('[data-test="operation-control"]').exists()).toBe(false)
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
