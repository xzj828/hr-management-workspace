import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())
vi.mock('@/api', () => ({ api: apiMock }))

import JobStandardDrawer from './JobStandardDrawer.vue'

const draft = {
  id: 7,
  version: 2,
  status: 'draft',
  status_label: '草稿',
  criteria: {
    summary: '负责核心服务研发',
    dimensions: [
      { key: 'experience', name: '相关经验', weight: 60, description: '后端经验', evidence_block_ids: ['doc-1'] },
      { key: 'skills', name: '技能匹配', weight: 40, description: 'Python', evidence_block_ids: ['doc-2'] },
    ],
    required: [], preferred: [], risks: [],
  },
  unresolved_questions: [],
}

describe('JobStandardDrawer', () => {
  it('edits dimensions and only enables publishing when weights total 100', async () => {
    const wrapper = mount(JobStandardDrawer, { props: { job: { id: 1, title: '后端工程师' }, standard: draft, documents: [] } })
    await flushPromises()

    expect(wrapper.get('[data-test="publish-standard"]').attributes()).not.toHaveProperty('disabled')
    await wrapper.get('[data-test="dimension-weight-0"]').setValue(50)
    expect(wrapper.get('[data-test="weight-total"]').text()).toContain('90')
    expect(wrapper.get('[data-test="publish-standard"]').attributes()).toHaveProperty('disabled')

    await wrapper.get('[data-test="remove-dimension-1"]').trigger('click')
    expect(wrapper.find('[data-test="dimension-weight-1"]').exists()).toBe(false)
    await wrapper.get('[data-test="add-dimension"]').trigger('click')
    expect(wrapper.find('[data-test="dimension-weight-1"]').exists()).toBe(true)
    await wrapper.get('[data-test="add-hard-requirement"]').trigger('click')
    expect(wrapper.text()).toContain('重点核实项')
    expect(wrapper.text()).toContain('不重复计分')
    expect(wrapper.text()).not.toContain('明确不满足时自动淘汰')
  })

  it('saves a draft and requires explicit publish confirmation', async () => {
    apiMock.mockReset()
    apiMock.mockImplementation((path) => {
      if (path === 'recruitment/job-standards/7/') return Promise.resolve(draft)
      if (path === 'recruitment/job-standards/7/publish/') return Promise.resolve({ ...draft, status: 'published', status_label: '已启用' })
      throw new Error(`unexpected path: ${path}`)
    })
    const wrapper = mount(JobStandardDrawer, { props: { job: { id: 1, title: '后端工程师' }, standard: draft, documents: [] } })

    await wrapper.get('[data-test="save-standard"]').trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/job-standards/7/', expect.objectContaining({ method: 'PATCH' }))

    await wrapper.get('[data-test="publish-standard"]').trigger('click')
    expect(wrapper.find('[data-test="publish-confirm"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="publish-confirm"]').text()).toContain('AI 建议不会自动改变候选人阶段')
    expect(apiMock).not.toHaveBeenCalledWith('recruitment/job-standards/7/publish/', expect.anything())
    await wrapper.get('[data-test="confirm-publish-standard"]').trigger('click')
    await flushPromises()
    expect(apiMock).toHaveBeenCalledWith('recruitment/job-standards/7/publish/', { method: 'POST' })
  })

  it('ignores the legacy auto-reject switch and presents priority-only scoring semantics', async () => {
    apiMock.mockReset()
    apiMock.mockResolvedValue(draft)
    const standard = {
      ...draft,
      criteria: {
        ...draft.criteria,
        auto_reject_on_hard_fail: true,
        hard_requirements: [{ key: 'degree', text: '学历低于本科', evidence_block_ids: [], rule: { field: 'highest_degree', operator: 'gte', value: '本科' } }],
      },
    }
    const wrapper = mount(JobStandardDrawer, { props: { job: { id: 1, title: '后端工程师' }, standard, documents: [] } })

    expect(wrapper.text()).toContain('重点核实项')
    expect(wrapper.text()).toContain('不重复计分')
    expect(wrapper.text()).toContain('不自动淘汰候选人')
    await wrapper.get('[data-test="save-standard"]').trigger('click')
    await flushPromises()
    const payload = JSON.parse(apiMock.mock.calls.find(([path]) => path === 'recruitment/job-standards/7/')[1].body)
    expect(payload.criteria.auto_reject_on_hard_fail).toBeUndefined()
    expect(payload.criteria.priority_requirements[0].rule).toEqual({ field: 'highest_degree', operator: 'gte', value: '本科' })
    expect(payload.criteria.hard_requirements).toEqual([])

    await wrapper.get('[data-test="publish-standard"]').trigger('click')
    expect(wrapper.get('[data-test="publish-confirm"]').text()).toContain('AI 建议不会自动改变候选人阶段')
  })
})
