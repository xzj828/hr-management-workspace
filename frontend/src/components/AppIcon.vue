<script setup>
import { computed } from 'vue'
import {
  ArrowRight,
  BriefcaseBusiness,
  Calculator,
  CalendarCheck2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  Clock3,
  Crown,
  Download,
  Ellipsis,
  Eye,
  FileText,
  Headphones,
  LayoutDashboard,
  Lightbulb,
  ListFilter,
  Maximize2,
  Minimize2,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Upload,
  UserRound,
  UserRoundCheck,
  UsersRound,
  Workflow,
  X,
  ZoomIn,
  ZoomOut,
} from '@lucide/vue'

const iconComponents = Object.freeze({
  'alert-circle': CircleAlert,
  'arrow-right': ArrowRight,
  briefcase: BriefcaseBusiness,
  'calculator-check': Calculator,
  'calendar-check': CalendarCheck2,
  'check-circle': CircleCheck,
  'chevron-down': ChevronDown,
  'chevron-left': ChevronLeft,
  'chevron-right': ChevronRight,
  clock: Clock3,
  close: X,
  crown: Crown,
  dashboard: LayoutDashboard,
  document: FileText,
  download: Download,
  eye: Eye,
  filter: ListFilter,
  maximize: Maximize2,
  minimize: Minimize2,
  headset: Headphones,
  'more-horizontal': Ellipsis,
  plus: Plus,
  refresh: RefreshCw,
  reset: RotateCcw,
  search: Search,
  shield: ShieldCheck,
  sliders: SlidersHorizontal,
  sparkles: Lightbulb,
  upload: Upload,
  user: UserRound,
  'user-check': UserRoundCheck,
  users: UsersRound,
  workflow: Workflow,
  'zoom-in': ZoomIn,
  'zoom-out': ZoomOut,
})

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 20 },
  label: { type: String, default: '' },
  strokeWidth: { type: [Number, String], default: 1.8 },
})

const icon = computed(() => {
  const definition = iconComponents[props.name]
  if (!definition) throw new Error(`Unknown icon: ${props.name}`)
  return definition
})
</script>

<template>
  <component
    :is="icon"
    class="app-icon"
    :size="size"
    :stroke-width="strokeWidth"
    style="color: inherit"
    :role="label ? 'img' : undefined"
    :aria-hidden="label ? undefined : 'true'"
    focusable="false"
  >
    <title v-if="label">{{ label }}</title>
  </component>
</template>
