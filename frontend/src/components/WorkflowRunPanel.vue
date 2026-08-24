<script setup>
import AppIcon from './AppIcon.vue'

defineProps({ run: { type: Object, required: true }, busy: Boolean })
defineEmits(['pause', 'resume', 'cancel', 'decision', 'retry', 'close'])

const runLabels = { queued: '已排队', running: '运行中', waiting_human: '等待人工', paused: '已暂停', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const nodeLabels = { blocked: '等待前置', ready: '就绪', running: '运行中', waiting_human: '等待人工', succeeded: '成功', failed: '失败', skipped: '已跳过', cancelled: '已取消' }
</script>

<template>
  <aside class="workflow-run-panel" aria-label="流程运行状态">
    <header>
      <div><span class="panel-kicker">LIVE RUN</span><h3>{{ run.template_name || '流程运行' }}</h3><small>{{ run.mode === 'dry_run' ? '试运行 · 不会操作 BOSS' : '正式运行 · HR 确认受控' }}</small></div>
      <button class="icon-button" type="button" aria-label="关闭运行面板" @click="$emit('close')"><AppIcon name="close" :size="16" /></button>
    </header>
    <div class="workflow-run-state"><i :class="`is-${run.status}`"></i><strong>{{ runLabels[run.status] || run.status }}</strong><span>{{ run.account_name }}</span></div>
    <div class="workflow-run-actions">
      <button v-if="['running','waiting_human'].includes(run.status)" type="button" :disabled="busy" @click="$emit('pause')">暂停</button>
      <button v-if="run.status === 'paused'" type="button" :disabled="busy" @click="$emit('resume')">继续</button>
      <button v-if="!['succeeded','failed','cancelled'].includes(run.status)" class="is-danger" type="button" :disabled="busy" @click="$emit('cancel')">取消运行</button>
    </div>
    <section class="workflow-run-nodes"><span>节点进度</span><article v-for="node in run.node_runs" :key="node.id" :class="`is-${node.status}`"><i></i><div><strong>{{ node.node_key }}</strong><small>{{ nodeLabels[node.status] || node.status }}<template v-if="node.attempt"> · 第 {{ node.attempt + 1 }} 次</template></small></div><div v-if="node.status === 'waiting_human'" class="workflow-run-node-actions"><button type="button" @click="$emit('decision', { nodeId: node.id, approved: false })">跳过</button><button class="is-primary" type="button" @click="$emit('decision', { nodeId: node.id, approved: true })">通过</button></div><button v-if="node.status === 'failed'" type="button" @click="$emit('retry', node.id)">重试</button></article></section>
    <section class="workflow-run-events"><span>运行日志</span><ol><li v-for="event in run.events?.slice().reverse()" :key="event.id"><time>{{ new Date(event.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }}</time><p>{{ event.message }}</p></li></ol></section>
  </aside>
</template>
