<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, listItems } from '@/api'
import EChart from './EChart.vue'
import ModalPanel from './ModalPanel.vue'

const props = defineProps({ employee: Object, batchId: [Number, String] })
defineEmits(['close'])
const rows = ref([])
const loading = ref(true)

function minutes(item) {
  if (!item?.valid) return null
  return item.minutes
}

function formatMinutes(value) {
  if (value == null) return '-'
  const dayPrefix = value >= 1440 ? '次日 ' : ''
  const normalized = value % 1440
  return `${dayPrefix}${String(Math.floor(normalized / 60)).padStart(2, '0')}:${String(normalized % 60).padStart(2, '0')}`
}

const option = computed(() => {
  const dates = rows.value.map((row) => row.work_date.slice(8))
  const first = rows.value.map((row) => {
    const values = row.punches.map(minutes).filter((item) => item != null)
    return values.length ? Math.min(...values) : null
  })
  const last = rows.value.map((row) => {
    const values = row.punches.map(minutes).filter((item) => item != null)
    return values.length ? Math.max(...values) : null
  })
  return {
    tooltip: { trigger: 'axis', valueFormatter: formatMinutes },
    legend: { data: ['首次打卡', '末次打卡'], right: 8, top: 0 },
    grid: { left: 56, right: 18, top: 46, bottom: 34 },
    xAxis: { type: 'category', data: dates, axisTick: { show: false }, axisLine: { lineStyle: { color: '#CBD5E1' } } },
    yAxis: { type: 'value', min: 0, max: 1620, interval: 180, axisLabel: { formatter: formatMinutes }, splitLine: { lineStyle: { color: '#E2E8F0', type: 'dashed' } } },
    series: [
      { name: '首次打卡', type: 'line', connectNulls: false, data: first, smooth: 0.2, symbolSize: 7, lineStyle: { color: '#0F9F8F', width: 2 }, itemStyle: { color: '#0F9F8F' } },
      { name: '末次打卡', type: 'line', connectNulls: false, data: last, smooth: 0.2, symbolSize: 7, lineStyle: { color: '#334155', width: 2 }, itemStyle: { color: '#334155' } },
    ],
  }
})

onMounted(async () => {
  try {
    rows.value = listItems(await api(`raw-days/?batch=${props.batchId}&employee=${props.employee.id}`))
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <ModalPanel :title="`${employee.name} · 月度打卡曲线`" wide @close="$emit('close')">
    <div v-if="loading" class="skeleton-block"></div>
    <template v-else>
      <div class="chart-note"><span>{{ employee.employee_no }}</span><span>{{ employee.department || '未分组' }}</span><span>凌晨跨日按 24:00 以后展示</span></div>
      <EChart class="attendance-chart" :option="option" />
      <div class="mini-calendar">
        <div v-for="row in rows" :key="row.id" :class="['calendar-day', { 'calendar-day--work': row.effective_has_punch, 'calendar-day--warning': row.is_cross_day_suspicion }]">
          <strong>{{ Number(row.work_date.slice(8)) }}</strong><span>{{ row.raw_value || '休' }}</span>
        </div>
      </div>
    </template>
  </ModalPanel>
</template>

