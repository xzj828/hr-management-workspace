<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'

const NODE_WIDTH = 154
const NODE_HEIGHT = 58
const CANVAS_WIDTH = 1400
const CANVAS_HEIGHT = 680

const props = defineProps({
  accounts: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
  snapshot: { type: Object, default: null },
  nodeStatuses: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['save'])

const library = [
  { type: 'recommend', label: '读取推荐' },
  { type: 'search', label: '常规搜索' },
  { type: 'human_screen', label: '人工筛选' },
  { type: 'human_approval', label: '人工确认' },
  { type: 'wait_reply', label: '等待回复' },
  { type: 'request_resume', label: '索要简历' },
  { type: 'wait_resume', label: '等待简历' },
  { type: 'human_review', label: '人工复核' },
  { type: 'send_interview', label: '面试邀约' },
  { type: 'end', label: '结束' },
]

const workflowName = ref('')
const accountId = ref('')
const templateId = ref(null)
const connectingFrom = ref('')
const connectionDrag = ref(null)
const connectionError = ref('')
const selected = ref(null)
const canvas = ref(null)
const canvasScroller = ref(null)
const nodes = ref([])
const edges = ref([])
let dragging = null
let nodeSequence = 0

function defaultSnapshot() {
  return {
    name: '标准候选人沟通',
    accountId: props.accounts[0]?.id || '',
    templateId: null,
    nodes: [
      { key: 'source', type: 'search', label: '常规搜索', position: { x: 42, y: 128 } },
      { key: 'screen', type: 'human_screen', label: '人工筛选', position: { x: 242, y: 128 } },
      { key: 'approval', type: 'human_approval', label: '人工确认', position: { x: 442, y: 128 } },
      { key: 'greet', type: 'greet', label: '打招呼', position: { x: 642, y: 128 } },
      { key: 'end', type: 'end', label: '结束', position: { x: 842, y: 128 } },
    ],
    edges: [
      { source: 'source', target: 'screen' },
      { source: 'screen', target: 'approval' },
      { source: 'approval', target: 'greet' },
      { source: 'greet', target: 'end' },
    ],
  }
}

function cloneNodes(items = []) {
  return items.map((node) => ({
    key: node.key,
    type: node.type,
    label: node.label,
    position: { x: Number(node.position?.x) || 16, y: Number(node.position?.y) || 24 },
    config: { ...(node.config || {}) },
  }))
}

function applySnapshot(value) {
  const next = value || defaultSnapshot()
  workflowName.value = next.name || '未命名流程'
  accountId.value = next.accountId || props.accounts[0]?.id || ''
  templateId.value = next.templateId || null
  nodes.value = cloneNodes(next.nodes)
  edges.value = (next.edges || []).map((edge) => ({ source: edge.source, target: edge.target }))
  selected.value = null
  connectingFrom.value = ''
}

watch(() => props.snapshot, applySnapshot, { immediate: true })
watch(() => props.accounts, (accounts) => {
  if (!accountId.value && accounts.length) accountId.value = accounts[0].id
}, { deep: true })

const nodeByKey = computed(() => Object.fromEntries(nodes.value.map((node) => [node.key, node])))
const edgePaths = computed(() => edges.value.map((edge) => {
  const source = nodeByKey.value[edge.source]
  const target = nodeByKey.value[edge.target]
  if (!source || !target) return null
  const x1 = source.position.x + NODE_WIDTH
  const y1 = source.position.y + NODE_HEIGHT / 2
  const x2 = target.position.x
  const y2 = target.position.y + NODE_HEIGHT / 2
  const curve = Math.max(55, Math.abs(x2 - x1) / 2)
  return { ...edge, path: `M ${x1} ${y1} C ${x1 + curve} ${y1}, ${x2 - curve} ${y2}, ${x2} ${y2}` }
}).filter(Boolean))
const connectionPreviewPath = computed(() => {
  if (!connectionDrag.value) return ''
  const source = nodeByKey.value[connectionDrag.value.source]
  if (!source) return ''
  const x1 = source.position.x + NODE_WIDTH
  const y1 = source.position.y + NODE_HEIGHT / 2
  const { x: x2, y: y2 } = connectionDrag.value
  const curve = Math.max(55, Math.abs(x2 - x1) / 2)
  return `M ${x1} ${y1} C ${x1 + curve} ${y1}, ${x2 - curve} ${y2}, ${x2} ${y2}`
})
const selectedNode = computed(() => selected.value?.kind === 'node' ? nodeByKey.value[selected.value.key] : null)

const selectionLabel = computed(() => {
  if (connectingFrom.value) return `正在从「${nodeByKey.value[connectingFrom.value]?.label || ''}」连线，请点击目标节点左侧圆点`
  if (selected.value?.kind === 'node') return `已选择节点「${nodeByKey.value[selected.value.key]?.label || ''}」`
  if (selected.value?.kind === 'edge') return '已选择一条连线'
  return '拖动节点自由编排；选中节点或连线后可删除'
})

function makeNodeKey(type) {
  nodeSequence += 1
  return `${type}-${Date.now()}-${nodeSequence}`
}

function addNode(item, position) {
  const index = nodes.value.length
  const nextPosition = position || { x: 70 + (index % 5) * 190, y: 80 + Math.floor(index / 5) * 110 }
  const node = { key: makeNodeKey(item.type), type: item.type, label: item.label, position: nextPosition, config: {} }
  nodes.value.push(node)
  selected.value = { kind: 'node', key: node.key }
}

function dragLibrary(event, item) {
  event.dataTransfer.setData('application/x-workflow-node', JSON.stringify(item))
  event.dataTransfer.effectAllowed = 'copy'
}

function dropNode(event) {
  const raw = event.dataTransfer.getData('application/x-workflow-node')
  if (!raw) return
  const item = JSON.parse(raw)
  const rect = canvas.value.getBoundingClientRect()
  addNode(item, {
    x: Math.min(CANVAS_WIDTH - NODE_WIDTH - 16, Math.max(16, event.clientX - rect.left + canvas.value.scrollLeft - NODE_WIDTH / 2)),
    y: Math.min(CANVAS_HEIGHT - NODE_HEIGHT - 16, Math.max(24, event.clientY - rect.top + canvas.value.scrollTop - NODE_HEIGHT / 2)),
  })
}

function startPointerDrag(event, node) {
  if (event.button !== 0 || event.target.closest('button')) return
  const rect = canvas.value.getBoundingClientRect()
  selected.value = { kind: 'node', key: node.key }
  dragging = {
    key: node.key,
    offsetX: event.clientX - rect.left + canvas.value.scrollLeft - node.position.x,
    offsetY: event.clientY - rect.top + canvas.value.scrollTop - node.position.y,
  }
  event.preventDefault()
}

function movePointer(event) {
  if (!dragging || !canvas.value) return
  const node = nodeByKey.value[dragging.key]
  if (!node) return
  const rect = canvas.value.getBoundingClientRect()
  node.position = {
    x: Math.min(CANVAS_WIDTH - NODE_WIDTH - 16, Math.max(16, event.clientX - rect.left + canvas.value.scrollLeft - dragging.offsetX)),
    y: Math.min(CANVAS_HEIGHT - NODE_HEIGHT - 16, Math.max(24, event.clientY - rect.top + canvas.value.scrollTop - dragging.offsetY)),
  }
}

function stopPointerDrag() { dragging = null }

function beginConnection(key) {
  connectionError.value = ''
  connectingFrom.value = key
  selected.value = { kind: 'node', key }
}

function wouldCreateCycle(source, target) {
  const outgoing = {}
  for (const node of nodes.value) outgoing[node.key] = []
  for (const edge of edges.value) outgoing[edge.source]?.push(edge.target)
  const pending = [target]
  const visited = new Set()
  while (pending.length) {
    const key = pending.pop()
    if (key === source) return true
    if (visited.has(key)) continue
    visited.add(key)
    pending.push(...(outgoing[key] || []))
  }
  return false
}

function connectNodes(source, target) {
  if (!source || !target) return false
  if (source === target) {
    connectionError.value = '节点不能连接自身'
    return false
  }
  if (edges.value.some((edge) => edge.source === source && edge.target === target)) {
    connectionError.value = '这条连线已存在'
    return false
  }
  if (wouldCreateCycle(source, target)) {
    connectionError.value = '流程不能形成循环'
    return false
  }
  edges.value.push({ source, target })
  selected.value = { kind: 'edge', key: `${source}-${target}`, source, target }
  connectionError.value = ''
  return true
}

function completeConnection(key) {
  if (!connectingFrom.value) return
  const source = connectingFrom.value
  connectNodes(source, key)
  connectingFrom.value = ''
}

function canvasPoint(event) {
  const rect = canvas.value.getBoundingClientRect()
  return {
    x: event.clientX - rect.left + canvas.value.scrollLeft,
    y: event.clientY - rect.top + canvas.value.scrollTop,
  }
}

function startConnectionDrag(event, key) {
  if (event.button !== 0) return
  connectionError.value = ''
  connectionDrag.value = { source: key, ...canvasPoint(event) }
  connectingFrom.value = key
  selected.value = { kind: 'node', key }
  event.preventDefault()
}

function finishConnectionDrag(key) {
  if (!connectionDrag.value) return
  connectNodes(connectionDrag.value.source, key)
  connectionDrag.value = null
  connectingFrom.value = ''
}

function cancelConnectionDrag() {
  connectionDrag.value = null
  connectingFrom.value = ''
}

function selectEdge(edge) {
  selected.value = { kind: 'edge', key: `${edge.source}-${edge.target}`, source: edge.source, target: edge.target }
  connectingFrom.value = ''
}

function removeSelection() {
  if (selected.value?.kind === 'node') {
    const key = selected.value.key
    nodes.value = nodes.value.filter((node) => node.key !== key)
    edges.value = edges.value.filter((edge) => edge.source !== key && edge.target !== key)
    if (connectingFrom.value === key) connectingFrom.value = ''
  } else if (selected.value?.kind === 'edge') {
    const { source, target } = selected.value
    edges.value = edges.value.filter((edge) => edge.source !== source || edge.target !== target)
  }
  selected.value = null
}

function autoArrange() {
  const incoming = Object.fromEntries(nodes.value.map((node) => [node.key, 0]))
  const outgoing = Object.fromEntries(nodes.value.map((node) => [node.key, []]))
  edges.value.forEach((edge) => {
    if (incoming[edge.target] !== undefined && outgoing[edge.source]) {
      incoming[edge.target] += 1
      outgoing[edge.source].push(edge.target)
    }
  })
  const queue = nodes.value.filter((node) => incoming[node.key] === 0).map((node) => ({ key: node.key, level: 0 }))
  const levels = {}
  while (queue.length) {
    const current = queue.shift()
    levels[current.key] = Math.max(levels[current.key] || 0, current.level)
    outgoing[current.key]?.forEach((key) => {
      incoming[key] -= 1
      if (incoming[key] === 0) queue.push({ key, level: current.level + 1 })
    })
  }
  nodes.value.forEach((node, index) => {
    if (levels[node.key] === undefined) levels[node.key] = index
  })
  const rows = {}
  nodes.value.forEach((node) => {
    const level = levels[node.key]
    const row = rows[level] || 0
    rows[level] = row + 1
    node.position = { x: 50 + level * 205, y: 70 + row * 105 }
  })
  nextTick(() => canvasScroller.value?.scrollTo?.({ left: 0, top: 0, behavior: 'smooth' }))
}

function clearSelection() {
  selected.value = null
  connectingFrom.value = ''
}

function handleKeydown(event) {
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(event.target?.tagName)) return
  if ((event.key === 'Delete' || event.key === 'Backspace') && selected.value) {
    event.preventDefault()
    removeSelection()
  } else if (event.key === 'Escape') clearSelection()
}

function save() {
  emit('save', {
    templateId: templateId.value,
    name: workflowName.value.trim(),
    accountId: Number(accountId.value),
    nodes: cloneNodes(nodes.value),
    edges: edges.value.map((edge) => ({ ...edge })),
  })
}

function moveConnection(event) {
  if (connectionDrag.value && canvas.value) connectionDrag.value = { ...connectionDrag.value, ...canvasPoint(event) }
}

function stopConnections(event) {
  if (!connectionDrag.value) return
  const targetPort = document.elementFromPoint?.(event.clientX, event.clientY)?.closest?.('[data-workflow-input]')
  if (targetPort?.dataset?.workflowInput) finishConnectionDrag(targetPort.dataset.workflowInput)
  else cancelConnectionDrag()
}

onMounted(() => {
  window.addEventListener('pointermove', movePointer)
  window.addEventListener('pointerup', stopPointerDrag)
  window.addEventListener('pointermove', moveConnection)
  window.addEventListener('pointerup', stopConnections)
  window.addEventListener('keydown', handleKeydown)
})
onUnmounted(() => {
  window.removeEventListener('pointermove', movePointer)
  window.removeEventListener('pointerup', stopPointerDrag)
  window.removeEventListener('pointermove', moveConnection)
  window.removeEventListener('pointerup', stopConnections)
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <section class="workflow-builder">
    <aside class="workflow-library">
      <span class="panel-kicker">SAFE NODES</span><h3>节点库</h3><p>拖入画布，或单击快速添加。</p>
      <button v-for="item in library" :key="item.type" type="button" draggable="true" :data-test="`workflow-library-${item.type}`" @dragstart="dragLibrary($event, item)" @click="addNode(item)"><AppIcon name="plus" :size="13" />{{ item.label }}</button>
    </aside>
    <div class="workflow-stage">
      <header>
        <label>流程名称<input v-model="workflowName" data-test="workflow-name" maxlength="120" /></label>
        <label>执行账号<select v-model="accountId"><option v-for="account in accounts" :key="account.id" :value="account.id">{{ account.name }}</option></select></label>
        <span>{{ templateId ? '正在基于历史版本重新编排，保存后生成新版本' : '创建可审计的新流程版本' }}</span>
        <button class="primary-button" data-test="save-workflow" :disabled="saving || !workflowName || !accountId" @click="save">{{ saving ? '保存中…' : '保存新版本' }}</button>
      </header>
      <div class="workflow-editor-toolbar">
        <span :class="{ 'is-error': connectionError }">{{ connectionError || selectionLabel }}</span>
        <div><button type="button" data-test="auto-layout" @click="autoArrange">自动排列</button><button v-if="connectingFrom" type="button" @click="connectingFrom = ''">取消连线</button><button type="button" data-test="remove-selection" :disabled="!selected" @click="removeSelection">删除所选</button></div>
      </div>
      <div ref="canvasScroller" class="workflow-canvas-scroll"><div ref="canvas" class="workflow-canvas" data-test="workflow-canvas" @dragover.prevent @drop.prevent="dropNode" @click.self="clearSelection">
        <svg :viewBox="`0 0 ${CANVAS_WIDTH} ${CANVAS_HEIGHT}`" aria-label="流程连线">
          <g v-for="edge in edgePaths" :key="`${edge.source}-${edge.target}`">
            <path class="workflow-edge" :class="{ 'is-selected': selected?.kind === 'edge' && selected.source === edge.source && selected.target === edge.target }" :d="edge.path" />
            <path class="workflow-edge-hit" :d="edge.path" :data-edge-key="`${edge.source}-${edge.target}`" role="button" tabindex="0" :aria-label="`选择 ${edge.source} 到 ${edge.target} 的连线`" @click.stop="selectEdge(edge)" @keydown.enter.prevent="selectEdge(edge)" />
          </g>
          <path v-if="connectionPreviewPath" class="workflow-edge workflow-edge--preview" :d="connectionPreviewPath" data-test="connection-preview" />
        </svg>
        <article v-for="node in nodes" :key="node.key" :data-node-key="node.key" :data-status="nodeStatuses[node.key] || ''" :class="['workflow-node', nodeStatuses[node.key] ? `is-status-${nodeStatuses[node.key]}` : '', { 'is-selected': selected?.kind === 'node' && selected.key === node.key, 'is-connecting': connectingFrom === node.key }]" :style="{ left: `${node.position.x}px`, top: `${node.position.y}px` }" @pointerdown="startPointerDrag($event, node)" @click.stop="selected = { kind: 'node', key: node.key }">
          <button class="workflow-node__port workflow-node__port--input" type="button" title="连接到此节点" :data-workflow-input="node.key" @pointerup.stop="finishConnectionDrag(node.key)" @click.stop="completeConnection(node.key)"></button>
          <i><AppIcon :name="node.type.includes('human') ? 'user' : node.type === 'end' ? 'check-circle' : 'workflow'" :size="16" /></i>
          <div><small>{{ node.type.replaceAll('_', ' ') }}</small><strong>{{ node.label }}</strong></div>
          <button class="workflow-node__port workflow-node__port--output" type="button" title="从此节点开始连线" @pointerdown.stop="startConnectionDrag($event, node.key)" @click.stop="beginConnection(node.key)"></button>
        </article>
      </div></div>
      <Transition name="workflow-config">
        <aside v-if="selectedNode" class="workflow-node-config" data-test="workflow-node-config">
          <header><div><span class="panel-kicker">NODE SETTINGS</span><h3>节点配置</h3></div><button class="icon-button" type="button" aria-label="关闭节点配置" @click="selected = null"><AppIcon name="close" :size="16" /></button></header>
          <label>显示名称<input v-model.trim="selectedNode.label" maxlength="120" data-test="node-label" /></label>
          <label class="workflow-node-config__switch"><input type="checkbox" :checked="selectedNode.config.enabled !== false" @change="selectedNode.config.enabled = $event.target.checked" /><span>启用此节点</span></label>
          <label v-if="['greet','request_resume','send_interview'].includes(selectedNode.type)">消息模板<textarea v-model="selectedNode.config.message" maxlength="1000" rows="5" placeholder="HR 确认时仍可修改"></textarea></label>
          <label v-if="['search','recommend','deep_search'].includes(selectedNode.type)">搜索关键词<input v-model.trim="selectedNode.config.keyword" maxlength="120" placeholder="例如：Vue 3" /></label>
          <p>节点标识：<code>{{ selectedNode.key }}</code></p>
          <button class="danger-text-button" type="button" data-test="delete-selected-node" @click="removeSelection">删除节点</button>
        </aside>
      </Transition>
    </div>
  </section>
</template>
