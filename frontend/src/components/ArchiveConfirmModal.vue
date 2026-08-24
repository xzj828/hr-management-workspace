<script setup>
import ModalPanel from '@/components/ModalPanel.vue'

defineProps({
  title: { type: String, required: true },
  name: { type: String, required: true },
  description: { type: String, required: true },
  actionLabel: { type: String, default: '确认归档' },
  saving: { type: Boolean, default: false },
})

defineEmits(['close', 'confirm'])
</script>

<template>
  <ModalPanel :title="title" @close="$emit('close')">
    <div class="archive-confirm-copy">
      <strong>{{ name }}</strong>
      <p>{{ description }}</p>
      <small>该操作会立即从当前工作列表移除；保留的历史记录可用于审计。</small>
    </div>
    <template #footer>
      <button class="secondary-button" type="button" :disabled="saving" @click="$emit('close')">取消</button>
      <button class="danger-button" data-test="confirm-archive" type="button" :disabled="saving" @click="$emit('confirm')">{{ saving ? '处理中…' : actionLabel }}</button>
    </template>
  </ModalPanel>
</template>
