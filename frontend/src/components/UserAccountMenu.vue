<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'

const props = defineProps({
  user: { type: Object, default: null },
})
const emit = defineEmits(['logout', 'model-settings'])
const open = ref(false)
const displayName = computed(() => props.user?.first_name || props.user?.username || '用户')
const initial = computed(() => displayName.value.slice(0, 1).toUpperCase())

function close() {
  open.value = false
}

function onDocumentClick(event) {
  if (!event.target.closest('.account-menu')) close()
}

function onKeydown(event) {
  if (event.key === 'Escape') close()
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
      data-testid="account-trigger"
      type="button"
      :aria-expanded="String(open)"
      aria-haspopup="menu"
      @click.stop="open = !open"
    >
      <span class="avatar">{{ initial }}</span>
      <span class="account-menu__name">{{ displayName }}</span>
      <span class="account-menu__chevron" aria-hidden="true">⌄</span>
    </button>
    <div v-if="open" class="account-menu__panel" role="menu">
      <div class="account-menu__identity">
        <strong>{{ displayName }}</strong>
        <span>{{ user?.role_label || '普通用户' }}</span>
      </div>
      <button data-testid="model-settings" role="menuitem" type="button" @click="choose('model-settings')">模型配置</button>
      <button data-testid="logout" role="menuitem" type="button" @click="choose('logout')">退出登录</button>
    </div>
  </div>
</template>
