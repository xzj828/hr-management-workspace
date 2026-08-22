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
        { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
        { path: 'employees', name: 'employees', component: () => import('@/views/EmployeesView.vue') },
        { path: 'imports', name: 'imports', component: () => import('@/views/ImportsView.vue') },
        { path: 'results', name: 'results', component: () => import('@/views/ResultsView.vue') },
        { path: 'suspicions', name: 'suspicions', component: () => import('@/views/SuspicionsView.vue') },
        { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (auth.loading) await auth.restore()
  if (!to.meta.public && !auth.isAuthenticated) return { name: 'login', query: { redirect: to.fullPath } }
  if (to.name === 'login' && auth.isAuthenticated) return { name: 'dashboard' }
})

export default router

