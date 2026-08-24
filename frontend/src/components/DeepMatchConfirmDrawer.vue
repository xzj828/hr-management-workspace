<script setup>
import RecruitmentDetailDrawer from '@/components/RecruitmentDetailDrawer.vue'
import AppIcon from '@/components/AppIcon.vue'

defineProps({ approval: { type: Object, required: true }, confirming: { type: Boolean, default: false } })
defineEmits(['close', 'confirm'])
</script>

<template>
  <RecruitmentDetailDrawer title="确认深度匹配" @close="$emit('close')">
    <section class="deep-confirm-intro">
      <i><AppIcon name="sparkles" :size="19" /></i>
      <div><strong>将消耗 1 次立即匹配额度</strong><p>本操作只读取候选人，不会发送消息或打招呼。</p></div>
    </section>
    <dl class="recruitment-detail-grid">
      <div><dt>BOSS 账号</dt><dd>{{ approval.account_name }}</dd></div>
      <div><dt>目标职位</dt><dd>{{ approval.payload.job_title }}</dd></div>
      <div><dt>核心要求</dt><dd>{{ approval.payload.core?.join('、') || '未设置' }}</dd></div>
      <div><dt>加分项</dt><dd>{{ approval.payload.bonus?.join('、') || '未设置' }}</dd></div>
    </dl>
    <template #footer>
      <button class="text-button" type="button" @click="$emit('close')">取消</button>
      <button class="primary-button" type="button" :disabled="confirming" @click="$emit('confirm')">{{ confirming ? '正在确认…' : '确认并开始匹配' }}</button>
    </template>
  </RecruitmentDetailDrawer>
</template>
