<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, listItems } from '@/api'
import EmployeeAttendanceModal from '@/components/EmployeeAttendanceModal.vue'
import ModalPanel from '@/components/ModalPanel.vue'
import ToastMessage from '@/components/ToastMessage.vue'

const route = useRoute()
const router = useRouter()
const batches = ref([])
const selectedBatch = ref(route.query.batch || '')
const results = ref([])
const loading = ref(false)
const query = ref('')
const statusFilter = ref('')
const editing = ref(null)
const chartEmployee = ref(null)
const toast = ref('')
const form = reactive({ leave_days: 0, overtime_days: 0, overtime_hours: 0, adjustment_days: 0, adjustment_hours: 0, late_count: 0, absence_count: 0, missing_punch_count: 0, deduction: 0, note: '' })

const currentBatch = computed(() => batches.value.find((item) => String(item.id) === String(selectedBatch.value)))
const filtered = computed(() => results.value.filter((result) => {
  const text = `${result.employee.name}${result.employee.employee_no}${result.employee.department}`.toLowerCase()
  return (!query.value || text.includes(query.value.toLowerCase())) && (!statusFilter.value || result.status === statusFilter.value)
}))

function flash(message) { toast.value = message; window.setTimeout(() => { toast.value = '' }, 2600) }

async function loadBatches() {
  batches.value = listItems(await api('imports/'))
  if (!selectedBatch.value && batches.value.length) selectedBatch.value = batches.value[0].id
}

async function loadResults() {
  if (!selectedBatch.value) return
  loading.value = true
  results.value = listItems(await api(`results/?batch=${selectedBatch.value}`))
  loading.value = false
}

function selectBatch() {
  router.replace({ query: { batch: selectedBatch.value } })
  loadResults()
}

function openEdit(result) {
  editing.value = result
  Object.keys(form).forEach((key) => { form[key] = result[key] ?? 0 })
  form.note = result.note || ''
}

async function saveResult() {
  try {
    await api(`results/${editing.value.id}/`, { method: 'PATCH', body: JSON.stringify(form) })
    editing.value = null
    await loadResults()
    flash('人工调整已保存并重新核算')
  } catch (err) { flash(err.message) }
}

async function approve(result) {
  await api(`results/${result.id}/approve/`, { method: 'POST', body: '{}' })
  await loadResults()
  flash(`${result.employee.name} 已确认`)
}

function exportWorkbook() {
  window.location.href = `/api/imports/${selectedBatch.value}/export/`
}

onMounted(async () => { await loadBatches(); await loadResults() })
watch(() => route.query.batch, (value) => { if (value && value !== selectedBatch.value) { selectedBatch.value = value; loadResults() } })
</script>

<template>
  <div class="page-stack">
    <ToastMessage :message="toast" />
    <div class="page-hero page-hero--compact"><div><h2>月度核算结果</h2><p>每一行都保留规则轨迹；人工调整后系统会立即重算，并在导出文件中记录。</p></div><button class="primary-button" :disabled="!selectedBatch" @click="exportWorkbook">↓ 导出考勤汇总</button></div>
    <section class="toolbar panel">
      <select v-model="selectedBatch" @change="selectBatch"><option value="" disabled>选择导入批次</option><option v-for="batch in batches" :key="batch.id" :value="batch.id">{{ batch.year }} 年 {{ batch.month }} 月 · {{ batch.original_filename }}</option></select>
      <label class="search-box"><span>⌕</span><input v-model="query" placeholder="搜索姓名、工号或部门" /></label>
      <select v-model="statusFilter"><option value="">全部状态</option><option value="normal">正常</option><option value="review">需要复核</option><option value="approved">已确认</option></select>
      <span class="toolbar__count">{{ filtered.length }} 人</span>
    </section>
    <div v-if="currentBatch" class="batch-summary-strip"><span><strong>{{ currentBatch.matched_rows }}</strong> 匹配人员</span><span><strong>{{ currentBatch.unmatched_rows }}</strong> 未匹配</span><span><strong>{{ currentBatch.pending_suspicions }}</strong> 跨日待审</span><span>默认应出勤 <strong>{{ currentBatch.default_expected_days }}</strong> 天</span></div>
    <section class="panel table-panel">
      <div v-if="loading" class="skeleton-block"></div>
      <div v-else class="table-scroll"><table class="data-table data-table--dense"><thead><tr><th>人员</th><th>应出勤</th><th>有效打卡</th><th>请假</th><th>加班</th><th>人工调整</th><th>实际出勤</th><th>状态</th><th>规则说明</th><th></th></tr></thead><tbody>
        <tr v-for="result in filtered" :key="result.id">
          <td><div class="person-cell"><span class="person-avatar">{{ result.employee.name.slice(-1) }}</span><div><strong>{{ result.employee.name }}</strong><small>{{ result.employee.department }} · {{ result.employee.employee_no }}</small></div></div></td>
          <td>{{ result.due_days }}</td><td><button class="link-number" @click="chartEmployee = result.employee">{{ result.punch_days }} 天</button></td><td>{{ result.leave_days || '—' }}</td><td><span>{{ result.overtime_days || '—' }}</span><small v-if="Number(result.overtime_hours)" class="block-text">+ {{ result.overtime_hours }} 小时</small></td><td>{{ Number(result.adjustment_days) > 0 ? '+' : '' }}{{ result.adjustment_days }}</td><td><strong class="result-number">{{ result.actual_days }}</strong></td>
          <td><span :class="['status-badge', `status-badge--${result.status}`]">{{ result.status_label }}</span></td>
          <td><span class="rule-text">{{ result.rule_trace.base_rule }}</span></td>
          <td><div class="table-actions"><button class="text-button" @click="openEdit(result)">调整</button><button v-if="result.status !== 'approved'" class="text-button" @click="approve(result)">确认</button></div></td>
        </tr>
        <tr v-if="!filtered.length"><td colspan="10"><div class="table-empty">当前筛选下没有核算结果</div></td></tr>
      </tbody></table></div>
    </section>

    <ModalPanel v-if="editing" :title="`${editing.employee.name} · 人工调整`" @close="editing = null">
      <div class="rule-preview rule-preview--top"><span>当前规则</span><p>{{ editing.rule_trace.base_rule }}</p></div>
      <form class="form-grid" @submit.prevent="saveResult">
        <label class="field-label">请假天数<input v-model="form.leave_days" type="number" step="0.5" /></label><label class="field-label">加班天数<input v-model="form.overtime_days" type="number" step="0.5" /></label>
        <label class="field-label">加班小时<input v-model="form.overtime_hours" type="number" step="0.5" /></label><label class="field-label">出勤天数调整<input v-model="form.adjustment_days" type="number" step="0.5" /></label>
        <label class="field-label">小时调整<input v-model="form.adjustment_hours" type="number" step="0.5" /></label><label class="field-label">迟到次数<input v-model="form.late_count" type="number" min="0" /></label>
        <label class="field-label">旷工次数<input v-model="form.absence_count" type="number" min="0" /></label><label class="field-label">缺卡次数<input v-model="form.missing_punch_count" type="number" min="0" /></label>
        <label class="field-label">扣款金额<input v-model="form.deduction" type="number" step="0.01" /></label><label class="field-label field-label--full">核算备注<textarea v-model="form.note" rows="3" placeholder="请填写人工调整原因"></textarea></label>
      </form>
      <template #footer><button class="secondary-button" @click="editing = null">取消</button><button class="primary-button" @click="saveResult">保存并重算</button></template>
    </ModalPanel>
    <EmployeeAttendanceModal v-if="chartEmployee" :employee="chartEmployee" :batch-id="selectedBatch" @close="chartEmployee = null" />
  </div>
</template>

