<script setup>
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
onMounted(() => auth.restore())
</script>

<template>
  <div v-if="auth.loading" class="app-loading">
    <div class="loading-mark">XM</div>
    <p>正在进入考勤系统…</p>
  </div>
  <router-view v-else />
</template>

