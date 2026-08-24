import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CommunicationConfirmDrawer from './CommunicationConfirmDrawer.vue'

describe('CommunicationConfirmDrawer', () => {
  it('shows recipients and emits an editable confirmation snapshot', async () => {
    const wrapper = mount(CommunicationConfirmDrawer, {
      props: { candidates: [{ applicationId: 11, name: '周晓宁', jobTitle: 'Vue 前端工程师' }], accountName: '主账号' },
    })
    expect(wrapper.text()).toContain('周晓宁')
    expect(wrapper.text()).toContain('发送前最后确认')
    await wrapper.get('[data-test="communication-action"]').setValue('request_resume')
    await wrapper.get('[data-test="communication-message"]').setValue('请发送最新版 PDF 简历')
    await wrapper.get('[data-test="confirm-communication"]').trigger('click')
    expect(wrapper.emitted('confirm')[0][0].message).toBe('请发送最新版 PDF 简历')
  })
})
