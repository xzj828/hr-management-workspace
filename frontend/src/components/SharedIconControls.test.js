import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import ModalPanel from './ModalPanel.vue'
import RecruitmentDetailDrawer from './RecruitmentDetailDrawer.vue'

afterEach(() => {
  document.body.innerHTML = ''
})

describe('shared icon controls', () => {
  it('uses an accessible SVG close control in modal panels', () => {
    const wrapper = mount(ModalPanel, { props: { title: '编辑信息' } })
    const button = document.body.querySelector('button[aria-label="关闭"]')
    expect(button).not.toBeNull()
    expect(button.querySelector('.app-icon')).not.toBeNull()
    wrapper.unmount()
  })

  it('uses an accessible SVG close control in recruitment drawers', () => {
    const wrapper = mount(RecruitmentDetailDrawer, { props: { title: '候选人详情' } })
    const button = wrapper.get('button[aria-label="关闭"]')
    expect(button.find('.app-icon').exists()).toBe(true)
  })
})
