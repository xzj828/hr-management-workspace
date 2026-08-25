import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: apiMock,
  listItems: (payload) => Array.isArray(payload) ? payload : payload?.results || [],
}))

import RecruitmentResumesView from './RecruitmentResumesView.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'


const resumes = [
  { id: 1, candidate_name: '周晓宁', job_title: 'Vue 前端工程师', original_name: 'zhou-xiaoning.pdf', content_type: 'application/pdf', file_size: 1536, source_label: '演示数据', processing_status: 'ready', status_label: '待 AI 评估', file_available: true, preview_url: '/api/recruitment/resumes/1/file/', download_url: '/api/recruitment/resumes/1/file/?download=1', version: 2, sha256: 'abcdef1234567890', acquired_at: '2026-08-22T10:00:00Z', updated_at: '2026-08-22T10:00:00Z' },
  { id: 2, candidate_name: '徐雯', job_title: '人事产品经理', original_name: 'xu-wen.pdf', content_type: 'application/pdf', file_size: 2048, source_label: '演示数据', processing_status: 'ready', status_label: '待 AI 评估', file_available: true, preview_url: '/api/recruitment/resumes/2/file/', download_url: '/api/recruitment/resumes/2/file/?download=1', updated_at: '2026-08-22T10:00:00Z' },
  { id: 3, candidate_name: '宋怡', job_title: '实施顾问', original_name: 'song-yi.pdf', content_type: 'application/pdf', file_size: 1024, source_label: '演示数据', processing_status: 'ready', status_label: '待 AI 评估', file_available: true, preview_url: '/api/recruitment/resumes/3/file/', download_url: '/api/recruitment/resumes/3/file/?download=1', updated_at: '2026-08-22T10:00:00Z' },
]

describe('RecruitmentResumesView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const context = useRecruitmentContextStore()
    context.jobs = [{ id: 1, title: 'Vue 前端工程师', headcount: 3, boss_account: 7 }]
    context.selectedJobId = '1'
    context.loaded = true
    apiMock.mockReset()
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/resumes/?job=1') return Promise.resolve({ results: [resumes[0]] })
      if (path === 'recruitment/job-documents/?job=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/job-standards/?job=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/structured-resumes/?job=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/resume-assessments/?job=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/ai-tasks/?job=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/resumes/?job=1&archived=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/resumes/1/archive/') return Promise.resolve({ ...resumes[0], archived_at: '2026-08-24T10:00:00Z' })
      if (path === 'recruitment/demo-data/') return Promise.resolve({ loaded: true, counts: { jobs: 3, candidates: 10, applications: 10, resumes: 3 } })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
  })

  it('requires a job and does not request mixed resumes', async () => {
    useRecruitmentContextStore().selectedJobId = ''
    apiMock.mockClear()
    const wrapper = mount(RecruitmentResumesView)
    await flushPromises()

    expect(wrapper.text()).toContain('请先选择在招职位')
    expect(apiMock.mock.calls.some(([path]) => path.startsWith('recruitment/resumes/'))).toBe(false)
  })

  it('renders PDF metadata and opens an inline preview', async () => {
    const wrapper = mount(RecruitmentResumesView)
    await flushPromises()

    expect(wrapper.text()).toContain('周晓宁')
    expect(wrapper.text()).not.toContain('徐雯')
    expect(wrapper.text()).not.toContain('宋怡')
    expect(wrapper.text()).toContain('1.5 KB')
    expect(wrapper.text()).toContain('V2')
    expect(wrapper.text()).toContain('已入库')
    expect(wrapper.text()).not.toContain('待 AI 评估')
    expect(wrapper.get('[data-test="download-1"]').attributes('href')).toBe('/api/recruitment/resumes/1/file/?download=1')
    expect(wrapper.get('[data-test="preview-1"]').findComponent(AppIcon).props('name')).toBe('eye')
    expect(wrapper.get('[data-test="download-1"]').findComponent(AppIcon).props('name')).toBe('download')

    await wrapper.get('[data-test="preview-1"]').trigger('click')
    expect(wrapper.get('iframe').attributes('src')).toBe('/api/recruitment/resumes/1/file/')
    expect(wrapper.get('iframe').attributes('title')).toBe('周晓宁的简历')
    expect(wrapper.get('.recruitment-download-link').findComponent(AppIcon).props('name')).toBe('download')
  })

  it('offers Word requirement upload and a real standard generation action', async () => {
    const wrapper = mount(RecruitmentResumesView)
    await flushPromises()

    const preview = wrapper.get('[data-test="resume-screening-preview"]')
    expect(preview.text()).toContain('岗位评分标准')
    expect(preview.text()).toContain('尚未生成')
    expect(preview.text()).toContain('上传 Word')
    expect(wrapper.get('[data-test="generate-standard"]').text()).toContain('生成标准')

    const upload = wrapper.get('[data-test="word-upload"]')
    expect(upload.attributes()).not.toHaveProperty('disabled')
    expect(wrapper.get('[data-test="word-file-input"]').attributes('accept')).toBe('.doc,.docx')

    await wrapper.get('[data-test="toggle-archived-resumes"]').trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/resumes/?job=1&archived=1')
    expect(wrapper.find('[data-test="resume-screening-preview"]').exists()).toBe(false)
  })

  it('does not offer preview or download for a missing PDF', async () => {
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/resumes/?job=1') return Promise.resolve({ results: [{ ...resumes[0], id: 4, file_available: false }] })
      if (path === 'recruitment/job-documents/?job=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/job-standards/?job=1') return Promise.resolve({ results: [] })
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

  it('renders BOSS online resume screenshots as images instead of PDF frames', async () => {
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/resumes/?job=1') return Promise.resolve({ results: [{
        ...resumes[0], id: 8, original_name: 'online.png', content_type: 'image/png', source_label: 'BOSS 在线简历',
        preview_url: '/api/recruitment/resumes/8/file/', download_url: '/api/recruitment/resumes/8/file/?download=1',
      }] })
      if (path === 'recruitment/job-documents/?job=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/job-standards/?job=1') return Promise.resolve({ results: [] })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const wrapper = mount(RecruitmentResumesView)
    await flushPromises()
    expect(wrapper.text()).toContain('PNG 在线简历')
    await wrapper.get('[data-test="preview-8"]').trigger('click')
    expect(wrapper.get('.recruitment-image-preview').attributes('src')).toBe('/api/recruitment/resumes/8/file/')
    expect(wrapper.find('iframe').exists()).toBe(false)
  })

  it('selects resumes and submits a visible batch scoring operation', async () => {
    apiMock.mockImplementation((path, options) => {
      if (path === 'recruitment/resumes/?job=1') return Promise.resolve({ results: [resumes[0]] })
      if (path === 'recruitment/job-documents/?job=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/job-standards/?job=1') return Promise.resolve({ results: [{ id: 9, version: 1, status: 'published', status_label: '已启用', criteria: { dimensions: [{ key: 'skills', weight: 100 }] } }] })
      if (path === 'recruitment/structured-resumes/?job=1') return Promise.resolve({ results: [{ id: 31, resume: 1, version: 1, data: {}, evidence: [], warnings: [] }] })
      if (path === 'recruitment/resume-assessments/?job=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/ai-tasks/?job=1') return Promise.resolve({ results: [] })
      if (path === 'recruitment/resume-assessments/score/' && options?.method === 'POST') return Promise.resolve({ results: [{ resume_id: 1, task_id: 'task-1', status: 'pending' }] })
      return Promise.reject(new Error(`unexpected path: ${path}`))
    })
    const wrapper = mount(RecruitmentResumesView)
    await flushPromises()

    await wrapper.get('[data-test="select-resume-1"]').setValue(true)
    expect(wrapper.get('[data-test="resume-batch-bar"]').text()).toContain('已选择 1 份')
    await wrapper.get('[data-test="batch-score"]').trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/resume-assessments/score/', expect.objectContaining({ method: 'POST' }))
    await wrapper.get('[data-test="clear-resume-selection"]').trigger('click')
    expect(wrapper.find('[data-test="resume-batch-bar"]').exists()).toBe(false)
  })
})
