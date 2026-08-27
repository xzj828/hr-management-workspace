<script setup>
import { computed, reactive, ref, watch } from 'vue'
import RecruitmentDetailDrawer from './RecruitmentDetailDrawer.vue'
import AppIcon from './AppIcon.vue'
import { communicationActions, defaultMessage, interviewMessage } from '@/recruitmentCommunications'

const props = defineProps({
  candidates: { type: Array, required: true },
  accountName: { type: String, default: '' },
  saving: { type: Boolean, default: false },
  fixedAction: { type: String, default: '' },
  excludedCount: { type: Number, default: 0 },
  error: { type: String, default: '' },
})
const emit = defineEmits(['close', 'confirm'])
const action = ref(props.fixedAction || 'greet')
const invitation = reactive({ interview_at: '', mode: 'online', location: '', contact_name: '', note: '' })
const message = ref(defaultMessage('greet', props.candidates[0]?.jobTitle))
const title = computed(() => props.fixedAction === 'greet'
  ? `确认批量打招呼 ${props.candidates.length} 位候选人`
  : `确认联系 ${props.candidates.length} 位候选人`)

watch(action, (value) => {
  message.value = value === 'send_interview'
    ? interviewMessage(invitation)
    : defaultMessage(value, props.candidates[0]?.jobTitle)
})
watch(invitation, () => {
  if (action.value === 'send_interview') message.value = interviewMessage(invitation)
}, { deep: true })

function confirm() {
  emit('confirm', { action: action.value, message: message.value.trim(), invitation: { ...invitation } })
}
</script>

<template>
  <RecruitmentDetailDrawer :title="title" @close="emit('close')">
    <section class="communication-intro">
      <i><AppIcon name="shield" :size="20" /></i>
      <div><strong>发送前最后确认</strong><p>系统会按候选人逐条执行；身份不唯一或出现验证时立即暂停。</p></div>
    </section>
    <div class="communication-meta"><span>执行账号</span><strong>{{ accountName }}</strong><span>预计条数</span><strong>{{ candidates.length }}</strong></div>
    <label v-if="!fixedAction" class="field-label communication-field">沟通动作
      <select v-model="action" data-test="communication-action"><option v-for="item in communicationActions" :key="item.key" :value="item.key">{{ item.label }}</option></select>
    </label>
    <div v-else class="communication-meta"><span>沟通动作</span><strong>批量打招呼</strong><span>话术规则</span><strong>本批统一</strong></div>
    <p v-if="excludedCount" class="communication-warning" role="status">另有 {{ excludedCount }} 位所选候选人因已联系、任务处理中或身份不可核验，本次不会提交。</p>
    <div v-if="action === 'send_interview'" class="interview-grid">
      <label class="field-label">面试时间<input v-model="invitation.interview_at" type="datetime-local" /></label>
      <label class="field-label">面试形式<select v-model="invitation.mode"><option value="online">线上</option><option value="offline">线下</option></select></label>
      <label class="field-label field-label--full">地址或会议链接<input v-model.trim="invitation.location" /></label>
      <label class="field-label">联系人<input v-model.trim="invitation.contact_name" /></label>
      <label class="field-label">备注<input v-model.trim="invitation.note" /></label>
    </div>
    <label class="field-label communication-field">{{ fixedAction === 'greet' ? '统一打招呼话术' : '最终发送内容' }}
      <textarea v-model="message" data-test="communication-message" rows="6" maxlength="1000"></textarea>
      <small>确认后保存为不可变快照，本批执行不会被后续模板修改影响。</small>
    </label>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <section class="communication-recipients"><span>本批候选人</span><article v-for="candidate in candidates" :key="candidate.applicationId"><strong>{{ candidate.name }}</strong><small>{{ candidate.jobTitle }}</small></article></section>
    <template #footer>
      <div class="drawer-confirm-footer"><button class="secondary-button" type="button" @click="emit('close')">取消</button><button class="primary-button" data-test="confirm-communication" type="button" :disabled="saving || !message.trim()" @click="confirm">{{ saving ? '正在创建…' : '确认并加入执行队列' }}</button></div>
    </template>
  </RecruitmentDetailDrawer>
</template>
