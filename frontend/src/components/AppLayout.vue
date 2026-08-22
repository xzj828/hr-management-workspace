<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { modules, moduleForRoute, navigationForModule } from '@/navigation'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const collapsed = ref(false)

const currentModule = computed(() => moduleForRoute(route))
const navigation = computed(() => navigationForModule(currentModule.value))
const currentTitle = computed(() => route.meta?.title || '人事管理')

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
          <strong>西鸣人事</strong>
          <span>People OS</span>
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
          <nav class="module-switcher" aria-label="业务模块">
            <router-link
              v-for="module in modules"
              :key="module.id"
              :to="{ name: module.routeName }"
              :class="{ active: currentModule === module.id }"
            >{{ module.label }}</router-link>
          </nav>
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

