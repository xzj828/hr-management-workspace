<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

const props = defineProps({
  resume: { type: Object, required: true },
  candidateName: { type: String, default: '' },
})
const emit = defineEmits(['close'])

const MIN_ZOOM = 50
const MAX_ZOOM = 200
const ZOOM_STEP = 25
const card = ref(null)
const closeButton = ref(null)
const viewport = ref(null)
const zoom = ref(100)
const expanded = ref(false)
let previousBodyOverflow = ''

const fileAvailable = computed(() => props.resume.file_available !== false && Boolean(props.resume.preview_url))
const isImage = computed(() => String(props.resume.content_type || '').startsWith('image/'))
const fileName = computed(() => props.resume.original_name || `${props.candidateName || props.resume.candidate_name || '候选人'}的原始简历`)
const fileType = computed(() => isImage.value ? '图片简历' : 'PDF 简历')
const pdfPreviewUrl = computed(() => {
  if (!fileAvailable.value || isImage.value) return ''
  return `${String(props.resume.preview_url).split('#')[0]}#toolbar=0&navpanes=0&zoom=${zoom.value}`
})

async function setZoom(nextZoom) {
  const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, nextZoom))
  if (next === zoom.value) return
  const target = viewport.value
  const oldWidth = target?.scrollWidth || 0
  const oldHeight = target?.scrollHeight || 0
  const centerX = target ? (target.scrollLeft + target.clientWidth / 2) / Math.max(1, oldWidth) : 0
  const centerY = target ? (target.scrollTop + target.clientHeight / 2) / Math.max(1, oldHeight) : 0
  zoom.value = next
  await nextTick()
  if (target && isImage.value) {
    target.scrollLeft = Math.max(0, centerX * target.scrollWidth - target.clientWidth / 2)
    target.scrollTop = Math.max(0, centerY * target.scrollHeight - target.clientHeight / 2)
  }
}

function close() {
  emit('close')
}

function onKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  if ((event.ctrlKey || event.metaKey) && ['+', '=', '-', '0'].includes(event.key)) {
    event.preventDefault()
    if (event.key === '0') setZoom(100)
    else setZoom(zoom.value + (event.key === '-' ? -ZOOM_STEP : ZOOM_STEP))
    return
  }
  if (event.key !== 'Tab' || !card.value) return
  const controls = [...card.value.querySelectorAll('button:not(:disabled), a[href], iframe, [tabindex]:not([tabindex="-1"])')]
  if (!controls.length) return
  const first = controls[0]
  const last = controls[controls.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(() => {
  previousBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  window.addEventListener('keydown', onKeydown)
  closeButton.value?.focus()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = previousBodyOverflow
})
</script>

<template>
  <div class="resume-viewer-backdrop" data-test="resume-document-viewer" role="presentation" @click.self="close">
    <section
      ref="card"
      :class="['resume-viewer-card', { 'resume-viewer-card--expanded': expanded }]"
      role="dialog"
      aria-modal="true"
      :aria-label="`${candidateName || resume.candidate_name || '候选人'}的原始简历预览`"
    >
      <header class="resume-viewer-toolbar">
        <div class="resume-viewer-toolbar__identity">
          <AppIcon name="document" :size="20" />
          <div><strong>{{ fileName }}</strong><span>{{ fileType }} · {{ zoom }}%</span></div>
        </div>

        <div class="resume-viewer-toolbar__controls" aria-label="简历预览工具">
          <button data-test="resume-zoom-out" type="button" aria-label="缩小简历" :disabled="zoom <= MIN_ZOOM" @click="setZoom(zoom - ZOOM_STEP)"><AppIcon name="zoom-out" :size="19" /></button>
          <output aria-live="polite" aria-label="当前缩放比例">{{ zoom }}%</output>
          <button data-test="resume-zoom-in" type="button" aria-label="放大简历" :disabled="zoom >= MAX_ZOOM" @click="setZoom(zoom + ZOOM_STEP)"><AppIcon name="zoom-in" :size="19" /></button>
          <button data-test="resume-zoom-reset" type="button" aria-label="恢复实际大小" :disabled="zoom === 100" @click="setZoom(100)"><AppIcon name="reset" :size="18" /></button>
          <span class="resume-viewer-toolbar__separator" aria-hidden="true"></span>
          <button type="button" :aria-label="expanded ? '退出全屏预览' : '展开预览'" @click="expanded = !expanded"><AppIcon :name="expanded ? 'minimize' : 'maximize'" :size="18" /></button>
          <a v-if="resume.download_url" :href="resume.download_url" aria-label="下载原始简历"><AppIcon name="download" :size="18" /></a>
          <button ref="closeButton" type="button" aria-label="关闭原始简历" @click="close"><AppIcon name="close" :size="20" /></button>
        </div>
      </header>

      <div ref="viewport" class="resume-viewer-viewport" data-test="resume-scroll-viewport">
        <div v-if="fileAvailable && isImage" class="resume-viewer-image-stage">
          <img class="resume-viewer-image" :src="resume.preview_url" :alt="`${candidateName || resume.candidate_name || '候选人'}的原始简历`" :style="{ width: `${zoom}%` }" />
        </div>
        <iframe v-else-if="fileAvailable" class="resume-viewer-pdf" :src="pdfPreviewUrl" :title="`${candidateName || resume.candidate_name || '候选人'}的原始简历`"></iframe>
        <div v-else class="resume-viewer-empty" role="status">
          <AppIcon name="document" :size="34" />
          <strong>原始文件暂不可预览</strong>
          <p>文件恢复后即可在此处查看。</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.resume-viewer-backdrop { position: fixed; inset: 0; z-index: 140; display: grid; place-items: center; padding: 18px; background: rgba(26, 38, 46, .62); backdrop-filter: blur(11px); -webkit-backdrop-filter: blur(11px); }
.resume-viewer-card { width: min(1040px, calc(100vw - 36px)); height: calc(100dvh - 36px); max-height: 960px; display: flex; flex-direction: column; overflow: hidden; color: #263549; background: #f6f8f8; border: 1px solid rgba(255, 255, 255, .9); border-radius: 16px; box-shadow: 0 34px 82px rgba(20, 31, 38, .34); animation: resume-viewer-arrive .2s cubic-bezier(.2,.8,.2,1); }
.resume-viewer-card--expanded { width: calc(100vw - 20px); height: calc(100dvh - 20px); max-height: none; border-radius: 12px; }
.resume-viewer-toolbar { min-height: 62px; flex: none; display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 0 14px 0 22px; background: rgba(255, 255, 255, .98); border-bottom: 1px solid #dce3e5; }
.resume-viewer-toolbar__identity { min-width: 0; display: flex; align-items: center; gap: 11px; color: #168b80; }
.resume-viewer-toolbar__identity > div { min-width: 0; display: grid; gap: 2px; }
.resume-viewer-toolbar__identity strong { max-width: 420px; overflow: hidden; color: #28374a; font-size: 14px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.resume-viewer-toolbar__identity span { color: #7a8793; font-size: 11px; }
.resume-viewer-toolbar__controls { flex: none; display: flex; align-items: center; gap: 4px; }
.resume-viewer-toolbar__controls button, .resume-viewer-toolbar__controls a { width: 36px; height: 36px; display: grid; place-items: center; color: #4f5f70; background: transparent; border: 1px solid transparent; border-radius: 9px; cursor: pointer; text-decoration: none; transition: 140ms ease; }
.resume-viewer-toolbar__controls button:hover:not(:disabled), .resume-viewer-toolbar__controls a:hover { color: #117c72; background: #eef7f5; border-color: #d5e8e5; }
.resume-viewer-toolbar__controls button:focus-visible, .resume-viewer-toolbar__controls a:focus-visible { outline: 3px solid rgba(17, 137, 124, .2); outline-offset: 1px; }
.resume-viewer-toolbar__controls button:disabled { color: #b9c1c8; cursor: not-allowed; }
.resume-viewer-toolbar__controls output { min-width: 48px; color: #546273; font-size: 12px; font-variant-numeric: tabular-nums; text-align: center; }
.resume-viewer-toolbar__separator { width: 1px; height: 22px; margin: 0 5px; background: #dfe4e6; }
.resume-viewer-viewport { min-height: 0; flex: 1; overflow: auto; overscroll-behavior: contain; background: #cfd5d8; scrollbar-color: #839096 #e2e6e8; }
.resume-viewer-image-stage { min-width: 100%; min-height: 100%; display: flex; align-items: flex-start; justify-content: flex-start; padding: 26px; }
.resume-viewer-image { max-width: none; height: auto; display: block; margin-inline: auto; background: #fff; box-shadow: 0 10px 30px rgba(22, 32, 38, .18); }
.resume-viewer-pdf { width: 100%; height: 100%; min-height: 620px; display: block; background: #fff; border: 0; }
.resume-viewer-empty { min-height: 100%; display: grid; place-content: center; justify-items: center; gap: 9px; color: #75828d; text-align: center; }
.resume-viewer-empty strong { margin-top: 5px; color: #435262; }
.resume-viewer-empty p { margin: 0; font-size: 12px; }
@keyframes resume-viewer-arrive { from { opacity: 0; transform: translateY(12px) scale(.99); } }
@media (max-width: 720px) {
  .resume-viewer-backdrop { padding: 8px; }
  .resume-viewer-card { width: calc(100vw - 16px); height: calc(100dvh - 16px); border-radius: 12px; }
  .resume-viewer-toolbar { min-height: 58px; padding: 0 8px 0 14px; gap: 8px; }
  .resume-viewer-toolbar__identity span, .resume-viewer-toolbar__controls output, .resume-viewer-toolbar__separator, .resume-viewer-toolbar__controls button[aria-label="恢复实际大小"] { display: none; }
  .resume-viewer-toolbar__identity strong { max-width: 150px; font-size: 12px; }
  .resume-viewer-toolbar__controls { gap: 0; }
  .resume-viewer-toolbar__controls button, .resume-viewer-toolbar__controls a { width: 33px; height: 34px; }
  .resume-viewer-image-stage { padding: 12px; }
}
@media (prefers-reduced-motion: reduce) {
  .resume-viewer-card, .resume-viewer-toolbar__controls button, .resume-viewer-toolbar__controls a { animation: none; transition: none; }
}
</style>
