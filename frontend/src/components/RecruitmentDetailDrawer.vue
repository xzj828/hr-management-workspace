<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

defineProps({
  title: { type: String, required: true },
  variant: { type: String, default: 'default' },
})

const emit = defineEmits(['close'])
const panel = ref(null)
const closeButton = ref(null)

function close() {
  emit('close')
}

function onKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  if (event.key !== 'Tab' || !panel.value) return
  const controls = [...panel.value.querySelectorAll('button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])')]
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
  closeButton.value?.focus()
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div :class="['recruitment-drawer-backdrop', `is-${variant}`]" role="presentation" @click.self="close">
    <section ref="panel" :class="['recruitment-drawer', `is-${variant}`]" role="dialog" aria-modal="true" :aria-label="title">
      <header class="recruitment-drawer__header">
        <h2>{{ title }}</h2>
        <button ref="closeButton" type="button" aria-label="关闭" @click="close"><AppIcon name="close" :size="18" /></button>
      </header>
      <div class="recruitment-drawer__body"><slot /></div>
      <footer v-if="$slots.footer" class="recruitment-drawer__footer"><slot name="footer" /></footer>
    </section>
  </div>
</template>
