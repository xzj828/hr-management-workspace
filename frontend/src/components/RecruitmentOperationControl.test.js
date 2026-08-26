import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import RecruitmentOperationControl from './RecruitmentOperationControl.vue'

const RouterLinkStub = {
  props: ['to'],
  template: '<a :href="typeof to === \'string\' ? to : to.path"><slot /></a>',
}

function mountControl(state, props = {}) {
  return mount(RecruitmentOperationControl, {
    props: {
      plan: {
        id: 31,
        effective_state: state,
        current_revision: { id: 41, revision: 3 },
        current_run: { id: 'run-9', status: state },
      },
      resultsTo: { path: '/recruitment/results' },
      ...props,
    },
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
}

describe('RecruitmentOperationControl', () => {
  it('offers stop and stop-then-edit for a running server plan', async () => {
    const wrapper = mountControl('running')

    expect(wrapper.attributes('aria-live')).toBe('polite')
    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('运行中')
    expect(wrapper.text()).toContain('停止会取消尚未开始的待确认、打招呼和求简历任务')
    await wrapper.get('[data-test="stop-operation"]').trigger('click')
    await wrapper.get('[data-test="stop-and-modify-operation"]').trigger('click')

    expect(wrapper.emitted('stop')).toHaveLength(1)
    expect(wrapper.emitted('stop-modify')).toHaveLength(1)
    expect(wrapper.find('[data-test="operation-results"]').exists()).toBe(true)
  })

  it('offers resume and stop while paused and disables both during a command', () => {
    const wrapper = mountControl('paused', { busy: 'resume' })

    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('已暂停')
    expect(wrapper.get('[data-test="resume-operation"]').attributes()).toHaveProperty('disabled')
    expect(wrapper.get('[data-test="stop-operation"]').attributes()).toHaveProperty('disabled')
  })

  it('explains safe drain while stopping without claiming the browser action was killed', () => {
    const wrapper = mountControl('stopping')

    expect(wrapper.get('[data-test="operation-state"]').text()).toBe('正在停止')
    expect(wrapper.get('[data-test="operation-stopping"]').attributes()).toHaveProperty('disabled')
    expect(wrapper.text()).toContain('安全收尾')
    expect(wrapper.find('[data-test="restart-operation"]').exists()).toBe(false)
  })

  it.each([
    ['stopped', '已停止'],
    ['failed', '运行失败'],
    ['completed', '本轮已完成'],
  ])('offers edit and a new revision after %s', async (state, label) => {
    const wrapper = mountControl(state)

    expect(wrapper.get('[data-test="operation-state"]').text()).toBe(label)
    await wrapper.get('[data-test="modify-operation"]').trigger('click')
    await wrapper.get('[data-test="restart-operation"]').trigger('click')
    expect(wrapper.emitted('modify')).toHaveLength(1)
    expect(wrapper.emitted('restart')).toHaveLength(1)
  })

  it('keeps terminal restart visibly disabled when server status is not trustworthy', () => {
    const wrapper = mountControl('stopped', {
      restartDisabled: true,
      disabledReason: '任务状态同步失败，请等待自动刷新后再试。',
    })

    expect(wrapper.get('[data-test="restart-operation"]').attributes()).toHaveProperty('disabled')
    expect(wrapper.text()).toContain('任务状态同步失败')
  })
})
