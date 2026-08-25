import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({ api: vi.fn(), listItems: (payload) => payload?.results || [] }))

import { api } from '@/api'
import ModelProfileDrawer from './ModelProfileDrawer.vue'

describe('ModelProfileDrawer', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.mockReset()
  })

  it('creates a custom profile without exposing the saved secret', async () => {
    api.mockResolvedValue({ id: 8, name: '自定义模型', api_url: 'https://models.example/v1', model: 'custom', has_api_key: true, key_last4: '3456', is_active: true })
    const wrapper = mount(ModelProfileDrawer)
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('自定义模型')
    await inputs[1].setValue('https://models.example/v1')
    await inputs[2].setValue('custom')
    await inputs[3].setValue('sk-secret-123456')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    const payload = JSON.parse(api.mock.calls[0][1].body)
    expect(payload).toEqual({ name: '自定义模型', api_url: 'https://models.example/v1', model: 'custom', api_key: 'sk-secret-123456', make_active: true })
    expect(wrapper.emitted('saved')[0][0].api_key).toBeUndefined()
  })

  it('leaves an existing masked key untouched when the key field is empty', async () => {
    const profile = { id: 3, name: '日常模型', api_url: 'https://models.example/v1', model: 'chat', has_api_key: true, key_last4: '9876', is_active: true }
    api.mockResolvedValue(profile)
    const wrapper = mount(ModelProfileDrawer, { props: { profile } })
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    const payload = JSON.parse(api.mock.calls[0][1].body)
    expect(payload.api_key).toBeUndefined()
    expect(wrapper.find('input[type="password"]').attributes('placeholder')).toContain('9876')
  })

  it('moves focus into the dialog and restores the opener after close', async () => {
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    const wrapper = mount(ModelProfileDrawer, { attachTo: document.body })
    await flushPromises()

    expect(document.activeElement).toBe(wrapper.findAll('input')[0].element)
    await wrapper.get('.model-drawer-close').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
    expect(document.activeElement).toBe(opener)
    opener.remove()
  })

  it('shows a server field error next to the form', async () => {
    const failure = new Error('请求失败')
    failure.status = 400
    failure.payload = { api_url: ['模型地址必须使用公网 HTTPS'] }
    api.mockRejectedValue(failure)
    const wrapper = mount(ModelProfileDrawer)
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('不安全模型')
    await inputs[1].setValue('http://localhost:8000/v1')
    await inputs[2].setValue('local')
    await inputs[3].setValue('sk-secret-123456')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('公网 HTTPS')
  })
})
