import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppIcon from './AppIcon.vue'

describe('AppIcon', () => {
  it('renders a registered icon using currentColor', () => {
    const wrapper = mount(AppIcon, { props: { name: 'briefcase', size: 20 } })
    expect(wrapper.get('svg').attributes('width')).toBe('20')
    expect(wrapper.get('svg').attributes('height')).toBe('20')
    expect(wrapper.get('svg').attributes('style')).toContain('color: inherit')
    expect(wrapper.findAll('path').length).toBeGreaterThan(0)
  })

  it('hides decorative icons from assistive technology', () => {
    const wrapper = mount(AppIcon, { props: { name: 'dashboard' } })
    expect(wrapper.get('svg').attributes('aria-hidden')).toBe('true')
  })

  it('exposes a title for meaningful standalone icons', () => {
    const wrapper = mount(AppIcon, { props: { name: 'alert-circle', label: '异常提醒' } })
    expect(wrapper.get('svg').attributes('role')).toBe('img')
    expect(wrapper.get('title').text()).toBe('异常提醒')
  })

  it('does not silently render an unknown name', () => {
    expect(() => mount(AppIcon, { props: { name: 'not-real' } })).toThrow(/Unknown icon/)
  })

  it('keeps the result-center headset and ranking crown as real SVG paths', () => {
    for (const name of ['headset', 'crown']) {
      const wrapper = mount(AppIcon, { props: { name } })
      expect(wrapper.get('svg').attributes('viewBox')).toBe('0 0 24 24')
      expect(wrapper.get('path').attributes('d')).toBeTruthy()
    }
  })
})
