<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, listItems } from '@/api'
import ModalPanel from '@/components/ModalPanel.vue'
import ToastMessage from '@/components/ToastMessage.vue'
import AppIcon from '@/components/AppIcon.vue'

const employees = ref([])
const policies = ref([])
const tags = ref([])
const query = ref('')
const mode = ref('')
const loading = ref(true)
const editing = ref(null)
const formOpen = ref(false)
const toast = ref('')
const saving = ref(false)

const emptyForm = () => ({
  employee_no: '', name: '', aliases_text: '', department: '', position: '', join_date: '',
  employment_status: 'regular', active: true, attendance_policy_id: null,
  expected_days_override: null, tag_ids: [], phone: '', bank_name: '', bank_account_holder: '',
  bank_province: '', bank_branch: '', bank_card_number: '', alipay_account: '',
})
const form = reactive(emptyForm())

const filtered = computed(() => employees.value.filter((employee) => {
  const text = `${employee.name}${employee.employee_no}${employee.department}${employee.position}`.toLowerCase()
  return (!query.value || text.includes(query.value.toLowerCase())) && (!mode.value || employee.attendance_policy?.mode === mode.value)
}))

function flash(message) {
  toast.value = message
  window.setTimeout(() => { toast.value = '' }, 2600)
}

async function load() {
  loading.value = true
  const [employeePayload, policyPayload, tagPayload] = await Promise.all([
    api('employees/?page_size=500'), api('policies/'), api('tags/'),
  ])
  employees.value = listItems(employeePayload)
  policies.value = listItems(policyPayload)
  tags.value = listItems(tagPayload)
  loading.value = false
}

function openForm(employee = null) {
  Object.assign(form, emptyForm())
  editing.value = employee
  formOpen.value = true
  if (employee) Object.assign(form, {
    ...employee,
    aliases_text: (employee.aliases || []).join('、'),
    attendance_policy_id: employee.attendance_policy?.id || null,
    tag_ids: (employee.tags || []).map((tag) => tag.id),
  })
}

async function save() {
  saving.value = true
  const payload = {
    ...form,
    aliases: form.aliases_text.split(/[、,，]/).map((item) => item.trim()).filter(Boolean),
    expected_days_override: form.expected_days_override || null,
    join_date: form.join_date || null,
  }
  delete payload.aliases_text
  try {
    await api(editing.value ? `employees/${editing.value.id}/` : 'employees/', {
      method: editing.value ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    })
    editing.value = null
    formOpen.value = false
    await load()
    flash('人员信息已保存')
  } catch (err) {
    flash(err.message)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <ToastMessage :message="toast" />
    <div class="page-hero page-hero--compact">
      <div><h2>人员档案与考勤归类</h2><p>人员标签、考勤策略和系统权限彼此独立，工号用于稳定匹配打卡记录。</p></div>
      <button class="primary-button button-with-icon" @click="openForm()"><AppIcon name="plus" :size="16" /><span>新增人员</span></button>
    </div>
    <section class="toolbar panel">
      <label class="search-box"><AppIcon name="search" :size="17" /><input v-model="query" placeholder="搜索姓名、工号、部门或岗位" /></label>
      <select v-model="mode"><option value="">全部考勤类型</option><option value="standard">标准考勤</option><option value="flexible">弹性工作</option><option value="exempt">免考勤</option><option value="part_time">兼职</option><option value="shift">轮班</option></select>
      <span class="toolbar__count">{{ filtered.length }} 人</span>
    </section>
    <section class="panel table-panel">
      <div v-if="loading" class="skeleton-block"></div>
      <div v-else class="table-scroll">
        <table class="data-table">
          <thead><tr><th>人员</th><th>部门 / 岗位</th><th>考勤策略</th><th>人员标签</th><th>状态</th><th>联系方式</th><th></th></tr></thead>
          <tbody>
            <tr v-for="employee in filtered" :key="employee.id">
              <td><div class="person-cell"><span class="person-avatar">{{ employee.name.slice(-1) }}</span><div><strong>{{ employee.name }}</strong><small>{{ employee.employee_no }}</small></div></div></td>
              <td><strong>{{ employee.department || '未分组' }}</strong><small class="block-text">{{ employee.position || '未设置岗位' }}</small></td>
              <td><span :class="['status-badge', `status-badge--${employee.attendance_policy?.mode || 'standard'}`]">{{ employee.attendance_policy?.name || '未设置' }}</span></td>
              <td><div class="tag-row"><span v-for="tag in employee.tags" :key="tag.id" class="tag-chip" :style="{ '--tag-color': tag.color }">{{ tag.name }}</span><small v-if="!employee.tags.length">—</small></div></td>
              <td><span :class="['live-state', { 'live-state--off': !employee.active }]"><i></i>{{ employee.active ? employee.employment_status_label : '已停用' }}</span></td>
              <td>{{ employee.phone || '—' }}</td>
              <td><button class="text-button" @click="openForm(employee)">编辑</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <ModalPanel v-if="formOpen" :title="editing ? '编辑人员档案' : '新增人员'" wide @close="formOpen = false; editing = null">
      <form class="form-grid" @submit.prevent="save">
        <label class="field-label">工号<input v-model="form.employee_no" required /></label>
        <label class="field-label">姓名<input v-model="form.name" required /></label>
        <label class="field-label">姓名别名<input v-model="form.aliases_text" placeholder="用顿号分隔，例如：陈圆、陈园" /></label>
        <label class="field-label">部门<input v-model="form.department" /></label>
        <label class="field-label">岗位<input v-model="form.position" /></label>
        <label class="field-label">入职日期<input v-model="form.join_date" type="date" /></label>
        <label class="field-label">在职状态<select v-model="form.employment_status"><option value="probation">试用期</option><option value="regular">已转正</option><option value="founder">创始人</option><option value="part_time">兼职</option><option value="left">已离职</option></select></label>
        <label class="field-label">考勤策略<select v-model="form.attendance_policy_id"><option :value="null">未设置</option><option v-for="policy in policies" :key="policy.id" :value="policy.id">{{ policy.name }}</option></select></label>
        <label class="field-label">个人应出勤覆盖<input v-model="form.expected_days_override" type="number" step="0.5" placeholder="留空使用导入批次默认值" /></label>
        <label class="field-label field-label--full">人员标签<div class="checkbox-row"><label v-for="tag in tags" :key="tag.id" class="checkbox-chip"><input v-model="form.tag_ids" type="checkbox" :value="tag.id" />{{ tag.name }}</label></div></label>
        <div class="form-section-title">联系方式与支付信息 <span>仅管理员和 HR 可见</span></div>
        <label class="field-label">手机号码<input v-model="form.phone" /></label>
        <label class="field-label">银行名称<input v-model="form.bank_name" /></label>
        <label class="field-label">开户人<input v-model="form.bank_account_holder" /></label>
        <label class="field-label">开户省份<input v-model="form.bank_province" /></label>
        <label class="field-label field-label--full">开户行<input v-model="form.bank_branch" /></label>
        <label class="field-label">银行卡号<input v-model="form.bank_card_number" /></label>
        <label class="field-label">支付宝账号<input v-model="form.alipay_account" /></label>
        <label class="switch-row field-label--full"><input v-model="form.active" type="checkbox" /><span>该人员当前在职并参与系统管理</span></label>
      </form>
      <template #footer><button class="secondary-button" @click="formOpen = false; editing = null">取消</button><button class="primary-button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存人员' }}</button></template>
    </ModalPanel>
  </div>
</template>
