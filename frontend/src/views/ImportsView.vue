<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, listItems } from '@/api'
import ToastMessage from '@/components/ToastMessage.vue'

const router = useRouter()
const batches = ref([])
const file = ref(null)
const dragging = ref(false)
const uploading = ref(false)
const toast = ref('')
const now = new Date()
const form = reactive({ year: now.getFullYear(), month: now.getMonth() + 1, default_expected_days: 25 })

const selectedFileLabel = computed(() => file.value ? `${file.value.name} · ${(file.value.size / 1024).toFixed(0)} KB` : '')

function choose(event) {
  const selected = event.target.files?.[0]
  if (selected) file.value = selected
}

function drop(event) {
  dragging.value = false
  const selected = event.dataTransfer.files?.[0]
  if (selected) file.value = selected
}

function flash(message) {
  toast.value = message
  window.setTimeout(() => { toast.value = '' }, 3000)
}

async function load() {
  batches.value = listItems(await api('imports/'))
}

async function upload() {
  if (!file.value) return flash('请先选择打卡 Excel 文件')
  uploading.value = true
  const body = new FormData()
  body.append('file', file.value)
  body.append('year', form.year)
  body.append('month', form.month)
  body.append('default_expected_days', form.default_expected_days)
  try {
    const batch = await api('imports/', { method: 'POST', body })
    file.value = null
    await load()
    flash(`导入完成：匹配 ${batch.matched_rows} 人，发现 ${batch.suspicion_count} 条跨日疑似`)
  } catch (err) {
    if (err.status === 409 && err.payload?.batch) {
      flash('这个文件已经导入过，已为你保留原批次')
    } else {
      flash(err.message)
    }
  } finally {
    uploading.value = false
  }
}

function openResults(batch) {
  router.push({ name: 'results', query: { batch: batch.id } })
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <ToastMessage :message="toast" />
    <div class="page-hero page-hero--compact"><div><h2>打卡机文件导入</h2><p>支持飞书打卡导出的 .xlsx 文件；原文件会留档，并记录文件校验值防止重复导入。</p></div></div>
    <section class="import-grid">
      <article class="panel upload-card">
        <header class="panel__header"><div><span class="panel-kicker">STEP 01</span><h3>选择打卡文件</h3></div></header>
        <label class="drop-zone" :class="{ 'drop-zone--active': dragging, 'drop-zone--selected': file }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="drop">
          <input type="file" accept=".xlsx" @change="choose" />
          <span class="drop-zone__icon">⇧</span>
          <strong>{{ file ? '文件已选择' : '拖入文件，或点击选择' }}</strong>
          <p>{{ selectedFileLabel || '仅支持 .xlsx，最大 10MB' }}</p>
        </label>
      </article>
      <article class="panel upload-card">
        <header class="panel__header"><div><span class="panel-kicker">STEP 02</span><h3>确认核算期间</h3></div></header>
        <div class="form-grid form-grid--compact">
          <label class="field-label">年份<input v-model="form.year" type="number" min="2020" max="2100" /></label>
          <label class="field-label">月份<select v-model="form.month"><option v-for="month in 12" :key="month" :value="month">{{ month }} 月</option></select></label>
          <label class="field-label field-label--full">默认应出勤天数<input v-model="form.default_expected_days" type="number" min="0" max="31" step="0.5" /><small>个人档案中的覆盖值优先</small></label>
        </div>
        <div class="rule-preview"><span>核算规则 v1</span><p>空白 / “-”算休息，有打卡算出勤；凌晨单条打卡进入疑似审核。</p></div>
        <button class="primary-button primary-button--large" :disabled="uploading || !file" @click="upload">{{ uploading ? '正在解析与核算…' : '开始导入并核算' }}</button>
      </article>
    </section>

    <section class="panel table-panel">
      <header class="panel__header panel__header--padded"><div><span class="panel-kicker">IMPORT HISTORY</span><h3>导入批次</h3></div><span>{{ batches.length }} 个批次</span></header>
      <div class="table-scroll"><table class="data-table"><thead><tr><th>期间</th><th>源文件</th><th>导入质量</th><th>跨日疑似</th><th>状态</th><th>时间</th><th></th></tr></thead><tbody>
        <tr v-for="batch in batches" :key="batch.id">
          <td><strong>{{ batch.year }} 年 {{ batch.month }} 月</strong><small class="block-text">应出勤 {{ batch.default_expected_days }} 天</small></td>
          <td>{{ batch.original_filename }}</td>
          <td><div class="metric-inline"><span class="text-success">{{ batch.matched_rows }} 已匹配</span><span v-if="batch.unmatched_rows" class="text-warning">{{ batch.unmatched_rows }} 未匹配</span></div></td>
          <td><span :class="['count-badge', { 'count-badge--warning': batch.pending_suspicions }]">{{ batch.pending_suspicions }} 待审</span></td>
          <td><span :class="['status-badge', `status-badge--${batch.status}`]">{{ batch.status_label }}</span></td>
          <td>{{ new Date(batch.created_at).toLocaleString() }}</td>
          <td><button class="text-button" @click="openResults(batch)">查看结果 →</button></td>
        </tr>
        <tr v-if="!batches.length"><td colspan="7"><div class="table-empty">还没有导入记录</div></td></tr>
      </tbody></table></div>
    </section>
  </div>
</template>

