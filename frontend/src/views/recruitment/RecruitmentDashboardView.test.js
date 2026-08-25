import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())
const pushMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({ api: apiMock }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: pushMock }) }))

import RecruitmentDashboardView from './RecruitmentDashboardView.vue'

const payload = () => ({
  metrics: { open_jobs: 3, active_candidates: 12, waiting_resumes: 4, waiting_interviews: 2, boss_accounts_ready: 1 },
  today_actions: [
    { key: 'to_contact', label: '待联系候选人', count: 5, route: '/recruitment/candidates?stage=to_contact', priority: 'high' },
    { key: 'to_screen', label: '待筛选简历', count: 4, route: '/recruitment/resumes', priority: 'high' },
  ],
  alerts: [{ key: 'account-1', severity: 'high', title: '招聘主账号需要处理', detail: '等待人工处理', route: '/recruitment/automation', action_label: '查看账号' }],
  funnel: [
    { key: 'new', label: '新候选人', count: 12 },
    { key: 'communicating', label: '沟通中', count: 8 },
    { key: 'resume', label: '简历筛选', count: 4 },
    { key: 'interview', label: '面试', count: 2 },
    { key: 'hired', label: '已录用', count: 1 },
  ],
  job_progress: [{ id: 7, title: '产品经理', headcount: 2, candidates: 8, to_screen: 3, to_interview: 2, interviews: 2, hired: 1, completion: 50, account_name: '招聘主账号', account_status: 'ready', updated_at: '2026-08-24T08:00:00Z', route: '/recruitment/candidates?job=7' }],
  trend: [
    { date: '2026-08-18', label: '8/18', candidates: 1, resumes: 0, interviews: 0, hires: 0 },
    { date: '2026-08-19', label: '8/19', candidates: 2, resumes: 1, interviews: 0, hires: 0 },
    { date: '2026-08-20', label: '8/20', candidates: 3, resumes: 1, interviews: 1, hires: 0 },
    { date: '2026-08-21', label: '8/21', candidates: 1, resumes: 2, interviews: 1, hires: 0 },
    { date: '2026-08-22', label: '8/22', candidates: 2, resumes: 1, interviews: 0, hires: 0 },
    { date: '2026-08-23', label: '8/23', candidates: 0, resumes: 1, interviews: 1, hires: 0 },
    { date: '2026-08-24', label: '8/24', candidates: 3, resumes: 2, interviews: 1, hires: 1 },
  ],
  recent_tasks: [{ id: 'task-1', account_name: '招聘主账号', action_label: '检查状态', status: 'succeeded', status_label: '成功', created_at: '2026-08-24T08:00:00Z', route: '/recruitment/automation' }],
})

describe('RecruitmentDashboardView', () => {
  beforeEach(() => {
    apiMock.mockReset()
    pushMock.mockReset()
    apiMock.mockResolvedValue(payload())
  })

  it('renders the complete HR operations dashboard', async () => {
    const wrapper = mount(RecruitmentDashboardView)
    await flushPromises()

    expect(wrapper.text()).toContain('今日工作')
    expect(wrapper.text()).toContain('风险提醒')
    expect(wrapper.text()).toContain('招聘漏斗')
    expect(wrapper.text()).toContain('近 7 天趋势')
    expect(wrapper.text()).toContain('职位进度')
    expect(wrapper.text()).toContain('最近自动化')
    expect(wrapper.text()).toContain('产品经理')
    expect(wrapper.text()).toContain('待筛选 3')
    expect(wrapper.text()).toContain('待面试 2')
    expect(wrapper.text()).toContain('50%')
    expect(wrapper.findAll('[data-test="dashboard-metric"]')).toHaveLength(5)
    expect(wrapper.findAll('[data-test="trend-day"]')).toHaveLength(7)
  })

  it('opens a job workspace from its progress card', async () => {
    const wrapper = mount(RecruitmentDashboardView)
    await flushPromises()

    await wrapper.get('[data-test="job-progress-7"]').trigger('click')

    expect(pushMock).toHaveBeenCalledWith('/recruitment/candidates?job=7')
  })

  it('navigates from an actionable work item', async () => {
    const wrapper = mount(RecruitmentDashboardView)
    await flushPromises()

    await wrapper.get('[data-test="today-action-to_contact"]').trigger('click')

    expect(pushMock).toHaveBeenCalledWith('/recruitment/candidates?stage=to_contact')
  })

  it('shows a useful onboarding state when recruitment data is empty', async () => {
    const empty = payload()
    empty.metrics = { open_jobs: 0, active_candidates: 0, waiting_resumes: 0, waiting_interviews: 0, boss_accounts_ready: 0 }
    empty.job_progress = []
    empty.recent_tasks = []
    empty.alerts = []
    empty.today_actions = empty.today_actions.map((item) => ({ ...item, count: 0 }))
    empty.funnel = empty.funnel.map((item) => ({ ...item, count: 0 }))
    apiMock.mockResolvedValue(empty)

    const wrapper = mount(RecruitmentDashboardView)
    await flushPromises()

    expect(wrapper.text()).toContain('先同步在招职位')
    expect(wrapper.text()).toContain('前往职位管理')
  })

  it('keeps the page understandable when the dashboard request fails', async () => {
    apiMock.mockRejectedValue(new Error('看板加载失败'))

    const wrapper = mount(RecruitmentDashboardView)
    await flushPromises()

    expect(wrapper.text()).toContain('看板加载失败')
    expect(wrapper.text()).toContain('招聘看板')
  })
})
