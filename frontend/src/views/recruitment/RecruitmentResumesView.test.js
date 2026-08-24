import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentResumesView from './RecruitmentResumesView.vue'
import AppIcon from '@/components/AppIcon.vue'


const resumes = [
  { id: 1, candidate_name: '周晓宁', job_title: 'Vue 前端工程师', original_name: 'zhou-xiaoning.pdf', content_type: 'application/pdf', file_size: 1536, source_label: '演示数据', processing_status: 'ready', status_label: '待 AI 评估', file_available: true, preview_url: '/api/recruitment/resumes/1/file/', download_url: '/api/recruitment/resumes/1/file/?download=1', version: 2, sha256: 'abcdef1234567890', acquired_at: '2026-08-22T10:00:00Z', updated_at: '2026-08-22T10:00:00Z' },
  { id: 2, candidate_name: '徐雯', job_title: '人事产品经理', original_name: 'xu-wen.pdf', content_type: 'application/pdf', file_size: 2048, source_label: '演示数据', processing_status: 'ready', status_label: '待 AI 评估', file_available: true, preview_url: '/api/recruitment/resumes/2/file/', download_url: '/api/recruitment/resumes/2/file/?download=1', updated_at: '2026-08-22T10:00:00Z' },
  { id: 3, candidate_name: '宋怡', job_title: '实施顾问', original_name: 'song-yi.pdf', content_type: 'application/pdf', file_size: 1024, source_label: '演示数据', processing_status: 'ready', status_label: '待 AI 评估', file_available: true, preview_url: '/api/recruitment/resumes/3/file/', download_url: '/api/recruitment/resumes/3/file/?download=1', updated_at: '2026-08-22T10:00:00Z' },
]

describe('RecruitmentResumesView', () => {
  beforeEach(() => {
    apiMock.mockReset()
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/resumes/') return Promise.resolve({ results: resumes })
      if (path === 'recruitment/resumes/1/archive/') return Promise.resolve({ ...resumes[0], archived_at: '2026-08-24T10:00:00Z' })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: true, counts: { jobs: 3, candidates: 10, applications: 10, resumes: 3 } })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
  })

  it('renders PDF metadata and opens an inline preview', async () => {
    const wrapper = mount(RecruitmentResumesView)
    await flushPromises()

    expect(wrapper.text()).toContain('周晓宁')
    expect(wrapper.text()).toContain('徐雯')
    expect(wrapper.text()).toContain('宋怡')
    expect(wrapper.text()).toContain('1.5 KB')
    expect(wrapper.text()).toContain('V2')
    expect(wrapper.text()).toContain('待 AI 评估')
    expect(wrapper.get('[data-test="download-1"]').attributes('href')).toBe('/api/recruitment/resumes/1/file/?download=1')
    expect(wrapper.get('[data-test="preview-1"]').findComponent(AppIcon).props('name')).toBe('eye')
    expect(wrapper.get('[data-test="download-1"]').findComponent(AppIcon).props('name')).toBe('download')

    await wrapper.get('[data-test="preview-1"]').trigger('click')
    expect(wrapper.get('iframe').attributes('src')).toBe('/api/recruitment/resumes/1/file/')
    expect(wrapper.get('iframe').attributes('title')).toBe('周晓宁的简历')
    expect(wrapper.get('.recruitment-download-link').findComponent(AppIcon).props('name')).toBe('download')
  })

  it('does not offer preview or download for a missing PDF', async () => {
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/resumes/') return Promise.resolve({ results: [{ ...resumes[0], id: 4, file_available: false }] })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: true, counts: { jobs: 3, candidates: 10, applications: 10, resumes: 3 } })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const wrapper = mount(RecruitmentResumesView)
    await flushPromises()

    expect(wrapper.text()).toContain('文件不可用')
    expect(wrapper.find('[data-test="preview-4"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="download-4"]').exists()).toBe(false)
  })

  it('archives a resume without deleting its audit history', async () => {
    const wrapper = mount(RecruitmentResumesView, { global: { stubs: { teleport: { template: '<div><slot /></div>' } } } })
    await flushPromises()

    await wrapper.get('[data-test="archive-resume-1"]').trigger('click')
    expect(wrapper.text()).toContain('归档简历')
    await wrapper.get('[data-test="confirm-archive"]').trigger('click')
    await flushPromises()

    expect(apiMock).toHaveBeenCalledWith('recruitment/resumes/1/archive/', { method: 'POST' })
  })
})
