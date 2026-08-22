<script setup>
import { computed } from 'vue'
import { iconPaths } from '@/icons/iconPaths'

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 20 },
  label: { type: String, default: '' },
})

const icon = computed(() => {
  const definition = iconPaths[props.name]
  if (!definition) throw new Error(`Unknown icon: ${props.name}`)
  return definition
})
</script>

<template>
  <svg
    class="app-icon"
    :viewBox="icon.viewBox"
    :width="size"
    :height="size"
    style="color: inherit"
    fill="currentColor"
    :role="label ? 'img' : undefined"
    :aria-hidden="label ? undefined : 'true'"
    focusable="false"
  >
    <title v-if="label">{{ label }}</title>
    <path v-for="path in icon.paths" :key="path" :d="path" />
  </svg>
</template>

