import { defineStore } from 'pinia'
import { api, ensureCsrf } from '@/api'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    loading: true,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.user),
    canManage: (state) => ['admin', 'hr'].includes(state.user?.role),
  },
  actions: {
    async restore() {
      try {
        this.user = await api('auth/me/')
      } catch {
        this.user = null
      } finally {
        this.loading = false
      }
    },
    async login(username, password) {
      await ensureCsrf()
      this.user = await api('auth/login/', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      return this.user
    },
    async logout() {
      await api('auth/logout/', { method: 'POST' })
      this.user = null
    },
  },
})

