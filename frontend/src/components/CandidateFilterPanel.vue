<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import {
  CANDIDATE_FILTER_GROUPS,
  TALENT_KEYWORD_OPTIONS,
  candidateFilterCount,
  candidateFilterSummary,
  defaultCandidateFilters,
  normalizeCandidateFilters,
} from '@/recruitmentCandidateFilters'

const props = defineProps({
  modelValue: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const trigger = ref(null)
const floatingForm = ref(null)
const floatingStyle = ref({ position: 'fixed', zIndex: 300 })
const filters = computed(() => normalizeCandidateFilters(props.modelValue))
const selectedCount = computed(() => candidateFilterCount(filters.value))
const summary = computed(() => candidateFilterSummary(filters.value))
const ageEnabled = computed(() => filters.value.age_min !== null)

function update(patch) {
  emit('update:modelValue', normalizeCandidateFilters({ ...filters.value, ...patch }))
}

function selectSingle(key, value) {
  update({ [key]: value })
}

function toggleKeyword(value) {
  const selected = new Set(filters.value.talent_keywords)
  if (selected.has(value)) selected.delete(value)
  else selected.add(value)
  update({ talent_keywords: [...selected] })
}

function enableAge() {
  if (!ageEnabled.value) update({ age_min: 22, age_max: 35 })
}

function updateAge(key, rawValue) {
  const value = Number(rawValue)
  const currentMin = filters.value.age_min ?? 22
  const currentMax = filters.value.age_max ?? 35
  update({
    age_min: key === 'age_min' ? Math.min(value, currentMax) : currentMin,
    age_max: key === 'age_max' ? Math.max(value, currentMin) : currentMax,
  })
}

function clearAge() {
  update({ age_min: null, age_max: null })
}

function clearAll() {
  emit('update:modelValue', defaultCandidateFilters())
}

function updateFloatingPosition() {
  if (!open.value || !trigger.value) return

  const edge = 12
  const gap = 6
  const maxPanelHeight = 430
  const minUsefulHeight = 180
  const rect = trigger.value.getBoundingClientRect()
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const availableWidth = Math.max(0, viewportWidth - edge * 2)
  const width = Math.min(rect.width || 320, availableWidth)
  const left = Math.min(Math.max(edge, rect.left), Math.max(edge, viewportWidth - edge - width))
  const spaceBelow = Math.max(0, viewportHeight - rect.bottom - gap - edge)
  const spaceAbove = Math.max(0, rect.top - gap - edge)
  const openAbove = spaceBelow < minUsefulHeight && spaceAbove > spaceBelow
  const availableHeight = openAbove ? spaceAbove : spaceBelow

  floatingStyle.value = {
    position: 'fixed',
    zIndex: 300,
    left: `${left}px`,
    width: `${width}px`,
    maxHeight: `${Math.max(120, Math.min(maxPanelHeight, availableHeight))}px`,
    top: openAbove ? 'auto' : `${rect.bottom + gap}px`,
    bottom: openAbove ? `${viewportHeight - rect.top + gap}px` : 'auto',
  }
}

function closePanel() {
  open.value = false
}

function togglePanel() {
  open.value = !open.value
}

function handlePointerDown(event) {
  if (trigger.value?.contains(event.target) || floatingForm.value?.contains(event.target)) return
  closePanel()
}

function handleKeydown(event) {
  if (event.key !== 'Escape') return
  closePanel()
  trigger.value?.focus()
}

function bindFloatingListeners() {
  window.addEventListener('resize', updateFloatingPosition)
  window.addEventListener('scroll', updateFloatingPosition, true)
  document.addEventListener('pointerdown', handlePointerDown, true)
  document.addEventListener('keydown', handleKeydown)
}

function unbindFloatingListeners() {
  window.removeEventListener('resize', updateFloatingPosition)
  window.removeEventListener('scroll', updateFloatingPosition, true)
  document.removeEventListener('pointerdown', handlePointerDown, true)
  document.removeEventListener('keydown', handleKeydown)
}

watch(open, async (value) => {
  unbindFloatingListeners()
  if (!value) return
  await nextTick()
  updateFloatingPosition()
  bindFloatingListeners()
})

onBeforeUnmount(unbindFloatingListeners)
</script>

<template>
  <section class="candidate-filter" data-test="candidate-filter">
    <button
      ref="trigger"
      class="candidate-filter__trigger"
      data-test="candidate-filter-trigger"
      type="button"
      :aria-expanded="open"
      aria-controls="candidate-filter-form"
      :disabled="disabled"
      @click="togglePanel"
    >
      <span>
        <strong>主动寻访条件</strong>
        <small>{{ summary }}</small>
      </span>
      <em v-if="selectedCount">已选 {{ selectedCount }} 项</em>
      <AppIcon name="chevron-down" :size="15" :class="{ 'is-open': open }" />
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        id="candidate-filter-form"
        ref="floatingForm"
        class="candidate-filter__form"
        data-test="candidate-filter-form"
        role="dialog"
        aria-label="主动寻访条件"
        :style="floatingStyle"
      >
      <div class="candidate-filter__row candidate-filter__age">
        <span class="candidate-filter__label">年龄</span>
        <div class="candidate-filter__options">
          <button type="button" :class="{ 'is-selected': !ageEnabled }" data-test="filter-age-any" @click="clearAge">不限</button>
          <button v-if="!ageEnabled" type="button" data-test="filter-age-enable" @click="enableAge">设置年龄范围</button>
          <template v-else>
            <label>
              <span>{{ filters.age_min }}</span>
              <input
                data-test="filter-age-min"
                type="range"
                min="18"
                max="60"
                :value="filters.age_min"
                :aria-valuetext="`${filters.age_min} 岁`"
                @input="updateAge('age_min', $event.target.value)"
              />
            </label>
            <b>至</b>
            <label>
              <span>{{ filters.age_max }}</span>
              <input
                data-test="filter-age-max"
                type="range"
                min="18"
                max="60"
                :value="filters.age_max"
                :aria-valuetext="`${filters.age_max} 岁`"
                @input="updateAge('age_max', $event.target.value)"
              />
            </label>
          </template>
        </div>
      </div>

      <div v-for="group in CANDIDATE_FILTER_GROUPS.slice(0, 4)" :key="group.key" class="candidate-filter__row">
        <span class="candidate-filter__label">{{ group.label }}</span>
        <div class="candidate-filter__options">
          <button
            v-for="([value, label]) in group.options"
            :key="value"
            type="button"
            :class="{ 'is-selected': filters[group.key] === value }"
            :data-test="`filter-${group.key}-${value}`"
            @click="selectSingle(group.key, value)"
          >{{ label }}</button>
        </div>
      </div>

      <div class="candidate-filter__row">
        <span class="candidate-filter__label">牛人关键词</span>
        <div class="candidate-filter__options">
          <button
            v-for="([value, label]) in TALENT_KEYWORD_OPTIONS"
            :key="value"
            type="button"
            :class="{ 'is-selected': filters.talent_keywords.includes(value) }"
            :aria-pressed="filters.talent_keywords.includes(value)"
            :data-test="`filter-keyword-${value}`"
            @click="toggleKeyword(value)"
          >{{ label }}</button>
        </div>
      </div>

      <div v-for="group in CANDIDATE_FILTER_GROUPS.slice(4)" :key="group.key" class="candidate-filter__row">
        <span class="candidate-filter__label">{{ group.label }}</span>
        <div class="candidate-filter__options">
          <button
            v-for="([value, label]) in group.options"
            :key="value"
            type="button"
            :class="{ 'is-selected': filters[group.key] === value }"
            :data-test="`filter-${group.key}-${value}`"
            @click="selectSingle(group.key, value)"
          >{{ label }}</button>
        </div>
      </div>

      <footer class="candidate-filter__actions">
        <small>筛选条件会随本次主动寻访方案一并保存。</small>
        <button class="candidate-filter__clear" data-test="candidate-filter-clear" type="button" @click="clearAll">清除</button>
        <button class="candidate-filter__confirm" data-test="candidate-filter-confirm" type="button" @click="closePanel">确定</button>
      </footer>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.candidate-filter {
  position: relative;
  grid-column: 1 / -1;
  min-width: 0;
  overflow: visible;
  border: 1px solid #eadfce;
  border-radius: 12px;
  color: #3f3428;
  background: #fff;
}

.candidate-filter__trigger {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 13px 15px;
  border: 0;
  color: #3f3428;
  background: #fffcf7;
  text-align: left;
  cursor: pointer;
}

.candidate-filter__trigger > span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.candidate-filter__trigger strong {
  font-size: 14px;
}

.candidate-filter__trigger small {
  overflow: hidden;
  color: #786b5c;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-filter__trigger em {
  padding: 4px 8px;
  border-radius: 999px;
  color: #8b6235;
  background: #f5ead9;
  font-size: 12px;
  font-style: normal;
  font-weight: 700;
}

.candidate-filter__trigger .app-icon {
  color: #b78345;
  transition: transform 160ms ease;
}

.candidate-filter__trigger .app-icon.is-open {
  transform: rotate(180deg);
}

.candidate-filter__trigger:focus-visible,
.candidate-filter__options button:focus-visible,
.candidate-filter__actions button:focus-visible {
  outline: 3px solid rgba(183, 131, 69, .25);
  outline-offset: 2px;
}

.candidate-filter__form {
  position: fixed;
  z-index: 300;
  max-height: 430px;
  overflow-y: auto;
  overscroll-behavior: contain;
  border: 1px solid #eadfce;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 20px 48px rgba(63, 52, 40, .2);
}

.candidate-filter__row {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  gap: 14px;
  padding: 12px 16px;
  border-bottom: 1px solid #f3eadf;
}

.candidate-filter__label {
  padding-top: 6px;
  color: #5d5145;
  font-size: 13px;
  font-weight: 650;
}

.candidate-filter__options {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
  min-width: 0;
}

.candidate-filter__options button {
  min-height: 30px;
  padding: 5px 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: #51463b;
  background: #fff;
  font-size: 12px;
  cursor: pointer;
}

.candidate-filter__options button:hover {
  border-color: #dec49e;
  color: #8b6235;
  background: #f8efe2;
}

.candidate-filter__options button.is-selected {
  border-color: #b78345;
  color: #fff;
  background: #b78345;
}

.candidate-filter__age label {
  display: grid;
  grid-template-columns: 24px 110px;
  align-items: center;
  gap: 6px;
  color: #8b6235;
  font-size: 12px;
  font-weight: 700;
}

.candidate-filter__age input {
  width: 110px;
  accent-color: #b78345;
}

.candidate-filter__age b {
  color: #94a3b8;
  font-size: 12px;
}

.candidate-filter__actions {
  position: sticky;
  bottom: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 9px;
  padding: 11px 16px;
  border-top: 1px solid #eadfce;
  background: #fffcf7;
}

.candidate-filter__actions small {
  color: #786b5c;
  font-size: 11px;
}

.candidate-filter__actions button {
  min-height: 32px;
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.candidate-filter__clear {
  border: 1px solid #d8c8b4;
  color: #68594a;
  background: #fff;
}

.candidate-filter__confirm {
  border: 1px solid #b78345;
  color: #fff;
  background: #b78345;
}

@media (max-width: 720px) {
  .candidate-filter__row {
    grid-template-columns: minmax(0, 1fr);
    gap: 6px;
  }

  .candidate-filter__label {
    padding-top: 0;
  }

  .candidate-filter__age label {
    grid-template-columns: 24px minmax(90px, 1fr);
    flex: 1 1 150px;
  }

  .candidate-filter__age input {
    width: 100%;
  }

  .candidate-filter__actions {
    grid-template-columns: 1fr 1fr;
  }

  .candidate-filter__actions small {
    grid-column: 1 / -1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .candidate-filter__trigger .app-icon {
    transition: none;
  }
}
</style>
