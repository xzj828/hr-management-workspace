<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useModelCredentialStore } from '@/stores/modelCredential'

const emit = defineEmits(['close'])
const credentials = useModelCredentialStore()
const form = reactive({ api_url: '', model: '', api_key: '' })
const message = ref('')

onMounted(async () => {
  await credentials.load()
  form.api_url = credentials.config.api_url || ''
  form.model = credentials.config.model || ''
})

async function save() {
  const payload = { api_url: form.api_url.trim(), model: form.model.trim() }
  if (form.api_key.trim()) payload.api_key = form.api_key.trim()
  await credentials.save(payload)
  form.api_key = ''
  message.value = '模型配置已安全保存；真实 Copilot 后端将在后续阶段接入。'
}
</script>

<template>
  <div class="drawer-backdrop" @click.self="emit('close')">
    <aside class="copilot-drawer" aria-label="招聘 Copilot">
      <header><div><span class="eyebrow">Recruiting Copilot</span><h2>招聘助手</h2></div><button class="ghost-button" @click="emit('close')">关闭</button></header>
      <p class="muted">本阶段保存模型配置并展示交互入口，不会发送简历或调用模型。</p>
      <label class="field-label">API 地址<input v-model="form.api_url" placeholder="https://api.example.com/v1" /></label>
      <label class="field-label">模型名称<input v-model="form.model" placeholder="model-name" /></label>
      <label class="field-label">API Key<input v-model="form.api_key" type="password" autocomplete="off" :placeholder="credentials.config.has_api_key ? `已保存 ····${credentials.config.key_last4}` : '请输入 API Key'" /></label>
      <div class="copilot-actions"><button class="primary-button" @click="save">保存配置</button><button class="ghost-button" disabled>测试连接（待接入）</button></div>
      <p v-if="message" class="success-note">{{ message }}</p>
      <section class="copilot-capabilities">
        <button disabled>总结候选人</button><button disabled>对照 JD 分析</button><button disabled>生成面试问题</button><button disabled>生成沟通话术</button>
      </section>
    </aside>
  </div>
</template>
