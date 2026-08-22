<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '@/api'

const emit = defineEmits(['changed'])
const open = ref(false)
const busy = ref(false)
const error = ref('')
const status = reactive({
  loaded: false,
  counts: { jobs: 0, candidates: 0, applications: 0, resumes: 0 },
})

function assignStatus(payload) {
  status.loaded = Boolean(payload?.loaded)
  Object.assign(status.counts, payload?.counts || {})
}

async function loadStatus() {
  try {
    assignStatus(await api('recruitment/demo-data/'))
  } catch (err) {
    error.value = err.message
  }
}

async function loadDemo() {
  busy.value = true
  error.value = ''
  try {
    assignStatus(await api('recruitment/demo-data/', { method: 'POST' }))
    emit('changed')
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
  }
}

async function clearDemo() {
  if (!window.confirm('只会清除演示数据，确定继续吗？')) return
  busy.value = true
  error.value = ''
  try {
    assignStatus(await api('recruitment/demo-data/', { method: 'DELETE' }))
    emit('changed')
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
  }
}

onMounted(loadStatus)
</script>

<template>
  <div class="recruitment-demo-menu">
    <button
      class="text-button recruitment-demo-menu__trigger"
      type="button"
      data-test="demo-trigger"
      :aria-expanded="open"
      @click="open = !open"
    >演示数据 <span aria-hidden="true">⌄</span></button>
    <div v-if="open" class="recruitment-demo-menu__popover">
      <div class="recruitment-demo-menu__summary">
        <strong>{{ status.loaded ? '演示数据已加载' : '尚未加载演示数据' }}</strong>
        <span>{{ status.counts.jobs }} 个职位 · {{ status.counts.candidates }} 位候选人</span>
        <span>{{ status.counts.applications }} 条应聘记录 · {{ status.counts.resumes }} 份简历</span>
      </div>
      <p v-if="error" class="recruitment-inline-error">{{ error }}</p>
      <div class="recruitment-demo-menu__actions">
        <button type="button" data-test="demo-load" :disabled="busy" @click="loadDemo">
          {{ busy ? '处理中…' : '加载演示数据' }}
        </button>
        <button type="button" data-test="demo-clear" :disabled="busy || !status.loaded" @click="clearDemo">
          清除演示数据
        </button>
      </div>
    </div>
  </div>
</template>
