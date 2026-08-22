<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, listItems } from '@/api'
import ToastMessage from '@/components/ToastMessage.vue'

const batches = ref([])
const selectedBatch = ref('')
const rows = ref([])
const statusFilter = ref('pending')
const toast = ref('')
const loading = ref(false)

const currentBatch = computed(() => batches.value.find((item) => String(item.id) === String(selectedBatch.value)))

function flash(message) { toast.value = message; window.setTimeout(() => { toast.value = '' }, 2600) }

async function loadBatches() {
  batches.value = listItems(await api('imports/'))
  if (batches.value.length) selectedBatch.value = batches.value[0].id
}

async function load() {
  if (!selectedBatch.value) return
  loading.value = true
  const status = statusFilter.value ? `&status=${statusFilter.value}` : ''
  rows.value = listItems(await api(`suspicions/?batch=${selectedBatch.value}${status}`))
  loading.value = false
}

async function resolve(row, resolution) {
  try {
    await api(`suspicions/${row.id}/resolve/`, { method: 'POST', body: JSON.stringify({ resolution }) })
    await load()
    flash(resolution === 'assign_previous' ? '已归入前一天，未把次日算作出勤' : '已保留在当天并计入出勤')
  } catch (err) { flash(err.message) }
}

onMounted(async () => { await loadBatches(); await load() })
</script>

<template>
  <div class="page-stack">
    <ToastMessage :message="toast" />
    <div class="page-hero page-hero--compact"><div><h2>跨日打卡审核</h2><p>当天只有一条凌晨记录、且前一天有晚间打卡时，先进入这里，不直接把第二天算作出勤。</p></div></div>
    <section class="toolbar panel">
      <select v-model="selectedBatch" @change="load"><option v-for="batch in batches" :key="batch.id" :value="batch.id">{{ batch.year }} 年 {{ batch.month }} 月</option></select>
      <div class="segmented"><button :class="{ active: statusFilter === 'pending' }" @click="statusFilter = 'pending'; load()">待审核</button><button :class="{ active: statusFilter === '' }" @click="statusFilter = ''; load()">全部记录</button></div>
      <span class="toolbar__count">{{ rows.length }} 条</span>
    </section>
    <section v-if="currentBatch" class="review-explainer"><div class="review-explainer__mark">!</div><div><strong>本批次识别到 {{ currentBatch.suspicion_count }} 条疑似记录</strong><p>选择“归前一天”时，凌晨记录不计入当天；选择“保留当天”时，当天增加一个有效出勤日。</p></div></section>
    <div v-if="loading" class="skeleton-block"></div>
    <section v-else class="review-list">
      <article v-for="row in rows" :key="row.id" class="review-card">
        <div class="review-card__person"><span class="person-avatar person-avatar--large">{{ row.employee_name.slice(-1) }}</span><div><strong>{{ row.employee_name }}</strong><span>{{ row.employee_no || row.source_name }} · {{ row.department || '未匹配部门' }}</span></div></div>
        <div class="review-card__timeline">
          <div><span>{{ row.previous_date }}</span><strong>{{ row.previous_raw_value || '—' }}</strong><small>前一天记录</small></div>
          <i>→</i>
          <div class="timeline-alert"><span>{{ row.work_date }}</span><strong>{{ row.punch_text }}</strong><small>次日单条凌晨记录</small></div>
        </div>
        <p class="review-card__reason">{{ row.reason }}</p>
        <div v-if="row.status === 'pending'" class="review-card__actions"><button class="secondary-button" @click="resolve(row, 'keep_current')">保留当天</button><button class="primary-button" @click="resolve(row, 'assign_previous')">归入前一天</button></div>
        <span v-else :class="['status-badge', `status-badge--${row.status}`]">{{ row.status_label }}</span>
      </article>
      <div v-if="!rows.length" class="empty-state"><div class="empty-state__icon">✓</div><strong>没有待审核的跨日记录</strong><p>本批次的疑似记录已经处理完毕。</p></div>
    </section>
  </div>
</template>

