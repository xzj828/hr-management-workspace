import { mount } from '@vue/test-utils'
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
})
