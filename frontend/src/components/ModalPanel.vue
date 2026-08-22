<script setup>
defineProps({ title: String, wide: Boolean })
defineEmits(['close'])
</script>

<template>
  <teleport to="body">
    <div class="modal-mask" @mousedown.self="$emit('close')">
      <section class="modal-panel" :class="{ 'modal-panel--wide': wide }">
        <header><h2>{{ title }}</h2><button class="icon-button" @click="$emit('close')">×</button></header>
        <div class="modal-panel__body"><slot /></div>
        <footer v-if="$slots.footer"><slot name="footer" /></footer>
      </section>
    </div>
  </teleport>
</template>
