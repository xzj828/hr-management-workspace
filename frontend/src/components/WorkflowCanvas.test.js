import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkflowCanvas from './WorkflowCanvas.vue'

describe('WorkflowCanvas', () => {
  it('starts with a safe approval path and emits a version snapshot', async () => {
    const wrapper = mount(WorkflowCanvas, { props: { accounts: [{ id: 7, name: '主账号' }] } })
    expect(wrapper.text()).toContain('人工确认')
    expect(wrapper.text()).toContain('打招呼')
    await wrapper.get('[data-test="workflow-name"]').setValue('标准沟通')
    await wrapper.get('[data-test="save-workflow"]').trigger('click')
    const payload = wrapper.emitted('save')[0][0]
    expect(payload.accountId).toBe(7)
    expect(payload.nodes.some((node) => node.type === 'human_approval')).toBe(true)
    expect(payload.edges.length).toBeGreaterThan(0)
  })
})
