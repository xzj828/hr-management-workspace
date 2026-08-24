import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TaskProgressBar from './TaskProgressBar.vue'

describe('TaskProgressBar', () => {
  it('renders accessible staged progress', () => {
    const wrapper = mount(TaskProgressBar, { props: { status: 'running' } })
    const progress = wrapper.get('[role="progressbar"]')

    expect(progress.attributes('aria-valuenow')).toBe('62')
    expect(wrapper.text()).toContain('正在读取 BOSS 职位')
  })

  it('marks reduced motion without a looping animation', () => {
    const wrapper = mount(TaskProgressBar, { props: { status: 'leased', reducedMotion: true } })

    expect(wrapper.get('.task-progress').classes()).toContain('is-reduced-motion')
    expect(wrapper.find('.is-pulsing').exists()).toBe(false)
  })
})
