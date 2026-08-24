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
})

const metricCards = [
  { key: 'open_jobs', label: '在招职位', note: '当前开放', icon: 'briefcase', route: '/recruitment/jobs' },
  { key: 'active_candidates', label: '活跃候选人', note: '招聘流程中', icon: 'users', route: '/recruitment/candidates' },
  { key: 'waiting_resumes', label: '待收简历', note: '等待候选人', icon: 'document', route: '/recruitment/resumes' },
  { key: 'waiting_interviews', label: '待安排面试', note: '需要 HR 跟进', icon: 'calendar-check', route: '/recruitment/pipeline' },
  { key: 'boss_accounts_ready', label: '可用 BOSS 账号', note: '登录状态正常', icon: 'shield', route: '/recruitment/automation' },
]

const actionIcons = { to_contact: 'user', to_screen: 'document', to_interview: 'calendar-check', waiting_human: 'alert-circle' }
const funnelMax = computed(() => Math.max(1, ...dashboard.funnel.map((item) => item.count)))
const trendMax = computed(() => Math.max(1, ...dashboard.trend.flatMap((item) => [item.candidates, item.resumes, item.interviews, item.hires])))
const isEmpty = computed(() => !loading.value && !error.value && Object.values(dashboard.metrics).every((value) => value === 0))

function go(route) {
  if (route) router.push(route)
}

function formatTime(value) {
  return value ? new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : '—'
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

    <section v-if="isEmpty" class="panel recruitment-dashboard-empty">
      <span class="recruitment-dashboard-empty__icon"><AppIcon name="briefcase" :size="24" /></span>
      <div><span class="panel-kicker">GET STARTED</span><h3>从连接 BOSS 账号开始</h3><p>完成登录后同步职位，候选人、简历与自动化进度会汇总到这里。</p></div>
      <button class="primary-button" type="button" @click="go('/recruitment/automation')">前往自动化任务</button>
    </section>

    <template v-else>
      <div class="recruitment-command-grid">
        <section class="panel recruitment-dashboard-panel">
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

      <div class="recruitment-analysis-grid">
        <section class="panel recruitment-dashboard-panel">
          <header class="panel__header"><div><span class="panel-kicker">PIPELINE</span><h3>招聘漏斗</h3></div><button class="text-button" type="button" @click="go('/recruitment/pipeline')">查看流程</button></header>
          <div class="recruitment-funnel"><div v-for="item in dashboard.funnel" :key="item.key"><span>{{ item.label }}</span><div><i :style="{ width: `${Math.max(3, item.count / funnelMax * 100)}%` }"></i></div><strong>{{ item.count }}</strong></div></div>
        </section>

        <section class="panel recruitment-dashboard-panel">
          <header class="panel__header"><div><span class="panel-kicker">7 DAY PULSE</span><h3>近 7 天趋势</h3></div><span class="trend-legend"><i></i>候选人 <i></i>简历 <i></i>面试 <i></i>录用</span></header>
          <div class="recruitment-trend" role="img" aria-label="近七天候选人、简历、面试和录用数量趋势">
            <div v-for="day in dashboard.trend" :key="day.date" data-test="trend-day" :aria-label="`${day.label}：候选人 ${day.candidates}，简历 ${day.resumes}，面试 ${day.interviews}，录用 ${day.hires}`"><span class="trend-bars"><i :style="{ height: `${day.candidates / trendMax * 100}%` }"></i><i :style="{ height: `${day.resumes / trendMax * 100}%` }"></i><i :style="{ height: `${day.interviews / trendMax * 100}%` }"></i><i :style="{ height: `${day.hires / trendMax * 100}%` }"></i></span><small>{{ day.label }}</small></div>
          </div>
        </section>
      </div>

      <div class="recruitment-detail-grid-dashboard">
        <section class="panel recruitment-dashboard-panel">
          <header class="panel__header"><div><span class="panel-kicker">HIRING GOALS</span><h3>职位进度</h3></div><button class="text-button" type="button" @click="go('/recruitment/jobs')">全部职位</button></header>
          <div v-if="dashboard.job_progress.length" class="job-progress-list"><button v-for="job in dashboard.job_progress" :key="job.id" type="button" @click="go(job.route)"><span><strong>{{ job.title }}</strong><small>{{ job.candidates }} 位候选人 · {{ job.interviews }} 人进入面试 · {{ job.hired }} 人录用</small></span><span class="job-progress-track"><i :style="{ width: `${job.completion}%` }"></i></span><b>{{ job.completion }}%</b><small>{{ job.hired }}/{{ job.headcount }}</small></button></div>
          <p v-else class="table-empty">暂无在招职位</p>
        </section>

        <section class="panel recruitment-dashboard-panel">
          <header class="panel__header"><div><span class="panel-kicker">AUTOMATION LOG</span><h3>最近自动化</h3></div><button class="text-button" type="button" @click="go('/recruitment/automation')">查看全部</button></header>
          <div v-if="dashboard.recent_tasks.length" class="dashboard-task-list"><button v-for="task in dashboard.recent_tasks" :key="task.id" type="button" @click="go(task.route)"><i :class="`is-${task.status}`"></i><span><strong>{{ task.action_label }}</strong><small>{{ task.account_name }} · {{ formatTime(task.created_at) }}</small></span><b>{{ task.status_label }}</b></button></div>
          <p v-else class="table-empty">暂无自动化记录</p>
        </section>
      </div>
    </template>
  </div>
</template>
