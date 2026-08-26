<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import AppIcon from '@/components/AppIcon.vue'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const dashboard = reactive({
  metrics: { open_jobs: 0, active_candidates: 0, waiting_resumes: 0, waiting_interviews: 0, boss_accounts_ready: 0 },
  today_actions: [], alerts: [], funnel: [], job_progress: [], trend: [], recent_tasks: [],
  resume_intelligence: { pending_parse: 0, pending_standard_review: 0, pending_hr_review: 0, recommended_advance: 0, by_job: [] },
})

const metricCards = [
  { key: 'open_jobs', label: '全部在招职位', note: '当前开放', icon: 'briefcase', route: '/recruitment/jobs' },
  { key: 'active_candidates', label: '活跃候选人', note: '招聘流程中', icon: 'users', route: '/recruitment/candidates' },
  { key: 'waiting_resumes', label: '待收简历', note: '等待候选人', icon: 'document', route: '/recruitment/resumes' },
  { key: 'waiting_interviews', label: '待安排面试', note: '需要 HR 跟进', icon: 'calendar-check', route: '/recruitment/pipeline' },
  { key: 'boss_accounts_ready', label: '可用 BOSS 账号', note: '登录状态正常', icon: 'shield', route: '/recruitment/automation' },
]

const actionIcons = { to_contact: 'user', to_screen: 'document', to_interview: 'calendar-check', waiting_human: 'alert-circle' }
const intelligenceCards = [
  { key: 'pending_parse', label: '待解析简历', note: '等待结构化', icon: 'document', filter: 'pending_parse' },
  { key: 'pending_standard_review', label: '待确认标准', note: '需要 HR 检查', icon: 'sliders', filter: 'pending_standard_review' },
  { key: 'pending_hr_review', label: '待人工复核', note: 'AI 建议复核', icon: 'eye', filter: 'pending_hr_review' },
  { key: 'recommended_advance', label: '建议进一步沟通', note: '仍需 HR 决策', icon: 'check-circle', filter: 'recommended_advance' },
]
const funnelMax = computed(() => Math.max(1, ...dashboard.funnel.map((item) => item.count)))
const trendMax = computed(() => Math.max(1, ...dashboard.trend.flatMap((item) => [item.candidates, item.resumes, item.interviews, item.hires])))
const isEmpty = computed(() => !loading.value && !error.value && Object.values(dashboard.metrics).every((value) => value === 0))

function go(route) {
  if (route) router.push(route)
}

function formatTime(value) {
  return value ? new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : '—'
}

function accountHealth(status) {
  return ({ ready: '账号正常', risk: '账号风险', offline: '账号离线', local: '本地职位' })[status] || '待检查'
}

onMounted(async () => {
  try {
    Object.assign(dashboard, await api('recruitment/dashboard/'))
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page-stack recruitment-dashboard">
    <header class="page-hero recruitment-dashboard__hero">
      <div><span class="eyebrow">Recruitment Operations</span><h2>招聘看板</h2><p>从今日待办开始，掌握候选人推进、账号风险与招聘目标。</p></div>
      <div class="dashboard-live"><i></i><span>数据随工作台实时更新</span></div>
    </header>
    <p v-if="error" class="form-error">{{ error }}</p>

    <section class="recruitment-metrics" aria-label="招聘核心指标">
      <button v-for="(card, index) in metricCards" :key="card.key" type="button" class="recruitment-metric" :class="{ 'recruitment-metric--primary': index === 0 }" data-test="dashboard-metric" @click="go(card.route)">
        <span class="recruitment-metric__icon"><AppIcon :name="card.icon" :size="18" /></span><span>{{ card.label }}</span><strong>{{ dashboard.metrics[card.key] }}</strong><small>{{ card.note }}</small>
      </button>
    </section>

    <section class="intelligence-overview" aria-label="简历智能处理概览">
      <header><div><span class="panel-kicker">RESUME INTELLIGENCE</span><h3>简历初筛进度</h3></div><span>AI 结果不会自动改变招聘流程</span></header>
      <div><button v-for="card in intelligenceCards" :key="card.key" :data-test="`intelligence-metric-${card.key}`" @click="go(`/recruitment/resumes?filter=${card.filter}`)"><AppIcon :name="card.icon" :size="16" /><span><strong>{{ card.label }}</strong><small>{{ card.note }}</small></span><b>{{ dashboard.resume_intelligence?.[card.key] || 0 }}</b><AppIcon name="chevron-right" :size="12" /></button></div>
    </section>

    <section v-if="isEmpty" class="panel recruitment-dashboard-empty">
      <span class="recruitment-dashboard-empty__icon"><AppIcon name="briefcase" :size="24" /></span>
      <div><span class="panel-kicker">GET STARTED</span><h3>先同步在招职位</h3><p>前往职位管理同步 BOSS 职位，成功后即可按岗位查看候选人、简历与招聘流程。</p></div>
      <button class="primary-button" type="button" @click="go('/recruitment/jobs')">前往职位管理</button>
    </section>

    <template v-else>
      <div class="panel recruitment-command-grid recruitment-command-workspace">
        <section class="panel recruitment-dashboard-panel recruitment-today-panel">
          <header class="panel__header"><div><span class="panel-kicker">TODAY</span><h3>今日工作</h3></div><span>按优先级处理</span></header>
          <div class="today-action-list">
            <button v-for="action in dashboard.today_actions" :key="action.key" type="button" :data-test="`today-action-${action.key}`" @click="go(action.route)">
              <span class="today-action-icon"><AppIcon :name="actionIcons[action.key] || 'check-circle'" :size="17" /></span><span><strong>{{ action.label }}</strong><small>{{ action.count ? '有待处理事项' : '当前已处理完毕' }}</small></span><b>{{ action.count }}</b><AppIcon name="chevron-right" :size="13" />
            </button>
          </div>
        </section>

        <section class="panel recruitment-dashboard-panel recruitment-alert-panel">
          <header class="panel__header"><div><span class="panel-kicker">ATTENTION</span><h3>风险提醒</h3></div><span>{{ dashboard.alerts.length }} 项</span></header>
          <div v-if="dashboard.alerts.length" class="recruitment-alert-list">
            <article v-for="alert in dashboard.alerts" :key="alert.key" :class="`is-${alert.severity}`"><i></i><div><strong>{{ alert.title }}</strong><small>{{ alert.detail }}</small></div><button type="button" @click="go(alert.route)">{{ alert.action_label }}</button></article>
          </div>
          <div v-else class="dashboard-calm-state"><AppIcon name="check-circle" :size="22" /><strong>当前没有需要处理的风险</strong><span>账号与自动化任务运行正常</span></div>
        </section>
      </div>

      <section class="panel recruitment-dashboard-panel recruitment-job-overview">
        <header class="panel__header"><div><span class="panel-kicker">HIRING GOALS</span><h3>职位进度</h3></div><button class="text-button" type="button" @click="go('/recruitment/jobs')">全部职位</button></header>
        <div v-if="dashboard.job_progress.length" class="job-progress-list"><button v-for="job in dashboard.job_progress" :key="job.id" type="button" :data-test="`job-progress-${job.id}`" @click="go(job.route)"><span><strong>{{ job.title }}</strong><small>{{ job.account_name }} · {{ accountHealth(job.account_status) }} · 更新于 {{ formatTime(job.updated_at) }}</small><small class="job-progress-focus">{{ job.candidates }} 位候选人 · 待筛选 {{ job.to_screen }} · 待面试 {{ job.to_interview }}</small></span><span class="job-progress-track"><i :style="{ width: `${job.completion}%` }"></i></span><b>{{ job.completion }}%</b><small>{{ job.hired }}/{{ job.headcount }} 录用</small></button></div>
        <p v-else class="table-empty">暂无在招职位，请先到职位管理同步</p>
      </section>

      <div class="panel recruitment-analysis-grid recruitment-analysis-workspace">
        <section class="panel recruitment-dashboard-panel recruitment-funnel-panel">
          <header class="panel__header"><div><span class="panel-kicker">PIPELINE</span><h3>招聘漏斗</h3></div><button class="text-button" type="button" @click="go('/recruitment/pipeline')">查看流程</button></header>
          <div class="recruitment-funnel"><div v-for="item in dashboard.funnel" :key="item.key"><span>{{ item.label }}</span><div><i :style="{ width: `${Math.max(3, item.count / funnelMax * 100)}%` }"></i></div><strong>{{ item.count }}</strong></div></div>
        </section>

        <section class="panel recruitment-dashboard-panel recruitment-trend-panel">
          <header class="panel__header"><div><span class="panel-kicker">7 DAY PULSE</span><h3>近 7 天趋势</h3></div><span class="trend-legend"><i></i>候选人 <i></i>简历 <i></i>面试 <i></i>录用</span></header>
          <div class="recruitment-trend" role="img" aria-label="近七天候选人、简历、面试和录用数量趋势">
            <div v-for="day in dashboard.trend" :key="day.date" data-test="trend-day" :aria-label="`${day.label}：候选人 ${day.candidates}，简历 ${day.resumes}，面试 ${day.interviews}，录用 ${day.hires}`"><span class="trend-bars"><i :style="{ height: `${day.candidates / trendMax * 100}%` }"></i><i :style="{ height: `${day.resumes / trendMax * 100}%` }"></i><i :style="{ height: `${day.interviews / trendMax * 100}%` }"></i><i :style="{ height: `${day.hires / trendMax * 100}%` }"></i></span><small>{{ day.label }}</small></div>
          </div>
        </section>
      </div>

      <div class="recruitment-detail-grid-dashboard recruitment-detail-grid-dashboard--single">
        <section class="panel recruitment-dashboard-panel recruitment-recent-panel">
          <header class="panel__header"><div><span class="panel-kicker">AUTOMATION LOG</span><h3>最近自动化</h3></div><button class="text-button" type="button" @click="go('/recruitment/automation')">查看全部</button></header>
          <div v-if="dashboard.recent_tasks.length" class="dashboard-task-list"><button v-for="task in dashboard.recent_tasks" :key="task.id" type="button" @click="go(task.route)"><i :class="`is-${task.status}`"></i><span><strong>{{ task.action_label }}</strong><small>{{ task.account_name }} · {{ formatTime(task.created_at) }}</small></span><b>{{ task.status_label }}</b></button></div>
          <p v-else class="table-empty">暂无自动化记录</p>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.recruitment-dashboard {
  --rd-surface: var(--paper);
  --rd-surface-hover: color-mix(in srgb, var(--rd-surface) 92%, var(--rd-teal));
  --rd-ink: var(--ink);
  --rd-slate: var(--slate);
  --rd-muted: var(--muted);
  --rd-muted-soft: color-mix(in srgb, var(--rd-muted) 65%, var(--rd-surface));
  --rd-line: var(--line);
  --rd-line-soft: color-mix(in srgb, var(--rd-line) 70%, var(--rd-surface));
  --rd-teal: var(--teal);
  --rd-teal-dark: var(--teal-dark);
  --rd-teal-soft: color-mix(in srgb, var(--rd-surface) 90%, var(--rd-teal));
  --rd-amber: var(--amber);
  --rd-red: var(--red);
  --rd-status-neutral: var(--rd-muted);
  --rd-panel-border: 1px solid var(--rd-line);
  --rd-soft-border: 1px solid var(--rd-line-soft);
  --rd-radius-panel: 15px;
  --rd-radius-control: 9px;
  --rd-radius-pill: 999px;
  --rd-shadow-panel: 0 1px 2px rgba(15, 23, 42, .025);
  --rd-space-0: 0;
  --rd-space-1: 4px;
  --rd-space-2: 8px;
  --rd-space-3: 12px;
  --rd-space-4: 16px;
  --rd-space-5: 22px;
  --rd-font-meta: 10px;
  --rd-font-control: 12px;
  --rd-font-panel: 15px;
  --rd-font-kpi: 30px;
  --rd-weight-bold: 700;
  --rd-line-height-tight: 1.4;
  --rd-metric-height: 118px;
  --rd-list-row-height: 58px;
  --rd-intelligence-row-height: 64px;
  --rd-chart-height: 230px;
  --rd-dot-size: 7px;
  --rd-status-bar-width: 4px;
  --rd-progress-height: 6px;
  --rd-motion: 160ms ease;
  --rd-metric-columns: repeat(5, minmax(0, 1fr));
  --rd-command-columns: minmax(0, 1.42fr) minmax(280px, .58fr);
  --rd-analysis-columns: minmax(280px, .72fr) minmax(0, 1.28fr);
  --rd-six-columns: repeat(6, minmax(0, 1fr));
  --rd-four-columns: repeat(4, minmax(0, 1fr));
  --rd-two-columns: repeat(2, minmax(0, 1fr));
  --rd-one-column: minmax(0, 1fr);
  container-name: recruitment-dashboard;
  container-type: inline-size;
  min-width: var(--rd-space-0);
  gap: var(--rd-space-5);
}

.recruitment-dashboard__hero {
  align-items: flex-end;
}

.recruitment-dashboard > .recruitment-metrics {
  grid-template-columns: var(--rd-metric-columns);
  gap: var(--rd-space-3);
  min-width: var(--rd-space-0);
}

.recruitment-metric {
  min-width: var(--rd-space-0);
  min-height: var(--rd-metric-height);
  padding: var(--rd-space-4);
  color: var(--rd-muted);
  background: var(--rd-surface);
  border: var(--rd-panel-border);
  border-radius: var(--rd-radius-panel);
  box-shadow: var(--rd-shadow-panel);
  transition: border-color var(--rd-motion), background var(--rd-motion);
}

.recruitment-metric:hover,
.recruitment-metric:focus-visible {
  transform: none;
  background: var(--rd-surface-hover);
  border-color: var(--rd-teal);
  box-shadow: var(--rd-shadow-panel);
}

.recruitment-metric > span:not(.recruitment-metric__icon) {
  color: var(--rd-muted);
  font-size: var(--rd-font-control);
}

.recruitment-metric strong {
  color: var(--rd-ink);
  font-size: var(--rd-font-kpi);
}

.recruitment-metric small {
  color: var(--rd-muted-soft);
  font-size: var(--rd-font-meta);
}

.recruitment-metric__icon {
  color: var(--rd-teal-dark);
  background: var(--rd-teal-soft);
  border-radius: var(--rd-radius-control);
}

.recruitment-metric--primary {
  color: var(--rd-surface);
  background: var(--rd-ink);
  border-color: var(--rd-ink);
}

.recruitment-metric--primary:hover,
.recruitment-metric--primary:focus-visible {
  background: var(--rd-slate);
  border-color: var(--rd-slate);
}

.recruitment-metric--primary > span:not(.recruitment-metric__icon),
.recruitment-metric--primary strong {
  color: var(--rd-surface);
}

.recruitment-metric--primary small {
  color: var(--rd-muted-soft);
}

.intelligence-overview {
  display: grid;
  gap: var(--rd-space-4);
  min-width: var(--rd-space-0);
  padding: var(--rd-space-4) var(--rd-space-5);
  color: var(--rd-slate);
  background: var(--rd-surface);
  border: var(--rd-panel-border);
  border-radius: var(--rd-radius-panel);
  box-shadow: var(--rd-shadow-panel);
}

.intelligence-overview > header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--rd-space-4);
}

.intelligence-overview h3 {
  margin: var(--rd-space-1) var(--rd-space-0) var(--rd-space-0);
  color: var(--rd-ink);
  font-family: inherit;
  font-size: var(--rd-font-panel);
}

.intelligence-overview .panel-kicker {
  color: var(--rd-muted-soft);
}

.intelligence-overview > header > span {
  color: var(--rd-muted);
  font-size: var(--rd-font-meta);
}

.recruitment-dashboard > .intelligence-overview > div {
  display: grid;
  grid-template-columns: var(--rd-four-columns);
  min-width: var(--rd-space-0);
  border-top: var(--rd-panel-border);
}

.intelligence-overview button {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: var(--rd-space-3);
  min-width: var(--rd-space-0);
  min-height: var(--rd-intelligence-row-height);
  padding: var(--rd-space-2) var(--rd-space-4);
  color: var(--rd-muted);
  background: transparent;
  border: var(--rd-space-0);
  border-left: var(--rd-panel-border);
  border-radius: var(--rd-space-0);
  text-align: left;
  transition: color var(--rd-motion), background var(--rd-motion);
}

.intelligence-overview button:first-child {
  border-left: var(--rd-space-0);
}

.intelligence-overview button:hover,
.intelligence-overview button:focus-visible {
  color: var(--rd-teal-dark);
  background: var(--rd-surface-hover);
  transform: none;
}

.intelligence-overview button > span {
  display: grid;
  gap: var(--rd-space-1);
  min-width: var(--rd-space-0);
}

.intelligence-overview button strong {
  color: var(--rd-ink);
  font-size: var(--rd-font-control);
  line-height: var(--rd-line-height-tight);
  overflow-wrap: break-word;
  white-space: normal;
}

.intelligence-overview button small {
  color: var(--rd-muted);
  font-size: var(--rd-font-meta);
}

.intelligence-overview button b {
  color: var(--rd-teal-dark);
  font-family: inherit;
  font-size: var(--rd-font-panel);
  font-weight: var(--rd-weight-bold);
}

.recruitment-command-grid,
.recruitment-analysis-grid {
  gap: var(--rd-space-0);
  min-width: var(--rd-space-0);
  overflow: hidden;
  background: var(--rd-surface);
}

.recruitment-command-grid {
  grid-template-columns: var(--rd-command-columns);
}

.recruitment-analysis-grid {
  grid-template-columns: var(--rd-analysis-columns);
}

.recruitment-command-workspace > .recruitment-dashboard-panel,
.recruitment-analysis-workspace > .recruitment-dashboard-panel {
  min-width: var(--rd-space-0);
  padding: var(--rd-space-5);
  background: transparent;
  border: var(--rd-space-0);
  border-radius: var(--rd-space-0);
  box-shadow: none;
}

.recruitment-command-workspace > .recruitment-dashboard-panel + .recruitment-dashboard-panel,
.recruitment-analysis-workspace > .recruitment-dashboard-panel + .recruitment-dashboard-panel {
  border-left: var(--rd-panel-border);
}

.recruitment-dashboard-panel > .panel__header {
  margin: var(--rd-space-0);
  padding-bottom: var(--rd-space-3);
  border-bottom: var(--rd-panel-border);
}

.today-action-list {
  grid-template-columns: var(--rd-two-columns);
  gap: var(--rd-space-0);
}

.today-action-list > button {
  min-width: var(--rd-space-0);
  min-height: var(--rd-list-row-height);
  padding: var(--rd-space-3) var(--rd-space-2);
  color: var(--rd-slate);
  background: transparent;
  border: var(--rd-space-0);
  border-bottom: var(--rd-soft-border);
  border-radius: var(--rd-space-0);
  transition: color var(--rd-motion), background var(--rd-motion);
}

.today-action-list > button:nth-child(even) {
  border-left: var(--rd-soft-border);
}

.today-action-list > button:hover,
.today-action-list > button:focus-visible {
  color: var(--rd-teal-dark);
  background: var(--rd-surface-hover);
  border-color: var(--rd-line-soft);
}

.today-action-icon {
  color: var(--rd-teal-dark);
  background: var(--rd-teal-soft);
  border-radius: var(--rd-radius-control);
}

.today-action-list strong,
.recruitment-alert-list strong {
  color: var(--rd-ink);
  font-size: var(--rd-font-control);
}

.today-action-list small,
.recruitment-alert-list small {
  color: var(--rd-muted);
  font-size: var(--rd-font-meta);
}

.today-action-list b {
  color: var(--rd-ink);
  font-size: var(--rd-font-panel);
}

.recruitment-alert-list {
  gap: var(--rd-space-0);
}

.recruitment-alert-list article {
  min-height: var(--rd-list-row-height);
  gap: var(--rd-space-3);
  padding: var(--rd-space-3) var(--rd-space-0);
  border: var(--rd-space-0);
  border-bottom: var(--rd-soft-border);
  border-radius: var(--rd-space-0);
}

.recruitment-alert-list article:last-child {
  border-bottom: var(--rd-space-0);
}

.recruitment-alert-list article > i {
  width: var(--rd-status-bar-width);
  background: var(--rd-amber);
}

.recruitment-alert-list article.is-high > i {
  background: var(--rd-red);
}

.recruitment-alert-list button {
  color: var(--rd-teal-dark);
  font-size: var(--rd-font-meta);
}

.dashboard-calm-state {
  color: var(--rd-teal);
}

.dashboard-calm-state strong {
  color: var(--rd-slate);
  font-size: var(--rd-font-control);
}

.dashboard-calm-state span {
  color: var(--rd-muted);
  font-size: var(--rd-font-meta);
}

.recruitment-job-overview,
.recruitment-recent-panel {
  margin-top: var(--rd-space-0);
  padding: var(--rd-space-0);
  overflow: hidden;
}

.recruitment-job-overview > .panel__header,
.recruitment-recent-panel > .panel__header {
  padding: var(--rd-space-5);
}

.job-progress-list > button,
.dashboard-task-list > button {
  min-width: var(--rd-space-0);
  min-height: var(--rd-list-row-height);
  padding: var(--rd-space-3) var(--rd-space-5);
  border-bottom: var(--rd-soft-border);
  transition: color var(--rd-motion), background var(--rd-motion);
}

.job-progress-list > button:hover,
.job-progress-list > button:focus-visible,
.dashboard-task-list > button:hover,
.dashboard-task-list > button:focus-visible {
  color: var(--rd-teal-dark);
  background: var(--rd-surface-hover);
}

.job-progress-list > button {
  grid-template-columns: minmax(180px, 1.25fr) minmax(120px, .75fr) auto auto;
}

.job-progress-list strong,
.dashboard-task-list strong {
  color: var(--rd-ink);
  font-size: var(--rd-font-control);
}

.job-progress-list small,
.dashboard-task-list small,
.dashboard-task-list b {
  color: var(--rd-muted);
  font-size: var(--rd-font-meta);
}

.job-progress-list .job-progress-focus,
.job-progress-list b {
  color: var(--rd-teal-dark);
}

.job-progress-track {
  height: var(--rd-progress-height);
  background: var(--rd-teal-soft);
  border-radius: var(--rd-radius-pill);
}

.job-progress-track i {
  background: var(--rd-teal);
}

.recruitment-funnel {
  gap: var(--rd-space-0);
  padding: var(--rd-space-0);
}

.recruitment-funnel > div {
  min-height: var(--rd-list-row-height);
  padding: var(--rd-space-2) var(--rd-space-0);
  border-bottom: var(--rd-soft-border);
}

.recruitment-funnel > div:last-child {
  border-bottom: var(--rd-space-0);
}

.recruitment-funnel span,
.recruitment-funnel strong {
  color: var(--rd-slate);
  font-size: var(--rd-font-meta);
}

.recruitment-funnel > div > div {
  height: var(--rd-progress-height);
  background: var(--rd-teal-soft);
}

.recruitment-funnel i {
  background: var(--rd-teal);
}

.trend-legend {
  flex-wrap: wrap;
  justify-content: flex-end;
  color: var(--rd-muted);
  font-size: var(--rd-font-meta) !important;
}

.recruitment-trend {
  height: var(--rd-chart-height);
  gap: var(--rd-space-3);
  padding-top: var(--rd-space-4);
  border-bottom: var(--rd-space-0);
}

.recruitment-trend small {
  color: var(--rd-muted);
  font-size: var(--rd-font-meta);
}

.trend-bars i {
  background: var(--rd-teal-dark);
}

.trend-bars i:nth-child(2) {
  background: var(--rd-teal);
}

.trend-bars i:nth-child(3) {
  background: var(--rd-amber);
}

.trend-bars i:nth-child(4) {
  background: var(--rd-slate);
}

.dashboard-task-list > button > i {
  width: var(--rd-dot-size);
  height: var(--rd-dot-size);
  background: var(--rd-status-neutral);
}

.dashboard-task-list > button > i.is-succeeded {
  background: var(--rd-teal);
}

.dashboard-task-list > button > i.is-failed {
  background: var(--rd-red);
}

.dashboard-task-list > button > i.is-waiting_human {
  background: var(--rd-amber);
}

@container recruitment-dashboard (max-width: 1320px) {
  .recruitment-dashboard > .recruitment-metrics {
    grid-template-columns: var(--rd-six-columns);
  }

  .recruitment-dashboard > .recruitment-metrics > .recruitment-metric {
    grid-column: span 2;
  }

  .recruitment-dashboard > .recruitment-metrics > .recruitment-metric:nth-last-child(-n + 2) {
    grid-column: span 3;
  }

  .recruitment-dashboard > .intelligence-overview > div {
    grid-template-columns: var(--rd-two-columns);
  }

  .recruitment-dashboard > .intelligence-overview button {
    border-left: var(--rd-space-0);
    border-bottom: var(--rd-panel-border);
  }

  .recruitment-dashboard > .intelligence-overview button:nth-child(even) {
    border-left: var(--rd-panel-border);
  }

  .recruitment-dashboard > .intelligence-overview button:nth-last-child(-n + 2) {
    border-bottom: var(--rd-space-0);
  }
}

@container recruitment-dashboard (max-width: 1050px) {
  .recruitment-command-grid,
  .recruitment-analysis-grid {
    grid-template-columns: var(--rd-one-column);
  }

  .recruitment-command-workspace > .recruitment-dashboard-panel + .recruitment-dashboard-panel,
  .recruitment-analysis-workspace > .recruitment-dashboard-panel + .recruitment-dashboard-panel {
    border-left: var(--rd-space-0);
    border-top: var(--rd-panel-border);
  }
}

@container recruitment-dashboard (max-width: 720px) {
  .recruitment-dashboard__hero,
  .intelligence-overview > header {
    align-items: flex-start;
    flex-direction: column;
  }

  .recruitment-dashboard > .recruitment-metrics,
  .recruitment-dashboard > .intelligence-overview > div,
  .recruitment-dashboard .today-action-list {
    grid-template-columns: var(--rd-two-columns);
  }

  .recruitment-dashboard > .recruitment-metrics > .recruitment-metric {
    grid-column: span 1;
  }

  .recruitment-dashboard > .recruitment-metrics > .recruitment-metric:last-child {
    grid-column: span 2;
  }

  .today-action-list > button:nth-child(even) {
    border-left: var(--rd-space-0);
  }

  .job-progress-list > button {
    grid-template-columns: minmax(0, 1fr) minmax(76px, .42fr) auto;
  }

  .job-progress-list > button > small:last-child {
    grid-column: 2 / -1;
    text-align: right;
  }

  .trend-legend {
    justify-content: flex-start;
  }
}

@container recruitment-dashboard (max-width: 520px) {
  .recruitment-dashboard > .recruitment-metrics,
  .recruitment-dashboard > .intelligence-overview > div,
  .recruitment-dashboard .today-action-list {
    grid-template-columns: var(--rd-one-column);
  }

  .recruitment-dashboard > .recruitment-metrics > .recruitment-metric,
  .recruitment-dashboard > .recruitment-metrics > .recruitment-metric:last-child {
    grid-column: span 1;
  }

  .recruitment-dashboard > .intelligence-overview button,
  .recruitment-dashboard > .intelligence-overview button:nth-child(even) {
    border-left: var(--rd-space-0);
    border-bottom: var(--rd-panel-border);
  }

  .recruitment-dashboard > .intelligence-overview button:last-child {
    border-bottom: var(--rd-space-0);
  }

  .recruitment-command-workspace > .recruitment-dashboard-panel,
  .recruitment-analysis-workspace > .recruitment-dashboard-panel,
  .recruitment-job-overview > .panel__header,
  .recruitment-recent-panel > .panel__header,
  .job-progress-list > button,
  .dashboard-task-list > button {
    padding-right: var(--rd-space-4);
    padding-left: var(--rd-space-4);
  }
}

@media (prefers-reduced-motion: reduce) {
  .recruitment-metric,
  .intelligence-overview button,
  .today-action-list > button,
  .job-progress-list > button,
  .dashboard-task-list > button {
    transition: none;
  }
}
</style>
