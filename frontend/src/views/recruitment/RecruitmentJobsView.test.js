import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentDemoMenu from '@/components/RecruitmentDemoMenu.vue'
import { useAuthStore } from '@/stores/auth'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'
import RecruitmentJobsView from './RecruitmentJobsView.vue'


const jobs = [
  { id: 1, title: 'Vue 前端工程师', department: '研发中心', headcount: 2, owner_name: 'admin', candidate_count: 3, status: 'open', jd: '负责 Vue 3 页面开发。', account_name: null, is_demo: true, updated_at: '2026-08-22T10:00:00Z' },
  { id: 2, title: '人事产品经理', department: '产品中心', headcount: 1, owner_name: 'admin', candidate_count: 4, status: 'open', jd: '负责人事产品规划。', account_name: null, is_demo: true, updated_at: '2026-08-22T10:00:00Z' },
  { id: 3, title: '实施顾问', department: '客户成功部', headcount: 2, owner_name: 'admin', candidate_count: 3, status: 'paused', jd: '负责项目实施。', account_name: null, is_demo: true, updated_at: '2026-08-22T10:00:00Z' },
]

describe('RecruitmentJobsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useAuthStore().user = { id: 7, username: 'hr' }
    const context = useRecruitmentContextStore()
    context.jobs = jobs.slice(0, 2)
    context.loaded = true
    context.loadedUserId = '7'
    apiMock.mockReset()
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/jobs/') return Promise.resolve({ results: jobs })
      if (path === 'recruitment/jobs/?status=open') return Promise.resolve({ results: jobs.slice(1) })
      if (path === 'recruitment/jobs/1/archive/') return Promise.resolve({ ...jobs[0], archived_at: '2026-08-24T10:00:00Z' })
      if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [{ id: 8, name: '北京账号', login_status: 'ready' }] })
      if (path === 'recruitment/jobs/sync/') return Promise.resolve({ task_id: 'task-1', status: 'pending' })
      if (path === 'recruitment/rpa-tasks/task-1/') return Promise.resolve({
        id: 'task-1',
        status: 'succeeded',
        result: { sync: { created: 2, updated: 1, unchanged: 4, total: 7 } },
      })
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

  it('runs one-click position sync and shows persisted counts', async () => {
    const wrapper = mount(RecruitmentJobsView)
    await flushPromises()

    await wrapper.get('[data-test="sync-account"]').setValue('8')
    await wrapper.get('[data-test="sync-positions"]').trigger('click')
    await flushPromises()

    const syncCall = apiMock.mock.calls.find(([path]) => path === 'recruitment/jobs/sync/')
    expect(syncCall).toBeTruthy()
    expect(syncCall[1].method).toBe('POST')
    expect(JSON.parse(syncCall[1].body)).toMatchObject({ boss_account: 8 })
    expect(JSON.parse(syncCall[1].body).request_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(wrapper.text()).toContain('新增 2 · 更新 1 · 未变化 4 · 共 7 个职位')
    expect(apiMock.mock.calls.filter(([path]) => path === 'recruitment/jobs/')).toHaveLength(2)
    expect(apiMock).toHaveBeenCalledWith('recruitment/jobs/?status=open')
    expect(useRecruitmentContextStore().jobs).toEqual(jobs.slice(1))
  })

  it('does not refresh the shared job selector when sync needs human action', async () => {
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/jobs/') return Promise.resolve({ results: jobs })
      if (path === 'recruitment/boss-accounts/') return Promise.resolve({ results: [{ id: 8, name: '北京账号' }] })
      if (path === 'recruitment/jobs/sync/') return Promise.resolve({ task_id: 'task-human', status: 'pending' })
      if (path === 'recruitment/rpa-tasks/task-human/') return Promise.resolve({ id: 'task-human', status: 'waiting_human' })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const oldJobs = useRecruitmentContextStore().jobs
    const wrapper = mount(RecruitmentJobsView)
    await flushPromises()

    await wrapper.get('[data-test="sync-positions"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('需要在隔离浏览器中完成验证')
    expect(apiMock.mock.calls.some(([path]) => path === 'recruitment/jobs/?status=open')).toBe(false)
    expect(useRecruitmentContextStore().jobs).toEqual(oldJobs)
  })

  it('archives a saved position from its detail drawer', async () => {
    const wrapper = mount(RecruitmentJobsView, { global: { stubs: { teleport: { template: '<div><slot /></div>' } } } })
    await flushPromises()
    await wrapper.get('tbody tr').trigger('click')

    await wrapper.get('[data-test="archive-job"]').trigger('click')
    expect(wrapper.text()).toContain('关闭并归档职位')
    await wrapper.get('[data-test="confirm-archive"]').trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/jobs/1/archive/', { method: 'POST' })
  })
})
