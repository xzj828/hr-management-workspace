<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { GaugeChart } from 'echarts/charts'
import { use } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import * as echarts from 'echarts/core'

use([GaugeChart, SVGRenderer])

const props = defineProps({
  value: { type: Number, required: true },
})

const chartRoot = ref(null)
let chart = null
let resizeObserver = null

function renderChart() {
  if (!chartRoot.value || chartRoot.value.clientWidth === 0) return
  if (!chart) chart = echarts.init(chartRoot.value, null, { renderer: 'svg' })
  chart.setOption({
    animation: false,
    series: [{
      type: 'gauge',
      startAngle: 90,
      endAngle: -270,
      min: 0,
      max: 100,
      radius: '99%',
      center: ['50%', '50%'],
      pointer: { show: false },
      progress: { show: true, roundCap: true, width: 11, itemStyle: { color: '#12988d' } },
      axisLine: { roundCap: true, lineStyle: { width: 11, color: [[1, '#edf2f2']] } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      anchor: { show: false },
      title: { show: false },
      detail: { show: false },
      data: [{ value: Math.max(0, Math.min(100, props.value)) }],
    }],
  }, true)
}

watch(() => props.value, () => nextTick(renderChart))

onMounted(() => {
  nextTick(renderChart)
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartRoot.value)
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
})
</script>

<template>
  <div ref="chartRoot" class="circular-task-progress" aria-hidden="true"></div>
</template>

<style scoped>
.circular-task-progress { width: 100%; height: 100%; }
</style>
