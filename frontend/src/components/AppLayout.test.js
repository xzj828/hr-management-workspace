import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

const routerState = vi.hoisted(() => ({
  route: {
    name: 'recruitment-dashboard',
    meta: { module: 'recruitment', recruitmentScope: 'global', title: '招聘看板' },
    query: {},
  },
  push: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routerState.route,
  useRouter: () => ({ push: routerState.push }),
}))

import AppLayout from './AppLayout.vue'
import { useAuthStore } from '@/stores/auth'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

describe('AppLayout navigation hierarchy', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    routerState.route = {
      name: 'recruitment-dashboard',
      meta: { module: 'recruitment', recruitmentScope: 'global', title: '招聘看板' },
      query: {},
    }
    useAuthStore().user = { id: 7, username: 'hr' }
    const context = useRecruitmentContextStore()
    context.loaded = true
    context.loadedUserId = '7'
  })

  it('renders two modules in the sidebar and recruitment pages in the top bar', () => {
    const wrapper = mount(AppLayout, {
      global: {
        stubs: {
          RouterLink: { props: ['to'], template: '<a><slot /></a>' },
          RouterView: true,
          RecruitmentCopilotDrawer: true,
        },
      },
    })

    expect(wrapper.findAll('.module-nav .nav-item__label').map((item) => item.text())).toEqual([
      '招聘管理',
      '考勤管理',
    ])
    expect(wrapper.findAll('.top-navigation__link').map((item) => item.text())).toEqual([
      '招聘看板',
      '职位管理',
      '候选人',
      '招聘流程',
      '自动化任务',
      '简历中心',
    ])
    expect(wrapper.findAll('.module-nav .app-icon')).toHaveLength(2)
    expect(wrapper.findAll('.top-navigation__link .app-icon')).toHaveLength(6)
    expect(wrapper.find('.collapse-button .app-icon').exists()).toBe(true)
    expect(wrapper.find('.copilot-entry .app-icon').exists()).toBe(true)
    expect(wrapper.find('.module-switcher').exists()).toBe(false)
    expect(wrapper.find('.topbar h1').exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'RecruitmentJobContext' }).exists()).toBe(true)
  })

  it('keeps the selected job only on job-scoped navigation links', () => {
    routerState.route = {
      name: 'recruitment-candidates',
      meta: { module: 'recruitment', recruitmentScope: 'job', title: '候选人' },
      query: { job: '12' },
    }
    const context = useRecruitmentContextStore()
    context.jobs = [{ id: 12, title: '产品经理' }]
    context.selectedJobId = '12'
    const RouterLink = { name: 'RouterLink', props: ['to'], template: '<a><slot /></a>' }
    const wrapper = mount(AppLayout, {
      global: { stubs: { RouterLink, RouterView: true, RecruitmentJobContext: true, RecruitmentCopilotDrawer: true } },
    })
    const links = wrapper.findAllComponents(RouterLink).map((link) => link.props('to'))

    expect(links).toContainEqual({ name: 'recruitment-pipeline', query: { job: '12' } })
    expect(links).toContainEqual({ name: 'recruitment-resumes', query: { job: '12' } })
    expect(links).toContainEqual({ name: 'recruitment-jobs' })
    expect(links).toContainEqual({ name: 'recruitment-automation' })
  })
})
