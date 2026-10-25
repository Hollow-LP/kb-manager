import { createRouter, createWebHistory } from 'vue-router'

import { useUserStore } from '@/stores/user'

import { routes } from './routes'

const router = createRouter({ history: createWebHistory(), routes })

// 布局内的子路由：登录后无访问权限时统一跳 403（挂在布局内，保留菜单与顶栏）
router.addRoute({
  path: '/403',
  component: () => import('@/layouts/AppLayout.vue'),
  children: [{ path: '', name: 'Forbidden', component: () => import('@/views/ForbiddenView.vue'), meta: { title: '无访问权限' } }],
})

router.beforeEach(async (to) => {
  const store = useUserStore()
  const isPublic = to.meta.public === true

  if (isPublic) {
    if (to.name === 'Login' && store.isLoggedIn) return { path: '/' }
    return true
  }
  if (!store.isLoggedIn) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  const ok = await store.ensureLoaded()
  if (!ok) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  const required = (to.meta.permissions as string[] | undefined) ?? []
  if (required.length && !store.hasAny(required)) {
    return { name: 'Forbidden' }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} - 知识库管理平台` : '知识库管理平台'
})

export default router
