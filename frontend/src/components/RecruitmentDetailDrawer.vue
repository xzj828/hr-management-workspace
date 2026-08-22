<script setup>
import AppIcon from '@/components/AppIcon.vue'

defineProps({
  title: { type: String, required: true },
})

defineEmits(['close'])
</script>

<template>
  <div class="recruitment-drawer-backdrop" role="presentation" @click.self="$emit('close')">
    <aside class="recruitment-drawer" role="dialog" aria-modal="true" :aria-label="title">
      <header class="recruitment-drawer__header">
        <h2>{{ title }}</h2>
        <button type="button" aria-label="关闭" @click="$emit('close')"><AppIcon name="close" :size="18" /></button>
      </header>
      <div class="recruitment-drawer__body"><slot /></div>
      <footer v-if="$slots.footer" class="recruitment-drawer__footer"><slot name="footer" /></footer>
    </aside>
  </div>
</template>
