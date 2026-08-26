import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import router from './router'

describe('recruitment workspace routes', () => {
  it('exposes the global dashboard and three user-facing workspaces', () => {
    const routes = router.getRoutes()
    const dashboard = routes.find((route) => route.name === 'recruitment-dashboard')
    expect(dashboard?.path).toBe('/recruitment')
    expect(dashboard?.redirect).toBeUndefined()
    expect(dashboard?.meta.recruitmentScope).toBe('global')
    expect(dashboard?.components.default).toBeTypeOf('function')
    expect(routes.find((route) => route.name === 'recruitment-workbench')?.path).toBe('/recruitment/workbench')
    expect(routes.find((route) => route.name === 'recruitment-results')?.path).toBe('/recruitment/results')
    expect(routes.find((route) => route.name === 'recruitment-admin')?.path).toBe('/recruitment/admin')
  })

  it('loads the real recruitment dashboard instead of redirecting overview to attention', async () => {
    const loader = router.getRoutes().find((route) => route.name === 'recruitment-dashboard').components.default
    const loaded = await loader()

    expect(loaded.default.__name).toBe('RecruitmentDashboardView')
  })

  it('keeps settings links mapped to admin without losing account context', () => {
    const routes = router.getRoutes()
    const jobs = routes.find((route) => route.name === 'recruitment-jobs')
    expect(jobs.redirect({ query: { account: '3' } })).toEqual({
      name: 'recruitment-admin',
      query: { account: '3', section: 'jobs' },
    })
  })

  it('preserves every legacy context field while routing old URLs into the result center', () => {
    const routes = router.getRoutes()
    const candidates = routes.find((route) => route.name === 'legacy-recruitment-candidates')
    const resumes = routes.find((route) => route.name === 'legacy-recruitment-resumes')
    const automation = routes.find((route) => route.name === 'legacy-recruitment-automation')
    const context = { job: '12', run: 'run-8', filter: 'pending_hr_review', application: '19', candidate: '7', account: '3' }

    expect(candidates.redirect({ query: context })).toEqual({
      name: 'recruitment-results', query: { ...context, view: 'candidates' },
    })
    expect(resumes.redirect({ query: context })).toEqual({
      name: 'recruitment-results', query: { ...context, view: 'candidates' },
    })
    expect(automation.redirect({ query: context })).toEqual({
      name: 'recruitment-results', query: { ...context, view: 'tasks' },
    })

    for (const name of ['recruitment-candidates', 'recruitment-resumes', 'recruitment-pipeline', 'recruitment-automation']) {
      const route = routes.find((item) => item.name === name)
      expect(route.redirect).toBeUndefined()
      expect(route.meta.hiddenDetail).toBe(true)
      expect(route.components.default).toBeTypeOf('function')
    }

    const resolved = router.resolve({ name: 'legacy-recruitment-candidates', query: context })
    expect(resolved.fullPath).toContain('/recruitment/candidates?')
    expect(resolved.query).toEqual(context)
  })

  it('loads the real production drill-down components instead of redirect placeholders', async () => {
    const routes = router.getRoutes()
    const expectations = {
      'recruitment-candidates': 'RecruitmentCandidatesView',
      'recruitment-resumes': 'RecruitmentResumesView',
      'recruitment-pipeline': 'RecruitmentPipelineView',
      'recruitment-automation': 'RecruitmentAutomationView',
    }

    for (const [name, componentName] of Object.entries(expectations)) {
      const loader = routes.find((route) => route.name === name).components.default
      const loaded = await loader()
      expect(loaded.default.__name).toBe(componentName)
    }
  })

  it('integrates the production route table for an old bookmarked URL', async () => {
    const integrationRouter = createRouter({ history: createMemoryHistory(), routes: router.options.routes })
    await integrationRouter.push('/recruitment/candidates?job=12&run=run-8&filter=pending_hr_review&application=19&candidate=7&account=3')
    await integrationRouter.isReady()

    expect(integrationRouter.currentRoute.value.name).toBe('recruitment-results')
    expect(integrationRouter.currentRoute.value.query).toEqual({
      job: '12', run: 'run-8', filter: 'pending_hr_review', application: '19', candidate: '7', account: '3', view: 'candidates',
    })
  })
})
