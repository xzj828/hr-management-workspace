import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentTasksView from './RecruitmentTasksView.vue'
import ArchiveConfirmModal from '@/components/ArchiveConfirmModal.vue'

const taskFixture = (overrides = {}) => ({
  id: 'run-77',
  job: 51,
  job_title: 'Python 后端工程师',
  automation_plan: 301,
  automation_plan_kind: 'active_resume_search',
  automation_plan_revision: 401,
  automation_plan_revision_number: 2,
  automation_plan_current_run: true,
  automation_plan_effective_state: 'running',
  status: 'running',
  archived_at: null,
  updated_at: '2026-08-27T02:00:00+08:00',
  ...overrides,
})

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/recruitment/tasks', name: 'recruitment-tasks', component: RecruitmentTasksView },
      { path: '/recruitment/tasks/:planId', name: 'recruitment-task-detail', component: { template: '<div>detail</div>' } },
      { path: '/recruitment/results', name: 'recruitment-results', component: { template: '<div>results</div>' } },
      { path: '/recruitment/workbench', name: 'recruitment-workbench', component: { template: '<div>workbench</div>' } },
    ],
  })
  await router.push({ name: 'recruitment-tasks' })
  await router.isReady()
  const wrapper = mount(RecruitmentTasksView, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('RecruitmentTasksView', () => {
  let wrapper

  beforeEach(() => {
    apiMock.mockReset()
  })
  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
  })

  it('opens the selected two-column task execution card from the whole task card', async () => {
    apiMock.mockResolvedValue({
      results: [
        taskFixture(),
        taskFixture({ id: 'run-88', job: 52, job_title: '招聘产品经理', automation_plan: 302, automation_plan_kind: 'passive_resume', automation_plan_effective_state: 'waiting_human', status: 'waiting_human' }),
      ],
    })
    ;({ wrapper } = await mountView())

    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-runs/?automation_plan=1')
    expect(wrapper.get('[data-test="results-nav-tasks"]').classes()).toContain('is-active')
    expect(wrapper.text()).toContain('招聘任务')
    expect(wrapper.text()).toContain('Python 后端工程师')
    expect(wrapper.text()).toContain('招聘产品经理')
    expect(wrapper.text()).toContain('等待人工')
    expect(wrapper.get('.tasks-card-grid').findAll('.tasks-card')).toHaveLength(2)
    expect(wrapper.get('[data-test="task-scroll-region"]').attributes('tabindex')).toBe('0')
    expect(wrapper.find('.tasks-table__head').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('查看与维护')
    expect(wrapper.find('.tasks-card__cover').exists()).toBe(true)
    expect(wrapper.get('[data-test="archive-task-run-77"]').attributes()).toHaveProperty('disabled')

    await wrapper.get('[data-test="task-row-run-77"]').trigger('click')
    expect(wrapper.get('[role="dialog"]').attributes('aria-label')).toBe('任务执行中')
    expect(wrapper.get('.recruitment-drawer').classes()).toContain('is-task-execution')
    expect(wrapper.get('[data-test="task-execution-report"]').text()).toContain('当前正在执行')
    expect(wrapper.get('[data-test="task-execution-report"]').text()).toContain('运行中')
    expect(wrapper.get('[data-test="task-execution-report"]').text()).toContain('暂无需要 HR 处理的事项')
    expect(wrapper.get('.execution-phases').findAll('li')).toHaveLength(4)
    expect(wrapper.get('.execution-record-link').attributes('href')).toContain('/recruitment/tasks/301')
  })

  it('keeps every execution as a separate card even when runs share one plan and job', async () => {
    apiMock.mockResolvedValue({
      results: [
        taskFixture({ id: 'run-old', automation_plan_current_run: false, automation_plan_effective_state: null, status: 'succeeded', automation_plan_revision_number: 1 }),
        taskFixture({ id: 'run-new', automation_plan_revision_number: 2 }),
      ],
    })
    ;({ wrapper } = await mountView())

    expect(wrapper.get('.tasks-card-grid').findAll('.tasks-card')).toHaveLength(2)
    expect(wrapper.find('[data-test="task-row-run-old"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="task-row-run-new"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('方案 V1')
    expect(wrapper.text()).toContain('方案 V2')
  })

  it('filters tasks by status, kind and keyword without mixing jobs', async () => {
    apiMock.mockResolvedValue({
      results: [
        taskFixture(),
        taskFixture({ id: 'run-88', job: 52, job_title: '招聘产品经理', automation_plan: 302, automation_plan_kind: 'passive_resume', automation_plan_effective_state: 'waiting_human', status: 'waiting_human' }),
        taskFixture({ id: 'run-99', job: 53, job_title: '测试工程师', automation_plan: 303, automation_plan_effective_state: 'stopped', status: 'cancelled' }),
      ],
    })
    ;({ wrapper } = await mountView())

    await wrapper.get('[data-test="task-state-filter"]').setValue('waiting')
    expect(wrapper.find('[data-test="task-row-run-77"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="task-row-run-88"]').exists()).toBe(true)

    await wrapper.get('[data-test="task-state-filter"]').setValue('all')
    await wrapper.get('[data-test="task-kind-filter"]').setValue('passive_resume')
    expect(wrapper.find('[data-test="task-row-run-88"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="task-row-run-99"]').exists()).toBe(false)

    await wrapper.get('[data-test="task-kind-filter"]').setValue('all')
    await wrapper.get('[data-test="task-search"]').setValue('测试')
    expect(wrapper.find('[data-test="task-row-run-99"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="task-row-run-88"]').exists()).toBe(false)
  })

  it('omits the redundant summary and current/deleted task rows', async () => {
    apiMock.mockResolvedValue({ results: [taskFixture()] })
    ;({ wrapper } = await mountView())

    expect(wrapper.find('.tasks-summary').exists()).toBe(false)
    expect(wrapper.find('.tasks-panel__header').exists()).toBe(false)
    expect(wrapper.find('[data-test="show-archived-tasks"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('自动更新于')
    expect(apiMock).not.toHaveBeenCalledWith('recruitment/workflow-runs/?automation_plan=1&archived=1')
  })

  it('shows a retryable error without hiding the create-task entry', async () => {
    apiMock.mockImplementation((path) => path
      ? Promise.reject(new Error('服务暂不可用'))
      : Promise.resolve({ results: [] }))
    ;({ wrapper } = await mountView())

    expect(wrapper.find('[data-test="tasks-error"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('服务暂不可用')
    expect(wrapper.text()).toContain('创建新任务')
    expect(wrapper.text()).toContain('重新加载')
  })

  it('archives a terminal run directly from its card and removes only that card', async () => {
    const terminalTask = taskFixture({
      id: 'run-done',
      automation_plan_effective_state: null,
      status: 'succeeded',
    })
    const otherTask = taskFixture({
      id: 'run-other',
      automation_plan: 302,
      automation_plan_effective_state: null,
      status: 'cancelled',
    })
    apiMock.mockImplementation((path, options = {}) => {
      if (path === 'recruitment/workflow-runs/?automation_plan=1') return Promise.resolve({ results: [terminalTask, otherTask] })
      if (path === 'recruitment/workflow-runs/run-done/archive/' && options.method === 'POST') {
        return Promise.resolve({ ...terminalTask, archived_at: '2026-08-27T12:00:00Z' })
      }
      return Promise.reject(new Error(`unexpected request: ${path}`))
    })
    ;({ wrapper } = await mountView())

    await wrapper.get('[data-test="archive-task-run-done"]').trigger('click')
    const confirmModal = wrapper.getComponent(ArchiveConfirmModal)
    expect(confirmModal.props('description')).toContain('仅这一次任务会从当前列表移除')
    confirmModal.vm.$emit('confirm')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/workflow-runs/run-done/archive/', { method: 'POST' })
    expect(wrapper.find('[data-test="task-row-run-done"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="task-row-run-other"]').exists()).toBe(true)
  })

  it('keeps the card and confirmation context when card deletion fails', async () => {
    const terminalTask = taskFixture({
      id: 'run-failed-delete',
      automation_plan_effective_state: null,
      status: 'failed',
    })
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/workflow-runs/?automation_plan=1') return Promise.resolve({ results: [terminalTask] })
      if (path === 'recruitment/workflow-runs/run-failed-delete/archive/') return Promise.reject(new Error('删除服务暂不可用'))
      return Promise.reject(new Error(`unexpected request: ${path}`))
    })
    ;({ wrapper } = await mountView())

    await wrapper.get('[data-test="archive-task-run-failed-delete"]').trigger('click')
    wrapper.getComponent(ArchiveConfirmModal).vm.$emit('confirm')
    await flushPromises()

    expect(wrapper.find('[data-test="task-row-run-failed-delete"]').exists()).toBe(true)
    expect(wrapper.getComponent(ArchiveConfirmModal).props('error')).toBe('删除服务暂不可用')
  })

})
