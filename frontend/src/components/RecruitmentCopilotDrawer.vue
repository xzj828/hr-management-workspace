<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useModelCredentialStore } from '@/stores/modelCredential'

const emit = defineEmits(['close'])
const credentials = useModelCredentialStore()
const form = reactive({ api_url: '', model: '', api_key: '' })
const message = ref('')
const error = ref('')
const saving = ref(false)

onMounted(async () => {
  await credentials.load()
  form.api_url = credentials.config.api_url || ''
  form.model = credentials.config.model || ''
})

async function save() {
  saving.value = true
  error.value = ''
  const payload = { api_url: form.api_url.trim(), model: form.model.trim() }
  if (form.api_key.trim()) payload.api_key = form.api_key.trim()
  try {
    await credentials.save(payload)
    form.api_key = ''
    message.value = '模型配置已保存到当前登录账号。'
  } catch (err) { error.value = err.message }
  finally { saving.value = false }
}

async function testConnection() {
  error.value = ''; message.value = ''
  try { await credentials.testConnection() }
  catch (err) { error.value = err.message }
}
</script>

<template>
  <div class="drawer-backdrop" @click.self="emit('close')">
    <aside class="copilot-drawer" aria-label="招聘 Copilot">
      <header><div><span class="eyebrow">Recruiting Copilot</span><h2>招聘助手</h2></div><button class="ghost-button" @click="emit('close')">关闭</button></header>
      <p class="muted">配置 OpenAI 兼容接口。原文件留在本机，模型只接收本地提取后的文字块。</p>
      <label class="field-label">API 地址<input v-model="form.api_url" placeholder="https://api.example.com/v1" /></label>
      <label class="field-label">模型名称<input v-model="form.model" placeholder="model-name" /></label>
      <label class="field-label">API Key<input v-model="form.api_key" type="password" autocomplete="off" :placeholder="credentials.config.has_api_key ? `已保存 ····${credentials.config.key_last4}` : '请输入 API Key'" /></label>
      <div class="copilot-actions"><button class="primary-button" :disabled="saving || credentials.testing" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button><button class="ghost-button" :disabled="saving || credentials.testing || !credentials.config.has_api_key" data-test="test-model-connection" @click="testConnection">{{ credentials.testing ? '连接中…' : '测试连接' }}</button></div>
      <p v-if="message" class="success-note">{{ message }}</p>
      <p v-if="credentials.connection.status === 'success'" class="model-connection-note model-connection-note--success"><span></span>{{ credentials.connection.model }} 已连接<small v-if="credentials.connection.latency_ms !== null">{{ credentials.connection.latency_ms }} ms</small></p>
      <p v-if="error || credentials.connection.status === 'error'" class="model-connection-note model-connection-note--error">{{ error || credentials.connection.detail }}</p>
      <section class="copilot-capabilities">
        <button disabled>结构化简历</button><button disabled>按标准评分</button><button disabled>查看证据链</button><button disabled>生成核实问题</button>
      </section>
    </aside>
  </div>
</template>
