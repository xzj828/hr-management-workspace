import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

const routerState = vi.hoisted(() => ({
  route: { name: 'recruitment-dashboard', meta: { module: 'recruitment', recruitmentScope: 'global' }, query: {} },
  replace: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routerState.route,
  useRouter: () => ({ replace: routerState.replace }),
}))

import { useAuthStore } from '@/stores/auth'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'
import RecruitmentJobContext from './RecruitmentJobContext.vue'

const jobs = [
  { id: 12, title: '产品经理', department: '产品部', account_name: '招聘主账号' },
  { id: 18, title: '前端工程师', department: '研发部', account_name: '研发招聘' },
]

describe('RecruitmentJobContext', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    routerState.replace.mockReset()
    routerState.route = { name: 'recruitment-dashboard', meta: { module: 'recruitment', recruitmentScope: 'global' }, query: {} }
    useAuthStore().user = { id: 7, username: 'hr' }
    const context = useRecruitmentContextStore()
    context.jobs = jobs
    context.loaded = true
    context.loadedUserId = '7'
  })

  it('renders a non-interactive global view marker on global pages', () => {
    const wrapper = mount(RecruitmentJobContext)

    expect(wrapper.text()).toContain('全部职位')
    expect(wrapper.text()).toContain('全局视图')
    expect(wrapper.find('[data-test="job-context-trigger"]').exists()).toBe(false)
  })

  it('selects a job from the searchable menu and updates the current URL', async () => {
    routerState.route = { name: 'recruitment-candidates', meta: { module: 'recruitment', recruitmentScope: 'job' }, query: {} }
    const wrapper = mount(RecruitmentJobContext)

    await wrapper.get('[data-test="job-context-trigger"]').trigger('click')
    await wrapper.get('[data-test="job-context-search"]').setValue('前端')
    await wrapper.get('[data-test="job-context-option-18"]').trigger('click')

    expect(useRecruitmentContextStore().selectedJobId).toBe('18')
    expect(routerState.replace).toHaveBeenCalledWith({
      name: 'recruitment-candidates',
      query: { job: '18' },
    })
    expect(wrapper.text()).toContain('前端工程师')
  })
})
