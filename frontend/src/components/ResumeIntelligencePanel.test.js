import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ResumeIntelligencePanel from './ResumeIntelligencePanel.vue'

const resume = { id: 1, candidate_name: '周晓宁', job_title: '后端工程师', content_type: 'application/pdf', preview_url: '/resume/1' }
const structure = {
  id: 11,
  data: {
    basics: { name: '周晓宁', city: null, target_role: '后端工程师', current_title: '高级软件工程师', education: '本科' },
    total_experience_months: 60,
    summary: '拥有五年后端研发经验，长期参与核心业务系统建设，具备服务设计、性能优化与跨团队协作经验',
    skills: ['Python', 'Django', 'MySQL', 'Redis'],
  },
  warnings: ['城市信息不足'],
}
const assessment = {
  id: 21,
  version: 1,
  total_score: '78.00',
  confidence: '0.820',
  recommendation: 'review',
  recommendation_label: '建议进一步沟通',
  dimension_scores: [
    { criterion_key: 'experience', criterion_name: '项目经验', score: 38, max_score: 50, reason: '相关经验明确，项目职责和技术实践与岗位要求具有较高关联', resume_evidence_block_ids: ['resume-1-block-2'] },
    { criterion_key: 'engineering', criterion_name: '工程能力', score: 20, max_score: 30, reason: '具备服务治理与性能优化经验，但复杂系统规模仍需核实', resume_evidence_block_ids: ['resume-1-block-3'] },
  ],
  hard_failures: [{ criterion_key: 'degree', text: '本科及以上', reason: '学历信息的原始证明材料尚未核实' }],
  gaps: ['缺少团队规模'],
  verification_questions: ['候选人在项目中的决策边界与实际贡献'],
}

describe('ResumeIntelligencePanel', () => {
  afterEach(() => { document.body.innerHTML = '' })

  it('renders the selected single-page evidence card without tabs or pagination', () => {
    const wrapper = mount(ResumeIntelligencePanel, { props: { resume, structure, assessment, tasks: [] } })
    expect(wrapper.get('[role="dialog"]').attributes('aria-label')).toBe('证据详情')
    expect(wrapper.text()).toContain('证据详情')
    expect(wrapper.text()).toContain('AI 分析报告')
    expect(wrapper.text()).toContain('关键信息提取')
    expect(wrapper.text()).toContain('建议进一步沟通')
    expect(wrapper.find('nav').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('历史版本')
  })

  it('creates a natural multi-paragraph report and extracts keywords from real evidence', () => {
    const wrapper = mount(ResumeIntelligencePanel, { props: { resume, structure, assessment, tasks: [] } })
    const paragraphs = wrapper.findAll('.analysis-report__copy p')
    expect(paragraphs).toHaveLength(3)
    expect(paragraphs.map((item) => item.text()).join('').length).toBeGreaterThan(180)
    expect(wrapper.text()).toContain('Python')
    expect(wrapper.text()).toContain('项目经验')
    expect(wrapper.text()).toContain('最终判断仍由 HR 复核')
  })

  it('loads the PDF only after clicking the original-resume button', async () => {
    const wrapper = mount(ResumeIntelligencePanel, { props: { resume, structure, assessment, tasks: [] } })
    expect(wrapper.find('iframe').exists()).toBe(false)
    const button = wrapper.get('[data-test="view-original-resume"]')
    expect(button.text()).toBe('查看原始简历')
    await button.trigger('click')
    expect(wrapper.get('[data-test="resume-document-viewer"]').exists()).toBe(true)
    expect(wrapper.get('iframe').attributes('src')).toBe('/resume/1#toolbar=0&navpanes=0&zoom=100')
    expect(button.text()).toBe('查看原始简历')
  })

  it('renders a recoverable failed state', () => {
    const wrapper = mount(ResumeIntelligencePanel, {
      props: { resume, structure: null, assessment: null, tasks: [{ kind: 'resume_structure', status: 'failed', error_message: 'PDF 无法读取' }] },
    })
    expect(wrapper.text()).toContain('PDF 无法读取')
    expect(wrapper.get('[data-test="retry-structure"]').exists()).toBe(true)
  })

  it('keeps the original resume behind an explicit click while details are loading', async () => {
    const wrapper = mount(ResumeIntelligencePanel, {
      props: { resume, structure, assessment, tasks: [], loading: true },
    })
    expect(wrapper.get('[data-test="intelligence-detail-loading"]').text()).toContain('正在加载完整分析报告')
    expect(wrapper.find('iframe').exists()).toBe(false)
    await wrapper.get('[data-test="view-original-resume"]').trigger('click')
    expect(wrapper.get('iframe').attributes('src')).toContain('zoom=100')
  })

  it('is an accessible modal and closes with Escape', async () => {
    const wrapper = mount(ResumeIntelligencePanel, {
      attachTo: document.body,
      props: { resume, structure, assessment, tasks: [] },
    })
    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(wrapper.get('button[aria-label="关闭"]').element)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })
})
