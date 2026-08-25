import { defineStore } from 'pinia'
import { api, listItems } from '@/api'

const storagePrefix = 'ximing-hr:recruitment-job:'
const normalizeId = (value) => (value === null || value === undefined || value === '' ? '' : String(value))
const storageKey = (userId) => `${storagePrefix}${userId}`

export const useRecruitmentContextStore = defineStore('recruitmentContext', {
  state: () => ({
    jobs: [],
    selectedJobId: '',
    loading: false,
    loaded: false,
    loadedUserId: '',
    error: '',
    invalidationReason: '',
    requestSequence: 0,
  }),
  getters: {
    currentJob: (state) => state.jobs.find((job) => String(job.id) === state.selectedJobId) || null,
    hasJobs: (state) => state.jobs.length > 0,
  },
  actions: {
    restoreSelection(userId) {
      const normalizedUserId = normalizeId(userId)
      if (!normalizedUserId) return false
      const remembered = normalizeId(localStorage.getItem(storageKey(normalizedUserId)))
      if (!remembered) return false
      const exists = this.jobs.some((job) => String(job.id) === remembered)
      if (!exists) {
        localStorage.removeItem(storageKey(normalizedUserId))
        this.selectedJobId = ''
        this.invalidationReason = '上次选择的职位已关闭、不再开放或无权访问，请重新选择'
        return false
      }
      this.selectedJobId = remembered
      this.invalidationReason = ''
      return true
    },
    selectJob(jobId, { userId } = {}) {
      const normalizedUserId = normalizeId(userId || this.loadedUserId)
      const normalizedJobId = normalizeId(jobId)
      if (!normalizedUserId || !this.jobs.some((job) => String(job.id) === normalizedJobId)) return false
      this.selectedJobId = normalizedJobId
      this.invalidationReason = ''
      localStorage.setItem(storageKey(normalizedUserId), normalizedJobId)
      return true
    },
    invalidateSelection({ userId, reason = '当前职位已关闭、不再开放或无权访问，请重新选择' } = {}) {
      const normalizedUserId = normalizeId(userId || this.loadedUserId)
      if (normalizedUserId) localStorage.removeItem(storageKey(normalizedUserId))
      this.selectedJobId = ''
      this.invalidationReason = reason
    },
    async loadJobs({ userId, force = false } = {}) {
      const normalizedUserId = normalizeId(userId)
      if (!normalizedUserId) {
        this.reset()
        return []
      }
      if (!force && this.loaded && this.loadedUserId === normalizedUserId) return this.jobs

      const sequence = ++this.requestSequence
      const previousUserId = this.loadedUserId
      this.loading = true
      this.error = ''
      try {
        const payload = await api('recruitment/jobs/?status=open')
        if (sequence !== this.requestSequence) return this.jobs

        const previousSelection = previousUserId === normalizedUserId ? this.selectedJobId : ''
        this.jobs = listItems(payload)
        this.loaded = true
        this.loadedUserId = normalizedUserId
        this.selectedJobId = ''

        const candidate = previousSelection || normalizeId(localStorage.getItem(storageKey(normalizedUserId)))
        if (candidate && this.jobs.some((job) => String(job.id) === candidate)) {
          this.selectedJobId = candidate
          this.invalidationReason = ''
        } else if (candidate) {
          localStorage.removeItem(storageKey(normalizedUserId))
          this.invalidationReason = '上次选择的职位已关闭、不再开放或无权访问，请重新选择'
        } else {
          this.invalidationReason = ''
        }
        return this.jobs
      } catch (error) {
        if (sequence === this.requestSequence) this.error = error.message || '职位列表加载失败'
        throw error
      } finally {
        if (sequence === this.requestSequence) this.loading = false
      }
    },
    reset() {
      this.requestSequence += 1
      this.jobs = []
      this.selectedJobId = ''
      this.loading = false
      this.loaded = false
      this.loadedUserId = ''
      this.error = ''
      this.invalidationReason = ''
    },
  },
})
