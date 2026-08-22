import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import LoginView from '@/views/LoginView.vue'
import AppLayout from '@/components/AppLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', redirect: { name: 'attendance-dashboard' } },
        { path: 'attendance', name: 'attendance-dashboard', component: () => import('@/views/DashboardView.vue'), meta: { module: 'attendance', title: '考勤看板' } },
        { path: 'employees', name: 'employees', component: () => import('@/views/EmployeesView.vue'), meta: { module: 'attendance', title: '人员管理' } },
        { path: 'imports', name: 'imports', component: () => import('@/views/ImportsView.vue'), meta: { module: 'attendance', title: '导入中心' } },
        { path: 'results', name: 'results', component: () => import('@/views/ResultsView.vue'), meta: { module: 'attendance', title: '核算结果' } },
        { path: 'suspicions', name: 'suspicions', component: () => import('@/views/SuspicionsView.vue'), meta: { module: 'attendance', title: '异常审核' } },
        { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { module: 'attendance', title: '规则与标签' } },
        { path: 'recruitment', name: 'recruitment-dashboard', component: () => import('@/views/recruitment/RecruitmentDashboardView.vue'), meta: { module: 'recruitment', title: '招聘看板' } },
        { path: 'recruitment/jobs', name: 'recruitment-jobs', component: () => import('@/views/recruitment/RecruitmentPlaceholderView.vue'), meta: { module: 'recruitment', title: '职位管理' } },
        { path: 'recruitment/candidates', name: 'recruitment-candidates', component: () => import('@/views/recruitment/RecruitmentPlaceholderView.vue'), meta: { module: 'recruitment', title: '候选人' } },
        { path: 'recruitment/pipeline', name: 'recruitment-pipeline', component: () => import('@/views/recruitment/RecruitmentPlaceholderView.vue'), meta: { module: 'recruitment', title: '招聘流程' } },
        { path: 'recruitment/automation', name: 'recruitment-automation', component: () => import('@/views/recruitment/RecruitmentAutomationView.vue'), meta: { module: 'recruitment', title: '自动化任务' } },
        { path: 'recruitment/resumes', name: 'recruitment-resumes', component: () => import('@/views/recruitment/RecruitmentPlaceholderView.vue'), meta: { module: 'recruitment', title: '简历中心' } },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (auth.loading) await auth.restore()
  if (!to.meta.public && !auth.isAuthenticated) return { name: 'login', query: { redirect: to.fullPath } }
  if (to.name === 'login' && auth.isAuthenticated) return { name: 'attendance-dashboard' }
})

export default router

