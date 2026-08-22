<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api, listItems } from '@/api'
import ModalPanel from '@/components/ModalPanel.vue'
import ToastMessage from '@/components/ToastMessage.vue'

const policies = ref([])
const tags = ref([])
const policyOpen = ref(false)
const tagOpen = ref(false)
const editingPolicy = ref(null)
const editingTag = ref(null)
const toast = ref('')
const policyForm = reactive({ code: '', name: '', mode: 'standard', start_time: '', end_time: '', grace_minutes: 0, cross_day_cutoff_minutes: 180, description: '', active: true })
const tagForm = reactive({ name: '', color: '#0F9F8F', description: '' })

function flash(message) { toast.value = message; window.setTimeout(() => { toast.value = '' }, 2600) }

async function load() {
  const [policyPayload, tagPayload] = await Promise.all([api('policies/'), api('tags/')])
  policies.value = listItems(policyPayload)
  tags.value = listItems(tagPayload)
}

function editPolicy(policy = null) {
  editingPolicy.value = policy
  Object.assign(policyForm, { code: '', name: '', mode: 'standard', start_time: '', end_time: '', grace_minutes: 0, cross_day_cutoff_minutes: 180, description: '', active: true }, policy || {})
  policyOpen.value = true
}

function editTag(tag = null) {
  editingTag.value = tag
  Object.assign(tagForm, { name: '', color: '#0F9F8F', description: '' }, tag || {})
  tagOpen.value = true
}

async function savePolicy() {
  const payload = { ...policyForm, start_time: policyForm.start_time || null, end_time: policyForm.end_time || null }
  try {
    await api(editingPolicy.value ? `policies/${editingPolicy.value.id}/` : 'policies/', { method: editingPolicy.value ? 'PATCH' : 'POST', body: JSON.stringify(payload) })
    policyOpen.value = false; await load(); flash('考勤策略已保存')
  } catch (err) { flash(err.message) }
}

async function saveTag() {
  try {
    await api(editingTag.value ? `tags/${editingTag.value.id}/` : 'tags/', { method: editingTag.value ? 'PATCH' : 'POST', body: JSON.stringify(tagForm) })
    tagOpen.value = false; await load(); flash('人员标签已保存')
  } catch (err) { flash(err.message) }
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <ToastMessage :message="toast" />
    <div class="page-hero page-hero--compact"><div><h2>规则与分类</h2><p>考勤策略决定如何核算；人员标签只做归类；管理员权限在账号系统中单独维护。</p></div></div>
    <section class="settings-grid">
      <article class="panel settings-panel">
        <header class="panel__header"><div><span class="panel-kicker">ATTENDANCE POLICY</span><h3>考勤策略</h3></div><button class="secondary-button" @click="editPolicy()">＋ 新增策略</button></header>
        <div class="policy-list">
          <button v-for="policy in policies" :key="policy.id" class="policy-card" @click="editPolicy(policy)">
            <span :class="['policy-icon', `policy-icon--${policy.mode}`]">{{ policy.mode === 'exempt' ? '免' : policy.mode === 'flexible' ? '弹' : policy.mode === 'shift' ? '班' : '标' }}</span>
            <div><strong>{{ policy.name }}</strong><p>{{ policy.description || policy.mode_label }}</p><small>{{ policy.employee_count }} 人 · 跨日截止 {{ Math.floor(policy.cross_day_cutoff_minutes / 60).toString().padStart(2, '0') }}:{{ (policy.cross_day_cutoff_minutes % 60).toString().padStart(2, '0') }}</small></div><i>›</i>
          </button>
        </div>
      </article>
      <article class="panel settings-panel">
        <header class="panel__header"><div><span class="panel-kicker">PEOPLE TAGS</span><h3>人员标签</h3></div><button class="secondary-button" @click="editTag()">＋ 新增标签</button></header>
        <div class="tag-cloud">
          <button v-for="tag in tags" :key="tag.id" class="tag-manage" :style="{ '--tag-color': tag.color }" @click="editTag(tag)"><i></i><strong>{{ tag.name }}</strong><span>{{ tag.description || '暂无说明' }}</span></button>
        </div>
      </article>
    </section>
    <section class="permission-note panel"><div class="permission-note__icon">⌘</div><div><strong>系统角色不等于人员标签</strong><p>“管理员、HR、部门主管、只读”控制系统操作权限；“领导层、弹性工作”等用于人员归类和考勤规则，请不要混用。</p></div></section>

    <ModalPanel v-if="policyOpen" :title="editingPolicy ? '编辑考勤策略' : '新增考勤策略'" @close="policyOpen = false">
      <form class="form-grid" @submit.prevent="savePolicy">
        <label class="field-label">策略编码<input v-model="policyForm.code" required placeholder="standard" /></label><label class="field-label">策略名称<input v-model="policyForm.name" required /></label>
        <label class="field-label">核算模式<select v-model="policyForm.mode"><option value="standard">标准考勤</option><option value="flexible">弹性工作</option><option value="exempt">免考勤</option><option value="part_time">兼职</option><option value="shift">轮班</option></select></label><label class="field-label">迟到宽限（分钟）<input v-model="policyForm.grace_minutes" type="number" min="0" /></label>
        <label class="field-label">上班时间<input v-model="policyForm.start_time" type="time" /></label><label class="field-label">下班时间<input v-model="policyForm.end_time" type="time" /></label>
        <label class="field-label field-label--full">跨日疑似截止（凌晨分钟数）<input v-model="policyForm.cross_day_cutoff_minutes" type="number" min="0" max="720" /><small>180 表示 03:00 以前的单条打卡进入疑似队列</small></label>
        <label class="field-label field-label--full">说明<textarea v-model="policyForm.description" rows="3" /></label>
      </form>
      <template #footer><button class="secondary-button" @click="policyOpen = false">取消</button><button class="primary-button" @click="savePolicy">保存策略</button></template>
    </ModalPanel>
    <ModalPanel v-if="tagOpen" :title="editingTag ? '编辑人员标签' : '新增人员标签'" @close="tagOpen = false">
      <form class="form-grid" @submit.prevent="saveTag"><label class="field-label">标签名称<input v-model="tagForm.name" required /></label><label class="field-label">标识颜色<input v-model="tagForm.color" type="color" /></label><label class="field-label field-label--full">标签说明<textarea v-model="tagForm.description" rows="3" /></label></form>
      <template #footer><button class="secondary-button" @click="tagOpen = false">取消</button><button class="primary-button" @click="saveTag">保存标签</button></template>
    </ModalPanel>
  </div>
</template>
