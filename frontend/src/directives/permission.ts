import type { App } from 'vue'

import { useUserStore } from '@/stores/user'

/**
 * 按钮级操作权限：v-permission="'org:user:create'" 或 v-permission="['a','b']"（任一即可）。
 * 无权限时直接移除元素。仅用于展示控制，后端仍会二次校验。
 */
export function setupPermissionDirective(app: App) {
  app.directive('permission', {
    mounted(el: HTMLElement, binding) {
      const required: string[] = Array.isArray(binding.value) ? binding.value : [binding.value]
      const store = useUserStore()
      if (!store.hasAny(required)) {
        el.parentNode?.removeChild(el)
      }
    },
  })
}
