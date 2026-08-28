import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ArchiveConfirmModal from './ArchiveConfirmModal.vue'

describe('ArchiveConfirmModal', () => {
  it('explains the consequence and emits an explicit confirmation', async () => {
    const wrapper = mount(ArchiveConfirmModal, { props: {
      title: '移除 BOSS 账号', name: '招聘主账号',
      description: '账号历史任务仍会保留，可从归档记录恢复。', actionLabel: '确认移除',
    }, global: { stubs: { teleport: { template: '<div><slot /></div>' } } } })

    expect(wrapper.text()).toContain('招聘主账号')
    expect(wrapper.text()).toContain('历史任务仍会保留')
    await wrapper.get('[data-test="confirm-archive"]').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('exposes a modal dialog, focuses cancel, and cannot close while saving', async () => {
    const wrapper = mount(ArchiveConfirmModal, {
      attachTo: document.body,
      props: {
        title: '永久删除模型配置', name: '主模型', description: '删除后不可恢复。',
        actionLabel: '永久删除', saving: false,
      },
      global: { stubs: { teleport: true } },
    })
    await flushPromises()

    const dialog = wrapper.get('[role="dialog"]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(document.activeElement.textContent).toContain('取消')

    await wrapper.setProps({ saving: true })
    await wrapper.get('.modal-mask').trigger('mousedown')
    await dialog.trigger('keydown', { key: 'Escape' })
    await wrapper.get('button[aria-label="关闭"]').trigger('click')
    expect(wrapper.emitted('close')).toBeUndefined()
    expect(wrapper.get('button[aria-label="关闭"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('scopes the readable regular-weight typography to business-result dialogs', () => {
    const wrapper = mount(ArchiveConfirmModal, {
      props: {
        title: '一键清除任务结果', name: '前置部署工程师 · 5 个任务',
        description: '将当前岗位中已经结束的任务结果从当前列表归档。',
        businessResultsTypography: true,
      },
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.get('[role="dialog"]').classes()).toContain('modal-panel--business-results')
  })
})
