import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ResumeIntelligencePanel from './ResumeIntelligencePanel.vue'

const resume = { id: 1, candidate_name: '周晓宁', content_type: 'application/pdf', preview_url: '/resume/1' }
const structure = {
  id: 11,
  data: { basics: { name: '周晓宁', city: null, target_role: '后端工程师' }, summary: '五年研发经验', skills: ['Python'], work_experiences: [] },
  evidence: [{ field: 'summary', block_ids: ['resume-1-block-2'] }],
  warnings: ['城市信息不足'],
}
const assessment = {
  id: 21, version: 1, total_score: '78.00', confidence: '0.820', recommendation: 'review', recommendation_label: '建议人工复核',
  dimension_scores: [{ criterion_key: 'experience', score: 38, max_score: 50, status: 'supported', reason: '相关经验明确', resume_evidence_block_ids: ['resume-1-block-2'] }],
  hard_failures: [{ criterion_key: 'degree', text: '本科及以上', reason: '学历信息不足', resume_evidence_block_ids: ['resume-1-block-2'] }],
  gaps: ['缺少团队规模'], verification_questions: ['请核实团队规模'], evidence: [],
}

describe('ResumeIntelligencePanel', () => {
  afterEach(() => document.body.innerHTML = '')

  it('renders structured facts without guessing missing fields', async () => {
    const wrapper = mount(ResumeIntelligencePanel, { props: { resume, structure, assessment, tasks: [] } })
    await wrapper.get('[data-test="tab-structured"]').trigger('click')
    expect(wrapper.text()).toContain('周晓宁')
    expect(wrapper.text()).toContain('信息不足')
    expect(wrapper.text()).toContain('城市信息不足')
  })

  it('shows scoring evidence and returns to the original on evidence click', async () => {
    const wrapper = mount(ResumeIntelligencePanel, { props: { resume, structure, assessment, tasks: [] } })
    await wrapper.get('[data-test="tab-evidence"]').trigger('click')
    expect(wrapper.text()).toContain('78')
    expect(wrapper.text()).toContain('AI 建议，需 HR 复核')
    expect(wrapper.text()).toContain('重点评分项')
    expect(wrapper.text()).toContain('重点项差距')
    expect(wrapper.text()).not.toContain('淘汰条件')
    await wrapper.get('[data-test="evidence-resume-1-block-2"]').trigger('click')
    expect(wrapper.get('[data-test="tab-original"]').attributes('aria-selected')).toBe('true')
    expect(wrapper.text()).toContain('resume-1-block-2')
  })

  it('renders a recoverable failed state', () => {
    const wrapper = mount(ResumeIntelligencePanel, { props: { resume, structure: null, assessment: null, tasks: [{ kind: 'resume_structure', status: 'failed', error_message: 'PDF 无法读取' }] } })
    expect(wrapper.text()).toContain('PDF 无法读取')
    expect(wrapper.get('[data-test="retry-structure"]').exists()).toBe(true)
  })

  it('keeps the original resume available while the full report is loading', () => {
    const wrapper = mount(ResumeIntelligencePanel, {
      props: { resume, structure: { id: 11, resume: 1, version: 1 }, assessment: { id: 21, total_score: 78, confidence: 0.82, recommendation_label: '建议人工复核' }, tasks: [], loading: true },
    })
    expect(wrapper.get('[data-test="intelligence-detail-loading"]').text()).toContain('正在加载完整分析报告')
    expect(wrapper.get('iframe').attributes('src')).toBe('/resume/1')
  })

  it('is an accessible modal, closes with Escape, and never presents an AI result as automatic rejection', async () => {
    const wrapper = mount(ResumeIntelligencePanel, {
      attachTo: document.body,
      props: { resume, structure, assessment: { ...assessment, auto_rejected: true }, tasks: [] },
    })
    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(wrapper.get('button[aria-label="关闭"]').element)
    expect(wrapper.text()).toContain('评分仅作参考，不会自动淘汰或推进候选人')
    expect(wrapper.text()).not.toContain('触发硬性淘汰')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })
})
