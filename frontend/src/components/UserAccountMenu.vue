<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

const props = defineProps({
  user: { type: Object, default: null },
})
const emit = defineEmits(['logout', 'model-settings'])
const open = ref(false)
const trigger = ref(null)
const panel = ref(null)
const displayName = computed(() => props.user?.first_name || props.user?.username || '用户')
const initial = computed(() => displayName.value.slice(0, 1).toUpperCase())

function close({ restoreFocus = false } = {}) {
  open.value = false
  if (restoreFocus) nextTick(() => trigger.value?.focus())
}

function toggle() {
  open.value = !open.value
  if (open.value) nextTick(() => panel.value?.querySelector('[role="menuitem"]')?.focus())
}

function onDocumentClick(event) {
  if (!event.target.closest('.account-menu')) close()
}

function onKeydown(event) {
  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    close({ restoreFocus: true })
  }
}

function onMenuKeydown(event) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  const items = [...(panel.value?.querySelectorAll('[role="menuitem"]') || [])]
  if (!items.length) return
  event.preventDefault()
  const current = Math.max(0, items.indexOf(document.activeElement))
  const index = event.key === 'Home'
    ? 0
    : event.key === 'End'
      ? items.length - 1
      : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
  items[index].focus()
}

document.addEventListener('click', onDocumentClick)
document.addEventListener('keydown', onKeydown)
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})

function choose(action) {
  close()
  emit(action)
}
</script>

<template>
  <div class="account-menu">
    <button
      class="account-menu__trigger"
      ref="trigger"
      data-testid="account-trigger"
      type="button"
      :aria-expanded="String(open)"
      aria-haspopup="menu"
      @click.stop="toggle"
    >
      <span class="avatar">{{ initial }}</span>
      <span class="account-menu__name">{{ displayName }}</span>
      <AppIcon class="account-menu__chevron" name="chevron-down" :size="15" />
    </button>
    <div v-if="open" ref="panel" class="account-menu__panel" role="menu" @keydown="onMenuKeydown">
      <div class="account-menu__identity">
        <strong>{{ displayName }}</strong>
        <span>{{ user?.role_label || '普通用户' }}</span>
      </div>
      <button data-testid="model-settings" role="menuitem" type="button" @click="choose('model-settings')">新增自定义模型</button>
      <button data-testid="logout" role="menuitem" type="button" @click="choose('logout')">退出登录</button>
    </div>
  </div>
</template>
