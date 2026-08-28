import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import RecruitmentTaskExecutionModal from './RecruitmentTaskExecutionModal.vue'

const task = {
  id: '3580f43f',
  job: 51,
  job_title: '前置部署工程师',
  automation_plan: 301,
  automation_plan_kind: 'active_resume_search',
  automation_plan_effective_state: 'running',
  status: 'running',
  account_name: '系统自动执行',
  started_at: '2026-08-28T09:30:12+08:00',
  node_runs: [
    { id: 1, node_type: 'prepare', status: 'succeeded', completed_at: '2026-08-28T09:30:42+08:00' },
    { id: 2, node_type: 'search', status: 'succeeded', completed_at: '2026-08-28T09:31:12+08:00' },
    { id: 3, node_type: 'search_and_pull_resumes', status: 'running', output: { searched_count: 86, scanned_count: 12, qualified_resume_count: 4 } },
    { id: 4, node_type: 'archive', status: 'pending' },
  ],
}

async function mountModal(overrides = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/recruitment/tasks/:planId', name: 'recruitment-task-detail', component: { template: '<div />' } }],
  })
  await router.push('/recruitment/tasks/301')
  await router.isReady()
  return mount(RecruitmentTaskExecutionModal, {
    props: { task: { ...task, ...overrides } },
    global: { plugins: [router] },
  })
}

describe('RecruitmentTaskExecutionModal', () => {
  it('matches the selected running-task hierarchy with real run values', async () => {
    const wrapper = await mountModal()

    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('68')
    expect(wrapper.text()).toContain('简历拉取与分析')
    expect(wrapper.text()).toContain('86')
    expect(wrapper.text()).toContain('12')
    expect(wrapper.text()).toContain('4')
    expect(wrapper.text()).toContain('下一步：结果归档')
    expect(wrapper.get('.execution-phases').findAll('li')).toHaveLength(4)
    expect(wrapper.get('.execution-record-link').attributes('href')).toContain('/recruitment/tasks/301?run=3580f43f')
  })

  it('surfaces a waiting-human state instead of showing the all-clear message', async () => {
    const wrapper = await mountModal({ automation_plan_effective_state: 'waiting_human', status: 'waiting_human' })

    expect(wrapper.text()).toContain('有事项需要 HR 处理')
    expect(wrapper.text()).not.toContain('暂无需要 HR 处理的事项')
  })
})
