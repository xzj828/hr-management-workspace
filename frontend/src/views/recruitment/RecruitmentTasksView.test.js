import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentTasksView from './RecruitmentTasksView.vue'

const planFixture = (overrides = {}) => ({
  id: 301,
  job: 51,
  job_title: 'Python 后端工程师',
  kind: 'active_resume_search',
  effective_state: 'running',
  current_revision: { id: 401, revision: 2 },
  current_run: { id: 'run-77', status: 'running' },
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

  beforeEach(() => apiMock.mockReset())
  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
  })

  it('exposes a visible cross-job task page inside the results center', async () => {
    apiMock.mockResolvedValue({
      results: [
        planFixture(),
        planFixture({ id: 302, job: 52, job_title: '招聘产品经理', kind: 'passive_resume', effective_state: 'waiting_human', current_run: { id: 'run-88', status: 'waiting_human' } }),
      ],
    })
    ;({ wrapper } = await mountView())

    expect(apiMock).toHaveBeenCalledWith('recruitment/automation-plans/')
    expect(wrapper.get('[data-test="results-nav-tasks"]').classes()).toContain('is-active')
    expect(wrapper.text()).toContain('招聘任务')
    expect(wrapper.text()).toContain('Python 后端工程师')
    expect(wrapper.text()).toContain('招聘产品经理')
    expect(wrapper.text()).toContain('等待人工')
    expect(wrapper.get('.tasks-card-grid').findAll('.tasks-card')).toHaveLength(2)
    expect(wrapper.find('.tasks-table__head').exists()).toBe(false)
    expect(wrapper.get('[data-test="open-task-301"]').attributes('href')).toContain('/recruitment/tasks/301')
  })

  it('filters tasks by status, kind and keyword without mixing jobs', async () => {
    apiMock.mockResolvedValue({
      results: [
        planFixture(),
        planFixture({ id: 302, job: 52, job_title: '招聘产品经理', kind: 'passive_resume', effective_state: 'waiting_human' }),
        planFixture({ id: 303, job: 53, job_title: '测试工程师', effective_state: 'stopped' }),
      ],
    })
    ;({ wrapper } = await mountView())

    await wrapper.get('[data-test="task-state-filter"]').setValue('waiting')
    expect(wrapper.find('[data-test="task-row-301"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="task-row-302"]').exists()).toBe(true)

    await wrapper.get('[data-test="task-state-filter"]').setValue('all')
    await wrapper.get('[data-test="task-kind-filter"]').setValue('passive_resume')
    expect(wrapper.find('[data-test="task-row-302"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="task-row-303"]').exists()).toBe(false)

    await wrapper.get('[data-test="task-kind-filter"]').setValue('all')
    await wrapper.get('[data-test="task-search"]').setValue('测试')
    expect(wrapper.find('[data-test="task-row-303"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="task-row-302"]').exists()).toBe(false)
  })

  it('omits the redundant summary and current/deleted task rows', async () => {
    apiMock.mockResolvedValue({ results: [planFixture()] })
    ;({ wrapper } = await mountView())

    expect(wrapper.find('.tasks-summary').exists()).toBe(false)
    expect(wrapper.find('.tasks-panel__header').exists()).toBe(false)
    expect(wrapper.find('[data-test="show-archived-tasks"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('自动更新于')
    expect(apiMock).not.toHaveBeenCalledWith('recruitment/automation-plans/?archived=1')
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

})
