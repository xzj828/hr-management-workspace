<script setup>
import * as echarts from 'echarts'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({ option: { type: Object, required: true } })
const element = ref(null)
let chart
let resizeObserver

function draw() {
  if (!chart || !props.option) return
  chart.setOption(props.option, true)
}

onMounted(async () => {
  await nextTick()
  chart = echarts.init(element.value)
  draw()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(element.value)
})

watch(() => props.option, draw, { deep: true })
onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
})
</script>

<template><div ref="element" class="echart"></div></template>

