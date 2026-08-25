import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api', () => ({ api: vi.fn(), listItems: (payload) => payload?.results || payload || [] }))

import { api } from '@/api'
import { useRecruitmentContextStore } from './recruitmentContext'

const jobs = [
  { id: 12, title: '产品经理', department: '产品部', account_name: '招聘主账号', status: 'open' },
  { id: 18, title: '前端工程师', department: '研发部', account_name: '研发招聘', status: 'open' },
]

describe('recruitment context store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.mockReset()
    localStorage.clear()
  })

  it('loads open jobs and persists a valid selection per user', async () => {
    api.mockResolvedValue({ results: jobs })
    const store = useRecruitmentContextStore()

    await store.loadJobs({ userId: 7 })
    const selected = store.selectJob(12, { userId: 7 })

    expect(api).toHaveBeenCalledWith('recruitment/jobs/?status=open')
    expect(selected).toBe(true)
    expect(store.currentJob.id).toBe(12)
    expect(localStorage.getItem('ximing-hr:recruitment-job:7')).toBe('12')
  })

  it('restores a remembered selection only when it is still open and accessible', async () => {
    localStorage.setItem('ximing-hr:recruitment-job:7', '18')
    api.mockResolvedValue({ results: jobs })
    const store = useRecruitmentContextStore()

    await store.loadJobs({ userId: 7 })

    expect(store.selectedJobId).toBe('18')
    expect(store.currentJob.title).toBe('前端工程师')
  })

  it('invalidates a remembered job missing from a successful refresh', async () => {
    localStorage.setItem('ximing-hr:recruitment-job:7', '12')
    api.mockResolvedValue({ results: [jobs[1]] })
    const store = useRecruitmentContextStore()

    await store.loadJobs({ userId: 7, force: true })

    expect(store.selectedJobId).toBe('')
    expect(store.invalidationReason).toContain('不再开放')
    expect(localStorage.getItem('ximing-hr:recruitment-job:7')).toBeNull()
  })

  it('does not auto-select the first job', async () => {
    api.mockResolvedValue({ results: jobs })
    const store = useRecruitmentContextStore()

    await store.loadJobs({ userId: 7 })

    expect(store.selectedJobId).toBe('')
    expect(store.currentJob).toBeNull()
  })

  it('ignores an older load response that finishes after a forced refresh', async () => {
    const resolvers = []
    api.mockImplementation(() => new Promise((resolve) => resolvers.push(resolve)))
    const store = useRecruitmentContextStore()

    const first = store.loadJobs({ userId: 7 })
    const second = store.loadJobs({ userId: 7, force: true })
    resolvers[1]({ results: [jobs[1]] })
    await second
    resolvers[0]({ results: [jobs[0]] })
    await first

    expect(store.jobs).toEqual([jobs[1]])
  })

  it('keeps the last successful list when refresh fails', async () => {
    api.mockResolvedValueOnce({ results: jobs }).mockRejectedValueOnce(new Error('同步结果读取失败'))
    const store = useRecruitmentContextStore()
    await store.loadJobs({ userId: 7 })

    await expect(store.loadJobs({ userId: 7, force: true })).rejects.toThrow('同步结果读取失败')

    expect(store.jobs).toEqual(jobs)
    expect(store.error).toBe('同步结果读取失败')
  })
})
