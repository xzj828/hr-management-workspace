<script setup>
import ModalPanel from '@/components/ModalPanel.vue'

defineProps({
  title: { type: String, required: true },
  name: { type: String, required: true },
  description: { type: String, required: true },
  actionLabel: { type: String, default: '确认归档' },
  note: { type: String, default: '该操作会立即从当前工作列表移除；保留的历史记录可用于审计。' },
  saving: { type: Boolean, default: false },
  error: { type: String, default: '' },
  businessResultsTypography: { type: Boolean, default: false },
})

defineEmits(['close', 'confirm'])
</script>

<template>
  <ModalPanel
    :title="title"
    :dismissible="!saving"
    :panel-class="{ 'modal-panel--business-results': businessResultsTypography }"
    initial-focus="[data-modal-initial-focus]"
    @close="$emit('close')"
  >
    <div class="archive-confirm-copy">
      <strong>{{ name }}</strong>
      <p>{{ description }}</p>
      <small>{{ note }}</small>
      <p v-if="error" class="archive-confirm-error" role="alert">{{ error }}</p>
    </div>
    <template #footer>
      <button class="secondary-button" data-modal-initial-focus type="button" :disabled="saving" @click="$emit('close')">取消</button>
      <button class="danger-button" data-test="confirm-archive" type="button" :disabled="saving" @click="$emit('confirm')">{{ saving ? '处理中…' : actionLabel }}</button>
    </template>
  </ModalPanel>
</template>

<style scoped>
.archive-confirm-error {
  padding: 9px 10px;
  color: #9f3340;
  background: #fff2f3;
  border: 1px solid #efc8cb;
  border-radius: 8px;
}
</style>
