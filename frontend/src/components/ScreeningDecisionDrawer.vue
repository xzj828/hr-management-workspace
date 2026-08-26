<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

const props = defineProps({
  mode: { type: String, required: true, validator: (value) => ['pass', 'fail'].includes(value) },
  candidates: { type: Array, required: true },
  jobTitle: { type: String, default: '' },
  accountName: { type: String, default: '' },
  saving: { type: Boolean, default: false },
  decisionSaved: { type: Boolean, default: false },
  decisionError: { type: String, default: '' },
  notificationError: { type: String, default: '' },
})
const emit = defineEmits(['close', 'confirm'])

const dialog = ref(null)
const reasonInput = ref(null)
const reason = ref('')
const initialMessage = () => `您好，感谢您对${props.jobTitle || '该'}岗位的关注和时间。综合本次招聘安排，我们暂时无法继续推进后续流程，祝您求职顺利。`
const message = ref(initialMessage())
const acknowledged = ref(false)

const title = computed(() => props.mode === 'pass'
  ? `确认通过 ${props.candidates.length} 位候选人`
  : `确认未通过 ${props.candidates.length} 位候选人`)
const neutralMessage = computed(initialMessage)
function hasBlockingNotice(candidate) {
  return !['not_requested', 'cancelled'].includes(candidate.notificationStatus)
    || String(candidate.notificationErrorCode || '').toLowerCase().includes('uncertain')
}
const candidatesWithActiveNotice = computed(() => props.candidates.filter(hasBlockingNotice))
const candidatesInProtectedStage = computed(() => props.candidates.filter((candidate) =>
  ['to_interview', 'interviewing', 'to_offer', 'hired'].includes(candidate.stage)))
const canSave = computed(() => Boolean(reason.value.trim() && acknowledged.value) && !props.saving && !props.decisionSaved)
const canNotify = computed(() => props.mode === 'fail'
  && Boolean(reason.value.trim() && message.value.trim() && acknowledged.value)
  && candidatesWithActiveNotice.value.length === 0
  && candidatesInProtectedStage.value.length === 0
  && Boolean(props.accountName)
  && !props.saving)

watch(() => props.mode, () => {
  reason.value = ''
  message.value = neutralMessage.value
  acknowledged.value = false
})

function close() {
  if (!props.saving) emit('close')
}

function confirm(notify) {
  emit('confirm', {
    notify,
    reason: reason.value.trim(),
    message: message.value.trim(),
  })
}

function onKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  if (event.key !== 'Tab' || !dialog.value) return
  const controls = [...dialog.value.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), [href], select:not(:disabled), [tabindex]:not([tabindex="-1"])')]
  if (!controls.length) return
  const first = controls[0]
  const last = controls[controls.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  reasonInput.value?.focus()
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="screening-drawer-backdrop" role="presentation" @click.self="close">
    <aside ref="dialog" class="screening-decision-drawer" role="dialog" aria-modal="true" :aria-label="title">
      <header class="screening-decision-drawer__header">
        <div><span class="eyebrow">HR Screening Decision</span><h2>{{ title }}</h2><p>AI 建议仅作参考，本操作记录独立的 HR 结论，不会自动改变招聘阶段。</p></div>
        <button type="button" aria-label="关闭" :disabled="saving" @click="close"><AppIcon name="close" :size="18" /></button>
      </header>

      <main class="screening-decision-drawer__body">
        <section v-if="decisionSaved" class="decision-feedback decision-feedback--success" role="status" data-test="decision-saved">
          <AppIcon name="check-circle" :size="18" /><div><strong>HR 未通过结论已保存</strong><p>通知仍是独立操作；即使通知创建失败，人工结论也不会丢失。</p></div>
        </section>
        <section v-if="decisionError" class="decision-feedback decision-feedback--error" role="alert" data-test="decision-error">
          <AppIcon name="alert-circle" :size="18" /><div><strong>人工结论未保存</strong><p>{{ decisionError }}</p></div>
        </section>
        <section v-if="notificationError" class="decision-feedback decision-feedback--warning" role="alert" data-test="notification-error">
          <AppIcon name="alert-circle" :size="18" /><div><strong>结论已保存，通知未加入队列</strong><p>{{ notificationError }}。候选人选择、内部原因和通知文案已保留，可安全重试。</p></div>
        </section>
        <section v-if="mode === 'fail' && candidatesWithActiveNotice.length" class="decision-feedback decision-feedback--warning" role="status" data-test="notice-duplicate-warning">
          <AppIcon name="alert-circle" :size="18" /><div><strong>{{ candidatesWithActiveNotice.length }} 位候选人已有通知记录</strong><p>为防止重复联系，执行中、已完成、失败或结果不确定的记录都不能自动重试。可仅保存 HR 结论，或返回列表取消勾选后处理。</p></div>
        </section>
        <section v-if="mode === 'fail' && candidatesInProtectedStage.length" class="decision-feedback decision-feedback--warning" role="status" data-test="notice-stage-warning">
          <AppIcon name="alert-circle" :size="18" /><div><strong>{{ candidatesInProtectedStage.length }} 位候选人已进入后续招聘阶段</strong><p>面试、Offer 或录用阶段不能自动创建未通过通知。请返回列表核对后再操作。</p></div>
        </section>
        <section v-if="mode === 'fail' && !accountName" class="decision-feedback decision-feedback--warning" role="status" data-test="notice-account-warning">
          <AppIcon name="alert-circle" :size="18" /><div><strong>当前岗位未绑定可用 BOSS 账号</strong><p>仍可保存 HR 结论，但不能加入通知队列。</p></div>
        </section>

        <dl class="screening-decision-meta">
          <div><dt>岗位</dt><dd>{{ jobTitle || '当前岗位' }}</dd></div>
          <div v-if="mode === 'fail'"><dt>执行账号</dt><dd>{{ accountName || '岗位绑定账号' }}</dd></div>
          <div><dt>本批人数</dt><dd>{{ candidates.length }} 人</dd></div>
        </dl>

        <label class="field-label">内部决策原因 <span aria-hidden="true">*</span>
          <textarea ref="reasonInput" v-model="reason" data-test="screening-reason" rows="4" maxlength="1000" :disabled="decisionSaved" placeholder="仅供内部审计，不会发送给候选人"></textarea>
          <small>必填。分数、AI 建议和硬性条件冲突不得自动成为 HR 结论。</small>
        </label>

        <label v-if="mode === 'fail'" class="field-label">候选人收到的最终文案
          <textarea v-model="message" data-test="rejection-message" rows="6" maxlength="1000" readonly aria-readonly="true"></textarea>
          <small>文案由系统按岗位生成，只包含中性招聘结果说明；不会带入评分、AI 判断或内部原因。</small>
        </label>

        <label class="screening-acknowledgement">
          <input v-model="acknowledged" data-test="screening-acknowledgement" type="checkbox" />
          <span>我已逐项核对候选人，并确认这是 HR 的人工决定。</span>
        </label>

        <section class="screening-recipient-list" aria-label="本批候选人">
          <span>本批候选人</span>
          <article v-for="candidate in candidates" :key="candidate.applicationId">
            <div><strong>{{ candidate.name }}</strong><small>{{ candidate.title || '当前岗位未填写' }}</small></div>
            <em v-if="hasBlockingNotice(candidate)">已有通知或结果待确认，不会再次加入队列</em>
          </article>
        </section>
      </main>

      <footer class="screening-decision-drawer__footer">
        <button class="secondary-button" type="button" :disabled="saving" @click="close">取消</button>
        <button v-if="mode === 'pass'" class="primary-button" data-test="save-pass-decision" type="button" :disabled="!canSave" @click="confirm(false)">{{ saving ? '正在保存…' : '保存 HR 通过结论' }}</button>
        <template v-else>
          <button class="secondary-button" data-test="save-fail-decision" type="button" :disabled="!canSave" @click="confirm(false)">{{ saving ? '正在保存…' : '仅保存 HR 未通过结论' }}</button>
          <button class="primary-button" data-test="queue-rejection-notice" type="button" :disabled="!canNotify" @click="confirm(true)">{{ saving ? '正在创建…' : decisionSaved ? '重试加入通知队列' : '确认未通过并加入通知队列' }}</button>
        </template>
      </footer>
    </aside>
  </div>
</template>

<style scoped>
.screening-drawer-backdrop{position:fixed;inset:0;z-index:80;display:flex;justify-content:flex-end;background:rgba(15,23,42,.46);backdrop-filter:blur(2px)}
.screening-decision-drawer{display:flex;flex-direction:column;width:min(620px,100%);height:100%;overflow:hidden;background:#fff;box-shadow:-18px 0 46px rgba(15,23,42,.18)}
.screening-decision-drawer__header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:28px 30px 22px;border-bottom:1px solid #e2e8f0}.screening-decision-drawer__header h2{margin:5px 0 7px;color:#0f172a;font-size:23px}.screening-decision-drawer__header p{margin:0;color:#64748b;font-size:13px;line-height:1.6}.screening-decision-drawer__header>button{display:grid;place-items:center;flex:0 0 40px;width:40px;height:40px;border:1px solid #e2e8f0;border-radius:10px;background:#fff;color:#334155}
.screening-decision-drawer__body{display:grid;gap:20px;overflow-y:auto;padding:24px 30px}.screening-decision-meta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin:0;padding:16px 18px;border:1px solid #e2e8f0;border-radius:12px;background:#f8fafc}.screening-decision-meta div{display:grid;gap:5px}.screening-decision-meta dt{color:#64748b;font-size:11px}.screening-decision-meta dd{overflow:hidden;margin:0;color:#0f172a;font-size:13px;font-weight:700;text-overflow:ellipsis;white-space:nowrap}
.field-label{display:grid;gap:8px;color:#334155;font-size:12px;font-weight:700}.field-label textarea{box-sizing:border-box;width:100%;padding:12px 13px;border:1px solid #cbd5e1;border-radius:10px;color:#0f172a;font:inherit;font-weight:500;line-height:1.55;resize:vertical}.field-label textarea:focus{outline:3px solid rgba(15,159,143,.14);border-color:#0f9f8f}.field-label small{color:#64748b;font-size:11px;font-weight:500;line-height:1.5}
.field-label textarea[readonly]{background:#f8fafc;color:#475569;cursor:default;resize:none}
.screening-acknowledgement{display:flex;align-items:flex-start;gap:10px;padding:14px 16px;border:1px solid #bddbd7;border-radius:10px;background:#f1fbf9;color:#245a53;font-size:12px;line-height:1.55}.screening-acknowledgement input{width:17px;height:17px;margin:1px 0 0;accent-color:#0f9f8f}
.screening-recipient-list{display:grid;gap:0;border-top:1px solid #e2e8f0}.screening-recipient-list>span{padding:16px 0 8px;color:#64748b;font-size:11px;font-weight:800;letter-spacing:.08em}.screening-recipient-list article{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-bottom:1px solid #edf2f7}.screening-recipient-list article div{display:grid;gap:3px}.screening-recipient-list strong{color:#0f172a;font-size:13px}.screening-recipient-list small{color:#64748b;font-size:11px}.screening-recipient-list em{color:#b45309;font-size:10px;font-style:normal;text-align:right}
.decision-feedback{display:flex;align-items:flex-start;gap:10px;padding:13px 15px;border-radius:10px}.decision-feedback div{display:grid;gap:3px}.decision-feedback strong{font-size:12px}.decision-feedback p{margin:0;font-size:11px;line-height:1.55}.decision-feedback--success{color:#087f73;background:#eefaf8}.decision-feedback--warning{color:#92400e;background:#fff8e7}.decision-feedback--error{color:#b42332;background:#fff2f3}
.screening-decision-drawer__footer{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-top:auto;padding:18px 30px calc(18px + env(safe-area-inset-bottom));border-top:1px solid #e2e8f0;background:#fff}.screening-decision-drawer__footer button{min-height:44px}
@media(max-width:640px){.screening-decision-drawer__header,.screening-decision-drawer__body,.screening-decision-drawer__footer{padding-right:18px;padding-left:18px}.screening-decision-meta{grid-template-columns:1fr}.screening-decision-drawer__footer{flex-wrap:wrap}.screening-decision-drawer__footer button{flex:1 1 100%}}
</style>
