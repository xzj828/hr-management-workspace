<script setup>
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({ accounts: { type: Array, default: () => [] }, saving: { type: Boolean, default: false } })
const emit = defineEmits(['save'])
const workflowName = ref('标准候选人沟通')
const accountId = ref(props.accounts[0]?.id || '')
const connectingFrom = ref('')
const canvas = ref(null)
const nodes = ref([
  { key: 'source', type: 'search', label: '常规搜索', position: { x: 42, y: 128 } },
  { key: 'screen', type: 'human_screen', label: '人工筛选', position: { x: 232, y: 128 } },
  { key: 'approval', type: 'human_approval', label: '人工确认', position: { x: 422, y: 128 } },
  { key: 'greet', type: 'greet', label: '打招呼', position: { x: 612, y: 128 } },
  { key: 'end', type: 'end', label: '结束', position: { x: 802, y: 128 } },
])
const edges = ref([
  { source: 'source', target: 'screen' }, { source: 'screen', target: 'approval' },
  { source: 'approval', target: 'greet' }, { source: 'greet', target: 'end' },
])
const library = [
  { type: 'recommend', label: '读取推荐' }, { type: 'search', label: '常规搜索' },
  { type: 'human_approval', label: '人工确认' }, { type: 'wait_reply', label: '等待回复' },
  { type: 'request_resume', label: '索要简历' }, { type: 'wait_resume', label: '等待简历' },
  { type: 'human_review', label: '人工复核' }, { type: 'send_interview', label: '面试邀约' },
]
const nodeByKey = computed(() => Object.fromEntries(nodes.value.map((node) => [node.key, node])))
const edgeLines = computed(() => edges.value.map((edge) => {
  const source = nodeByKey.value[edge.source], target = nodeByKey.value[edge.target]
  return source && target ? { ...edge, x1: source.position.x + 144, y1: source.position.y + 26, x2: target.position.x, y2: target.position.y + 26 } : null
}).filter(Boolean))

function dragLibrary(event, item) { event.dataTransfer.setData('application/x-workflow-node', JSON.stringify(item)) }
function dropNode(event) {
  const raw = event.dataTransfer.getData('application/x-workflow-node')
  if (!raw) return
  const item = JSON.parse(raw), rect = canvas.value.getBoundingClientRect()
  const key = `${item.type}-${Date.now()}`
  nodes.value.push({ key, type: item.type, label: item.label, position: { x: Math.max(16, event.clientX - rect.left - 72), y: Math.max(24, event.clientY - rect.top - 24) } })
}
function dragNode(event, node) { event.dataTransfer.setData('application/x-workflow-existing', node.key) }
function dropExisting(event) {
  const key = event.dataTransfer.getData('application/x-workflow-existing')
  if (!key) return false
  const node = nodeByKey.value[key], rect = canvas.value.getBoundingClientRect()
  node.position = { x: Math.max(16, event.clientX - rect.left - 72), y: Math.max(24, event.clientY - rect.top - 24) }
  return true
}
function handleDrop(event) { if (!dropExisting(event)) dropNode(event) }
function connect(key) {
  if (!connectingFrom.value) { connectingFrom.value = key; return }
  if (connectingFrom.value !== key && !edges.value.some((edge) => edge.source === connectingFrom.value && edge.target === key)) {
    edges.value.push({ source: connectingFrom.value, target: key })
  }
  connectingFrom.value = ''
}
function save() { emit('save', { name: workflowName.value.trim(), accountId: Number(accountId.value), nodes: nodes.value, edges: edges.value }) }
</script>

<template>
  <section class="workflow-builder">
    <aside class="workflow-library"><span class="panel-kicker">SAFE NODES</span><h3>节点库</h3><p>仅开放经过验证的动作。</p><button v-for="item in library" :key="item.type" draggable="true" @dragstart="dragLibrary($event, item)"><AppIcon name="plus" :size="13" />{{ item.label }}</button></aside>
    <div class="workflow-stage">
      <header><label>流程名称<input v-model="workflowName" data-test="workflow-name" maxlength="120" /></label><label>执行账号<select v-model="accountId"><option v-for="account in accounts" :key="account.id" :value="account.id">{{ account.name }}</option></select></label><span>拖动节点；依次点击节点右侧圆点完成连线</span><button class="primary-button" data-test="save-workflow" :disabled="saving || !workflowName || !accountId" @click="save">{{ saving ? '保存中…' : '保存新版本' }}</button></header>
      <div ref="canvas" class="workflow-canvas" @dragover.prevent @drop.prevent="handleDrop">
        <svg aria-hidden="true"><line v-for="edge in edgeLines" :key="`${edge.source}-${edge.target}`" :x1="edge.x1" :y1="edge.y1" :x2="edge.x2" :y2="edge.y2" /></svg>
        <article v-for="node in nodes" :key="node.key" :class="['workflow-node', { 'is-connecting': connectingFrom === node.key }]" :style="{ left: `${node.position.x}px`, top: `${node.position.y}px` }" draggable="true" @dragstart="dragNode($event, node)"><i><AppIcon :name="node.type.includes('human') ? 'user' : node.type === 'end' ? 'check-circle' : 'workflow'" :size="16" /></i><div><small>{{ node.type.replaceAll('_', ' ') }}</small><strong>{{ node.label }}</strong></div><button type="button" title="连接节点" @click.stop="connect(node.key)"></button></article>
      </div>
    </div>
  </section>
</template>
