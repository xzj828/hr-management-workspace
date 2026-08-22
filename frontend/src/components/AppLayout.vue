<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const collapsed = ref(false)

const navigation = [
  { name: 'dashboard', label: '考勤看板', icon: '⌁' },
  { name: 'employees', label: '人员管理', icon: '◎' },
  { name: 'imports', label: '导入中心', icon: '⇧' },
  { name: 'results', label: '核算结果', icon: '✓' },
  { name: 'suspicions', label: '异常审核', icon: '!' },
  { name: 'settings', label: '规则与标签', icon: '⚙' },
]

const currentTitle = computed(() => navigation.find((item) => item.name === route.name)?.label || '考勤管理')

async function signOut() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="shell" :class="{ 'shell--collapsed': collapsed }">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand__mark">XM</div>
        <div class="brand__text">
          <strong>西鸣考勤</strong>
          <span>Attendance OS</span>
        </div>
      </div>
      <nav class="nav-list">
        <router-link v-for="item in navigation" :key="item.name" :to="{ name: item.name }" class="nav-item">
          <span class="nav-item__icon">{{ item.icon }}</span>
          <span class="nav-item__label">{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar__foot">
        <div class="system-state"><i></i><span>本地服务运行中</span></div>
        <button class="collapse-button" @click="collapsed = !collapsed">{{ collapsed ? '›' : '‹ 收起导航' }}</button>
      </div>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <div>
          <span class="eyebrow">西鸣科技 · 人事行政中心</span>
          <h1>{{ currentTitle }}</h1>
        </div>
        <div class="topbar__actions">
          <div class="user-chip">
            <span class="avatar">{{ auth.user?.username?.slice(0, 1)?.toUpperCase() }}</span>
            <div><strong>{{ auth.user?.first_name || auth.user?.username }}</strong><span>{{ auth.user?.role_label }}</span></div>
          </div>
          <button class="ghost-button" @click="signOut">退出</button>
        </div>
      </header>
      <section class="page-container"><router-view /></section>
    </main>
  </div>
</template>

