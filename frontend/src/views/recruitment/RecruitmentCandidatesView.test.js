import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentCandidatesView from './RecruitmentCandidatesView.vue'


const candidates = [
  { id: 1, name: '周晓宁', phone: '138****0001', email: 'zhou.xiaoning@example.com', current_title: '前端开发工程师', current_city: '北京', resume_count: 1, applications: [{ id: 11, job: 1, job_title: 'Vue 前端工程师', stage: 'new', stage_label: '新候选人', owner_name: 'admin' }] },
  { id: 2, name: '林雨薇', phone: '138****0002', email: 'lin.yuwei@example.com', current_title: '高级前端工程师', current_city: '上海', resume_count: 0, applications: [{ id: 12, job: 1, job_title: 'Vue 前端工程师', stage: 'to_screen', stage_label: '初筛', owner_name: 'admin' }] },
]

describe('RecruitmentCandidatesView', () => {
  beforeEach(() => {
    apiMock.mockReset()
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/jobs/') return Promise.resolve({ results: [{ id: 1, title: 'Vue 前端工程师' }] })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: true, counts: { jobs: 3, candidates: 10, applications: 10, resumes: 3 } })
      if (path.startsWith('recruitment/candidates/')) {
        if (path.includes('search=%E5%91%A8')) return Promise.resolve({ results: [candidates[0]] })
        if (path.includes('stage=to_screen')) return Promise.resolve({ results: [candidates[1]] })
        return Promise.resolve({ results: candidates })
      }
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
  })

  it('filters candidates by search and stage', async () => {
    const wrapper = mount(RecruitmentCandidatesView)
    await flushPromises()
    expect(wrapper.text()).toContain('周晓宁')
    expect(wrapper.text()).toContain('林雨薇')

    await wrapper.get('[data-test="candidate-search"]').setValue('周')
    await flushPromises()
    expect(wrapper.text()).toContain('周晓宁')
    expect(wrapper.text()).not.toContain('林雨薇')

    await wrapper.get('[data-test="candidate-search"]').setValue('')
    await wrapper.get('[data-test="candidate-stage"]').setValue('to_screen')
    await flushPromises()
    expect(apiMock.mock.calls.some(([path]) => path.includes('stage=to_screen'))).toBe(true)
    expect(wrapper.text()).toContain('林雨薇')
  })

  it('opens complete candidate details from a row', async () => {
    const wrapper = mount(RecruitmentCandidatesView)
    await flushPromises()
    await wrapper.get('tbody tr').trigger('click')

    expect(wrapper.text()).toContain('138****0001')
    expect(wrapper.text()).toContain('zhou.xiaoning@example.com')
    expect(wrapper.text()).toContain('Vue 前端工程师')
    expect(wrapper.text()).toContain('admin')
    expect(wrapper.text()).toContain('1 份简历')
  })
})
