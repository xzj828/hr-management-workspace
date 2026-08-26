import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

const routerState = vi.hoisted(() => ({
  route: {
    name: 'recruitment-workbench',
    meta: { module: 'recruitment', recruitmentScope: 'job', inlineJobContext: true, title: '招聘作业台' },
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
import { useModelCredentialStore } from '@/stores/modelCredential'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

const ModelSwitcherStub = { template: '<button class="model-switcher">切换模型</button>' }

describe('AppLayout navigation hierarchy', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    routerState.route = {
      name: 'recruitment-workbench',
      meta: { module: 'recruitment', recruitmentScope: 'job', inlineJobContext: true, title: '招聘作业台' },
      query: {},
    }
    useAuthStore().user = { id: 7, username: 'hr', role: 'hr' }
    const context = useRecruitmentContextStore()
    context.loaded = true
    context.loadedUserId = '7'
  })

  it('renders two modules, recruitment pages and the model switcher', () => {
    const wrapper = mount(AppLayout, {
      global: {
        stubs: {
          RouterLink: { props: ['to'], template: '<a><slot /></a>' },
          RouterView: true,
          ModelSwitcher: ModelSwitcherStub,
        },
      },
    })

    expect(wrapper.findAll('.module-nav .nav-item__label').map((item) => item.text())).toEqual(['招聘管理', '考勤管理'])
    expect(wrapper.findAll('.top-navigation__link').map((item) => item.text())).toEqual(['招聘看板', '招聘作业台', '结果中心', '管理后台'])
    expect(wrapper.findAll('.module-nav .app-icon')).toHaveLength(2)
    expect(wrapper.findAll('.top-navigation__link .app-icon')).toHaveLength(4)
    expect(wrapper.find('.collapse-button .app-icon').exists()).toBe(true)
    expect(wrapper.find('.model-switcher').text()).toBe('切换模型')
    expect(wrapper.text()).not.toContain('Copilot')
    expect(wrapper.find('.topbar h1').exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'RecruitmentJobContext' }).exists()).toBe(false)
  })

  it('keeps the selected job only on job-scoped navigation links', () => {
    routerState.route = {
      name: 'recruitment-results',
      meta: { module: 'recruitment', recruitmentScope: 'job', inlineJobContext: true, title: '结果中心' },
      query: { job: '12' },
    }
    const context = useRecruitmentContextStore()
    context.jobs = [{ id: 12, title: '产品经理' }]
    context.selectedJobId = '12'
    const RouterLink = { name: 'RouterLink', props: ['to'], template: '<a><slot /></a>' }
    const wrapper = mount(AppLayout, {
      global: { stubs: { RouterLink, RouterView: true, RecruitmentJobContext: true, ModelSwitcher: ModelSwitcherStub } },
    })
    const links = wrapper.findAllComponents(RouterLink).map((link) => link.props('to'))

    expect(links).toContainEqual({ name: 'recruitment-dashboard' })
    expect(links).toContainEqual({ name: 'recruitment-workbench', query: { job: '12' } })
    expect(links).toContainEqual({ name: 'recruitment-results', query: { job: '12' } })
    expect(links).toContainEqual({ name: 'recruitment-admin' })
  })

  it('hides management navigation from viewer roles', () => {
    useAuthStore().user = { id: 8, username: 'viewer', role: 'viewer' }
    const wrapper = mount(AppLayout, {
      global: {
        stubs: {
          RouterLink: { props: ['to'], template: '<a><slot /></a>' },
          RouterView: true,
          ModelSwitcher: ModelSwitcherStub,
        },
      },
    })

    expect(wrapper.findAll('.top-navigation__link').map((item) => item.text())).toEqual(['招聘看板', '招聘作业台', '结果中心'])
  })

  it('clears personal model metadata when the signed-in user changes', async () => {
    const wrapper = mount(AppLayout, {
      global: {
        stubs: {
          RouterLink: { props: ['to'], template: '<a><slot /></a>' },
          RouterView: true,
          ModelSwitcher: ModelSwitcherStub,
        },
      },
    })
    const models = useModelCredentialStore()
    models.profiles = [{ id: 1, name: '上一账号模型', key_last4: '1111', is_active: true }]

    useAuthStore().user = { id: 99, username: 'new-user', role: 'hr' }
    await wrapper.vm.$nextTick()

    expect(models.profiles).toEqual([])
    expect(models.config.key_last4).toBe('')
  })
})
