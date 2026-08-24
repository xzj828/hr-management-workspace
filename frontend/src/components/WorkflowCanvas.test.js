import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import WorkflowCanvas from './WorkflowCanvas.vue'

describe('WorkflowCanvas', () => {
  let wrapper

  afterEach(() => wrapper?.unmount())

  it('starts with a safe approval path and emits a version snapshot', async () => {
    wrapper = mount(WorkflowCanvas, { props: { accounts: [{ id: 7, name: '主账号' }] } })
    expect(wrapper.text()).toContain('人工确认')
    expect(wrapper.text()).toContain('打招呼')
    await wrapper.get('[data-test="workflow-name"]').setValue('标准沟通')
    await wrapper.get('[data-test="save-workflow"]').trigger('click')
    const payload = wrapper.emitted('save')[0][0]
    expect(payload.accountId).toBe(7)
    expect(payload.nodes.some((node) => node.type === 'human_approval')).toBe(true)
    expect(payload.edges.length).toBeGreaterThan(0)
  })

  it('deletes a selected node together with all connected edges', async () => {
    wrapper = mount(WorkflowCanvas, { props: { accounts: [{ id: 7, name: '主账号' }] } })

    await wrapper.get('[data-node-key="screen"]').trigger('click')
    await wrapper.get('[data-test="remove-selection"]').trigger('click')
    await wrapper.get('[data-test="save-workflow"]').trigger('click')

    const payload = wrapper.emitted('save')[0][0]
    expect(payload.nodes.some((node) => node.key === 'screen')).toBe(false)
    expect(payload.edges.some((edge) => edge.source === 'screen' || edge.target === 'screen')).toBe(false)
  })

  it('selects and deletes a connection without deleting its nodes', async () => {
    wrapper = mount(WorkflowCanvas, { props: { accounts: [{ id: 7, name: '主账号' }] } })

    await wrapper.get('[data-edge-key="source-screen"]').trigger('click')
    await wrapper.get('[data-test="remove-selection"]').trigger('click')
    await wrapper.get('[data-test="save-workflow"]').trigger('click')

    const payload = wrapper.emitted('save')[0][0]
    expect(payload.nodes.some((node) => node.key === 'screen')).toBe(true)
    expect(payload.edges).not.toContainEqual({ source: 'source', target: 'screen' })
  })

  it('moves an existing node continuously with pointer dragging', async () => {
    wrapper = mount(WorkflowCanvas, { props: { accounts: [{ id: 7, name: '主账号' }] }, attachTo: document.body })
    vi.spyOn(wrapper.get('[data-test="workflow-canvas"]').element, 'getBoundingClientRect').mockReturnValue({
      left: 0, top: 0, right: 1100, bottom: 600, width: 1100, height: 600, x: 0, y: 0, toJSON: () => {},
    })

    await wrapper.get('[data-node-key="screen"]').trigger('pointerdown', { clientX: 250, clientY: 150, button: 0 })
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 520, clientY: 310, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointerup', { clientX: 520, clientY: 310, bubbles: true }))
    await wrapper.get('[data-test="save-workflow"]').trigger('click')

    const screen = wrapper.emitted('save')[0][0].nodes.find((node) => node.key === 'screen')
    expect(screen.position.x).toBeGreaterThan(400)
    expect(screen.position.y).toBeGreaterThan(250)
  })

  it('loads a saved version for rearrangement and keeps its template identity', async () => {
    const snapshot = {
      templateId: 12,
      name: '人才池流程',
      accountId: 7,
      nodes: [
        { key: 'source-a', type: 'search', label: '搜索', position: { x: 40, y: 80 } },
        { key: 'end-a', type: 'end', label: '结束', position: { x: 320, y: 80 } },
      ],
      edges: [{ source: 'source-a', target: 'end-a' }],
    }
    wrapper = mount(WorkflowCanvas, { props: { accounts: [{ id: 7, name: '主账号' }], snapshot } })

    expect(wrapper.find('[data-node-key="source"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="workflow-name"]').element.value).toBe('人才池流程')
    await wrapper.get('[data-test="save-workflow"]').trigger('click')

    expect(wrapper.emitted('save')[0][0].templateId).toBe(12)
    expect(wrapper.emitted('save')[0][0].nodes).toHaveLength(2)
  })

  it('adds library nodes and reconnects them through explicit input and output ports', async () => {
    wrapper = mount(WorkflowCanvas, { props: { accounts: [{ id: 7, name: '主账号' }] } })

    await wrapper.get('[data-test="workflow-library-wait_reply"]').trigger('click')
    const added = wrapper.findAll('[data-node-key]').at(-1)
    const addedKey = added.attributes('data-node-key')
    await wrapper.get('[data-node-key="greet"] .workflow-node__port--output').trigger('click')
    await wrapper.get(`[data-node-key="${addedKey}"] .workflow-node__port--input`).trigger('click')
    await wrapper.get('[data-test="save-workflow"]').trigger('click')

    const payload = wrapper.emitted('save')[0][0]
    expect(payload.nodes.find((node) => node.key === addedKey)?.type).toBe('wait_reply')
    expect(payload.edges).toContainEqual({ source: 'greet', target: addedKey })
  })

  it('drags an output port to a chosen input port with a live preview', async () => {
    wrapper = mount(WorkflowCanvas, { props: { accounts: [{ id: 7, name: '主账号' }] }, attachTo: document.body })
    vi.spyOn(wrapper.get('[data-test="workflow-canvas"]').element, 'getBoundingClientRect').mockReturnValue({
      left: 0, top: 0, right: 1100, bottom: 600, width: 1100, height: 600, x: 0, y: 0, toJSON: () => {},
    })

    await wrapper.get('[data-node-key="source"] .workflow-node__port--output').trigger('pointerdown', { clientX: 196, clientY: 157, button: 0, pointerId: 1 })
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 520, clientY: 220, bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-test="connection-preview"]').exists()).toBe(true)
    await wrapper.get('[data-node-key="end"] .workflow-node__port--input').trigger('pointerup', { clientX: 842, clientY: 157, pointerId: 1 })
    await wrapper.get('[data-test="save-workflow"]').trigger('click')

    expect(wrapper.emitted('save')[0][0].edges).toContainEqual({ source: 'source', target: 'end' })
  })

  it('rejects cycle connections and explains the graph error', async () => {
    wrapper = mount(WorkflowCanvas, { props: { accounts: [{ id: 7, name: '主账号' }] } })
    vi.spyOn(wrapper.get('[data-test="workflow-canvas"]').element, 'getBoundingClientRect').mockReturnValue({
      left: 0, top: 0, right: 1100, bottom: 600, width: 1100, height: 600, x: 0, y: 0, toJSON: () => {},
    })
    await wrapper.get('[data-node-key="end"] .workflow-node__port--output').trigger('pointerdown', { clientX: 996, clientY: 157, button: 0, pointerId: 2 })
    await wrapper.get('[data-node-key="source"] .workflow-node__port--input').trigger('pointerup', { clientX: 42, clientY: 157, pointerId: 2 })

    expect(wrapper.text()).toContain('流程不能形成循环')
    await wrapper.get('[data-test="save-workflow"]').trigger('click')
    expect(wrapper.emitted('save')[0][0].edges).not.toContainEqual({ source: 'end', target: 'source' })
  })

  it('reconfigures a selected node and persists the configuration', async () => {
    wrapper = mount(WorkflowCanvas, { props: { accounts: [{ id: 7, name: '主账号' }] } })
    await wrapper.get('[data-node-key="greet"]').trigger('click')
    expect(wrapper.find('[data-test="workflow-node-config"]').exists()).toBe(true)
    await wrapper.get('[data-test="node-label"]').setValue('首次问候')
    await wrapper.get('.workflow-node-config textarea').setValue('您好，想和您沟通这个岗位。')
    await wrapper.get('[data-test="save-workflow"]').trigger('click')

    const node = wrapper.emitted('save')[0][0].nodes.find((item) => item.key === 'greet')
    expect(node.label).toBe('首次问候')
    expect(node.config.message).toContain('沟通')
  })
})
