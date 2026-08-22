import { createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace: vi.fn() }),
}))

import AppIcon from '@/components/AppIcon.vue'
import LoginView from './LoginView.vue'

describe('LoginView icons', () => {
  it('uses a shield icon for the local-data assurance', () => {
    const wrapper = mount(LoginView, { global: { plugins: [createPinia()] } })
    expect(wrapper.get('.security-note').findComponent(AppIcon).props('name')).toBe('shield')
    expect(wrapper.get('.security-note').text()).not.toContain('●')
  })
})
