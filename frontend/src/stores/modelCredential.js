import { defineStore } from 'pinia'
import { api, listItems } from '@/api'

const emptyConfig = () => ({ api_url: '', model: '', has_api_key: false, key_last4: '' })

function replaceById(items, value) {
  const index = items.findIndex((item) => String(item.id) === String(value.id))
  if (index === -1) return [...items, value]
  const next = [...items]
  next[index] = value
  return next
}

function isUncertainMutationError(error) {
  return !Number.isInteger(error?.status) || error.status >= 500
}

function sameText(left, right) {
  return String(left ?? '').trim() === String(right ?? '').trim()
}

function sameUrl(left, right) {
  try {
    const normalize = (value) => {
      const parsed = new URL(String(value ?? '').trim())
      parsed.pathname = parsed.pathname.replace(/\/+$/, '')
      return parsed.toString().replace(/\/$/, '')
    }
    return normalize(left) === normalize(right)
  } catch {
    return sameText(left, right)
  }
}

function uncertainResultError(action) {
  const error = new Error(`${action}结果待确认，请刷新模型列表后再继续`)
  error.code = 'model_state_uncertain'
  return error
}

export const useModelCredentialStore = defineStore('modelCredential', {
  state: () => ({
    config: emptyConfig(),
    profiles: [],
    connection: { status: 'unknown', model: '', latency_ms: null, detail: '' },
    loading: false,
    saving: false,
    switchingId: null,
    deletingId: null,
    testingId: null,
    error: '',
    testing: false,
    generation: 0,
    profileRevision: 0,
    loadSequence: 0,
    activeStateUncertain: false,
  }),
  getters: {
    activeProfile: (state) => state.profiles.find((profile) => profile.is_active) || null,
  },
  actions: {
    reset() {
      this.generation += 1
      this.profileRevision += 1
      this.loadSequence += 1
      this.config = emptyConfig()
      this.profiles = []
      this.connection = { status: 'unknown', model: '', latency_ms: null, detail: '' }
      this.loading = false
      this.saving = false
      this.switchingId = null
      this.deletingId = null
      this.testingId = null
      this.testing = false
      this.error = ''
      this.activeStateUncertain = false
    },
    syncConfigFromProfiles() {
      const active = this.profiles.find((profile) => profile.is_active)
      this.config = active ? {
        api_url: active.api_url,
        model: active.model,
        has_api_key: active.has_api_key,
        key_last4: active.key_last4,
      } : emptyConfig()
    },
    async load() {
      const generation = this.generation
      this.loading = true
      try {
        const config = await api('account/model-credential/')
        if (generation === this.generation) this.config = config
      } finally {
        if (generation === this.generation) this.loading = false
      }
    },
    async loadProfiles() {
      const generation = this.generation
      const revision = this.profileRevision
      const loadSequence = ++this.loadSequence
      this.loading = true
      this.error = ''
      try {
        const payload = await api('account/model-profiles/')
        if (generation !== this.generation || revision !== this.profileRevision || loadSequence !== this.loadSequence) return this.profiles
        this.profiles = listItems(payload)
        this.syncConfigFromProfiles()
        this.activeStateUncertain = false
        return this.profiles
      } catch (error) {
        if (generation !== this.generation || revision !== this.profileRevision || loadSequence !== this.loadSequence) return this.profiles
        this.error = error.message || '模型列表加载失败'
        throw error
      } finally {
        if (generation === this.generation && loadSequence === this.loadSequence) this.loading = false
      }
    },
    async createProfile(payload) {
      const generation = this.generation
      const existingIds = new Set(this.profiles.map((profile) => String(profile.id)))
      this.profileRevision += 1
      this.saving = true
      this.error = ''
      try {
        const profile = await api('account/model-profiles/', { method: 'POST', body: JSON.stringify(payload) })
        if (generation !== this.generation) return profile
        this.profileRevision += 1
        if (profile.is_active) this.profiles = this.profiles.map((item) => ({ ...item, is_active: false }))
        this.profiles = replaceById(this.profiles, profile)
        this.syncConfigFromProfiles()
        this.activeStateUncertain = false
        return profile
      } catch (error) {
        if (generation !== this.generation) throw error
        if (isUncertainMutationError(error)) {
          try {
            const profiles = await this.reconcileProfiles(generation)
            if (profiles === null) throw error
            const created = profiles.find((profile) => (
              !existingIds.has(String(profile.id))
              && sameText(profile.name, payload.name)
              && sameUrl(profile.api_url, payload.api_url)
              && sameText(profile.model, payload.model)
              && (!payload.make_active || profile.is_active)
            ))
            if (created) return created
          } catch {
            if (generation !== this.generation) throw error
            const uncertain = uncertainResultError('模型保存')
            this.error = uncertain.message
            this.activeStateUncertain = Boolean(payload.make_active)
            throw uncertain
          }
        }
        this.error = error.message || '模型保存失败'
        throw error
      } finally {
        if (generation === this.generation) this.saving = false
      }
    },
    async updateProfile(id, payload) {
      const generation = this.generation
      const wasActive = Boolean(this.profiles.find((profile) => String(profile.id) === String(id))?.is_active)
      this.profileRevision += 1
      this.saving = true
      this.error = ''
      try {
        const profile = await api(`account/model-profiles/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) })
        if (generation !== this.generation) return profile
        this.profileRevision += 1
        this.profiles = replaceById(this.profiles, profile)
        this.syncConfigFromProfiles()
        this.activeStateUncertain = false
        return profile
      } catch (error) {
        if (generation !== this.generation) throw error
        if (isUncertainMutationError(error)) {
          try {
            const profiles = await this.reconcileProfiles(generation)
            if (profiles === null) throw error
            const updated = profiles.find((profile) => String(profile.id) === String(id))
            const apiKeyMatches = !payload.api_key || (
              updated?.has_api_key && String(updated.key_last4) === String(payload.api_key).slice(-4)
            )
            const fieldsMatch = updated
              && (!Object.hasOwn(payload, 'name') || sameText(updated.name, payload.name))
              && (!Object.hasOwn(payload, 'api_url') || sameUrl(updated.api_url, payload.api_url))
              && (!Object.hasOwn(payload, 'model') || sameText(updated.model, payload.model))
              && apiKeyMatches
            if (fieldsMatch) return updated
          } catch {
            if (generation !== this.generation) throw error
            const uncertain = uncertainResultError('模型保存')
            this.error = uncertain.message
            this.activeStateUncertain = wasActive
            throw uncertain
          }
        }
        this.error = error.message || '模型保存失败'
        throw error
      } finally {
        if (generation === this.generation) this.saving = false
      }
    },
    async activateProfile(id) {
      if (this.switchingId) return null
      this.switchingId = id
      this.error = ''
      const generation = this.generation
      this.profileRevision += 1
      try {
        const profile = await api(`account/model-profiles/${id}/activate/`, { method: 'POST' })
        if (generation !== this.generation) return profile
        this.profileRevision += 1
        this.profiles = this.profiles.map((item) => ({ ...item, is_active: String(item.id) === String(profile.id) }))
        this.profiles = replaceById(this.profiles, profile)
        this.syncConfigFromProfiles()
        this.connection = { status: 'unknown', model: profile.model, latency_ms: null, detail: '' }
        this.activeStateUncertain = false
        return profile
      } catch (error) {
        if (generation !== this.generation) throw error
        if (isUncertainMutationError(error)) {
          try {
            const profiles = await this.reconcileProfiles(generation)
            if (profiles === null) throw error
            const selected = profiles.find((profile) => String(profile.id) === String(id) && profile.is_active)
            if (selected) return selected
          } catch {
            if (generation !== this.generation) throw error
            const uncertain = uncertainResultError('模型切换')
            this.error = uncertain.message
            this.activeStateUncertain = true
            throw uncertain
          }
        }
        this.error = error.message || '模型切换失败'
        throw error
      } finally {
        if (generation === this.generation) this.switchingId = null
      }
    },
    async deleteProfile(id) {
      if (this.deletingId) return null
      const generation = this.generation
      const target = this.profiles.find((profile) => String(profile.id) === String(id))
      const wasActive = Boolean(target?.is_active)
      this.deletingId = id
      this.profileRevision += 1
      this.error = ''
      try {
        await api(`account/model-profiles/${id}/`, { method: 'DELETE' })
        if (generation !== this.generation) return { deleted: true, wasActive }
        this.profileRevision += 1
        this.profiles = this.profiles.filter((profile) => String(profile.id) !== String(id))
        this.syncConfigFromProfiles()
        if (wasActive) this.connection = { status: 'unknown', model: '', latency_ms: null, detail: '' }
        this.activeStateUncertain = false
        return { deleted: true, wasActive }
      } catch (error) {
        if (generation !== this.generation) throw error
        if (isUncertainMutationError(error)) {
          try {
            const profiles = await this.reconcileProfiles(generation)
            if (profiles === null) throw error
            if (!profiles.some((profile) => String(profile.id) === String(id))) {
              if (wasActive) this.connection = { status: 'unknown', model: '', latency_ms: null, detail: '' }
              return { deleted: true, wasActive }
            }
          } catch {
            if (generation !== this.generation) throw error
            const uncertain = uncertainResultError('模型删除')
            this.error = uncertain.message
            this.activeStateUncertain = wasActive
            throw uncertain
          }
        }
        this.error = error.message || '模型删除失败'
        throw error
      } finally {
        if (generation === this.generation) this.deletingId = null
      }
    },
    async testProfile(id) {
      this.testingId = id
      this.error = ''
      const profile = this.profiles.find((item) => String(item.id) === String(id))
      const generation = this.generation
      this.connection = { status: 'testing', model: profile?.model || '', latency_ms: null, detail: '正在验证模型连接…' }
      try {
        const result = await api(`account/model-profiles/${id}/test/`, { method: 'POST' })
        if (generation !== this.generation) return result
        this.connection = {
          status: 'success',
          model: result.model || profile?.model || '',
          latency_ms: result.latency_ms ?? null,
          detail: result.detail || '连接成功',
        }
        return result
      } catch (error) {
        if (generation !== this.generation) throw error
        this.connection = { status: 'error', model: profile?.model || '', latency_ms: null, detail: error.message || '连接失败' }
        throw error
      } finally {
        if (generation === this.generation) this.testingId = null
      }
    },
    async reconcileProfiles(generation = this.generation) {
      const payload = await api('account/model-profiles/')
      if (generation !== this.generation) return null
      this.profileRevision += 1
      this.loadSequence += 1
      this.profiles = listItems(payload)
      this.syncConfigFromProfiles()
      this.activeStateUncertain = false
      this.error = ''
      return this.profiles
    },
    async save(payload) {
      const generation = this.generation
      this.profileRevision += 1
      const config = await api('account/model-credential/', { method: 'PUT', body: JSON.stringify(payload) })
      if (generation === this.generation) {
        this.profileRevision += 1
        this.config = config
        this.activeStateUncertain = false
        this.connection = { status: 'unknown', model: '', latency_ms: null, detail: '' }
      }
    },
    async clear() {
      const generation = this.generation
      this.profileRevision += 1
      await api('account/model-credential/', { method: 'DELETE' })
      if (generation !== this.generation) return
      this.profileRevision += 1
      this.config = emptyConfig()
      this.profiles = this.profiles.filter((profile) => !profile.is_active)
      this.activeStateUncertain = false
      this.connection = { status: 'unknown', model: '', latency_ms: null, detail: '' }
    },
    async testConnection() {
      const generation = this.generation
      this.testing = true
      this.connection = { status: 'testing', model: this.config.model || '', latency_ms: null, detail: '正在验证模型连接…' }
      try {
        const result = await api('account/model-credential/test/', { method: 'POST' })
        if (generation !== this.generation) return result
        this.connection = {
          status: 'success',
          model: result.model || this.config.model || '',
          latency_ms: result.latency_ms ?? null,
          detail: result.detail || '连接成功',
        }
        return result
      } catch (error) {
        if (generation !== this.generation) throw error
        this.connection = { status: 'error', model: this.config.model || '', latency_ms: null, detail: error.message || '连接失败' }
        throw error
      } finally {
        if (generation === this.generation) this.testing = false
      }
    },
  },
})
