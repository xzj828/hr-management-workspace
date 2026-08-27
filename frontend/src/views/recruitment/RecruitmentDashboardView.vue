<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import { BriefcaseBusiness, CalendarDays, CircleAlert, FileText, ShieldAlert, UserRound } from '@lucide/vue'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const dashboard = reactive({
  metrics: { open_jobs: 0, active_candidates: 0, waiting_resumes: 0, waiting_interviews: 0, boss_accounts_ready: 0 },
  today_actions: [], alerts: [], job_progress: [],
})

const metricCards = [
  { key: 'open_jobs', label: '在招职位', icon: 'briefcase', route: '/recruitment/jobs' },
  { key: 'active_candidates', label: '活跃候选人', icon: 'users', route: '/recruitment/candidates' },
  { key: 'waiting_resumes', label: '待收简历', icon: 'document', route: '/recruitment/resumes' },
  { key: 'waiting_interviews', label: '待安排面试', icon: 'calendar-check', route: '/recruitment/pipeline' },
  { key: 'boss_accounts_ready', label: '可用招聘账号', icon: 'shield', route: '/recruitment/automation' },
]
const actionIcons = { to_contact: UserRound, to_screen: FileText, to_interview: CalendarDays, waiting_human: CircleAlert }
const todayParts = new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', weekday: 'long' })
  .formatToParts(new Date()).reduce((parts, item) => ({ ...parts, [item.type]: item.value }), {})
const todayLabel = `${todayParts.month}月${todayParts.day}日 ${todayParts.weekday}`
const isEmpty = computed(() => !loading.value && !error.value && Object.values(dashboard.metrics).every((value) => value === 0))
const visibleJobs = computed(() => dashboard.job_progress.slice(0, 2))

function go(route) { if (route) router.push(route) }
function progressFor(job) {
  if (job.completion > 0) return job.completion
  if (job.to_interview > 0 || job.interviews > 0) return 50
  if (job.to_screen > 0) return Math.min(50, Math.max(25, Math.round(job.to_screen / Math.max(job.headcount, 1) * 50)))
  if (job.candidates > 0) return 25
  return 0
}
function jobStage(job) {
  if (job.hired > 0) return '录用推进'
  if (job.to_interview > 0 || job.interviews > 0) return '面试推进'
  return '简历筛选'
}
function jobWarning(job) { return progressFor(job) >= 50 ? '简历筛选较慢' : '简历量不足' }

async function loadDashboard() {
  loading.value = true
  error.value = ''
  try { Object.assign(dashboard, await api('recruitment/dashboard/')) }
  catch (err) { error.value = err.message }
  finally { loading.value = false }
}
onMounted(loadDashboard)
</script>

<template>
  <div class="recruitment-dashboard">
    <header class="dashboard-hero">
      <div><h1>招聘看板</h1><p>聚焦今日优先事项，推动招聘流程高效向前。</p></div>
      <div class="dashboard-hero__actions">
        <div class="dashboard-date"><strong>{{ todayLabel }}</strong><span><i></i>数据随工作台更新</span></div>
        <button class="dashboard-create" type="button" @click="go('/recruitment/workbench?new=1')"><AppIcon name="plus" :size="18" />创建招聘任务</button>
      </div>
    </header>

    <section v-if="loading" class="dashboard-loading" aria-live="polite" aria-label="正在加载招聘看板">
      <span class="sr-only">正在加载招聘看板</span><div></div><div></div><div></div>
    </section>
    <section v-else-if="error" class="dashboard-state dashboard-state--error" role="alert">
      <span><AppIcon name="alert-circle" :size="25" /></span><div><strong>招聘看板暂时无法加载</strong><p>{{ error }}</p></div><button type="button" data-test="dashboard-retry" @click="loadDashboard">重新加载</button>
    </section>
    <section v-else-if="isEmpty" class="dashboard-state dashboard-state--empty">
      <span><AppIcon name="briefcase" :size="25" /></span><div><h2>先同步在招职位</h2><p>前往职位管理同步 BOSS 职位，成功后即可查看招聘进度。</p></div><button type="button" @click="go('/recruitment/jobs')">前往职位管理</button>
    </section>

    <template v-else>
      <div class="dashboard-main-grid">
        <section class="dashboard-card dashboard-priority" aria-labelledby="today-priority-title">
          <header><h2 id="today-priority-title">今日优先</h2><p>按影响招聘进度排序，建议优先处理高优先级事项</p></header>
          <div class="priority-list">
            <button v-for="action in dashboard.today_actions" :key="action.key" type="button" :data-test="`today-action-${action.key}`" @click="go(action.route)">
              <span class="priority-icon"><component :is="actionIcons[action.key] || CircleAlert" :size="32" :stroke-width="1.9" /></span>
              <span class="priority-copy"><strong>{{ action.label }}</strong><small>有待处理事项</small></span>
              <b>{{ action.count }}</b><AppIcon class="priority-arrow" name="chevron-right" :size="18" />
            </button>
          </div>
        </section>

        <div class="dashboard-side-column">
          <section class="dashboard-card dashboard-jobs" aria-labelledby="job-progress-title">
            <header class="card-title-row"><h2 id="job-progress-title">职位进度</h2><button type="button" @click="go('/recruitment/jobs')">查看全部职位</button></header>
            <div v-if="visibleJobs.length" class="job-list">
              <button v-for="job in visibleJobs" :key="job.id" type="button" :data-test="`job-progress-${job.id}`" @click="go(job.route)">
                <span class="job-heading">
                  <i><BriefcaseBusiness :size="23" :stroke-width="1.9" /></i>
                  <span><strong>{{ job.title }}</strong><small>在招 {{ job.headcount }} 人&nbsp; | &nbsp;已入职 {{ job.hired }} 人</small></span>
                  <b>{{ progressFor(job) }}%</b><em>{{ job.hired }} / {{ job.headcount }}</em>
                </span>
                <span class="job-track"><i :style="{ width: `${progressFor(job)}%` }"></i></span>
                <span class="job-foot"><small>当前阶段：{{ jobStage(job) }}</small><em>{{ jobWarning(job) }}</em></span>
              </button>
            </div>
            <p v-else class="jobs-empty">暂无在招职位，请先到职位管理同步</p>
          </section>

          <section class="dashboard-card dashboard-risk" aria-labelledby="risk-title">
            <header class="card-title-row"><h2 id="risk-title">风险提醒</h2><button type="button" @click="go('/recruitment/automation')">查看全部</button></header>
            <button v-if="dashboard.alerts.length" class="risk-row" type="button" @click="go(dashboard.alerts[0].route)">
              <i class="risk-row__warning"><ShieldAlert :size="34" :stroke-width="1.9" /></i><span><strong>{{ dashboard.alerts[0].title }}</strong><small>{{ dashboard.alerts[0].detail }}</small></span><AppIcon class="risk-row__status" name="chevron-right" :size="18" />
            </button>
            <div v-else class="risk-row">
              <i class="risk-row__warning"><ShieldAlert :size="34" :stroke-width="1.9" /></i><span><strong>当前没有需要处理的风险</strong><small>账号与自动化任务运行正常</small></span><i class="risk-row__status"><AppIcon name="check-circle" :size="25" /></i>
            </div>
          </section>
        </div>
      </div>

      <section class="dashboard-metrics" aria-labelledby="metrics-title">
        <header><h2 id="metrics-title">关键数据</h2><span>点击指标查看对应工作区</span></header>
        <div class="metrics-strip">
          <button v-for="card in metricCards" :key="card.key" type="button" data-test="dashboard-metric" @click="go(card.route)">
            <span><small>{{ card.label }}</small><strong>{{ dashboard.metrics[card.key] }}</strong></span><i><BriefcaseBusiness v-if="card.key === 'open_jobs'" :size="21" :stroke-width="1.9" /><AppIcon v-else :name="card.icon" :size="20" /></i>
          </button>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.recruitment-dashboard { --dashboard-ink:#0b1427; --dashboard-copy:#63708a; --dashboard-line:#dce3e9; --dashboard-teal:#078d80; min-width:0; display:grid; gap:13px; container-type:inline-size; }
.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; }
.dashboard-hero { min-height:96px; display:flex; align-items:flex-start; justify-content:space-between; gap:24px; }
.dashboard-hero h1 { margin:0; color:var(--dashboard-ink); font-size:34px; line-height:1.22; letter-spacing:-.04em; }
.dashboard-hero p { margin:16px 0 0; color:#66738c; font-size:15px; line-height:1.5; }
.dashboard-hero__actions { display:flex; align-items:flex-start; gap:40px; padding-top:14px; }
.dashboard-date { min-width:166px; display:grid; justify-items:end; gap:5px; }
.dashboard-date strong { color:#28354a; font-size:15px; line-height:1.4; }
.dashboard-date span { display:inline-flex; align-items:center; gap:8px; color:#60708a; font-size:13px; white-space:nowrap; }
.dashboard-date i { width:8px; height:8px; border-radius:50%; background:#10a390; box-shadow:0 0 0 5px rgba(16,163,144,.1); }
.dashboard-create { min-width:177px; height:57px; display:inline-flex; align-items:center; justify-content:center; gap:11px; padding:0 18px; color:#fff; background:#0b172a; border:0; border-radius:11px; box-shadow:0 8px 18px rgba(15,23,42,.15); font-size:15px; }
.dashboard-create:hover { background:#17243a; transform:translateY(-1px); }
.dashboard-main-grid { min-width:0; height:615px; display:grid; grid-template-columns:minmax(0,1.475fr) minmax(330px,1fr); gap:17px; }
.dashboard-card { min-width:0; overflow:hidden; background:rgba(255,255,255,.92); border:1px solid var(--dashboard-line); border-radius:11px; box-shadow:0 1px 2px rgba(15,23,42,.015); }
.dashboard-card h2 { margin:0; color:var(--dashboard-ink); font-size:20px; line-height:1.3; letter-spacing:-.025em; }
.dashboard-priority { display:grid; grid-template-rows:98px minmax(0,1fr); }
.dashboard-priority>header { padding:22px 28px 18px; border-bottom:1px solid var(--dashboard-line); }
.dashboard-priority>header p { margin:5px 0 0; color:#66758e; font-size:13px; }
.priority-list { padding:0 24px; }
.priority-list>button { width:100%; height:125px; display:grid; grid-template-columns:74px minmax(0,1fr) auto 28px; align-items:center; gap:20px; padding:0 17px 0 4px; color:inherit; background:transparent; border:0; border-bottom:1px solid var(--dashboard-line); text-align:left; }
.priority-list>button:last-child { border-bottom:0; }
.priority-list>button:hover { background:#f9fcfc; }
.priority-icon { width:74px; height:74px; display:grid; place-content:center; color:var(--dashboard-teal); background:#eaf4f3; border-radius:11px; }
.priority-copy { display:grid; gap:2px; }
.priority-copy strong { color:var(--dashboard-ink); font-size:19px; line-height:1.4; }
.priority-copy small { color:#65728a; font-size:16px; line-height:1.4; }
.priority-list b { min-width:28px; color:#050d1d; font-size:44px; line-height:1; text-align:right; }
.priority-arrow { color:#15233a; }
.dashboard-side-column { min-width:0; display:grid; grid-template-rows:451px 152px; gap:12px; }
.dashboard-jobs { padding:27px 26px 20px; }
.card-title-row { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.card-title-row button { padding:3px 0; color:#596984; background:transparent; border:0; font-size:14px; }
.card-title-row button:hover { color:var(--dashboard-teal); }
.job-list { margin-top:35px; }
.job-list>button { width:100%; height:164px; display:grid; align-content:start; gap:28px; padding:0 0 17px; color:inherit; background:transparent; border:0; border-bottom:1px solid var(--dashboard-line); text-align:left; }
.job-list>button+button { height:196px; padding-top:29px; }
.job-list>button:last-child { border-bottom:0; }
.job-heading { display:grid; grid-template-columns:50px minmax(0,1fr) auto; grid-template-rows:auto auto; align-items:center; column-gap:12px; }
.job-heading>i { width:50px; height:50px; grid-row:1/3; display:grid; place-content:center; color:var(--dashboard-teal); background:#eaf4f3; border-radius:11px; font-style:normal; }
.job-heading>span { grid-row:1/3; display:grid; gap:3px; }
.job-heading strong { color:var(--dashboard-ink); font-size:16px; line-height:1.35; }
.job-heading small { color:#64728a; font-size:12px; }
.job-heading b { color:var(--dashboard-teal); font-size:20px; line-height:1.1; text-align:right; }
.job-heading em { color:#5e6d87; font-size:14px; font-style:normal; text-align:right; }
.job-track { height:8px; overflow:hidden; background:#edf0f3; border-radius:99px; }
.job-track i { height:100%; display:block; background:linear-gradient(90deg,#078d80,#079b8c); border-radius:inherit; }
.job-foot { display:flex; align-items:center; justify-content:space-between; gap:12px; transform:translateY(-8px); }
.job-foot small { color:#6c7b91; font-size:12px; }
.job-foot em { padding:5px 11px; color:#d77b00; background:#fff4de; border-radius:9px; font-size:12px; font-style:normal; white-space:nowrap; }
.jobs-empty { min-height:300px; display:grid; place-content:center; margin:0; color:#7b8799; font-size:13px; }
.dashboard-risk { padding:22px 26px 14px; }
.dashboard-risk .card-title-row h2 { font-size:19px; }
.risk-row { width:100%; min-height:78px; display:grid; grid-template-columns:43px minmax(0,1fr) auto; align-items:center; gap:14px; padding:12px 0 0; color:inherit; background:transparent; border:0; text-align:left; }
.risk-row__warning { color:#f1242f; font-style:normal; }
.risk-row>span { display:grid; gap:4px; }
.risk-row strong { color:#182238; font-size:13px; }
.risk-row small { color:#69778c; font-size:12px; }
.risk-row__status { display:grid; place-content:center; color:#09988b; font-style:normal; }
.dashboard-metrics { display:grid; gap:15px; margin-top:30px; }
.dashboard-metrics>header { display:flex; align-items:center; justify-content:space-between; padding:0 3px; }
.dashboard-metrics>header h2 { margin:0; color:#40506a; font-size:15px; }
.dashboard-metrics>header span { color:#64738a; font-size:12px; }
.metrics-strip { min-height:124px; display:grid; grid-template-columns:220fr 231fr 230fr 233fr 228fr; background:rgba(255,255,255,.92); border:1px solid var(--dashboard-line); border-radius:10px; }
.metrics-strip>button { min-width:0; display:flex; align-items:center; justify-content:space-between; gap:14px; margin:20px 0; padding:0 28px 0 24px; color:inherit; background:transparent; border:0; border-right:1px solid var(--dashboard-line); text-align:left; }
.metrics-strip>button:last-child { border-right:0; }
.metrics-strip>button:hover { background:#f9fcfc; }
.metrics-strip>button>span { display:grid; gap:8px; }
.metrics-strip small { color:#65738a; font-size:13px; white-space:nowrap; }
.metrics-strip strong { color:#071024; font-size:36px; line-height:1; }
.metrics-strip i { width:42px; height:42px; display:grid; place-content:center; flex:0 0 auto; color:var(--dashboard-teal); background:#eaf4f3; border-radius:14px; font-style:normal; }
.dashboard-loading { height:790px; display:grid; grid-template-columns:1.475fr 1fr; grid-template-rows:451px 152px 124px; gap:17px; }
.dashboard-loading div { background:linear-gradient(100deg,#edf2f5 30%,#fafcfd 50%,#edf2f5 70%); background-size:260% 100%; border:1px solid var(--dashboard-line); border-radius:11px; animation:shimmer 1.2s infinite; }
.dashboard-loading div:first-of-type { grid-row:1/3; }
.dashboard-loading div:last-of-type { grid-column:1/-1; }
.dashboard-state { min-height:615px; display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:18px; padding:32px; background:#fff; border:1px solid var(--dashboard-line); border-radius:11px; }
.dashboard-state>span { width:54px; height:54px; display:grid; place-content:center; color:var(--dashboard-teal); background:#eaf4f3; border-radius:13px; }
.dashboard-state h2,.dashboard-state strong { margin:0; color:var(--dashboard-ink); font-size:18px; }
.dashboard-state p { margin:5px 0 0; color:var(--dashboard-copy); }
.dashboard-state button { min-height:40px; padding:0 15px; color:#fff; background:#0b172a; border:0; border-radius:9px; }
.dashboard-state--error>span { color:#e23c49; background:#fff0f1; }
@keyframes shimmer { 50% { background-position:100% 0; } }
@container (max-width:900px) { .dashboard-main-grid{height:auto;grid-template-columns:1fr}.dashboard-priority{min-height:615px}.dashboard-side-column{grid-template-rows:auto auto}.dashboard-jobs{min-height:451px}.metrics-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.metrics-strip>button{border-bottom:1px solid var(--dashboard-line)} }
@media (max-width:760px) { .dashboard-hero{min-height:0;display:grid;gap:18px}.dashboard-hero h1{font-size:29px}.dashboard-hero p{margin-top:9px;font-size:13px}.dashboard-hero__actions{width:100%;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:12px;padding-top:0}.dashboard-date{min-width:0;justify-items:start}.dashboard-date strong{font-size:13px}.dashboard-date span{font-size:11px}.dashboard-create{min-width:158px;height:48px;padding:0 13px;font-size:13px}.priority-list{padding:0 12px}.priority-list>button{grid-template-columns:56px minmax(0,1fr) auto 18px;gap:12px;padding-right:8px}.priority-icon{width:56px;height:56px}.priority-copy strong{font-size:16px}.priority-copy small{font-size:13px}.priority-list b{font-size:34px}.dashboard-jobs,.dashboard-risk{padding-right:18px;padding-left:18px}.metrics-strip{grid-template-columns:1fr}.metrics-strip>button{min-height:92px;margin:0;border-right:0}.dashboard-metrics>header span{display:none} }
</style>
