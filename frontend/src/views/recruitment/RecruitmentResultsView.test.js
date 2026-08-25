import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentResultsView from './RecruitmentResultsView.vue'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

const RouterLinkStub = { props: ['to'], template: '<a data-router-link><slot /></a>' }

const run = (overrides = {}) => ({
  id: 'run-1000', job: 1, template_name: '主动寻访标准方案', mode: 'formal', status: 'waiting_human',
  account_name: '招聘主账号', created_at: '2026-08-25T08:00:00Z', updated_at: '2026-08-25T08:05:00Z',
  node_runs: [
    { id: 1, node_key: 'search', status: 'succeeded' },
    { id: 2, node_key: 'hr-review', status: 'waiting_human' },
  ],
  events: [{ id: 101, message: '已进入人工确认节点', created_at: '2026-08-25T08:05:00Z' }],
  ...overrides,
})

const campaign = {
  id: 9, name: '产品经理主动寻访', job: 1, workflow_run: 'run-1000', source: 'search', status: 'running',
  pulled_resume_count: 3, target_resume_count: 8, scanned_count: 12, max_scan_count: 40,
  created_at: '2026-08-25T08:00:00Z', updated_at: '2026-08-25T08:05:00Z',
}

const attention = {
  id: 7, job: 1, workflow_run: 'run-1000', application: 11, attention_type_label: '候选人观望',
  status: 'open', status_label: '待处理', title: '候选人希望先了解岗位',
  detail: { question: '想先了解一下团队规模和工作方式' }, candidate_name: '林溪',
  created_at: '2026-08-25T08:03:00Z',
}

const application = {
  id: 11, job: 1, stage: 'communicating', stage_label: '沟通', resume_count: 1,
  candidate: { id: 21, name: '林溪', current_title: '高级产品经理', current_city: '上海' },
}

const resume = {
  id: 31, application: 11, candidate: 21, candidate_name: '林溪', original_name: 'lin-xi.pdf',
  processing_status: 'ready', intelligence_status: 'completed',
}

function installContext() {
  setActivePinia(createPinia())
  const context = useRecruitmentContextStore()
  context.jobs = [
    { id: 1, title: '招聘产品经理', account_name: '招聘主账号', headcount: 2 },
    { id: 2, title: 'Vue 前端工程师', account_name: '技术招聘账号', headcount: 3 },
  ]
  context.selectedJobId = '1'
  context.loaded = true
  context.loadedUserId = '99'
  return context
}

async function mountView(query = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/recruitment/results', name: 'recruitment-results', component: { template: '<div />' } },
      { path: '/recruitment/workbench', name: 'recruitment-workbench', component: { template: '<div />' } },
      { path: '/recruitment/candidates', name: 'recruitment-candidates', component: { template: '<div />' } },
      { path: '/recruitment/resumes', name: 'recruitment-resumes', component: { template: '<div />' } },
      { path: '/recruitment/pipeline', name: 'recruitment-pipeline', component: { template: '<div />' } },
      { path: '/recruitment/automation', name: 'recruitment-automation', component: { template: '<div />' } },
    ],
  })
  await router.push({ name: 'recruitment-results', query })
  await router.isReady()
  const wrapper = mount(RecruitmentResultsView, {
    global: { plugins: [router], stubs: { RouterLink: RouterLinkStub } },
  })
  return { wrapper, router }
}

function mockCompletePayload() {
  apiMock.mockImplementation((path) => {
    if (path === 'recruitment/workflow-runs/run-1000/decision/') return Promise.resolve(run({
      status: 'running',
      node_runs: [{ id: 1, node_key: 'search', status: 'succeeded' }, { id: 2, node_key: 'hr-review', status: 'succeeded' }],
    }))
    if (path === 'recruitment/workflow-runs/run-1000/pause/') return Promise.resolve(run({ status: 'paused' }))
    if (path === 'recruitment/human-attentions/7/resolve/') return Promise.resolve({ ...attention, status: 'resolved', status_label: '已处理' })
    if (path === 'recruitment/workflow-runs/') return Promise.resolve({ results: [run()] })
    if (path === 'recruitment/search-campaigns/') return Promise.resolve({ results: [campaign] })
    if (path === 'recruitment/human-attentions/') return Promise.resolve({ results: [attention] })
    if (path === 'recruitment/applications/?job=1') return Promise.resolve({ results: [application] })
    if (path === 'recruitment/resumes/?job=1') return Promise.resolve({ results: [resume] })
    if (path === 'recruitment/structured-resumes/?job=1') return Promise.resolve({ results: [{ id: 41, resume: 31, version: 1 }] })
    if (path === 'recruitment/resume-assessments/?job=1') return Promise.resolve({ results: [{ id: 51, resume: 31, version: 1, total_score: 86, recommendation: 'advance', recommendation_label: '建议推进', confidence: 0.92 }] })
    return Promise.reject(new Error(`unexpected path: ${path}`))
  })
}

describe('RecruitmentResultsView', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/recruitment/results')
    apiMock.mockReset()
    installContext()
  })

  it('requires a job context and does not request mixed results', async () => {
    useRecruitmentContextStore().selectedJobId = ''
    const { wrapper } = await mountView()
    await flushPromises()

    expect(wrapper.get('[data-test="results-job-required"]').text()).toContain('请先选择在招职位')
    expect(apiMock).not.toHaveBeenCalled()
  })

  it('loads every persisted result source and keeps business views in one page', async () => {
    mockCompletePayload()
    const { wrapper } = await mountView()
    await flushPromises()

    expect(apiMock.mock.calls.map(([path]) => path)).toEqual(expect.arrayContaining([
      'recruitment/workflow-runs/',
      'recruitment/search-campaigns/',
      'recruitment/human-attentions/',
      'recruitment/applications/?job=1',
      'recruitment/resumes/?job=1',
      'recruitment/structured-resumes/?job=1',
      'recruitment/resume-assessments/?job=1',
    ]))
    expect(wrapper.get('[data-test="attention-view"]').text()).toContain('候选人希望先了解岗位')
    expect(wrapper.text()).toContain('想先了解一下团队规模和工作方式')

    await wrapper.get('[data-test="results-tab-tasks"]').trigger('click')
    expect(wrapper.get('[data-test="tasks-view"]').text()).toContain('主动寻访标准方案')
    expect(wrapper.get('[data-test="tasks-view"]').text()).toContain('3/8 份简历')
    await wrapper.get('[data-test="tasks-view"] button[aria-expanded="false"]').trigger('click')
    expect(wrapper.get('[data-test="tasks-view"]').text()).toContain('hr-review')
    expect(wrapper.get('[data-test="tasks-view"]').text()).toContain('已进入人工确认节点')

    await wrapper.get('[data-test="results-tab-candidates"]').trigger('click')
    expect(wrapper.get('[data-test="candidates-view"]').text()).toContain('林溪')
    expect(wrapper.get('[data-test="candidates-view"]').text()).toContain('86 分 · 建议推进')

    await wrapper.get('[data-test="results-tab-pipeline"]').trigger('click')
    expect(wrapper.get('[data-test="pipeline-view"]').text()).toContain('招聘进度')
    expect(wrapper.get('[data-test="pipeline-view"]').text()).toContain('沟通')
  })

  it('keeps successful sections visible and names a partially failed source', async () => {
    mockCompletePayload()
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/search-campaigns/') return Promise.reject(new Error('主动寻访服务暂不可用'))
      if (path === 'recruitment/workflow-runs/') return Promise.resolve({ results: [run()] })
      if (path === 'recruitment/human-attentions/') return Promise.resolve({ results: [attention] })
      if (path === 'recruitment/applications/?job=1') return Promise.resolve({ results: [application] })
      if (path === 'recruitment/resumes/?job=1') return Promise.resolve({ results: [resume] })
      if (path === 'recruitment/structured-resumes/?job=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/resume-assessments/?job=1') return Promise.resolve({ results: [] })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const { wrapper } = await mountView()
    await flushPromises()

    expect(wrapper.get('[data-test="partial-error"]').text()).toContain('主动寻访')
    expect(wrapper.get('[data-test="attention-view"]').text()).toContain('候选人希望先了解岗位')
    expect(wrapper.find('[data-test="results-error"]').exists()).toBe(false)
  })

  it('does not let a slow previous job response overwrite a quick job switch', async () => {
    let resolveOldApplications
    const oldApplications = new Promise((resolve) => { resolveOldApplications = resolve })
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/workflow-runs/' || path === 'recruitment/search-campaigns/' || path === 'recruitment/human-attentions/') return Promise.resolve({ results: [] })
      if (path === 'recruitment/applications/?job=1') return oldApplications
      if (path === 'recruitment/applications/?job=2') return Promise.resolve({ results: [{ ...application, id: 22, job: 2, candidate: { ...application.candidate, id: 32, name: '新岗位候选人' } }] })
      if (path.includes('?job=1') || path.includes('?job=2')) return Promise.resolve({ results: [] })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const { wrapper } = await mountView()
    await flushPromises()

    useRecruitmentContextStore().selectedJobId = '2'
    await flushPromises()
    await wrapper.get('[data-test="results-tab-candidates"]').trigger('click')
    expect(wrapper.text()).toContain('新岗位候选人')

    resolveOldApplications({ results: [{ ...application, candidate: { ...application.candidate, name: '旧岗位候选人' } }] })
    await flushPromises()
    expect(wrapper.text()).toContain('新岗位候选人')
    expect(wrapper.text()).not.toContain('旧岗位候选人')
  })

  it('refreshes persisted runs from the server instead of relying on page memory', async () => {
    let runRequest = 0
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/workflow-runs/') {
        runRequest += 1
        return Promise.resolve({ results: [run({ id: `run-${runRequest}`, template_name: runRequest === 1 ? '第一次运行' : '服务端恢复运行' })] })
      }
      if (path === 'recruitment/search-campaigns/' || path === 'recruitment/human-attentions/') return Promise.resolve({ results: [] })
      if (path.includes('?job=1')) return Promise.resolve({ results: [] })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const { wrapper } = await mountView()
    await flushPromises()
    await wrapper.get('[data-test="results-tab-tasks"]').trigger('click')
    expect(wrapper.text()).toContain('第一次运行')

    await wrapper.get('[data-test="refresh-results"]').trigger('click')
    await flushPromises()
    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/workflow-runs/')).toHaveLength(2)
    expect(wrapper.text()).toContain('服务端恢复运行')
    expect(wrapper.text()).not.toContain('第一次运行')
  })

  it('opens a legacy or execution deep link in the requested job, run, and business view', async () => {
    mockCompletePayload()
    const context = useRecruitmentContextStore()
    context.selectedJobId = '2'
    const { wrapper, router } = await mountView({ job: '1', run: 'run-1000', view: 'runs' })
    await flushPromises()

    expect(context.selectedJobId).toBe('1')
    expect(wrapper.get('[data-test="tasks-view"]').text()).toContain('主动寻访标准方案')
    expect(wrapper.get('[data-test="run-filter"]').element.value).toBe('run-1000')
    expect(wrapper.get('[aria-label="流程运行状态"]').text()).toContain('等待人工')

    await wrapper.get('[data-test="results-tab-candidates"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.view).toBe('candidates')
  })

  it('loads an older run directly when it is not present in the first results list', async () => {
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/workflow-runs/') return Promise.resolve({ results: [] })
      if (path === 'recruitment/workflow-runs/run-archive/') return Promise.resolve(run({ id: 'run-archive', template_name: '历史运行' }))
      if (path === 'recruitment/search-campaigns/' || path === 'recruitment/human-attentions/') return Promise.resolve({ results: [] })
      if (path.includes('?job=1')) return Promise.resolve({ results: [] })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const { wrapper } = await mountView({ job: '1', run: 'run-archive' })
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-runs/run-archive/')
    expect(wrapper.get('[data-test="tasks-view"]').text()).toContain('历史运行')
    expect(wrapper.get('[aria-label="流程运行状态"]').text()).toContain('历史运行')
  })

  it('recovers the job from a run-only legacy URL', async () => {
    useRecruitmentContextStore().selectedJobId = ''
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/workflow-runs/run-1000/') return Promise.resolve(run())
      if (path === 'recruitment/workflow-runs/') return Promise.resolve({ results: [run()] })
      if (path === 'recruitment/search-campaigns/' || path === 'recruitment/human-attentions/') return Promise.resolve({ results: [] })
      if (path.includes('?job=1')) return Promise.resolve({ results: [] })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const { wrapper, router } = await mountView({ run: 'run-1000', view: 'tasks' })
    await flushPromises()

    expect(useRecruitmentContextStore().selectedJobId).toBe('1')
    expect(router.currentRoute.value.query.job).toBe('1')
    expect(wrapper.get('[aria-label="流程运行状态"]').text()).toContain('主动寻访标准方案')
  })

  it('uses the existing run panel to keep pause and human-node decisions reachable', async () => {
    mockCompletePayload()
    const { wrapper } = await mountView({ job: '1', view: 'tasks' })
    await flushPromises()

    await wrapper.get('[data-test="manage-run-run-1000"]').trigger('click')
    await flushPromises()
    const panel = wrapper.get('[aria-label="流程运行状态"]')
    expect(panel.text()).toContain('hr-review')

    const approve = panel.findAll('button').find((button) => button.text() === '通过')
    await approve.trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-runs/run-1000/decision/', {
      method: 'POST',
      body: JSON.stringify({ node_id: 2, approved: true, note: 'HR 在结果中心确认通过' }),
    })

    const pause = wrapper.get('[aria-label="流程运行状态"]').findAll('button').find((button) => button.text() === '暂停')
    await pause.trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-runs/run-1000/pause/', {
      method: 'POST', body: JSON.stringify({}),
    })
    expect(wrapper.get('[aria-label="流程运行状态"]').text()).toContain('已暂停')
  })

  it('retries a failed workflow node from the same result-center panel', async () => {
    const failedRun = run({
      status: 'failed',
      node_runs: [{ id: 3, node_key: 'resume-pull', status: 'failed', error_message: '网络中断' }],
    })
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/workflow-runs/') return Promise.resolve({ results: [failedRun] })
      if (path === 'recruitment/workflow-runs/run-1000/retry/') return Promise.resolve(run({ status: 'running' }))
      if (path === 'recruitment/search-campaigns/' || path === 'recruitment/human-attentions/') return Promise.resolve({ results: [] })
      if (path.includes('?job=1')) return Promise.resolve({ results: [] })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const { wrapper } = await mountView({ job: '1', run: 'run-1000' })
    await flushPromises()

    const retry = wrapper.get('[aria-label="流程运行状态"]').findAll('button').find((button) => button.text() === '重试')
    await retry.trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-runs/run-1000/retry/', {
      method: 'POST', body: JSON.stringify({ node_id: 3 }),
    })
  })

  it('resolves a human attention item from the result center', async () => {
    mockCompletePayload()
    const { wrapper } = await mountView({ job: '1', view: 'attention' })
    await flushPromises()

    await wrapper.get('[data-test="resolve-attention-7"]').trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/human-attentions/7/resolve/', {
      method: 'POST', body: JSON.stringify({ note: 'HR 已在结果中心处理' }),
    })
    expect(wrapper.get('[data-test="attention-view"]').text()).toContain('已处理')
    expect(wrapper.find('[data-test="resolve-attention-7"]').exists()).toBe(false)
  })

  it('restores application, candidate, account, and resume-filter context from a legacy deep link', async () => {
    mockCompletePayload()
    const { wrapper, router } = await mountView({
      job: '1', application: '11', candidate: '21', account: '7', filter: 'recommended_advance',
    })
    await flushPromises()

    expect(wrapper.get('[data-test="legacy-context"]').text()).toContain('应聘 #11')
    expect(wrapper.get('[data-test="legacy-context"]').text()).toContain('候选人 #21')
    expect(wrapper.get('[data-test="legacy-context"]').text()).toContain('建议进一步沟通')
    expect(wrapper.get('[data-test="candidates-view"] [data-application-id="11"]').text()).toContain('林溪')

    await wrapper.get('[data-test="clear-legacy-context"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.application).toBeUndefined()
    expect(router.currentRoute.value.query.candidate).toBeUndefined()
    expect(router.currentRoute.value.query.account).toBeUndefined()
    expect(router.currentRoute.value.query.filter).toBeUndefined()
  })

  it('uses a run-only deep link to replace a different remembered job context', async () => {
    useRecruitmentContextStore().selectedJobId = '2'
    mockCompletePayload()
    const completeImplementation = apiMock.getMockImplementation()
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/workflow-runs/run-1000/') return Promise.resolve(run())
      if (path.includes('?job=2')) return Promise.resolve({ results: [] })
      return completeImplementation(path, options)
    })

    const { wrapper, router } = await mountView({ run: 'run-1000', view: 'tasks' })
    await flushPromises()
    await flushPromises()

    expect(useRecruitmentContextStore().selectedJobId).toBe('1')
    expect(router.currentRoute.value.query.job).toBe('1')
    expect(wrapper.text()).toContain('招聘产品经理')
    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-runs/run-1000/')
  })
})
