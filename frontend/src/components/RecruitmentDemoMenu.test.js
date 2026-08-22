import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({ api: apiMock }))

import RecruitmentDemoMenu from './RecruitmentDemoMenu.vue'


const loadedStatus = {
  loaded: true,
  counts: { jobs: 3, candidates: 10, applications: 10, resumes: 3 },
}

describe('RecruitmentDemoMenu', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    apiMock.mockReset()
    apiMock.mockResolvedValue(loadedStatus)
  })

  it('shows persisted demo counts in a low-emphasis popover', async () => {
    const wrapper = mount(RecruitmentDemoMenu)
    await flushPromises()

    expect(wrapper.text()).toContain('演示数据')
    expect(wrapper.text()).not.toContain('10 位候选人')
    await wrapper.get('[data-test="demo-trigger"]').trigger('click')

    expect(wrapper.text()).toContain('3 个职位')
    expect(wrapper.text()).toContain('10 位候选人')
    expect(wrapper.text()).toContain('3 份简历')
  })

  it('loads data and notifies the parent to refresh', async () => {
    const wrapper = mount(RecruitmentDemoMenu)
    await flushPromises()
    await wrapper.get('[data-test="demo-trigger"]').trigger('click')
    await wrapper.get('[data-test="demo-load"]').trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/demo-data/', { method: 'POST' })
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('does not clear data when confirmation is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = mount(RecruitmentDemoMenu)
    await flushPromises()
    await wrapper.get('[data-test="demo-trigger"]').trigger('click')
    await wrapper.get('[data-test="demo-clear"]').trigger('click')

    expect(apiMock).not.toHaveBeenCalledWith('recruitment/demo-data/', { method: 'DELETE' })
  })
})
