<script setup>
import AppIcon from '@/components/AppIcon.vue'

defineProps({ title: String, wide: Boolean })
defineEmits(['close'])
</script>

<template>
  <teleport to="body">
    <div class="modal-mask" @mousedown.self="$emit('close')">
      <section class="modal-panel" :class="{ 'modal-panel--wide': wide }">
        <header><h2>{{ title }}</h2><button class="icon-button" type="button" aria-label="关闭" @click="$emit('close')"><AppIcon name="close" :size="18" /></button></header>
        <div class="modal-panel__body"><slot /></div>
        <footer v-if="$slots.footer"><slot name="footer" /></footer>
      </section>
    </div>
  </teleport>
</template>
