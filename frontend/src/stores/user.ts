import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { apiLogin, apiLogout, apiMe, type UserInfo } from '@/api/auth'
import { TOKEN_KEY } from '@/api/http'

export const useUserStore = defineStore('user', () => {
  const token = ref<string>(localStorage.getItem(TOKEN_KEY) || '')
  const userInfo = ref<UserInfo | null>(null)
  const permissions = ref<string[]>([])
  const loaded = ref(false)
  const roles = computed(() => userInfo.value?.roles ?? [])
  const isLoggedIn = computed(() => !!token.value)

  function setSession(accessToken: string, info: UserInfo, perms: string[]) {
    token.value = accessToken
    userInfo.value = info
    permissions.value = perms
    loaded.value = true
    localStorage.setItem(TOKEN_KEY, accessToken)
  }

  async function login(username: string, password: string) {
    const res = await apiLogin(username, password)
    setSession(res.access_token, res.user_info, res.permissions)
  }

  /** 刷新页面后按 token 拉取用户信息 */
  async function ensureLoaded() {
    if (!token.value) return false
    if (loaded.value) return true
    try {
      const res = await apiMe()
      userInfo.value = res.user_info
      permissions.value = res.permissions
      loaded.value = true
      return true
    } catch {
      reset()
      return false
    }
  }

  function reset() {
    token.value = ''
    userInfo.value = null
    permissions.value = []
    loaded.value = false
    localStorage.removeItem(TOKEN_KEY)
  }

  async function logout() {
    try {
      if (token.value) await apiLogout()
    } finally {
      reset()
    }
  }

  function has(perm: string) {
    return permissions.value.includes(perm)
  }

  function hasAny(perms: string[]) {
    return perms.some((p) => permissions.value.includes(p))
  }

  return { token, userInfo, permissions, roles, isLoggedIn, loaded, login, ensureLoaded, logout, reset, has, hasAny }
})
