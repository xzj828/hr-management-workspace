<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import ModelProfileDrawer from '@/components/ModelProfileDrawer.vue'
import { useModelCredentialStore } from '@/stores/modelCredential'

const credentials = useModelCredentialStore()
const root = ref(null)
const trigger = ref(null)
const optionButtons = ref([])
const open = ref(false)
const drawerOpen = ref(false)
const editingProfile = ref(null)
const statusMessage = ref('')
const menuId = `model-switcher-${Math.random().toString(36).slice(2)}`
const activeLabel = computed(() => credentials.activeStateUncertain ? '状态待确认' : (credentials.activeProfile?.name || '尚未配置'))

async function load() {
  try { await credentials.loadProfiles() } catch {}
}

function toggle() {
  open.value = !open.value
  if (open.value) {
    const refresh = credentials.loading || credentials.error ? Promise.resolve() : load()
    Promise.resolve(refresh).finally(() => nextTick(() => {
      const activeIndex = credentials.profiles.findIndex((profile) => profile.is_active)
      optionButtons.value[Math.max(0, activeIndex)]?.focus()
    }))
  }
}

function setOptionButton(element, index) {
  if (element) optionButtons.value[index] = element
}

function focusOption(index) {
  if (!optionButtons.value.length) return
  const nextIndex = (index + optionButtons.value.length) % optionButtons.value.length
  optionButtons.value[nextIndex]?.focus()
}

function closeAndFocusTrigger() {
  open.value = false
  nextTick(() => trigger.value?.focus())
}

function openCreate() {
  open.value = false
  editingProfile.value = null
  drawerOpen.value = true
}

function openEdit(profile) {
  open.value = false
  editingProfile.value = profile
  drawerOpen.value = true
}

defineExpose({ openCreate })

async function choose(profile) {
  if (profile.is_active || credentials.switchingId) return
  statusMessage.value = ''
  try {
    const selected = await credentials.activateProfile(profile.id)
    statusMessage.value = `已切换到 ${selected.name}`
    open.value = false
    nextTick(() => trigger.value?.focus())
  } catch {}
}

async function saved(profile) {
  drawerOpen.value = false
  editingProfile.value = null
  statusMessage.value = `已保存并切换到 ${profile.name}`
  await nextTick()
  trigger.value?.focus()
}

function closeDrawer() {
  drawerOpen.value = false
  editingProfile.value = null
  nextTick(() => trigger.value?.focus())
}

function onDocumentClick(event) {
  if (open.value && root.value && !root.value.contains(event.target)) open.value = false
}

function onKeydown(event) {
  if (event.key === 'Escape' && open.value) closeAndFocusTrigger()
}

onMounted(() => {
  load()
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div ref="root" class="model-switcher">
    <button ref="trigger" class="model-switcher__trigger" type="button" :aria-controls="menuId" :aria-expanded="String(open)" aria-haspopup="dialog" @click.stop="toggle">
      <AppIcon name="sparkles" :size="17" />
      <span>切换模型</span>
      <small>{{ activeLabel }}</small>
      <AppIcon name="chevron-down" :size="14" />
    </button>
    <div v-if="open" :id="menuId" class="model-switcher__menu" role="dialog" aria-label="选择模型">
      <header><div><strong>选择模型</strong><small>只影响之后创建的 AI 任务</small></div><button type="button" aria-label="关闭模型菜单" @click="closeAndFocusTrigger"><AppIcon name="close" :size="15" /></button></header>
      <div v-if="credentials.loading" class="model-switcher__state" aria-live="polite">正在读取模型…</div>
      <template v-else>
        <p v-if="credentials.error" class="model-switcher__error" role="alert">{{ credentials.error }} <button type="button" @click="load">重试</button></p>
        <div v-if="credentials.profiles.length" class="model-switcher__options" role="radiogroup" aria-label="已保存模型">
          <button
            v-for="profile in credentials.profiles"
            :key="profile.id"
            :ref="(element) => setOptionButton(element, credentials.profiles.indexOf(profile))"
            type="button"
            role="radio"
            :aria-checked="String(profile.is_active)"
            :disabled="Boolean(credentials.switchingId)"
            @click="choose(profile)"
            @keydown.down.prevent="focusOption(credentials.profiles.indexOf(profile) + 1)"
            @keydown.up.prevent="focusOption(credentials.profiles.indexOf(profile) - 1)"
            @keydown.home.prevent="focusOption(0)"
            @keydown.end.prevent="focusOption(credentials.profiles.length - 1)"
          >
            <i :class="{ 'is-active': profile.is_active }"><AppIcon v-if="profile.is_active" name="check-circle" :size="16" /></i>
            <span><strong>{{ profile.name }}</strong><small>{{ profile.model }}</small></span>
            <em v-if="profile.is_active">当前使用</em>
            <em v-else-if="String(credentials.switchingId) === String(profile.id)">切换中…</em>
          </button>
        </div>
        <div v-else-if="!credentials.error" class="model-switcher__empty"><strong>尚未配置模型</strong><p>添加一个兼容模型后，可在这里快速切换。</p></div>
      </template>
      <footer>
        <button class="model-switcher__add" type="button" @click="openCreate"><AppIcon name="plus" :size="16" />新增自定义模型</button>
        <button v-if="credentials.activeProfile" class="model-switcher__edit" type="button" @click="openEdit(credentials.activeProfile)">编辑当前模型</button>
      </footer>
    </div>
    <span class="model-switcher__announcement" aria-live="polite">{{ statusMessage }}</span>
    <ModelProfileDrawer v-if="drawerOpen" :profile="editingProfile" @close="closeDrawer" @saved="saved" />
  </div>
</template>

<style scoped>
.model-switcher { position: relative; }
.model-switcher__trigger { min-height: 40px; display: inline-flex; align-items: center; gap: 6px; padding: 5px 8px; color: var(--slate); background: transparent; border: 0; border-radius: 8px; cursor: pointer; }
.model-switcher__trigger:hover,.model-switcher__trigger[aria-expanded="true"] { color: var(--teal-dark); background: #f3f8f7; }
.model-switcher__trigger:focus-visible,.model-switcher__options > button:focus-visible,.model-switcher__menu footer button:focus-visible,.model-switcher__menu header button:focus-visible { outline: 3px solid rgba(15, 159, 143, .22); outline-offset: 2px; }
.model-switcher__trigger > span { font-size: 12px; font-weight: 800; }
.model-switcher__trigger > small { max-width: 90px; overflow: hidden; color: var(--muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.model-switcher__menu { position: absolute; z-index: 70; top: calc(100% + 9px); right: 0; width: min(360px, calc(100vw - 24px)); overflow: hidden; color: var(--slate); background: #fff; border: 1px solid var(--line); border-radius: 13px; box-shadow: 0 18px 45px rgba(15, 23, 42, .15); }
.model-switcher__menu > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 15px 16px 12px; border-bottom: 1px solid var(--line); }
.model-switcher__menu header div { display: grid; gap: 3px; }
.model-switcher__menu header strong { color: var(--ink); font-size: 13px; }
.model-switcher__menu header small { color: var(--muted); font-size: 10px; }
.model-switcher__menu header button { display: grid; place-items: center; padding: 3px; color: var(--muted); background: transparent; border: 0; cursor: pointer; }
.model-switcher__state,.model-switcher__empty { padding: 28px 18px; text-align: center; }
.model-switcher__state { color: var(--muted); font-size: 11px; }
.model-switcher__empty strong { color: var(--ink); font-size: 12px; }
.model-switcher__empty p { margin: 5px 0 0; color: var(--muted); font-size: 10px; }
.model-switcher__error { margin: 10px 12px; padding: 9px 10px; color: #a43f49; background: #fff3f3; border-radius: 8px; font-size: 10px; }
.model-switcher__error button { margin-left: 5px; color: inherit; background: transparent; border: 0; text-decoration: underline; cursor: pointer; }
.model-switcher__options { max-height: 280px; overflow-y: auto; padding: 6px; }
.model-switcher__options > button { width: 100%; min-height: 53px; display: grid; grid-template-columns: 20px minmax(0, 1fr) auto; align-items: center; gap: 9px; padding: 8px 10px; color: var(--slate); background: transparent; border: 0; border-radius: 8px; text-align: left; cursor: pointer; }
.model-switcher__options > button:hover:not(:disabled) { background: #f3f8f7; }
.model-switcher__options > button:disabled { cursor: wait; }
.model-switcher__options i { width: 17px; height: 17px; display: grid; place-items: center; color: #b5c0c7; border: 1px solid #cbd5dc; border-radius: 50%; }
.model-switcher__options i.is-active { color: var(--teal-dark); border: 0; }
.model-switcher__options span { display: grid; gap: 2px; min-width: 0; }
.model-switcher__options strong,.model-switcher__options small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-switcher__options strong { color: var(--ink); font-size: 11px; }
.model-switcher__options small { color: var(--muted); font-size: 9px; }
.model-switcher__options em { color: var(--teal-dark); font-size: 9px; font-style: normal; font-weight: 700; white-space: nowrap; }
.model-switcher__menu > footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--line); background: #fbfcfc; }
.model-switcher__menu footer button { border: 0; cursor: pointer; }
.model-switcher__add { display: inline-flex; align-items: center; gap: 5px; color: var(--teal-dark); background: transparent; font-size: 10px; font-weight: 800; }
.model-switcher__edit { color: var(--muted); background: transparent; font-size: 9px; }
.model-switcher__announcement { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
@media (max-width: 760px) {
  .model-switcher__trigger > small { display: none; }
  .model-switcher__menu { position: fixed; top: 70px; right: 12px; left: 12px; width: auto; }
}
</style>
