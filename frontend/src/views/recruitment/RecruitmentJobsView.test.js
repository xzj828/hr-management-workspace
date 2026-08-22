import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentDemoMenu from '@/components/RecruitmentDemoMenu.vue'
import RecruitmentJobsView from './RecruitmentJobsView.vue'


const jobs = [
  { id: 1, title: 'Vue 前端工程师', department: '研发中心', headcount: 2, owner_name: 'admin', candidate_count: 3, status: 'open', jd: '负责 Vue 3 页面开发。', account_name: null, is_demo: true, updated_at: '2026-08-22T10:00:00Z' },
  { id: 2, title: '人事产品经理', department: '产品中心', headcount: 1, owner_name: 'admin', candidate_count: 4, status: 'open', jd: '负责人事产品规划。', account_name: null, is_demo: true, updated_at: '2026-08-22T10:00:00Z' },
  { id: 3, title: '实施顾问', department: '客户成功部', headcount: 2, owner_name: 'admin', candidate_count: 3, status: 'paused', jd: '负责项目实施。', account_name: null, is_demo: true, updated_at: '2026-08-22T10:00:00Z' },
]

describe('RecruitmentJobsView', () => {
  beforeEach(() => {
    apiMock.mockReset()
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/jobs/') return Promise.resolve({ results: jobs })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: true, counts: { jobs: 3, candidates: 10, applications: 10, resumes: 3 } })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
  })

  it('renders three jobs and opens row details', async () => {
    const wrapper = mount(RecruitmentJobsView)
    await flushPromises()

    expect(wrapper.text()).toContain('Vue 前端工程师')
    expect(wrapper.text()).toContain('人事产品经理')
    expect(wrapper.text()).toContain('实施顾问')
    await wrapper.get('tbody tr').trigger('click')

    expect(wrapper.text()).toContain('负责 Vue 3 页面开发。')
    expect(wrapper.text()).toContain('内部演示数据')
  })

  it('reloads jobs after demo data changes', async () => {
    const wrapper = mount(RecruitmentJobsView)
    await flushPromises()

    wrapper.getComponent(RecruitmentDemoMenu).vm.$emit('changed')
    await flushPromises()

    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/jobs/')).toHaveLength(2)
  })
})
