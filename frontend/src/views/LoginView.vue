<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const username = ref('admin')
const password = ref('')
const error = ref('')
const submitting = ref(false)

async function submit() {
  error.value = ''
  submitting.value = true
  try {
    await auth.login(username.value, password.value)
    router.replace(route.query.redirect || '/')
  } catch (err) {
    error.value = err.message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-story">
      <div class="login-brand"><span>XM</span> 西鸣科技</div>
      <div class="story-copy">
        <span class="story-kicker">ATTENDANCE · LOCAL SYSTEM</span>
        <h1>把繁琐核算<br />变成一次确认。</h1>
        <p>打卡表导入、异常识别、人工复核与汇总导出，都在本机完成。</p>
        <div class="story-stats">
          <div><strong>100%</strong><span>本地数据</span></div>
          <div><strong>可追溯</strong><span>每条规则</span></div>
          <div><strong>1 个文件</strong><span>完成导入</span></div>
        </div>
      </div>
      <div class="story-orbit"><i></i><i></i><i></i></div>
      <p class="story-foot">第一版 · 规则引擎模式 · 未接入 AI</p>
    </section>

    <section class="login-form-wrap">
      <form class="login-card" @submit.prevent="submit">
        <div class="login-card__heading">
          <span class="mobile-mark">XM</span>
          <span class="eyebrow">欢迎回来</span>
          <h2>登录考勤管理系统</h2>
          <p>使用管理员或 HR 账号继续</p>
        </div>
        <label class="field-label">账号<input v-model="username" autocomplete="username" required placeholder="请输入账号" /></label>
        <label class="field-label">密码<input v-model="password" type="password" autocomplete="current-password" required placeholder="请输入密码" /></label>
        <p v-if="error" class="form-error">{{ error }}</p>
        <button class="primary-button primary-button--large" :disabled="submitting">
          {{ submitting ? '正在登录…' : '进入系统' }}
        </button>
        <p class="security-note"><span>●</span> 数据仅保存在当前设备</p>
      </form>
    </section>
  </main>
</template>

