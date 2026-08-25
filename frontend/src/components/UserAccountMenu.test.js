import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import UserAccountMenu from './UserAccountMenu.vue'

const user = {
  username: 'hr-user',
  first_name: '小王',
  role_label: 'HR',
}

describe('UserAccountMenu', () => {
  it('keeps account actions hidden until the user trigger is opened', async () => {
    const wrapper = mount(UserAccountMenu, { props: { user } })
    const trigger = wrapper.get('[data-testid="account-trigger"]')

    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(trigger.find('.app-icon').exists()).toBe(true)
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)

    await trigger.trigger('click')

    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('[role="menu"]').text()).toContain('HR')
  })

  it('emits model settings and logout actions', async () => {
    const wrapper = mount(UserAccountMenu, { props: { user } })
    await wrapper.get('[data-testid="account-trigger"]').trigger('click')
    await wrapper.get('[data-testid="model-settings"]').trigger('click')
    expect(wrapper.emitted('model-settings')).toHaveLength(1)

    await wrapper.get('[data-testid="account-trigger"]').trigger('click')
    await wrapper.get('[data-testid="logout"]').trigger('click')
    expect(wrapper.emitted('logout')).toHaveLength(1)
  })

  it('supports menu arrow keys and restores focus on escape', async () => {
    const wrapper = mount(UserAccountMenu, { attachTo: document.body, props: { user } })
    const trigger = wrapper.get('[data-testid="account-trigger"]')
    await trigger.trigger('click')
    await wrapper.vm.$nextTick()
    const items = wrapper.findAll('[role="menuitem"]')

    expect(document.activeElement).toBe(items[0].element)
    await items[0].trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(items[1].element)
    await items[1].trigger('keydown', { key: 'Escape' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
  })
})
