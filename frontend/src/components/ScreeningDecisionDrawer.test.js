import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ScreeningDecisionDrawer from './ScreeningDecisionDrawer.vue'

const candidates = [{ applicationId: 11, name: '林溪', title: '高级产品经理', notificationStatus: 'not_requested' }]

describe('ScreeningDecisionDrawer', () => {
  afterEach(() => document.body.innerHTML = '')

  it('requires an internal reason and explicit human acknowledgement', async () => {
    const wrapper = mount(ScreeningDecisionDrawer, { attachTo: document.body, props: { mode: 'pass', candidates, jobTitle: '产品经理' } })
    expect(document.activeElement).toBe(wrapper.get('[data-test="screening-reason"]').element)
    expect(wrapper.get('[data-test="save-pass-decision"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="screening-reason"]').setValue('综合面试前筛选，经验匹配')
    await wrapper.get('[data-test="screening-acknowledgement"]').setValue(true)
    await wrapper.get('[data-test="save-pass-decision"]').trigger('click')
    expect(wrapper.emitted('confirm')[0][0]).toEqual({ notify: false, reason: '综合面试前筛选，经验匹配', message: expect.any(String) })
    wrapper.unmount()
  })

  it('keeps the external message neutral and exposes separate save/queue actions', async () => {
    const wrapper = mount(ScreeningDecisionDrawer, { props: { mode: 'fail', candidates, jobTitle: '产品经理', accountName: '招聘主账号' } })
    expect(wrapper.get('[data-test="rejection-message"]').element.value).toContain('暂时无法继续推进')
    expect(wrapper.get('[data-test="rejection-message"]').attributes('readonly')).toBeDefined()
    expect(wrapper.text()).not.toContain('立即发送')
    await wrapper.get('[data-test="screening-reason"]').setValue('本轮岗位数量有限')
    await wrapper.get('[data-test="screening-acknowledgement"]').setValue(true)
    await wrapper.get('[data-test="queue-rejection-notice"]').trigger('click')
    expect(wrapper.emitted('confirm')[0][0].notify).toBe(true)
  })

  it('distinguishes a saved decision from a failed notification and preserves the form', async () => {
    const wrapper = mount(ScreeningDecisionDrawer, { props: { mode: 'fail', candidates, decisionSaved: true, notificationError: '当前适配器需要人工介入' } })
    expect(wrapper.get('[data-test="decision-saved"]').text()).toContain('结论已保存')
    expect(wrapper.get('[data-test="notification-error"]').text()).toContain('通知未加入队列')
    expect(wrapper.get('[data-test="queue-rejection-notice"]').text()).toContain('重试加入通知队列')
  })

  it('blocks duplicate queueing when any selected candidate already has an active or successful notice', async () => {
    const wrapper = mount(ScreeningDecisionDrawer, {
      props: { mode: 'fail', candidates: [{ ...candidates[0], notificationStatus: 'succeeded' }] },
    })
    await wrapper.get('[data-test="screening-reason"]').setValue('招聘名额已满')
    await wrapper.get('[data-test="screening-acknowledgement"]').setValue(true)
    expect(wrapper.get('[data-test="notice-duplicate-warning"]').text()).toContain('防止重复联系')
    expect(wrapper.get('[data-test="queue-rejection-notice"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="save-fail-decision"]').attributes('disabled')).toBeUndefined()
  })

  it('treats an uncertain external result as notification-ineligible while keeping HR-only save available', async () => {
    const wrapper = mount(ScreeningDecisionDrawer, {
      props: { mode: 'fail', accountName: '招聘主账号', candidates: [{ ...candidates[0], notificationStatus: 'failed', notificationErrorCode: 'send_result_uncertain' }] },
    })
    await wrapper.get('[data-test="screening-reason"]').setValue('岗位匹配度不足')
    await wrapper.get('[data-test="screening-acknowledgement"]').setValue(true)
    expect(wrapper.get('[data-test="queue-rejection-notice"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="save-fail-decision"]').attributes('disabled')).toBeUndefined()
  })

  it('does not offer an automatic retry for a persisted failed notice', async () => {
    const wrapper = mount(ScreeningDecisionDrawer, {
      props: { mode: 'fail', accountName: '招聘主账号', candidates: [{ ...candidates[0], notificationStatus: 'failed' }] },
    })
    await wrapper.get('[data-test="screening-reason"]').setValue('本轮岗位名额有限')
    await wrapper.get('[data-test="screening-acknowledgement"]').setValue(true)
    expect(wrapper.get('[data-test="notice-duplicate-warning"]').text()).toContain('失败或结果不确定')
    expect(wrapper.get('[data-test="queue-rejection-notice"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="save-fail-decision"]').attributes('disabled')).toBeUndefined()
  })

  it('closes with Escape', async () => {
    const wrapper = mount(ScreeningDecisionDrawer, { props: { mode: 'fail', candidates } })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
