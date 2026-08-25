import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentPipelineView from './RecruitmentPipelineView.vue'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'


const initialApplications = () => [
  { id: 11, candidate: { id: 1, name: '周晓宁', current_title: '前端开发工程师', current_city: '北京' }, job: 1, job_title: 'Vue 前端工程师', stage: 'new', stage_label: '新候选人', owner_name: 'admin', resume_count: 1 },
]

describe('RecruitmentPipelineView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const context = useRecruitmentContextStore()
    context.jobs = [{ id: 1, title: 'Vue 前端工程师', headcount: 3, boss_account: 7 }]
    context.selectedJobId = '1'
    context.loaded = true
    apiMock.mockReset()
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/applications/?job=1' && !options) return Promise.resolve({ results: initialApplications() })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: true, counts: { jobs: 3, candidates: 10, applications: 10, resumes: 3 } })
      if (path === 'recruitment/applications/11/') return Promise.resolve({ ...initialApplications()[0], stage: 'interviewing', stage_label: '面试中' })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
  })

  it('requires a job and never loads a mixed pipeline', async () => {
    useRecruitmentContextStore().selectedJobId = ''
    apiMock.mockClear()
    const wrapper = mount(RecruitmentPipelineView)
    await flushPromises()

    expect(wrapper.text()).toContain('请先选择在招职位')
    expect(apiMock.mock.calls.some(([path]) => path.startsWith('recruitment/applications/'))).toBe(false)
  })

  it('offers one direct next step when the selected job has no candidates', async () => {
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/applications/?job=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: false, counts: {} })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const RouterLink = { name: 'RouterLink', props: ['to'], template: '<a><slot /></a>' }
    const wrapper = mount(RecruitmentPipelineView, { global: { stubs: { RouterLink } } })
    await flushPromises()

    expect(wrapper.text()).toContain('该职位还没有候选人')
    expect(wrapper.findComponent(RouterLink).props('to')).toEqual({ name: 'recruitment-candidates', query: { job: '1' } })
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
      if (path === 'recruitment/applications/?job=1' && !options) return Promise.resolve({ results: initialApplications() })
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
