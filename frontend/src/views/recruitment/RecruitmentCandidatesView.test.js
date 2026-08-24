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

const discoveries = [
  { id: 'd1', display_name: '林晓', current_title: '前端工程师', city: '北京', source_label: '推荐候选人', advantage: 'Vue 工程化', tags: ['Vue'], job_title: 'Vue 前端工程师', identity_quality: 'fingerprint', identity_quality_label: '组合指纹', imported_candidate: null },
]

describe('RecruitmentCandidatesView', () => {
  beforeEach(() => {
    apiMock.mockReset()
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/jobs/') return Promise.resolve({ results: [{ id: 1, title: 'Vue 前端工程师', boss_account: 7 }] })
      if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [{ id: 7, name: 'BOSS 测试账号' }] })
      if (path.startsWith('recruitment/candidate-discoveries/?')) return Promise.resolve({ results: discoveries })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: true, counts: { jobs: 3, candidates: 10, applications: 10, resumes: 3 } })
      if (path.startsWith('recruitment/candidates/')) {
        if (path === 'recruitment/candidates/1/archive/') return Promise.resolve({ ...candidates[0], archived_at: '2026-08-24T10:00:00Z' })
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

  it('removes a candidate from the active library with confirmation', async () => {
    const wrapper = mount(RecruitmentCandidatesView, { global: { stubs: { teleport: { template: '<div><slot /></div>' } } } })
    await flushPromises()
    await wrapper.get('tbody tr').trigger('click')

    await wrapper.get('[data-test="archive-candidate"]').trigger('click')
    expect(wrapper.text()).toContain('移出候选人库')
    await wrapper.get('[data-test="confirm-archive"]').trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/candidates/1/archive/', { method: 'POST' })
  })

  it('selects discoveries and imports them into the library', async () => {
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/jobs/') return Promise.resolve({ results: [{ id: 1, title: 'Vue 前端工程师', boss_account: 7 }] })
      if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [{ id: 7, name: 'BOSS 测试账号' }] })
      if (path.startsWith('recruitment/candidate-discoveries/?')) return Promise.resolve({ results: discoveries })
      if (path === 'recruitment/candidate-discoveries/import-selected/') return Promise.resolve({ total: 1, created_candidates: 1 })
      if (path.startsWith('recruitment/candidates/')) return Promise.resolve({ results: candidates })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: false, counts: {} })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const wrapper = mount(RecruitmentCandidatesView)
    await flushPromises()
    await wrapper.get('[data-test="candidate-tab-discovery"]').trigger('click')
    await wrapper.get('[data-test="discovery-check-d1"]').setValue(true)
    expect(wrapper.get('[data-test="discovery-batch-bar"]').text()).toContain('已选择 1 人')

    await wrapper.get('[data-test="import-selected"]').trigger('click')
    await flushPromises()

    expect(apiMock.mock.calls.some(([path, options]) => path === 'recruitment/candidate-discoveries/import-selected/' && options.method === 'POST')).toBe(true)
    expect(wrapper.get('[data-test="candidate-tab-library"]').classes()).toContain('active')
  })

  it('selects library candidates and creates an approved communication batch', async () => {
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/jobs/') return Promise.resolve({ results: [{ id: 1, title: 'Vue 前端工程师', boss_account: 7 }] })
      if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [{ id: 7, name: 'BOSS 测试账号' }] })
      if (path.startsWith('recruitment/candidate-discoveries/?')) return Promise.resolve({ results: [] })
      if (path.startsWith('recruitment/candidates/')) return Promise.resolve({ results: candidates })
      if (path === 'recruitment/communication-actions/prepare/') return Promise.resolve({ approval_id: 'approval-1', item_count: 1 })
      if (path === 'recruitment/automation-approvals/approval-1/approve/') return Promise.resolve({ batch: { id: 'batch-1' } })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const wrapper = mount(RecruitmentCandidatesView)
    await flushPromises()
    await wrapper.get('[data-test="candidate-check-1"]').setValue(true)
    expect(wrapper.get('[data-test="library-contact-bar"]').text()).toContain('已选择 1 人')
    await wrapper.get('[data-test="open-communication"]').trigger('click')
    await wrapper.get('[data-test="communication-action"]').setValue('request_resume')
    await wrapper.get('[data-test="confirm-communication"]').trigger('click')
    await flushPromises()
    expect(apiMock.mock.calls.some(([path]) => path === 'recruitment/communication-actions/prepare/')).toBe(true)
    expect(apiMock.mock.calls.some(([path]) => path === 'recruitment/automation-approvals/approval-1/approve/')).toBe(true)
  })
})
