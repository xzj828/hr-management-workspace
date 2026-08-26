<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

const props = defineProps({ title: String, wide: Boolean, dismissible: { type: Boolean, default: true }, initialFocus: String })
const emit = defineEmits(['close'])
const panel = ref(null)
const titleId = `modal-title-${useId()}`
let previousFocus = null

function focusableElements() {
  return [...(panel.value?.querySelectorAll('button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])') || [])]
}

function requestClose() {
  if (!props.dismissible) return
  emit('close')
  previousFocus?.focus?.()
}

function handleKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    requestClose()
    return
  }
  if (event.key !== 'Tab') return
  const focusable = focusableElements()
  if (!focusable.length) {
    event.preventDefault()
    panel.value?.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(async () => {
  previousFocus = document.activeElement
  await nextTick()
  const requested = props.initialFocus ? panel.value?.querySelector(props.initialFocus) : null
  ;(requested || focusableElements()[0] || panel.value)?.focus?.()
})

onBeforeUnmount(() => previousFocus?.focus?.())
</script>

<template>
  <teleport to="body">
    <div class="modal-mask" @mousedown.self="requestClose">
      <section ref="panel" class="modal-panel" :class="{ 'modal-panel--wide': wide }" role="dialog" aria-modal="true" :aria-labelledby="titleId" tabindex="-1" @keydown="handleKeydown">
        <header><h2 :id="titleId">{{ title }}</h2><button class="icon-button" type="button" aria-label="关闭" :disabled="!dismissible" @click="requestClose"><AppIcon name="close" :size="18" /></button></header>
        <div class="modal-panel__body"><slot /></div>
        <footer v-if="$slots.footer"><slot name="footer" /></footer>
      </section>
    </div>
  </teleport>
</template>
