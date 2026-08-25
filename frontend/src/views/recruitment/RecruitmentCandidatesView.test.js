import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import { useRecruitmentContextStore } from '@/stores/recruitmentContext'
import RecruitmentCandidatesView from './RecruitmentCandidatesView.vue'

const applications = [
  { id: 11, job: 1, job_title: 'Vue 前端工程师', stage: 'new', stage_label: '新候选人', owner_name: 'admin', resume_count: 1, candidate: { id: 1, name: '周晓宁', phone: '138****0001', email: 'zhou.xiaoning@example.com', current_title: '前端开发工程师', current_city: '北京' }, other_applications: [] },
  { id: 12, job: 1, job_title: 'Vue 前端工程师', stage: 'to_screen', stage_label: '初筛', owner_name: 'admin', resume_count: 0, candidate: { id: 2, name: '林雨薇', phone: '138****0002', email: 'lin.yuwei@example.com', current_title: '高级前端工程师', current_city: '上海' }, other_applications: [] },
]

const discoveries = [
  { id: 'd1', display_name: '林晓', current_title: '前端工程师', city: '北京', source_label: '推荐候选人', advantage: 'Vue 工程化', tags: ['Vue'], job_title: 'Vue 前端工程师', identity_quality: 'fingerprint', identity_quality_label: '组合指纹', imported_candidate: null },
]

function activateJob() {
  const context = useRecruitmentContextStore()
  context.jobs = [{ id: 1, title: 'Vue 前端工程师', department: '研发部', boss_account: 7, account_name: 'BOSS 测试账号', status: 'open' }]
  context.selectedJobId = '1'
  context.loaded = true
  context.loadedUserId = '7'
}

describe('RecruitmentCandidatesView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    activateJob()
    apiMock.mockReset()
    apiMock.mockImplementation((path) => {
      if (path.startsWith('recruitment/candidate-discoveries/?')) return Promise.resolve({ results: discoveries })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: true, counts: { jobs: 3, candidates: 10, applications: 10, resumes: 3 } })
      if (path.startsWith('recruitment/applications/')) {
        if (path === 'recruitment/applications/11/archive/') return Promise.resolve({ ...applications[0], archived_at: '2026-08-24T10:00:00Z' })
        if (path.includes('search=%E5%91%A8')) return Promise.resolve({ results: [applications[0]] })
        if (path.includes('stage=to_screen')) return Promise.resolve({ results: [applications[1]] })
        return Promise.resolve({ results: applications })
      }
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
  })

  it('loads only the selected job and removes duplicate job selectors', async () => {
    const wrapper = mount(RecruitmentCandidatesView)
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/applications/?job=1')
    expect(apiMock).toHaveBeenCalledWith('recruitment/candidate-discoveries/?imported=false&job=1')
    expect(wrapper.text()).toContain('周晓宁')
    expect(wrapper.find('select[aria-label="职位"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="discovery-job"]').exists()).toBe(false)
  })

  it('does not request mixed data before a job is selected', async () => {
    useRecruitmentContextStore().selectedJobId = ''
    apiMock.mockClear()

    const wrapper = mount(RecruitmentCandidatesView)
    await flushPromises()

    expect(wrapper.text()).toContain('请先选择在招职位')
    expect(apiMock.mock.calls.some(([path]) => path.startsWith('recruitment/applications/'))).toBe(false)
    expect(apiMock.mock.calls.some(([path]) => path.startsWith('recruitment/candidate-discoveries/'))).toBe(false)
  })

  it('filters applications by candidate search and stage', async () => {
    const wrapper = mount(RecruitmentCandidatesView)
    await flushPromises()

    await wrapper.get('[data-test="candidate-search"]').setValue('周')
    await flushPromises()
    expect(wrapper.text()).toContain('周晓宁')
    expect(wrapper.text()).not.toContain('林雨薇')

    await wrapper.get('[data-test="candidate-search"]').setValue('')
    await wrapper.get('[data-test="candidate-stage"]').setValue('to_screen')
    await flushPromises()
    expect(apiMock.mock.calls.some(([path]) => path.includes('job=1') && path.includes('stage=to_screen'))).toBe(true)
    expect(wrapper.text()).toContain('林雨薇')
  })

  it('opens job-specific application details and archives only that application', async () => {
    const wrapper = mount(RecruitmentCandidatesView, { global: { stubs: { teleport: { template: '<div><slot /></div>' } } } })
    await flushPromises()
    await wrapper.get('tbody tr').trigger('click')

    expect(wrapper.text()).toContain('138****0001')
    expect(wrapper.text()).toContain('Vue 前端工程师')
    expect(wrapper.text()).toContain('1 份简历')
    await wrapper.get('[data-test="archive-application"]').trigger('click')
    expect(wrapper.text()).toContain('移出当前职位')
    await wrapper.get('[data-test="confirm-archive"]').trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/applications/11/archive/', { method: 'POST' })
  })

  it('binds communication to the selected job account and application ids', async () => {
    apiMock.mockImplementation((path) => {
      if (path.startsWith('recruitment/candidate-discoveries/?')) return Promise.resolve({ results: discoveries })
      if (path.startsWith('recruitment/applications/')) return Promise.resolve({ results: applications })
      if (path === 'recruitment/communication-actions/prepare/') return Promise.resolve({ approval_id: 'approval-1', item_count: 1 })
      if (path === 'recruitment/automation-approvals/approval-1/approve/') return Promise.resolve({ batch: { id: 'batch-1' } })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: false, counts: {} })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const wrapper = mount(RecruitmentCandidatesView)
    await flushPromises()

    await wrapper.get('[data-test="application-check-11"]').setValue(true)
    await wrapper.get('[data-test="open-communication"]').trigger('click')
    await wrapper.get('[data-test="communication-action"]').setValue('request_resume')
    await wrapper.get('[data-test="confirm-communication"]').trigger('click')
    await flushPromises()

    const prepareCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/communication-actions/prepare/')
    expect(JSON.parse(prepareCall[1].body).application_ids).toEqual([11])
    expect(JSON.parse(prepareCall[1].body).boss_account).toBe(7)
  })
})
