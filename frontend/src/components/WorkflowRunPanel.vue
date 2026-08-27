<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from './AppIcon.vue'

const props = defineProps({ run: { type: Object, required: true }, busy: Boolean })
defineEmits(['pause', 'resume', 'cancel', 'decision', 'retry', 'close'])

const runLabels = { queued: '已排队', running: '运行中', waiting_human: '等待人工', paused: '已暂停', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const runDescriptions = {
  queued: '任务已经提交，正在等待开始。',
  running: '系统正在按招聘方案继续处理。',
  waiting_human: '系统已暂停在需要人工判断的位置，请完成下方处理。',
  paused: '任务已暂停，不会继续处理新的步骤。',
  succeeded: '本次任务已经完成，可以返回结果中心查看结果。',
  failed: '本次任务未能完成，请查看失败步骤并决定是否重试。',
  cancelled: '本次任务已经结束，不会继续处理。',
}
const nodeLabels = { blocked: '等待前一步完成', ready: '等待处理', running: '正在处理', waiting_human: '需要你处理', succeeded: '已完成', failed: '未完成', skipped: '已跳过', cancelled: '已取消' }
const fallbackNodeNames = {
  start: '准备任务', sync: '同步最新咨询', intent: '判断候选人意向', archive_existing: '保存已有简历',
  stop_rejected: '结束未通过咨询', attention: '整理需要人工跟进的事项', approve_request: '确认是否请求简历',
  request: '向候选人请求简历', wait: '等待候选人回复', archive_received: '保存收到的简历',
  search_pull: '搜索候选人并获取简历', end: '完成任务', end_existing: '完成任务', end_received: '完成任务',
}
const planManaged = computed(() => Boolean(props.run.automation_plan_revision))
const planManagedLink = computed(() => {
  const job = typeof props.run.job === 'object' ? props.run.job?.id : props.run.job
  if (props.run.automation_plan) {
    return {
      name: 'recruitment-task-detail',
      params: { planId: String(props.run.automation_plan) },
      query: { job: job ? String(job) : undefined, run: String(props.run.id), view: 'tasks' },
    }
  }
  return { name: 'recruitment-results', query: { job: job ? String(job) : undefined, run: String(props.run.id), view: 'tasks' } }
})
const graphNodeNames = computed(() => new Map(
  (props.run.graph_snapshot?.nodes || []).map((node) => [String(node.key || node.node_key || ''), node.label || node.name || '']),
))
const waitingNodes = computed(() => (props.run.node_runs || []).filter((node) => node.status === 'waiting_human'))
const completedCount = computed(() => (props.run.node_runs || []).filter((node) => ['succeeded', 'skipped'].includes(node.status)).length)

function nodeName(node) {
  return graphNodeNames.value.get(String(node.node_key)) || fallbackNodeNames[node.node_key] || '处理招聘任务'
}
</script>

<template>
  <aside class="workflow-run-panel" aria-label="流程运行状态">
    <header class="workflow-run-header">
      <div><span class="workflow-run-eyebrow">任务进展</span><h3>{{ run.template_name || '招聘任务' }}</h3><small>{{ run.mode === 'dry_run' ? '本次为试运行，不会操作招聘平台' : '系统会在需要你判断时自动暂停' }}</small></div>
      <button class="icon-button" type="button" aria-label="关闭运行面板" @click="$emit('close')"><AppIcon name="close" :size="16" /></button>
    </header>
    <section :class="['workflow-run-summary', `is-${run.status}`]">
      <span class="workflow-run-summary__icon"><AppIcon :name="run.status === 'failed' ? 'alert-circle' : run.status === 'succeeded' ? 'check-circle' : 'briefcase'" :size="20" /></span>
      <div><strong>{{ runLabels[run.status] || '状态更新中' }}</strong><p>{{ runDescriptions[run.status] || '系统正在同步最新进展。' }}</p></div>
      <small v-if="run.account_name">执行账号：{{ run.account_name }}</small>
    </section>
    <div v-if="!planManaged" class="workflow-run-actions">
      <button v-if="['running','waiting_human'].includes(run.status)" type="button" :disabled="busy" @click="$emit('pause')">暂停任务</button>
      <button v-if="run.status === 'paused'" class="is-primary" type="button" :disabled="busy" @click="$emit('resume')">继续任务</button>
      <button v-if="!['succeeded','failed','cancelled'].includes(run.status)" class="is-danger" type="button" :disabled="busy" @click="$emit('cancel')">结束本次任务</button>
    </div>
    <section v-if="planManaged" class="workflow-run-plan-guidance" data-test="plan-managed-guidance">
      <div><strong>任务设置与启停在任务详情中管理</strong><p>这里用于查看进度和处理当前需要你判断的事项。</p></div>
      <RouterLink data-test="plan-managed-task-link" :to="planManagedLink">打开任务详情<AppIcon name="chevron-right" :size="13" /></RouterLink>
    </section>
    <section v-if="waitingNodes.length" class="workflow-run-decisions" aria-label="需要你处理">
      <header><span><AppIcon name="alert-circle" :size="17" /></span><div><strong>需要你处理</strong><small>确认后任务才会继续，请按当前招聘要求判断。</small></div></header>
      <article v-for="node in waitingNodes" :key="node.id">
        <div><strong>{{ nodeName(node) }}</strong><p>{{ node.output?.approval_id ? '此操作会继续执行当前招聘动作，请确认信息无误。' : '系统需要你的判断才能继续后续步骤。' }}</p></div>
        <div class="workflow-run-node-actions"><button type="button" @click="$emit('decision', { nodeId: node.id, approved: false })">{{ node.output?.approval_id ? '暂不执行' : '跳过此步' }}</button><button class="is-primary" type="button" @click="$emit('decision', { nodeId: node.id, approved: true })">{{ node.output?.approval_id ? '同意并继续' : '继续处理' }}</button></div>
      </article>
    </section>
    <section class="workflow-run-progress">
      <header><div><strong>处理进度</strong><small>已完成 {{ completedCount }} / {{ run.node_runs?.length || 0 }} 步</small></div></header>
      <ol>
        <li v-for="node in run.node_runs" :key="node.id" :class="`is-${node.status}`">
          <span class="workflow-run-step-icon"><AppIcon :name="node.status === 'succeeded' ? 'check-circle' : node.status === 'failed' ? 'alert-circle' : 'clock'" :size="14" /></span>
          <div><strong>{{ nodeName(node) }}</strong><small>{{ nodeLabels[node.status] || '状态更新中' }}</small></div>
          <button v-if="node.status === 'failed' && !planManaged" type="button" @click="$emit('retry', node.id)">重新处理</button>
        </li>
      </ol>
    </section>
  </aside>
</template>

<style scoped>
.workflow-run-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
  padding: clamp(20px, 2vw, 30px);
  border: 1px solid #dbe6e4;
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 18px 48px rgba(15, 23, 42, .08);
}

.workflow-run-header {
  display: flex;
  grid-column: 1;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.workflow-run-header > div { display: grid; gap: 4px; }
.workflow-run-eyebrow { color: #0f8f82; font-size: 12px; font-weight: 800; letter-spacing: .08em; }
.workflow-run-header h3 { margin: 0; color: #0f172a; font-size: clamp(20px, 1.5vw, 26px); }
.workflow-run-header small { color: #64748b; font-size: 13px; }

.workflow-run-summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  border: 1px solid #cfe5e1;
  border-radius: 14px;
  color: #0f766e;
  background: #eefaf7;
}

.workflow-run-summary.is-waiting_human,
.workflow-run-summary.is-paused { color: #9a5b08; border-color: #f0d9a9; background: #fff9e9; }
.workflow-run-summary.is-failed,
.workflow-run-summary.is-cancelled { color: #b42332; border-color: #f1c9ce; background: #fff3f4; }
.workflow-run-summary__icon { display: grid; width: 40px; height: 40px; place-content: center; border-radius: 12px; background: rgba(255, 255, 255, .75); }
.workflow-run-summary > div { display: grid; gap: 3px; }
.workflow-run-summary strong { font-size: 15px; }
.workflow-run-summary p { margin: 0; color: #475569; font-size: 13px; line-height: 1.6; }
.workflow-run-summary > small { color: currentColor; font-size: 12px; white-space: nowrap; }

.workflow-run-actions { display: flex; grid-column: 1; gap: 10px; }
.workflow-run-actions button,
.workflow-run-node-actions button,
.workflow-run-progress li > button {
  min-height: 40px;
  padding: 0 15px;
  border: 1px solid #cbd8d6;
  border-radius: 10px;
  color: #334155;
  background: #fff;
  font-size: 13px;
  font-weight: 750;
  cursor: pointer;
}
.workflow-run-actions .is-primary,
.workflow-run-node-actions .is-primary { color: #fff; border-color: #0f9f8f; background: #0f9f8f; }
.workflow-run-actions .is-danger { color: #b42332; border-color: #efc5ca; }

.workflow-run-plan-guidance {
  display: flex;
  grid-column: 1;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid #d8e5e3;
  border-radius: 12px;
  color: #334155;
  background: #f7faf9;
}

.workflow-run-plan-guidance > div { display: grid; gap: 3px; }
.workflow-run-plan-guidance strong { font-size: 13px; }
.workflow-run-plan-guidance p { margin: 0; color: #64748b; font-size: 12px; line-height: 1.55; }

.workflow-run-plan-guidance a {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 5px;
  color: #087f73;
  font-size: 13px;
  font-weight: 750;
  text-decoration: none;
}

.workflow-run-decisions {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid #efcf91;
  border-radius: 15px;
  background: #fffbeb;
  box-shadow: 0 8px 20px rgba(146, 91, 8, .06);
}
.workflow-run-decisions > header { display: flex; align-items: center; gap: 10px; }
.workflow-run-decisions > header > span { display: grid; width: 34px; height: 34px; place-content: center; color: #9a5b08; border-radius: 10px; background: #fff3cd; }
.workflow-run-decisions header div { display: grid; gap: 2px; }
.workflow-run-decisions header strong { color: #714207; font-size: 14px; }
.workflow-run-decisions header small { color: #8a6425; font-size: 12px; }
.workflow-run-decisions article { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 14px 16px; border: 1px solid rgba(224, 184, 110, .55); border-radius: 12px; background: #fff; }
.workflow-run-decisions article > div:first-child { display: grid; gap: 4px; }
.workflow-run-decisions article strong { color: #1e293b; font-size: 14px; }
.workflow-run-decisions article p { margin: 0; color: #64748b; font-size: 12px; line-height: 1.55; }
.workflow-run-node-actions { display: flex; flex: none; gap: 8px; }

.workflow-run-progress { display: grid; gap: 12px; }
.workflow-run-progress > header > div { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.workflow-run-progress header strong { color: #1e293b; font-size: 15px; }
.workflow-run-progress header small { color: #64748b; font-size: 12px; }
.workflow-run-progress ol { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; margin: 0; padding: 0; list-style: none; }
.workflow-run-progress li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; min-height: 66px; padding: 12px 14px; border: 1px solid #e2e8e7; border-radius: 12px; background: #fbfcfc; }
.workflow-run-step-icon { display: grid; width: 28px; height: 28px; place-content: center; color: #94a3b8; border-radius: 50%; background: #eef2f1; }
.workflow-run-progress li.is-running .workflow-run-step-icon { color: #0f8f82; background: #e4f6f3; }
.workflow-run-progress li.is-waiting_human .workflow-run-step-icon { color: #a16207; background: #fff1c6; }
.workflow-run-progress li.is-succeeded .workflow-run-step-icon { color: #087f5b; background: #e7f7ef; }
.workflow-run-progress li.is-failed .workflow-run-step-icon { color: #b42332; background: #fff0f2; }
.workflow-run-progress li > div { display: grid; gap: 3px; min-width: 0; }
.workflow-run-progress li strong { overflow: hidden; color: #334155; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.workflow-run-progress li small { color: #64748b; font-size: 12px; }
.workflow-run-progress li > button { min-height: 34px; padding: 0 10px; color: #b42332; font-size: 12px; }

@media (max-width: 760px) {
  .workflow-run-summary { grid-template-columns: auto minmax(0, 1fr); }
  .workflow-run-summary > small { grid-column: 2; white-space: normal; }
  .workflow-run-plan-guidance,
  .workflow-run-decisions article { align-items: stretch; flex-direction: column; }
  .workflow-run-plan-guidance a { align-self: flex-start; }
  .workflow-run-node-actions { display: grid; grid-template-columns: 1fr 1fr; }
  .workflow-run-node-actions button { min-height: 44px; }
}
</style>
