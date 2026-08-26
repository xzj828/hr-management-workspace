import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  api: vi.fn(),
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import { api } from '@/api'
import ModelSwitcher from './ModelSwitcher.vue'

const profiles = [
  { id: 1, name: '快速模型', api_url: 'https://fast.example/v1', model: 'fast', has_api_key: true, key_last4: '1234', is_active: true },
  { id: 2, name: '深度模型', api_url: 'https://deep.example/v1', model: 'deep', has_api_key: true, key_last4: '5678', is_active: false },
]

describe('ModelSwitcher', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.mockReset()
    api.mockImplementation((path) => {
      if (path === 'account/model-profiles/') return Promise.resolve({ results: profiles })
      if (path === 'account/model-profiles/2/activate/') return Promise.resolve({ ...profiles[1], is_active: true })
      return Promise.reject(new Error(`unexpected ${path}`))
    })
  })

  it('uses a clear model switch label and exposes saved profiles', async () => {
    const wrapper = mount(ModelSwitcher, { global: { stubs: { ModelProfileDrawer: true } } })
    await flushPromises()

    expect(wrapper.get('.model-switcher__trigger').text()).toContain('切换模型')
    expect(wrapper.text()).not.toContain('Copilot')
    await wrapper.get('.model-switcher__trigger').trigger('click')
    expect(wrapper.findAll('[role="radio"]')).toHaveLength(2)
    expect(wrapper.get('[aria-checked="true"]').text()).toContain('当前使用')
  })

  it('uses the compact headset SVG on the result-center shell without removing the menu', async () => {
    const wrapper = mount(ModelSwitcher, { props: { compact: true }, global: { stubs: { ModelProfileDrawer: true } } })
    await flushPromises()

    expect(wrapper.get('.model-switcher__trigger').attributes('aria-label')).toBe('切换模型')
    expect(wrapper.get('.model-switcher__trigger svg').attributes('viewBox')).toBe('0 0 24 24')
    expect(wrapper.get('.model-switcher__trigger').text()).toBe('')
    await wrapper.get('.model-switcher__trigger').trigger('click')
    expect(wrapper.findAll('[role="radio"]')).toHaveLength(2)
  })

  it('switches to another profile and updates the active label', async () => {
    const wrapper = mount(ModelSwitcher, { global: { stubs: { ModelProfileDrawer: true } } })
    await flushPromises()
    await wrapper.get('.model-switcher__trigger').trigger('click')
    await wrapper.findAll('[role="radio"]')[1].trigger('click')
    await flushPromises()

    expect(api).toHaveBeenCalledWith('account/model-profiles/2/activate/', { method: 'POST' })
    expect(wrapper.get('.model-switcher__trigger').text()).toContain('深度模型')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })

  it('keeps the menu and current model visible when switching fails', async () => {
    api.mockImplementation((path) => {
      if (path === 'account/model-profiles/') return Promise.resolve({ results: profiles })
      if (path === 'account/model-profiles/2/activate/') return Promise.reject(new Error('模型服务暂不可用'))
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    const wrapper = mount(ModelSwitcher, { global: { stubs: { ModelProfileDrawer: true } } })
    await flushPromises()
    await wrapper.get('.model-switcher__trigger').trigger('click')
    await wrapper.findAll('[role="radio"]')[1].trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(wrapper.get('[role="alert"]').text()).toContain('模型服务暂不可用')
    expect(wrapper.get('.model-switcher__trigger').text()).toContain('快速模型')
    expect(wrapper.findAll('[role="radio"]')[1].attributes('disabled')).toBeUndefined()
  })

  it('recovers from a list error through the visible retry action', async () => {
    let listAttempts = 0
    api.mockImplementation((path) => {
      if (path !== 'account/model-profiles/') return Promise.reject(new Error(`unexpected ${path}`))
      listAttempts += 1
      return listAttempts === 1
        ? Promise.reject(new Error('模型列表加载失败'))
        : Promise.resolve({ results: profiles })
    })
    const wrapper = mount(ModelSwitcher, { global: { stubs: { ModelProfileDrawer: true } } })
    await flushPromises()
    await wrapper.get('.model-switcher__trigger').trigger('click')

    expect(wrapper.get('[role="alert"]').text()).toContain('模型列表加载失败')
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.findAll('[role="radio"]')).toHaveLength(2)
  })

  it('supports arrow-key navigation and returns focus on escape', async () => {
    const wrapper = mount(ModelSwitcher, { attachTo: document.body, global: { stubs: { ModelProfileDrawer: true } } })
    await flushPromises()
    const trigger = wrapper.get('.model-switcher__trigger')
    await trigger.trigger('click')
    await flushPromises()
    const options = wrapper.findAll('[role="radio"]')

    expect(document.activeElement).toBe(options[0].element)
    await options[0].trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(options[1].element)
    await options[1].trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
  })

  it('keeps an empty state actionable', async () => {
    api.mockResolvedValue({ results: [] })
    const wrapper = mount(ModelSwitcher, { global: { stubs: { ModelProfileDrawer: true } } })
    await flushPromises()
    await wrapper.get('.model-switcher__trigger').trigger('click')

    expect(wrapper.text()).toContain('尚未配置模型')
    expect(wrapper.get('.model-switcher__add').text()).toContain('新增自定义模型')
  })
})
