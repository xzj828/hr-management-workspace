<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const title = computed(() => route.meta.title || '招聘管理')
</script>

<template>
  <section class="empty-state-panel">
    <span class="eyebrow">Recruitment Foundation</span>
    <h2>{{ title }}</h2>
    <p>页面入口已建立，业务能力将在下一阶段按已确认的设计逐项接入。</p>
  </section>
</template>
