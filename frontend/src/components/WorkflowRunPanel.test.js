import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkflowRunPanel from './WorkflowRunPanel.vue'

const RouterLinkStub = { props: ['to'], template: '<a><slot /></a>' }

describe('WorkflowRunPanel', () => {
  it('shows runtime progress and emits human and control actions', async () => {
    const wrapper = mount(WorkflowRunPanel, { props: { run: {
      id: 'run-1', template_name: '标准沟通', mode: 'dry_run', status: 'waiting_human', account_name: '主账号',
      node_runs: [{ id: 2, node_key: 'approval', status: 'waiting_human', attempt: 0 }],
      events: [{ id: 1, message: '等待 HR 确认', created_at: '2026-08-24T08:00:00Z' }],
    } } })
    expect(wrapper.text()).toContain('本次为试运行，不会操作招聘平台')
    expect(wrapper.text()).toContain('需要你处理')
    expect(wrapper.text()).not.toContain('等待 HR 确认')
    expect(wrapper.text()).not.toContain('approval')
    await wrapper.get('.workflow-run-node-actions .is-primary').trigger('click')
    await wrapper.get('.workflow-run-actions button').trigger('click')
    expect(wrapper.emitted('decision')[0][0]).toEqual({ nodeId: 2, approved: true })
    expect(wrapper.emitted('pause')).toHaveLength(1)
  })

  it('labels approval-backed waiting nodes as a real confirmation', () => {
    const wrapper = mount(WorkflowRunPanel, {
      props: {
        run: {
          id: 'run-2', status: 'waiting_human', mode: 'formal', account_name: 'BOSS 账号', events: [],
          node_runs: [{ id: 22, node_key: 'search_pull', status: 'waiting_human', attempt: 0, output: { approval_id: 'approval-1' } }],
        },
      },
    })

    expect(wrapper.text()).toContain('搜索候选人并获取简历')
    expect(wrapper.text()).toContain('同意并继续')
    expect(wrapper.text()).toContain('暂不执行')
  })

  it('routes plan-managed lifecycle controls to the task detail while keeping human decisions', async () => {
    const wrapper = mount(WorkflowRunPanel, {
      props: {
        run: {
          id: 'run-plan', job: 51, status: 'waiting_human', mode: 'formal', account_name: 'BOSS 账号',
          automation_plan_revision: 402, automation_plan: 301,
          events: [],
          node_runs: [
            { id: 23, node_key: 'human-check', status: 'waiting_human', attempt: 0 },
            { id: 24, node_key: 'search', status: 'failed', attempt: 1 },
          ],
        },
      },
      global: { stubs: { RouterLink: RouterLinkStub } },
    })

    expect(wrapper.find('.workflow-run-actions').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('重新处理')
    expect(wrapper.get('[data-test="plan-managed-guidance"]').text()).toContain('任务设置与启停在任务详情中管理')
    expect(wrapper.getComponent(RouterLinkStub).props('to')).toEqual({
      name: 'recruitment-task-detail',
      params: { planId: '301' },
      query: { job: '51', run: 'run-plan', view: 'tasks' },
    })

    await wrapper.get('.workflow-run-node-actions .is-primary').trigger('click')
    expect(wrapper.emitted('decision')[0][0]).toEqual({ nodeId: 23, approved: true })
    expect(wrapper.emitted('pause')).toBeUndefined()
    expect(wrapper.emitted('retry')).toBeUndefined()
  })
})
