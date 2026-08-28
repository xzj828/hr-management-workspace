import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentTaskDetailView from './RecruitmentTaskDetailView.vue'

function planFixture({ state = 'running', archivedAt = null, controlVersion = 4, runId = 'run-77', kind = 'active_resume_search', revisionId = 401, controlGeneration = 6, startAuthorized = kind === 'passive_resume', monitoring = null } = {}) {
  return {
    id: 301,
    job: 51,
    job_title: 'Python 后端工程师',
    kind,
    desired_state: state === 'stopping' ? 'stopped' : state,
    effective_state: state,
    control_version: controlVersion,
    control_generation: controlGeneration,
    current_revision: {
      id: revisionId,
      revision: 2,
      kind,
      workflow_version: 91,
      workflow_mode: 'managed',
      config: {
        source: 'search',
        keyword: 'Python',
        target_resume_count: 5,
        max_scan_count: 30,
        core: ['3 年 Python 经验'],
        bonus: [],
        ...(startAuthorized ? {
          execution_authorization: {
            source: 'plan_start',
            actor_id: 1,
            actions: ['request_resume'],
          },
        } : {}),
      },
    },
    current_run: runId ? { id: runId, status: state } : null,
    monitoring,
    archived_at: archivedAt,
    updated_at: '2026-08-27T02:00:00+08:00',
  }
}

function taskFixture({ id = 'run-77', state = 'running', kind = 'active_resume_search', revision = 2, current = true, archivedAt = null, generation = 6 } = {}) {
  const runStatus = { completed: 'succeeded', stopped: 'cancelled' }[state] || state
  return {
    id,
    job: 51,
    job_title: 'Python 后端工程师',
    status: runStatus,
    automation_plan: 301,
    automation_plan_revision: 401,
    automation_plan_kind: kind,
    automation_plan_revision_number: revision,
    automation_plan_current_run: current,
    automation_plan_effective_state: current ? state : null,
    automation_generation: generation,
    archived_at: archivedAt,
    updated_at: '2026-08-27T02:00:00+08:00',
  }
}

async function mountView(apiImplementation, query = {}, selectedTask = taskFixture()) {
  apiMock.mockImplementation((...args) => {
    const [path, options] = args
    if (!options && path === `recruitment/workflow-runs/${selectedTask.id}/`) {
      return Promise.resolve(selectedTask)
    }
    return apiImplementation(...args)
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/recruitment/tasks', name: 'recruitment-tasks', component: { template: '<div>tasks</div>' } },
      { path: '/recruitment/tasks/:planId', name: 'recruitment-task-detail', component: RecruitmentTaskDetailView },
      { path: '/recruitment/workbench', name: 'recruitment-workbench', component: { template: '<div>workbench</div>' } },
      { path: '/recruitment/results', name: 'recruitment-results', component: { template: '<div>results</div>' } },
    ],
  })
  await router.push({ name: 'recruitment-task-detail', params: { planId: '301' }, query })
  await router.isReady()
  const wrapper = mount(RecruitmentTaskDetailView, {
    global: {
      plugins: [router],
      stubs: {
        teleport: true,
        RecruitmentResultsView: { template: '<div data-test="embedded-results">embedded results</div>' },
      },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('RecruitmentTaskDetailView', () => {
  let wrapper

  beforeEach(() => {
    apiMock.mockReset()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
  })

  it('restores a running plan and presents results-center styled task controls', async () => {
    const current = planFixture()
    ;({ wrapper } = await mountView((path) => {
      if (path === 'recruitment/automation-plans/301/') return Promise.resolve(current)
      return Promise.reject(new Error(`unexpected path: ${path}`))
    }))

    expect(wrapper.get('[data-test="task-state"]').text()).toContain('运行中')
    expect(wrapper.find('.task-detail-card').exists()).toBe(true)
    expect(wrapper.find('[data-test="embedded-results"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="stop-task"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="stop-modify-task"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="archive-task"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="results-nav-business"]').attributes('href')).toContain('job=51')
    expect(wrapper.get('[data-test="results-nav-business"]').attributes('href')).toContain('run=run-77')
  })

  it('stops an active task before returning its immutable revision to the workbench', async () => {
    const running = planFixture()
    const stopping = planFixture({ state: 'stopping', controlVersion: 5 })
    let router
    ;({ wrapper, router } = await mountView((path, options) => {
      if (path === 'recruitment/automation-plans/301/') return Promise.resolve(running)
      if (path === 'recruitment/automation-plans/301/stop/' && options?.method === 'POST') return Promise.resolve(stopping)
      return Promise.reject(new Error(`unexpected path: ${path}`))
    }))

    await wrapper.get('[data-test="stop-modify-task"]').trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/automation-plans/301/stop/', expect.objectContaining({ method: 'POST' }))
    expect(router.currentRoute.value.name).toBe('recruitment-workbench')
    expect(router.currentRoute.value.query).toMatchObject({ job: '51', editPlan: '301', step: 'standard' })
  })

  it('maintains passive resume approvals on the result task page', async () => {
    const passive = planFixture({ kind: 'passive_resume', revisionId: 451, controlGeneration: 8, startAuthorized: false })
    const approval = {
      id: 'approval-1',
      expires_at: '2026-08-27T10:30:00+08:00',
      payload: {
        message: '您好，方便发送一份简历吗？',
        items: [{ name: '陈翔', job_title: 'Python 后端工程师' }],
      },
    }
    ;({ wrapper } = await mountView((path, options) => {
      if (path === 'recruitment/automation-plans/301/') return Promise.resolve(passive)
      if (path.startsWith('recruitment/automation-approvals/?')) return Promise.resolve({ results: [approval] })
      if (path === 'recruitment/automation-approvals/approval-1/approve/' && options?.method === 'POST') {
        return Promise.resolve({ ...approval, batch: { id: 'batch-1', steps: [{ status: 'pending' }] } })
      }
      return Promise.reject(new Error(`unexpected path: ${path}`))
    }))

    expect(wrapper.get('[data-test="resume-approval-inbox"]').text()).toContain('陈翔')
    expect(wrapper.get('[data-test="resume-approval-inbox"]').text()).toContain('您好，方便发送一份简历吗？')
    const approvalQuery = apiMock.mock.calls.find(([path]) => path.startsWith('recruitment/automation-approvals/?'))[0]
    expect(approvalQuery).toContain('automation_plan_revision=451')
    expect(approvalQuery).toContain('automation_generation=8')

    await wrapper.get('[data-test="approve-resume-approval-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('发送批次已创建')
    expect(wrapper.find('[data-test="resume-approval-approval-1"]').exists()).toBe(false)
  })

  it('shows plan-start authorization without loading a second confirmation inbox', async () => {
    const passive = planFixture({ kind: 'passive_resume', revisionId: 452, controlGeneration: 9 })
    ;({ wrapper } = await mountView((path) => {
      if (path === 'recruitment/automation-plans/301/') return Promise.resolve(passive)
      return Promise.reject(new Error(`unexpected path: ${path}`))
    }))

    expect(wrapper.get('[data-test="plan-start-authorization"]').text()).toContain('不再要求 HR 重复确认')
    expect(wrapper.find('[data-test="resume-approval-inbox"]').exists()).toBe(false)
    expect(apiMock.mock.calls.some(([path]) => path.startsWith('recruitment/automation-approvals/?'))).toBe(false)
  })

  it('shows attachment uncertainty as a fail-closed monitoring warning', async () => {
    const passive = planFixture({
      kind: 'passive_resume',
      monitoring: {
        last_checked_at: '2026-08-27T09:28:54+08:00',
        status: 'succeeded',
        discovered_count: 1,
        synced_count: 1,
        message_failed_count: 0,
        attachment_failed_count: 1,
        error_code: 'conversation_attachment_read_incomplete',
      },
    })
    ;({ wrapper } = await mountView((path) => {
      if (path === 'recruitment/automation-plans/301/') return Promise.resolve(passive)
      return Promise.reject(new Error(`unexpected path: ${path}`))
    }))

    const monitoringCard = wrapper.get('[data-test="passive-monitoring"]')
    expect(monitoringCard.text()).toContain('监听发现异常')
    expect(monitoringCard.text()).toContain('附件状态尚未核验')
    expect(monitoringCard.text()).toContain('1 / 1')
  })

  it('deletes only a terminal task visibility record and can restore it', async () => {
    const stopped = planFixture({ state: 'stopped' })
    const stoppedTask = taskFixture({ state: 'stopped' })
    const archivedTask = taskFixture({ state: 'stopped', archivedAt: '2026-08-27T02:05:00+08:00' })
    ;({ wrapper } = await mountView((path, options) => {
      if (path === 'recruitment/automation-plans/301/') return Promise.resolve(stopped)
      if (path === 'recruitment/workflow-runs/run-77/archive/' && options?.method === 'POST') return Promise.resolve(archivedTask)
      if (path === 'recruitment/workflow-runs/run-77/restore/?automation_plan=1&archived=1' && options?.method === 'POST') return Promise.resolve(stoppedTask)
      return Promise.reject(new Error(`unexpected path: ${path}`))
    }, {}, stoppedTask))

    await wrapper.get('[data-test="archive-task"]').trigger('click')
    await wrapper.get('[data-test="confirm-archive"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="task-state"]').text()).toContain('已删除')
    expect(wrapper.find('[data-test="restore-task"]').exists()).toBe(true)

    await wrapper.get('[data-test="restore-task"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="task-state"]').text()).toContain('已停止')
    expect(wrapper.find('[data-test="archive-task"]').exists()).toBe(true)
  })

  it('pins a historical card to its own revision and hides current-plan controls', async () => {
    const current = planFixture({ state: 'running', runId: 'run-new' })
    const historical = taskFixture({ id: 'run-old', state: 'completed', revision: 1, current: false, generation: 1 })
    ;({ wrapper } = await mountView((path) => {
      if (path === 'recruitment/automation-plans/301/') return Promise.resolve(current)
      return Promise.reject(new Error(`unexpected path: ${path}`))
    }, { run: 'run-old' }, historical))

    expect(wrapper.text()).toContain('方案 V1')
    expect(wrapper.text()).toContain('运行 #run-old')
    expect(wrapper.get('[data-test="task-state"]').text()).toContain('本轮已完成')
    expect(wrapper.find('[data-test="stop-task"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="modify-task"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="restart-task"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="archive-task"]').exists()).toBe(true)
  })

  it('shows a recoverable error state when the plan cannot be read', async () => {
    ;({ wrapper } = await mountView(() => Promise.reject(Object.assign(new Error('任务不存在'), { status: 404 }))))

    expect(wrapper.find('[data-test="task-detail-error"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('任务不存在')
    expect(wrapper.text()).toContain('重新加载')
    expect(wrapper.text()).toContain('返回招聘任务')
  })
})
