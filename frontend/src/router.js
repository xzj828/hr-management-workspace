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
        { path: 'recruitment/workbench', name: 'recruitment-workbench', component: () => import('@/views/recruitment/RecruitmentWorkbenchView.vue'), meta: { module: 'recruitment', recruitmentScope: 'job', inlineJobContext: true, title: '招聘作业台' } },
        { path: 'recruitment/results', name: 'recruitment-results', component: () => import('@/views/recruitment/RecruitmentResultsView.vue'), meta: { module: 'recruitment', recruitmentScope: 'job', inlineJobContext: true, title: '结果中心' } },
        { path: 'recruitment/admin', name: 'recruitment-admin', component: () => import('@/views/recruitment/RecruitmentAdminView.vue'), meta: { module: 'recruitment', recruitmentScope: 'global', title: '管理后台' } },
        { path: 'recruitment', name: 'recruitment-dashboard', redirect: (to) => ({ name: 'recruitment-results', query: { ...to.query, view: to.query.view || 'overview' } }), meta: { module: 'recruitment', recruitmentScope: 'job', title: '招聘看板' } },
        { path: 'recruitment/jobs', name: 'recruitment-jobs', redirect: (to) => ({ name: 'recruitment-admin', query: { ...to.query, section: 'jobs' } }), meta: { module: 'recruitment', recruitmentScope: 'global', title: '职位管理' } },
        { path: 'recruitment/candidates', name: 'legacy-recruitment-candidates', redirect: (to) => ({ name: 'recruitment-results', query: { ...to.query, view: 'candidates' } }), meta: { module: 'recruitment', recruitmentScope: 'job', title: '候选人' } },
        { path: 'recruitment/pipeline', name: 'legacy-recruitment-pipeline', redirect: (to) => ({ name: 'recruitment-results', query: { ...to.query, view: 'pipeline' } }), meta: { module: 'recruitment', recruitmentScope: 'job', title: '招聘流程' } },
        { path: 'recruitment/automation', name: 'legacy-recruitment-automation', redirect: (to) => (to.query.run
          ? { name: 'recruitment-results', query: { ...to.query, view: 'tasks' } }
          : { name: 'recruitment-admin', query: { ...to.query, section: to.query.section || 'automation' } }), meta: { module: 'recruitment', recruitmentScope: 'global', title: '自动化任务' } },
        { path: 'recruitment/resumes', name: 'legacy-recruitment-resumes', redirect: (to) => ({ name: 'recruitment-results', query: { ...to.query, view: 'candidates' } }), meta: { module: 'recruitment', recruitmentScope: 'job', title: '简历中心' } },
        {
          path: 'recruitment/details/candidates',
          name: 'recruitment-candidates',
          component: () => import('@/views/recruitment/RecruitmentCandidatesView.vue'),
          meta: { module: 'recruitment', recruitmentScope: 'job', hiddenDetail: true, title: '候选人详情' },
        },
        {
          path: 'recruitment/details/pipeline',
          name: 'recruitment-pipeline',
          component: () => import('@/views/recruitment/RecruitmentPipelineView.vue'),
          meta: { module: 'recruitment', recruitmentScope: 'job', hiddenDetail: true, title: '招聘流程详情' },
        },
        {
          path: 'recruitment/details/automation',
          name: 'recruitment-automation',
          component: () => import('@/views/recruitment/RecruitmentAutomationView.vue'),
          meta: { module: 'recruitment', recruitmentScope: 'global', hiddenDetail: true, title: '自动化详情' },
        },
        {
          path: 'recruitment/details/resumes',
          name: 'recruitment-resumes',
          component: () => import('@/views/recruitment/RecruitmentResumesView.vue'),
          meta: { module: 'recruitment', recruitmentScope: 'job', hiddenDetail: true, title: '简历详情' },
        },
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

