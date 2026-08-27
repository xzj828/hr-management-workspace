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

  it('locks results-center greeting batches to one shared greeting message', async () => {
    const wrapper = mount(CommunicationConfirmDrawer, {
      props: {
        candidates: [
          { applicationId: 11, name: '周晓宁', jobTitle: 'Vue 前端工程师' },
          { applicationId: 12, name: '陈晨', jobTitle: 'Vue 前端工程师' },
        ],
        accountName: '主账号',
        fixedAction: 'greet',
        excludedCount: 1,
      },
    })

    expect(wrapper.text()).toContain('确认批量打招呼 2 位候选人')
    expect(wrapper.text()).toContain('本批统一')
    expect(wrapper.text()).toContain('另有 1 位')
    expect(wrapper.find('[data-test="communication-action"]').exists()).toBe(false)
    await wrapper.get('[data-test="communication-message"]').setValue('你好，想和你聊聊这个岗位。')
    await wrapper.get('[data-test="confirm-communication"]').trigger('click')
    expect(wrapper.emitted('confirm')[0][0]).toMatchObject({
      action: 'greet',
      message: '你好，想和你聊聊这个岗位。',
    })
  })
})
