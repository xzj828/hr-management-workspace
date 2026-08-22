import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

const routerState = vi.hoisted(() => ({
  route: {
    name: 'recruitment-dashboard',
    meta: { module: 'recruitment', title: '招聘看板' },
  },
  push: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routerState.route,
  useRouter: () => ({ push: routerState.push }),
}))

import AppLayout from './AppLayout.vue'

describe('AppLayout navigation hierarchy', () => {
  beforeEach(() => setActivePinia(createPinia()))

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
    expect(wrapper.find('.module-switcher').exists()).toBe(false)
    expect(wrapper.find('.topbar h1').exists()).toBe(false)
  })
})
