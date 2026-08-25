<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { useModelCredentialStore } from '@/stores/modelCredential'

const props = defineProps({
  profile: { type: Object, default: null },
})
const emit = defineEmits(['close', 'saved'])
const credentials = useModelCredentialStore()
const dialog = ref(null)
const nameInput = ref(null)
const form = reactive({
  name: props.profile?.name || '',
  api_url: props.profile?.api_url || '',
  model: props.profile?.model || '',
  api_key: '',
})
const error = ref('')
const message = ref('')
const isEditing = computed(() => Boolean(props.profile?.id))
let returnFocus = null

function requestErrorMessage(err, fallback) {
  const payload = err?.payload
  if (payload && typeof payload === 'object') {
    const fields = ['name', 'api_url', 'model', 'api_key', 'non_field_errors']
    for (const field of fields) {
      const value = payload[field]
      if (Array.isArray(value) && value.length) return String(value[0])
      if (typeof value === 'string' && value) return value
    }
  }
  return err?.message || fallback
}

function close() {
  if (!credentials.saving && !credentials.testingId) emit('close')
}

function onKeydown(event) {
  if (event.key === 'Escape') close()
  if (event.key !== 'Tab' || !dialog.value) return
  const focusable = [...dialog.value.querySelectorAll('button:not(:disabled), input:not(:disabled), [href], [tabindex]:not([tabindex="-1"])')]
  if (!focusable.length) return
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

onMounted(() => {
  returnFocus = document.activeElement
  document.addEventListener('keydown', onKeydown)
  nextTick(() => nameInput.value?.focus())
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  returnFocus?.focus?.()
})

async function saveAndSwitch() {
  error.value = ''
  message.value = ''
  const payload = {
    name: form.name.trim(),
    api_url: form.api_url.trim(),
    model: form.model.trim(),
  }
  if (form.api_key.trim()) payload.api_key = form.api_key.trim()
  try {
    let profile
    if (isEditing.value) {
      profile = await credentials.updateProfile(props.profile.id, payload)
      if (!profile.is_active) profile = await credentials.activateProfile(profile.id)
    } else {
      profile = await credentials.createProfile({ ...payload, make_active: true })
      if (!profile.is_active) profile = await credentials.activateProfile(profile.id)
    }
    form.api_key = ''
    emit('saved', profile)
  } catch (err) {
    error.value = requestErrorMessage(err, '模型保存失败')
  }
}

async function testConnection() {
  error.value = ''
  message.value = ''
  try {
    const result = await credentials.testProfile(props.profile.id)
    message.value = `${result.model || form.model} 连接成功${result.latency_ms != null ? ` · ${result.latency_ms} ms` : ''}`
  } catch (err) {
    error.value = requestErrorMessage(err, '连接测试失败')
  }
}
</script>

<template>
  <div class="model-drawer-backdrop" @click.self="close">
    <aside ref="dialog" class="model-profile-drawer" role="dialog" aria-modal="true" :aria-labelledby="`model-profile-title-${profile?.id || 'new'}`">
      <header>
        <div>
          <span class="eyebrow">MODEL CONNECTION</span>
          <h2 :id="`model-profile-title-${profile?.id || 'new'}`">{{ isEditing ? '编辑自定义模型' : '新增自定义模型' }}</h2>
        </div>
        <button class="model-drawer-close" type="button" aria-label="关闭模型配置" @click="close"><AppIcon name="close" :size="18" /></button>
      </header>
      <p class="model-drawer-intro">保存 OpenAI 兼容连接。API Key 只在服务端加密保存，前端不会读取明文。</p>
      <form id="model-profile-form" class="model-profile-form" @submit.prevent="saveAndSwitch">
        <label>配置名称<input ref="nameInput" v-model="form.name" required maxlength="80" autocomplete="off" placeholder="例如：日常简历模型" /></label>
        <label>API 地址<input v-model="form.api_url" required type="url" maxlength="500" autocomplete="url" placeholder="https://api.example.com/v1" /></label>
        <label>模型名称<input v-model="form.model" required maxlength="120" autocomplete="off" placeholder="例如：gpt-5-mini" /></label>
        <label>
          API Key
          <input v-model="form.api_key" :required="!isEditing || !profile?.has_api_key" type="password" autocomplete="new-password" :placeholder="profile?.has_api_key ? `已保存 ····${profile.key_last4}，留空则沿用` : '请输入 API Key'" />
          <small v-if="profile?.has_api_key">只显示密钥末四位；填写新值才会替换。</small>
        </label>
      </form>
      <p v-if="error" class="model-form-message is-error" role="alert">{{ error }}</p>
      <p v-if="message" class="model-form-message is-success" aria-live="polite">{{ message }}</p>
      <footer>
        <button v-if="isEditing" class="secondary-button" type="button" :disabled="credentials.saving || Boolean(credentials.testingId)" @click="testConnection">
          {{ credentials.testingId ? '连接中…' : '测试连接' }}
        </button>
        <button class="primary-button" type="submit" form="model-profile-form" :disabled="credentials.saving || Boolean(credentials.testingId)">
          {{ credentials.saving ? '保存中…' : '保存并切换' }}
        </button>
      </footer>
    </aside>
  </div>
</template>

<style scoped>
.model-drawer-backdrop { position: fixed; inset: 0; z-index: 100; display: flex; justify-content: flex-end; background: rgba(15, 23, 42, .38); backdrop-filter: blur(2px); }
.model-profile-drawer { width: min(500px, 100%); height: 100vh; overflow-y: auto; padding: 26px; color: var(--slate); background: var(--paper); border-left: 1px solid var(--line); box-shadow: -24px 0 55px rgba(15, 23, 42, .16); }
.model-profile-drawer header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.model-profile-drawer h2 { margin: 5px 0 0; color: var(--ink); font-size: 22px; }
.model-drawer-close { width: 36px; height: 36px; display: grid; place-items: center; flex: 0 0 auto; color: var(--muted); background: transparent; border: 1px solid var(--line); border-radius: 9px; cursor: pointer; }
.model-drawer-close:focus-visible,.model-profile-drawer footer button:focus-visible { outline: 3px solid rgba(15, 159, 143, .22); outline-offset: 2px; }
.model-drawer-intro { margin: 20px 0; color: var(--muted); font-size: 12px; line-height: 1.65; }
.model-profile-form { display: grid; gap: 15px; }
.model-profile-form label { display: grid; gap: 7px; color: #556174; font-size: 11px; font-weight: 700; }
.model-profile-form input { width: 100%; height: 42px; padding: 0 11px; color: #273449; background: #fff; border: 1px solid #d6dee7; border-radius: 8px; outline: 0; }
.model-profile-form input:focus { border-color: #5bbdb2; box-shadow: 0 0 0 3px rgba(15, 159, 143, .09); }
.model-profile-form small { color: #8b99a8; font-size: 10px; font-weight: 400; }
.model-form-message { margin: 15px 0 0; padding: 10px 12px; border-radius: 8px; font-size: 11px; }
.model-form-message.is-error { color: #a43f49; background: #fff3f3; border: 1px solid #f2d3d6; }
.model-form-message.is-success { color: #0d766d; background: #e9f8f5; border: 1px solid #c9ece5; }
.model-profile-drawer footer { display: flex; justify-content: flex-end; gap: 9px; margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--line); }
@media (max-width: 560px) {
  .model-profile-drawer { padding: 22px 18px; }
  .model-profile-drawer footer { align-items: stretch; flex-direction: column-reverse; }
  .model-profile-drawer footer button { width: 100%; }
}
</style>
