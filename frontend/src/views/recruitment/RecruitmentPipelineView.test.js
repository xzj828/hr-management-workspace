import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentPipelineView from './RecruitmentPipelineView.vue'


const initialApplications = () => [
  { id: 11, candidate: { id: 1, name: '周晓宁', current_title: '前端开发工程师', current_city: '北京', resume_count: 1 }, job: 1, job_title: 'Vue 前端工程师', stage: 'new', stage_label: '新候选人', owner_name: 'admin' },
  { id: 12, candidate: { id: 2, name: '徐雯', current_title: '产品经理', current_city: '深圳', resume_count: 0 }, job: 2, job_title: '人事产品经理', stage: 'interviewing', stage_label: '面试中', owner_name: 'admin' },
]

describe('RecruitmentPipelineView', () => {
  beforeEach(() => {
    apiMock.mockReset()
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/applications/' && !options) return Promise.resolve({ results: initialApplications() })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: true, counts: { jobs: 3, candidates: 10, applications: 10, resumes: 3 } })
      if (path === 'recruitment/applications/11/') return Promise.resolve({ ...initialApplications()[0], stage: 'interviewing', stage_label: '面试中' })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
  })

  it('moves a candidate and persists the new stage', async () => {
    const wrapper = mount(RecruitmentPipelineView, { global: { stubs: { teleport: true } } })
    await flushPromises()

    await wrapper.get('[data-application-id="11"]').trigger('dragstart')
    await wrapper.get('[data-stage="interviewing"]').trigger('drop')
    await wrapper.get('[data-test="stage-reason"]').setValue('HR 完成人工复核')
    await wrapper.get('[data-test="confirm-stage-change"]').trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/applications/11/', {
      method: 'PATCH',
      body: JSON.stringify({ stage: 'interviewing', stage_reason: 'HR 完成人工复核' }),
    })
    expect(wrapper.get('[data-stage="interviewing"]').text()).toContain('周晓宁')
    expect(wrapper.get('[data-stage="new"]').text()).not.toContain('周晓宁')
  })

  it('rolls the card back when persistence fails', async () => {
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/applications/' && !options) return Promise.resolve({ results: initialApplications() })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: true, counts: { jobs: 3, candidates: 10, applications: 10, resumes: 3 } })
      if (path === 'recruitment/applications/11/') return Promise.reject(new Error('阶段保存失败'))
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const wrapper = mount(RecruitmentPipelineView, { global: { stubs: { teleport: true } } })
    await flushPromises()

    await wrapper.get('[data-application-id="11"]').trigger('dragstart')
    await wrapper.get('[data-stage="interviewing"]').trigger('drop')
    await wrapper.get('[data-test="stage-reason"]').setValue('HR 完成人工复核')
    await wrapper.get('[data-test="confirm-stage-change"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-stage="new"]').text()).toContain('周晓宁')
    expect(wrapper.text()).toContain('阶段保存失败')
  })
})
