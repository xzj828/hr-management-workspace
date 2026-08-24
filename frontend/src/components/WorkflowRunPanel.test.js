import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkflowRunPanel from './WorkflowRunPanel.vue'

describe('WorkflowRunPanel', () => {
  it('shows runtime progress and emits human and control actions', async () => {
    const wrapper = mount(WorkflowRunPanel, { props: { run: {
      id: 'run-1', template_name: '标准沟通', mode: 'dry_run', status: 'waiting_human', account_name: '主账号',
      node_runs: [{ id: 2, node_key: 'approval', status: 'waiting_human', attempt: 0 }],
      events: [{ id: 1, message: '等待 HR 确认', created_at: '2026-08-24T08:00:00Z' }],
    } } })
    expect(wrapper.text()).toContain('试运行 · 不会操作 BOSS')
    expect(wrapper.text()).toContain('等待 HR 确认')
    await wrapper.get('.workflow-run-node-actions .is-primary').trigger('click')
    await wrapper.get('.workflow-run-actions button').trigger('click')
    expect(wrapper.emitted('decision')[0][0]).toEqual({ nodeId: 2, approved: true })
    expect(wrapper.emitted('pause')).toHaveLength(1)
  })
})
