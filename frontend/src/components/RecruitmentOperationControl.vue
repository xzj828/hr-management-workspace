<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  plan: { type: Object, required: true },
  busy: { type: [String, Boolean], default: '' },
  error: { type: String, default: '' },
  resultsTo: { type: Object, default: null },
  restartDisabled: { type: Boolean, default: false },
  disabledReason: { type: String, default: '' },
})

defineEmits(['resume', 'stop', 'stop-modify', 'modify', 'restart'])

const state = computed(() => {
  const value = String(props.plan.effective_state || props.plan.actual_state || props.plan.current_run?.status || props.plan.desired_state || '')
  return {
    queued: 'starting',
    pending: 'starting',
    waiting_human: 'waiting_human',
    succeeded: 'completed',
    cancelled: 'stopped',
  }[value] || value || 'stopped'
})

const active = computed(() => ['starting', 'running', 'waiting_human'].includes(state.value))
const terminal = computed(() => ['stopped', 'failed', 'completed'].includes(state.value))
const stateLabel = computed(() => ({
  starting: '正在开启',
  running: '运行中',
  waiting_human: '等待人工处理',
  paused: '已暂停',
  stopping: '正在停止',
  stopped: '已停止',
  failed: '运行失败',
  completed: '本轮已完成',
}[state.value] || '状态同步中'))
const stateHint = computed(() => ({
  starting: '服务端正在创建本轮运行，请稍候。',
  running: '当前版本正在执行；停止会取消尚未开始的待确认、打招呼和求简历任务。',
  waiting_human: '自动化正在等待人工确认；停止会取消尚未开始的确认与发送任务。',
  paused: '不会领取新的执行步骤；继续后沿用当前版本。',
  stopping: '停止指令已生效；已进入浏览器的单个动作会安全收尾，但不会再开始下一项。',
  stopped: '当前任务不会再产生新的自动化动作。',
  failed: '本轮已经结束；重新开启会生成新方案版本，并可能再次占用额度。',
  completed: '本轮已经完成；可先修改，或明确重新开启一个新方案版本。',
}[state.value] || '正在从服务端同步任务状态。'))
const revisionLabel = computed(() => {
  const revision = props.plan.current_revision
  const value = revision && typeof revision === 'object'
    ? (revision.revision ?? revision.version ?? revision.id)
    : revision
  return value ? `方案 V${value}` : '当前方案'
})
</script>

<template>
  <section
    :class="['recruitment-operation-control', `is-${state}`]"
    data-test="operation-control"
    aria-live="polite"
    aria-atomic="true"
  >
    <header>
      <span class="recruitment-operation-control__icon"><AppIcon name="workflow" :size="19" /></span>
      <div>
        <small>{{ revisionLabel }}</small>
        <strong data-test="operation-state">{{ stateLabel }}</strong>
      </div>
      <i aria-hidden="true"></i>
    </header>

    <p>{{ stateHint }}</p>
    <small v-if="plan.current_run?.id" class="recruitment-operation-control__run">
      运行编号 {{ plan.current_run.id }}
    </small>

    <p v-if="error" class="recruitment-operation-control__error" role="alert">{{ error }}</p>
    <p v-if="disabledReason" class="recruitment-operation-control__disabled-reason" role="status">
      {{ disabledReason }}
    </p>

    <div class="recruitment-operation-control__actions">
      <template v-if="active">
        <button
          class="recruitment-operation-control__stop"
          data-test="stop-operation"
          type="button"
          :disabled="Boolean(busy)"
          @click="$emit('stop')"
        >
          {{ busy === 'stop' ? '正在停止…' : '停止任务' }}
        </button>
        <button
          data-test="stop-and-modify-operation"
          type="button"
          :disabled="Boolean(busy)"
          @click="$emit('stop-modify')"
        >
          {{ busy === 'stop-modify' ? '正在停止…' : '停止并修改' }}
        </button>
      </template>

      <template v-else-if="state === 'paused'">
        <button
          class="recruitment-operation-control__primary"
          data-test="resume-operation"
          type="button"
          :disabled="Boolean(busy)"
          @click="$emit('resume')"
        >
          {{ busy === 'resume' ? '正在继续…' : '继续任务' }}
        </button>
        <button
          class="recruitment-operation-control__stop"
          data-test="stop-operation"
          type="button"
          :disabled="Boolean(busy)"
          @click="$emit('stop')"
        >
          {{ busy === 'stop' ? '正在停止…' : '停止任务' }}
        </button>
      </template>

      <button v-else-if="state === 'stopping'" type="button" disabled data-test="operation-stopping">
        正在等待安全收尾…
      </button>

      <template v-else-if="terminal">
        <button
          data-test="modify-operation"
          type="button"
          :disabled="Boolean(busy)"
          @click="$emit('modify')"
        >
          修改方案
        </button>
        <button
          class="recruitment-operation-control__primary"
          data-test="restart-operation"
          type="button"
          :disabled="Boolean(busy) || restartDisabled"
          @click="$emit('restart')"
        >
          {{ busy === 'restart' ? '正在开启…' : '重新开启' }}
        </button>
      </template>

      <RouterLink v-if="resultsTo" data-test="operation-results" :to="resultsTo">
        查看结果 <AppIcon name="arrow-right" :size="14" />
      </RouterLink>
    </div>
  </section>
</template>

<style scoped>
.recruitment-operation-control {
  display: grid;
  gap: 10px;
  margin-top: 16px;
  padding: 16px;
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  background: #fff;
}

.recruitment-operation-control header {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) 8px;
  align-items: center;
  gap: 10px;
}

.recruitment-operation-control__icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  color: #0f766e;
  background: #e6fffb;
}

.recruitment-operation-control header div {
  display: grid;
  gap: 2px;
}

.recruitment-operation-control header small,
.recruitment-operation-control__run {
  color: #64748b;
  font-size: 11px;
}

.recruitment-operation-control header strong {
  color: #0f172a;
  font-size: 14px;
}

.recruitment-operation-control header > i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
}

.recruitment-operation-control.is-running header > i,
.recruitment-operation-control.is-starting header > i {
  background: #14b8a6;
  box-shadow: 0 0 0 4px #ccfbf1;
}

.recruitment-operation-control.is-stopping header > i,
.recruitment-operation-control.is-paused header > i,
.recruitment-operation-control.is-waiting_human header > i {
  background: #d97706;
  box-shadow: 0 0 0 4px #fef3c7;
}

.recruitment-operation-control.is-failed header > i {
  background: #dc2626;
  box-shadow: 0 0 0 4px #fee2e2;
}

.recruitment-operation-control p {
  margin: 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.65;
}

.recruitment-operation-control__error {
  color: #b91c1c !important;
}

.recruitment-operation-control__disabled-reason {
  color: #92400e !important;
}

.recruitment-operation-control__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.recruitment-operation-control__actions button,
.recruitment-operation-control__actions a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #334155;
  background: #fff;
  font-size: 12px;
  font-weight: 650;
  text-decoration: none;
}

.recruitment-operation-control__actions button:not(:disabled):hover,
.recruitment-operation-control__actions a:hover {
  border-color: #94a3b8;
  background: #f8fafc;
}

.recruitment-operation-control__actions .recruitment-operation-control__primary {
  border-color: #0f766e;
  color: #fff;
  background: #0f766e;
}

.recruitment-operation-control__actions .recruitment-operation-control__stop {
  border-color: #fecaca;
  color: #b91c1c;
  background: #fffafa;
}

.recruitment-operation-control__actions button:disabled {
  cursor: wait;
  opacity: .58;
}

@media (max-width: 640px) {
  .recruitment-operation-control__actions > * {
    flex: 1 1 140px;
    min-height: 44px;
  }
}
</style>
