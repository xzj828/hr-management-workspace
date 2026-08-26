<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from './AppIcon.vue'

const props = defineProps({ run: { type: Object, required: true }, busy: Boolean })
defineEmits(['pause', 'resume', 'cancel', 'decision', 'retry', 'close'])

const runLabels = { queued: '已排队', running: '运行中', waiting_human: '等待人工', paused: '已暂停', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const nodeLabels = { blocked: '等待前置', ready: '就绪', running: '运行中', waiting_human: '等待人工', succeeded: '成功', failed: '失败', skipped: '已跳过', cancelled: '已取消' }
const planManaged = computed(() => Boolean(props.run.automation_plan_revision))
const workbenchLink = computed(() => {
  const job = typeof props.run.job === 'object' ? props.run.job?.id : props.run.job
  return { name: 'recruitment-workbench', query: job ? { job: String(job), step: 'plan' } : { step: 'plan' } }
})
</script>

<template>
  <aside class="workflow-run-panel" aria-label="流程运行状态">
    <header>
      <div><span class="panel-kicker">LIVE RUN</span><h3>{{ run.template_name || '流程运行' }}</h3><small>{{ run.mode === 'dry_run' ? '试运行 · 不会操作 BOSS' : '正式运行 · HR 确认受控' }}</small></div>
      <button class="icon-button" type="button" aria-label="关闭运行面板" @click="$emit('close')"><AppIcon name="close" :size="16" /></button>
    </header>
    <div class="workflow-run-state"><i :class="`is-${run.status}`"></i><strong>{{ runLabels[run.status] || run.status }}</strong><span>{{ run.account_name }}</span></div>
    <div v-if="!planManaged" class="workflow-run-actions">
      <button v-if="['running','waiting_human'].includes(run.status)" type="button" :disabled="busy" @click="$emit('pause')">暂停</button>
      <button v-if="run.status === 'paused'" type="button" :disabled="busy" @click="$emit('resume')">继续</button>
      <button v-if="!['succeeded','failed','cancelled'].includes(run.status)" class="is-danger" type="button" :disabled="busy" @click="$emit('cancel')">取消运行</button>
    </div>
    <section v-if="planManaged" class="workflow-run-plan-guidance" data-test="plan-managed-guidance">
      <strong>本次运行由招聘任务计划统一管理</strong>
      <p>请回招聘作业台停止/修改/重新开启；这里仍可处理等待人工确认的节点。</p>
      <RouterLink data-test="plan-managed-workbench-link" :to="workbenchLink">返回招聘作业台</RouterLink>
    </section>
    <section class="workflow-run-nodes"><span>节点进度</span><article v-for="node in run.node_runs" :key="node.id" :class="`is-${node.status}`"><i></i><div><strong>{{ node.node_key }}</strong><small>{{ nodeLabels[node.status] || node.status }}<template v-if="node.attempt"> · 第 {{ node.attempt + 1 }} 次</template></small></div><div v-if="node.status === 'waiting_human'" class="workflow-run-node-actions"><button type="button" @click="$emit('decision', { nodeId: node.id, approved: false })">{{ node.output?.approval_id ? '拒绝' : '跳过' }}</button><button class="is-primary" type="button" @click="$emit('decision', { nodeId: node.id, approved: true })">{{ node.output?.approval_id ? '确认并继续' : '通过' }}</button></div><button v-if="node.status === 'failed' && !planManaged" type="button" @click="$emit('retry', node.id)">重试</button></article></section>
    <section class="workflow-run-events"><span>运行日志</span><ol><li v-for="event in run.events?.slice().reverse()" :key="event.id"><time>{{ new Date(event.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }}</time><p>{{ event.message }}</p></li></ol></section>
  </aside>
</template>

<style scoped>
.workflow-run-plan-guidance {
  grid-column: 1 / -1;
  display: grid;
  gap: 6px;
  padding: 11px 12px;
  border: 1px solid #f1d7a8;
  border-radius: 10px;
  color: #714207;
  background: #fffbeb;
}

.workflow-run-plan-guidance strong,
.workflow-run-plan-guidance p {
  margin: 0;
  font-size: 9px;
  line-height: 1.55;
}

.workflow-run-plan-guidance a {
  justify-self: start;
  color: #087f73;
  font-size: 9px;
  font-weight: 750;
}
</style>
