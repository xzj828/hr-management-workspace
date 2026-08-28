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
import WorkflowRunPanel from '@/components/WorkflowRunPanel.vue'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

const RouterLinkStub = { props: ['to'], template: '<a data-router-link><slot /></a>' }

const run = (overrides = {}) => ({
  id: 'run-1000', job: 1, template_name: '主动寻访标准方案', mode: 'formal', status: 'waiting_human',
  account_name: '招聘主账号', created_at: '2026-08-25T08:00:00Z', updated_at: '2026-08-25T08:05:00Z',
  node_runs: [
    { id: 1, node_key: 'search', status: 'succeeded' },
    { id: 2, node_key: 'hr-review', status: 'waiting_human' },
    { id: 3, node_key: 'unused-branch', status: 'skipped' },
  ],
  events: [{ id: 101, message: '已进入人工确认节点', created_at: '2026-08-25T08:05:00Z' }],
  ...overrides,
})

const campaign = {
  id: 9, name: '产品经理主动寻访', job: 1, workflow_run: 'run-1000', source: 'search', status: 'running',
  pulled_resume_count: 3, qualified_resume_count: 3, target_resume_count: 8, scanned_count: 12, max_scan_count: 40,
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
  processing_status: 'ready', intelligence_status: 'completed', content_type: 'application/pdf',
  preview_url: '/api/recruitment/resumes/31/file/', download_url: '/api/recruitment/resumes/31/file/?download=1',
}
const structure = { id: 41, resume: 31, version: 1, data: { basics: { name: '林溪', target_role: '产品经理', city: '上海' }, skills: ['用户研究'] }, warnings: [] }
const assessment = { id: 51, resume: 31, structured_resume: 41, standard: 61, version: 1, total_score: 86, recommendation: 'advance', recommendation_label: '建议推进', confidence: 0.92, dimension_scores: [{ criterion_key: 'research', criterion_name: '用户研究', score: 24, max_score: 30, reason: '有完整研究项目', resume_evidence_block_ids: ['resume-31-block-2'] }], hard_failures: [], gaps: ['缺少国际化经历'], verification_questions: ['请核实英语沟通场景'] }
const structureSummary = { id: 41, resume: 31, version: 1, warnings_count: 0, created_at: '2026-08-25T08:02:00Z' }
const assessmentSummary = { id: 51, structured_resume: 41, standard: 61, standard_version: 1, version: 1, total_score: 86, recommendation: 'advance', recommendation_label: '建议推进', confidence: 0.92, auto_rejected: false, hard_failure_count: 0 }
const screeningRow = {
  rank: 1,
  application: { id: 11, job: 1, stage: 'communicating', stage_label: '沟通', source: 'boss' },
  candidate: application.candidate,
  resume,
  structure: structureSummary,
  assessment: assessmentSummary,
  ai_state: 'scored',
  hr_decision: null,
  notification: { status: 'not_requested' },
}

const screeningPayload = (results = [screeningRow], jobId = 1) => ({
  job: { id: jobId, title: jobId === 1 ? '招聘产品经理' : 'Vue 前端工程师', boss_account: 7 },
  standard: { id: 61, version: 1, status: 'published' },
  results,
})

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
      { path: '/recruitment/tasks', name: 'recruitment-tasks', component: { template: '<div />' } },
      { path: '/recruitment/tasks/:planId', name: 'recruitment-task-detail', component: { template: '<div />' } },
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
    if (path === 'recruitment/screening-results/?job=1') return Promise.resolve(screeningPayload())
    if (path === 'recruitment/structured-resumes/?resume=31') return Promise.resolve({ results: [structure] })
    if (path === 'recruitment/resume-assessments/?resume=31') return Promise.resolve({ results: [assessment] })
    if (path === 'recruitment/ai-tasks/?resume=31') return Promise.resolve({ results: [] })
    return Promise.reject(new Error(`unexpected path: ${path}`))
  })
}

describe('RecruitmentResultsView', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
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
      'recruitment/screening-results/?job=1',
    ]))
    expect(wrapper.get('[data-test="attention-view"]').text()).toContain('候选人希望先了解岗位')
    expect(wrapper.text()).toContain('想先了解一下团队规模和工作方式')
    expect(wrapper.get('.attention-list__head').text()).toContain('上下文摘要')

    await wrapper.get('[data-test="results-tab-tasks"]').trigger('click')
    expect(wrapper.get('[data-test="tasks-view"]').text()).toContain('主动寻访标准方案')
    expect(wrapper.get('[data-test="tasks-view"]').text()).toContain('2/3')
    expect(wrapper.get('[data-test="tasks-view"]').text()).toContain('3/8')
    expect(wrapper.get('[data-test="manage-run-run-1000"]').text()).toBe('处理待办')
    expect(wrapper.get('[data-test="tasks-view"]').text()).not.toContain('hr-review')
    expect(wrapper.get('[data-test="tasks-view"]').text()).not.toContain('已进入人工确认节点')

    await wrapper.get('[data-test="results-tab-candidates"]').trigger('click')
    expect(wrapper.get('[data-test="candidates-view"]').text()).toContain('林溪')
    expect(wrapper.get('[data-test="candidates-view"]').text()).toContain('86 分')
    expect(wrapper.get('[data-test="candidates-view"]').text()).toContain('AI 建议进一步沟通')
    expect(wrapper.get('[data-test="candidates-view"]').text()).not.toContain('高级产品经理')
    expect(wrapper.get('[data-test="candidates-view"]').text()).not.toContain('原件与报告已就绪')
    expect(wrapper.get('.candidate-rank svg').attributes('width')).toBe('18')
    expect(wrapper.get('.candidate-action-heading').text()).toBe('操作')
    expect(wrapper.findAll('.candidate-action-cell > div > button')).toHaveLength(2)

    await wrapper.get('[data-test="results-tab-pipeline"]').trigger('click')
    expect(wrapper.get('[data-test="pipeline-view"]').text()).toContain('招聘阶段分布')
    expect(wrapper.get('[data-test="pipeline-view"]').text()).toContain('沟通')
    expect(wrapper.get('[data-test="pipeline-view"]').text()).toContain('岗位招聘目标2 人')
    expect(wrapper.get('[data-test="pipeline-view"]').text()).toContain('在招中1 人')
    expect(wrapper.get('[data-test="pipeline-view"]').text()).toContain('完成进度0%')
  })

  it('keeps successful sections visible and names a partially failed source', async () => {
    mockCompletePayload()
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/search-campaigns/') return Promise.reject(new Error('主动寻访服务暂不可用'))
      if (path === 'recruitment/workflow-runs/') return Promise.resolve({ results: [run()] })
      if (path === 'recruitment/human-attentions/') return Promise.resolve({ results: [attention] })
      if (path === 'recruitment/screening-results/?job=1') return Promise.resolve(screeningPayload())
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const { wrapper } = await mountView()
    await flushPromises()

    expect(wrapper.get('[data-test="partial-error"]').text()).toContain('主动寻访')
    expect(wrapper.get('[data-test="attention-view"]').text()).toContain('候选人希望先了解岗位')
    expect(wrapper.find('[data-test="results-error"]').exists()).toBe(false)
  })

  it('does not let a slow previous job response overwrite a quick job switch', async () => {
    let resolveOldScreening
    const oldScreening = new Promise((resolve) => { resolveOldScreening = resolve })
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/workflow-runs/' || path === 'recruitment/search-campaigns/' || path === 'recruitment/human-attentions/') return Promise.resolve({ results: [] })
      if (path === 'recruitment/screening-results/?job=1') return oldScreening
      if (path === 'recruitment/screening-results/?job=2') return Promise.resolve(screeningPayload([{ ...screeningRow, application: { ...screeningRow.application, id: 22, job: 2 }, candidate: { ...screeningRow.candidate, id: 32, name: '新岗位候选人' }, resume: { ...resume, id: 42, application: 22, candidate: 32 } }], 2))
      if (path.includes('?job=1') || path.includes('?job=2')) return Promise.resolve({ results: [] })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const { wrapper } = await mountView()
    await flushPromises()

    useRecruitmentContextStore().selectedJobId = '2'
    await flushPromises()
    await wrapper.get('[data-test="results-tab-candidates"]').trigger('click')
    expect(wrapper.text()).toContain('新岗位候选人')

    resolveOldScreening(screeningPayload([{ ...screeningRow, candidate: { ...screeningRow.candidate, name: '旧岗位候选人' } }]))
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

  it('links plan-managed runs to task details and separates deleted tasks', async () => {
    const currentRun = run({ id: 'run-current', template_name: '当前任务', automation_plan: 301 })
    const archivedRun = run({
      id: 'run-removed',
      template_name: '已删除任务',
      automation_plan: 302,
      automation_plan_archived_at: '2026-08-27T02:00:00+08:00',
    })
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/workflow-runs/') return Promise.resolve({ results: [currentRun, archivedRun] })
      if (path === 'recruitment/search-campaigns/' || path === 'recruitment/human-attentions/') return Promise.resolve({ results: [] })
      if (path === 'recruitment/screening-results/?job=1') return Promise.resolve(screeningPayload([]))
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const { wrapper } = await mountView({ job: '1', view: 'tasks' })
    await flushPromises()

    expect(wrapper.get('.results-center').classes()).toContain('results-center--business-results-typography')

    expect(wrapper.get('[data-test="tasks-view"]').text()).toContain('当前任务')
    expect(wrapper.get('[data-test="tasks-view"]').text()).not.toContain('已删除任务')
    const taskLink = wrapper.findAllComponents(RouterLinkStub).find((link) => link.text().includes('查看任务'))
    expect(taskLink.props('to')).toMatchObject({ name: 'recruitment-task-detail', params: { planId: 301 } })

    await wrapper.get('[data-test="status-filter"]').setValue('archived')
    await flushPromises()
    expect(wrapper.get('[data-test="tasks-view"]').text()).toContain('已删除任务')
    expect(wrapper.get('[data-test="tasks-view"]').text()).not.toContain('当前任务')
  })

  it('does not apply business-result typography when embedded in a recruitment task', async () => {
    mockCompletePayload()
    const { wrapper } = await mountView()
    await wrapper.setProps({ embedded: true })
    await flushPromises()

    expect(wrapper.get('.results-center').classes()).not.toContain('results-center--business-results-typography')
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
    expect(panel.text()).toContain('处理招聘任务')
    expect(panel.text()).not.toContain('hr-review')

    const approve = panel.findAll('button').find((button) => button.text() === '继续处理')
    await approve.trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-runs/run-1000/decision/', {
      method: 'POST',
      body: JSON.stringify({ node_id: 2, approved: true, note: 'HR 在结果中心确认通过' }),
    })

    const pause = wrapper.get('[aria-label="流程运行状态"]').findAll('button').find((button) => button.text() === '暂停任务')
    await pause.trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-runs/run-1000/pause/', {
      method: 'POST', body: JSON.stringify({}),
    })
    expect(wrapper.get('[aria-label="流程运行状态"]').text()).toContain('已暂停')
  })

  it('keeps plan-managed runs read-only for lifecycle controls and links to their task detail', async () => {
    const managedRun = run({ automation_plan_revision: 402, automation_plan: 301 })
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/workflow-runs/') return Promise.resolve({ results: [managedRun] })
      if (path === 'recruitment/workflow-runs/run-1000/decision/') {
        return Promise.resolve(run({ ...managedRun, status: 'running' }))
      }
      if (path === 'recruitment/search-campaigns/') return Promise.resolve({ results: [campaign] })
      if (path === 'recruitment/human-attentions/') return Promise.resolve({ results: [attention] })
      if (path === 'recruitment/screening-results/?job=1') return Promise.resolve(screeningPayload())
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const { wrapper } = await mountView({ job: '1', view: 'tasks' })
    await flushPromises()

    await wrapper.get('[data-test="manage-run-run-1000"]').trigger('click')
    await flushPromises()
    const panel = wrapper.getComponent(WorkflowRunPanel)
    expect(panel.get('[data-test="plan-managed-guidance"]').text()).toContain('任务设置与启停在任务详情中管理')
    expect(panel.text()).not.toContain('暂停任务')
    expect(panel.text()).not.toContain('结束本次任务')
    expect(panel.getComponent(RouterLinkStub).props('to')).toEqual({
      name: 'recruitment-task-detail',
      params: { planId: '301' },
      query: { job: '1', run: 'run-1000', view: 'tasks' },
    })

    const approve = panel.findAll('button').find((button) => button.text() === '继续处理')
    await approve.trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-runs/run-1000/decision/', {
      method: 'POST',
      body: JSON.stringify({ node_id: 2, approved: true, note: 'HR 在结果中心确认通过' }),
    })
    expect(apiMock.mock.calls.some(([path]) => path.endsWith('/pause/') || path.endsWith('/cancel/') || path.endsWith('/retry/'))).toBe(false)
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

    const retry = wrapper.get('[aria-label="流程运行状态"]').findAll('button').find((button) => button.text() === '重新处理')
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

  it('bulk clears human attentions from the current list after confirmation', async () => {
    mockCompletePayload()
    const baseImplementation = apiMock.getMockImplementation()
    let cleared = false
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/human-attentions/bulk-archive/') {
        cleared = true
        return Promise.resolve({ archived_count: 1, archived_ids: [7], skipped_count: 0 })
      }
      if (path === 'recruitment/human-attentions/' && cleared) return Promise.resolve({ results: [] })
      return baseImplementation(path, options)
    })
    const { wrapper } = await mountView({ job: '1', view: 'attention' })
    await flushPromises()

    await wrapper.get('[data-test="clear-attentions"]').trigger('click')
    expect(document.body.textContent).toContain('一键清除人工事项')
    document.body.querySelector('[data-test="confirm-archive"]').click()
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/human-attentions/bulk-archive/', {
      method: 'POST', body: JSON.stringify({ attention_ids: [7] }),
    })
    expect(wrapper.get('[data-test="operation-notice"]').text()).toContain('已清除 1 项人工事项')
    expect(wrapper.get('[data-test="attention-view"]').text()).toContain('当前范围没有需要人工处理的事项')
  })

  it('bulk clears terminal task results while reporting protected active tasks', async () => {
    mockCompletePayload()
    const baseImplementation = apiMock.getMockImplementation()
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/workflow-runs/bulk-archive/') {
        return Promise.resolve({ archived_count: 0, archived_ids: [], skipped_count: 1 })
      }
      return baseImplementation(path, options)
    })
    const { wrapper } = await mountView({ job: '1', view: 'tasks' })
    await flushPromises()

    await wrapper.get('[data-test="clear-tasks"]').trigger('click')
    document.body.querySelector('[data-test="confirm-archive"]').click()
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-runs/bulk-archive/', {
      method: 'POST', body: JSON.stringify({ run_ids: ['run-1000'] }),
    })
    expect(wrapper.get('[data-test="operation-notice"]').text()).toContain('1 个运行中或受保护任务已保留')
  })

  it('bulk clears saved resume files and refreshes the ranking', async () => {
    mockCompletePayload()
    const baseImplementation = apiMock.getMockImplementation()
    let cleared = false
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/resumes/bulk-purge/') {
        cleared = true
        return Promise.resolve({ purged_count: 1, purged_ids: [31], released_bytes: 4096, failed_count: 0, failures: [] })
      }
      if (path === 'recruitment/screening-results/?job=1' && cleared) {
        return Promise.resolve(screeningPayload([{ ...screeningRow, resume: null, structure: null, assessment: null }]))
      }
      return baseImplementation(path, options)
    })
    const { wrapper } = await mountView({ job: '1', view: 'candidates' })
    await flushPromises()

    await wrapper.get('[data-test="clear-resumes"]').trigger('click')
    expect(document.body.textContent).toContain('物理删除当前岗位所有已保存的简历原文件')
    document.body.querySelector('[data-test="confirm-archive"]').click()
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/resumes/bulk-purge/', {
      method: 'POST', body: JSON.stringify({ resume_ids: [31] }),
    })
    expect(wrapper.get('[data-test="operation-notice"]').text()).toContain('释放 4.0 KB 本地空间')
    expect(wrapper.get('tr[data-application-id="11"]').text()).toContain('暂无简历')
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

  it('renders one authoritative native ranking with scored and unscored candidates without inferring HR decisions', async () => {
    mockCompletePayload()
    const baseImplementation = apiMock.getMockImplementation()
    const holdRow = {
      ...screeningRow,
      rank: 2,
      application: { ...screeningRow.application, id: 12, stage: 'communicating' },
      candidate: { id: 22, name: '陈沐', current_title: '产品运营', current_city: '杭州' },
      resume: { ...resume, id: 32, application: 12, candidate: 22, candidate_name: '陈沐' },
      structure: { ...structureSummary, id: 42, resume: 32 },
      assessment: { ...assessmentSummary, id: 52, structured_resume: 42, total_score: 68, recommendation: 'hold', recommendation_label: '建议暂缓' },
      hr_decision: { id: 71, decision: 'fail', reason: '岗位匹配度不足', version: 1 },
      notification: { status: 'waiting_human', error_message: '需要人工核对会话身份' },
    }
    const unscoredRow = {
      rank: null,
      application: { id: 13, job: 1, stage: 'rejected', stage_label: '已淘汰' },
      candidate: { id: 23, name: '许言', current_title: '产品助理', current_city: '苏州' },
      resume: null, structure: null, assessment: null, ai_state: 'no_resume', hr_decision: null,
      notification: { status: 'not_requested' },
    }
    apiMock.mockImplementation((path, options) => path === 'recruitment/screening-results/?job=1'
      ? Promise.resolve(screeningPayload([screeningRow, holdRow, unscoredRow]))
      : baseImplementation(path, options))

    const { wrapper } = await mountView({ job: '1', view: 'candidates' })
    await flushPromises()

    const table = wrapper.get('table.candidate-ranking-table')
    expect(table.get('th[aria-sort="descending"]').text()).toBe('排名')
    expect(table.findAll('tbody tr').map((row) => row.attributes('data-application-id'))).toEqual(['11', '12', '13'])
    expect(table.text()).toContain('AI 建议进一步沟通')
    expect(table.text()).toContain('AI 暂不建议推进')
    expect(table.text()).toContain('HR 已确认未通过')
    expect(table.text()).toContain('HR 待确认')
    expect(table.text()).toContain('不作为 0 分')
    expect(table.text()).toContain('等待人工介入')
    expect(wrapper.get('[data-test="candidate-filter-hr"]').findAll('option').map((option) => option.text())).toEqual(expect.arrayContaining(['已通过', '未通过']))
    expect(wrapper.get('[data-test="candidate-filter-ai"]').findAll('option').map((option) => option.text())).toContain('建议未通过')
    expect(wrapper.get('[data-test="notification-summary"]').text()).toContain('等待人工 1')
  })

  it('keeps selection stable while filtering and opens the resume report on the same result route', async () => {
    mockCompletePayload()
    const { wrapper, router } = await mountView({ job: '1', view: 'candidates' })
    await flushPromises()

    await wrapper.get('tr[data-application-id="11"] input[type="checkbox"]').setValue(true)
    await wrapper.get('[data-test="candidate-filter-ai"]').setValue('hold')
    expect(wrapper.get('[data-test="candidate-batch-bar"]').text()).toContain('已选择 1 人')
    expect(wrapper.find('tr[data-application-id="11"]').exists()).toBe(false)
    await wrapper.get('[data-test="candidate-filter-clear"]').trigger('click')

    expect(apiMock.mock.calls.some(([path]) => path.includes('?resume=31'))).toBe(false)
    await wrapper.get('[data-test="view-candidate-11"]').trigger('click')
    await flushPromises()
    expect(apiMock.mock.calls.map(([path]) => path)).toEqual(expect.arrayContaining([
      'recruitment/structured-resumes/?resume=31',
      'recruitment/resume-assessments/?resume=31',
      'recruitment/ai-tasks/?resume=31',
    ]))
    expect(router.currentRoute.value.query.application).toBe('11')
    expect(router.currentRoute.value.query.resume).toBe('31')
    const evidenceCard = wrapper.get('[role="dialog"][aria-label="证据详情"]')
    expect(evidenceCard.text()).toContain('林溪')
    expect(evidenceCard.text()).toContain('用户研究')
    expect(evidenceCard.text()).toContain('有完整研究项目')
    expect(evidenceCard.find('nav').exists()).toBe(false)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(router.currentRoute.value.query.application).toBeUndefined()
    expect(router.currentRoute.value.query.resume).toBeUndefined()

    await wrapper.get('[data-test="view-candidate-11"]').trigger('click')
    await flushPromises()
    router.back()
    await flushPromises()
    expect(wrapper.find('[role="dialog"][aria-label="证据详情"]').exists()).toBe(false)
  })

  it('confirms resume file deletion, refreshes results, and reports released space', async () => {
    mockCompletePayload()
    const baseImplementation = apiMock.getMockImplementation()
    let purged = false
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/resumes/31/purge/') {
        purged = true
        return Promise.resolve({ released_bytes: 2048 })
      }
      if (path === 'recruitment/screening-results/?job=1' && purged) {
        return Promise.resolve(screeningPayload([{ ...screeningRow, resume: null, structure: null, assessment: null }]))
      }
      return baseImplementation(path, options)
    })
    const { wrapper, router } = await mountView({ job: '1', view: 'candidates' })
    await flushPromises()

    await wrapper.get('[data-test="view-candidate-11"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="purge-resume-11"]').trigger('click')

    expect(wrapper.find('[role="dialog"][aria-label="证据详情"]').exists()).toBe(false)
    expect(document.body.textContent).toContain('物理删除本地原文件')
    expect(document.body.textContent).toContain('历史结构化结果、评分、HR 结论和审计记录仍会保留')

    document.body.querySelector('[data-test="confirm-archive"]').click()
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/resumes/31/purge/', { method: 'POST' })
    expect(router.currentRoute.value.query.resume).toBeUndefined()
    expect(document.body.querySelector('[data-test="confirm-archive"]')).toBeNull()
    expect(wrapper.get('[data-test="operation-notice"]').text()).toContain('释放 2.0 KB 本地空间')
    expect(wrapper.get('tr[data-application-id="11"]').text()).toContain('暂无简历')
  })

  it('keeps the resume deletion confirmation open when the API rejects the purge', async () => {
    mockCompletePayload()
    const baseImplementation = apiMock.getMockImplementation()
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/resumes/31/purge/') return Promise.reject(new Error('简历正在处理中，请稍后重试'))
      return baseImplementation(path, options)
    })
    const { wrapper, router } = await mountView({ job: '1', view: 'candidates' })
    await flushPromises()

    await wrapper.get('[data-test="view-candidate-11"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="purge-resume-11"]').trigger('click')
    document.body.querySelector('[data-test="confirm-archive"]').click()
    await flushPromises()

    expect(document.body.querySelector('[role="alert"]').textContent).toContain('简历正在处理中')
    expect(document.body.querySelector('[data-test="confirm-archive"]')).not.toBeNull()
    expect(router.currentRoute.value.query.resume).toBe('31')
  })

  it('submits only eligible selected candidates with one shared greeting snapshot', async () => {
    mockCompletePayload()
    const baseImplementation = apiMock.getMockImplementation()
    const eligibleRow = {
      ...screeningRow,
      application: { ...screeningRow.application, stage: 'new', stage_label: '新候选人' },
      greeting: { eligible: true, status: 'not_requested', reason_code: '', reason_label: '可打招呼' },
    }
    const blockedRow = {
      ...screeningRow,
      rank: 2,
      application: { ...screeningRow.application, id: 12, stage: 'greeted', stage_label: '已打招呼' },
      candidate: { id: 22, name: '陈沐', current_title: '产品运营', current_city: '杭州' },
      resume: null,
      greeting: { eligible: false, status: 'succeeded', reason_code: 'already_contacted', reason_label: '候选人已联系' },
    }
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/screening-results/?job=1') return Promise.resolve(screeningPayload([eligibleRow, blockedRow]))
      if (path === 'recruitment/communication-actions/prepare/') return Promise.resolve({ approval_id: 'greet-approval-1', item_count: 1 })
      if (path === 'recruitment/automation-approvals/greet-approval-1/approve/') return Promise.resolve({ batch: { id: 'greet-batch-1', steps: [{ id: 1, status: 'pending' }] } })
      return baseImplementation(path, options)
    })
    const { wrapper } = await mountView({ job: '1', view: 'candidates' })
    await flushPromises()

    await wrapper.get('[data-test="select-visible-candidates"]').setValue(true)
    expect(wrapper.get('[data-test="candidate-batch-bar"]').text()).toContain('其中 1 人可打招呼')
    await wrapper.get('[data-test="bulk-greet"]').trigger('click')
    expect(wrapper.text()).toContain('另有 1 位')
    await wrapper.get('[data-test="communication-message"]').setValue('你好，想和你聊聊产品经理岗位。')
    await wrapper.get('[data-test="confirm-communication"]').trigger('click')
    await flushPromises()

    const prepareCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/communication-actions/prepare/')
    expect(JSON.parse(prepareCall[1].body)).toMatchObject({
      boss_account: 7,
      application_ids: [11],
      action: 'greet',
      message: '你好，想和你聊聊产品经理岗位。',
    })
    expect(apiMock).toHaveBeenCalledWith('recruitment/automation-approvals/greet-approval-1/approve/', { method: 'POST' })
    expect(wrapper.get('[data-test="operation-notice"]').text()).toContain('统一打招呼任务加入顺序执行队列')
  })

  it('saves an explicit HR fail decision and queues a separate rejection notice without claiming it was sent', async () => {
    mockCompletePayload()
    const baseImplementation = apiMock.getMockImplementation()
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/screening-decisions/bulk/') {
        return Promise.resolve({
          decision_batch_id: 'decision-batch-1',
          decisions: [{ id: 81, application: 11, decision: 'fail', reason: '当前岗位更需要企业产品经验', version: 1 }],
        })
      }
      if (path === 'recruitment/rejection-notices/prepare/') return Promise.resolve({ approval_id: 'approval-1', status: 'draft', item_count: 1 })
      if (path === 'recruitment/automation-approvals/approval-1/approve/') return Promise.resolve({ batch: { id: 'execution-1' } })
      return baseImplementation(path, options)
    })
    const { wrapper } = await mountView({ job: '1', view: 'candidates' })
    await flushPromises()

    await wrapper.get('tr[data-application-id="11"] input[type="checkbox"]').setValue(true)
    await wrapper.get('[data-test="bulk-fail"]').trigger('click')
    expect(wrapper.text()).not.toContain('立即发送')
    await wrapper.get('[data-test="screening-reason"]').setValue('当前岗位更需要企业产品经验')
    await wrapper.get('[data-test="screening-acknowledgement"]').setValue(true)
    await wrapper.get('[data-test="queue-rejection-notice"]').trigger('click')
    await flushPromises()

    const decisionCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/screening-decisions/bulk/')
    expect(JSON.parse(decisionCall[1].body)).toMatchObject({ job: 1, application_ids: [11], decision: 'fail', reason: '当前岗位更需要企业产品经验' })
    const prepareCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/rejection-notices/prepare/')
    expect(JSON.parse(prepareCall[1].body)).toMatchObject({ decision_batch_id: 'decision-batch-1' })
    expect(apiMock).toHaveBeenCalledWith('recruitment/automation-approvals/approval-1/approve/', { method: 'POST' })
    expect(wrapper.get('[data-test="operation-notice"]').text()).toContain('不代表消息已经发送')
    expect(wrapper.find('[data-test="candidate-batch-bar"]').exists()).toBe(false)
  })

  it('keeps candidates and the editable form selected when the HR decision succeeds but notice preparation fails', async () => {
    mockCompletePayload()
    const baseImplementation = apiMock.getMockImplementation()
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/screening-decisions/bulk/') return Promise.resolve({ decision_batch_id: 'decision-batch-2', decisions: [{ id: 82, application: 11, decision: 'fail', reason: '招聘名额调整', version: 1 }] })
      if (path === 'recruitment/rejection-notices/prepare/') return Promise.reject(new Error('当前账号通知额度不足'))
      return baseImplementation(path, options)
    })
    const { wrapper } = await mountView({ job: '1', view: 'candidates' })
    await flushPromises()

    await wrapper.get('tr[data-application-id="11"] input[type="checkbox"]').setValue(true)
    await wrapper.get('[data-test="bulk-fail"]').trigger('click')
    await wrapper.get('[data-test="screening-reason"]').setValue('招聘名额调整')
    await wrapper.get('[data-test="screening-acknowledgement"]').setValue(true)
    const originalMessage = wrapper.get('[data-test="rejection-message"]').element.value
    await wrapper.get('[data-test="queue-rejection-notice"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="decision-saved"]').text()).toContain('结论已保存')
    expect(wrapper.get('[data-test="notification-error"]').text()).toContain('当前账号通知额度不足')
    expect(wrapper.get('[data-test="rejection-message"]').element.value).toBe(originalMessage)
    expect(wrapper.get('[data-test="candidate-batch-bar"]').text()).toContain('已选择 1 人')
    expect(wrapper.get('[data-test="queue-rejection-notice"]').text()).toContain('重试加入通知队列')
  })

  it('allows an HR conclusion update but blocks the notification action for an already active notice', async () => {
    mockCompletePayload()
    const baseImplementation = apiMock.getMockImplementation()
    apiMock.mockImplementation((path, options) => path === 'recruitment/screening-results/?job=1'
      ? Promise.resolve(screeningPayload([{ ...screeningRow, notification: { status: 'running' } }]))
      : baseImplementation(path, options))
    const { wrapper } = await mountView({ job: '1', view: 'candidates' })
    await flushPromises()

    await wrapper.get('tr[data-application-id="11"] input[type="checkbox"]').setValue(true)
    await wrapper.get('[data-test="bulk-fail"]').trigger('click')
    await wrapper.get('[data-test="screening-reason"]').setValue('岗位匹配度不足')
    await wrapper.get('[data-test="screening-acknowledgement"]').setValue(true)

    expect(wrapper.get('[data-test="notice-duplicate-warning"]').text()).toContain('防止重复联系')
    expect(wrapper.get('[data-test="queue-rejection-notice"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="save-fail-decision"]').attributes('disabled')).toBeUndefined()
  })

  it('does not let slow lazy detail responses overwrite a candidate selected afterwards', async () => {
    mockCompletePayload()
    const baseImplementation = apiMock.getMockImplementation()
    let resolveOldStructure
    let resolveOldAssessments
    let resolveOldTasks
    const oldStructure = new Promise((resolve) => { resolveOldStructure = resolve })
    const oldAssessments = new Promise((resolve) => { resolveOldAssessments = resolve })
    const oldTasks = new Promise((resolve) => { resolveOldTasks = resolve })
    const secondRow = {
      ...screeningRow,
      rank: 2,
      application: { ...screeningRow.application, id: 12 },
      candidate: { id: 22, name: '陈沐', current_title: '产品运营', current_city: '杭州' },
      resume: { ...resume, id: 32, application: 12, candidate: 22, candidate_name: '陈沐' },
      structure: { ...structureSummary, id: 42, resume: 32 },
      assessment: { ...assessmentSummary, id: 52, structured_resume: 42, total_score: 79 },
    }
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/screening-results/?job=1') return Promise.resolve(screeningPayload([screeningRow, secondRow]))
      if (path === 'recruitment/structured-resumes/?resume=31') return oldStructure
      if (path === 'recruitment/resume-assessments/?resume=31') return oldAssessments
      if (path === 'recruitment/ai-tasks/?resume=31') return oldTasks
      if (path === 'recruitment/structured-resumes/?resume=32') return Promise.resolve({ results: [{ ...structure, id: 42, resume: 32, data: { ...structure.data, summary: '快速切换后的新详情' } }] })
      if (path === 'recruitment/resume-assessments/?resume=32') return Promise.resolve({ results: [{ ...assessment, id: 52, resume: 32, structured_resume: 42, total_score: 79 }] })
      if (path === 'recruitment/ai-tasks/?resume=32') return Promise.resolve({ results: [] })
      return baseImplementation(path, options)
    })
    const { wrapper } = await mountView({ job: '1', view: 'candidates' })
    await flushPromises()

    await wrapper.get('[data-test="view-candidate-11"]').trigger('click')
    await Promise.resolve()
    await wrapper.get('[data-test="view-candidate-12"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="dialog"][aria-label="证据详情"]').text()).toContain('快速切换后的新详情')

    resolveOldStructure({ results: [{ ...structure, data: { ...structure.data, summary: '不应覆盖的新旧冲突详情' } }] })
    resolveOldAssessments({ results: [assessment] })
    resolveOldTasks({ results: [] })
    await flushPromises()
    expect(wrapper.get('[role="dialog"][aria-label="证据详情"]').text()).toContain('快速切换后的新详情')
    expect(wrapper.get('[role="dialog"][aria-label="证据详情"]').text()).not.toContain('不应覆盖的新旧冲突详情')
  })
})
