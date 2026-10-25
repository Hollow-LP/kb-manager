<script setup lang="ts">
import * as Icons from '@element-plus/icons-vue'
import { computed, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

interface MenuItem {
  path: string
  title: string
  icon: string
}

interface MenuGroup {
  title: string | null
  items: MenuItem[]
}

/** 根据当前用户权限过滤菜单；未分组的平铺在前，分组按出现顺序排列 */
const menus = computed<MenuGroup[]>(() => {
  const layout = router.options.routes.find((r) => r.path === '/')!
  const children = (layout.children ?? []).filter(
    (c) =>
      c.meta &&
      !c.meta.hidden &&
      ((c.meta.permissions as string[] | undefined) ?? []).some((p) => store.has(p)),
  )
  const ungrouped: MenuItem[] = []
  const groups = new Map<string, MenuItem[]>()
  for (const c of children) {
    const item = { path: '/' + c.path, title: String(c.meta!.title ?? ''), icon: String(c.meta!.icon ?? 'Menu') }
    const group = c.meta!.group as string | undefined
    if (group) {
      groups.set(group, [...(groups.get(group) ?? []), item])
    } else {
      ungrouped.push(item)
    }
  }
  return [
    { title: null, items: ungrouped },
    ...[...groups.entries()].map(([title, items]) => ({ title, items })),
  ].filter((g) => g.items.length > 0)
})

const iconOf = (name: string): Component =>
  (Icons as unknown as Record<string, Component>)[name] ?? Icons.Menu

const activeMenu = computed(() => route.path)
const displayName = computed(() => store.userInfo?.display_name ?? '')
const departmentName = computed(() => store.userInfo?.department?.name ?? '未分配部门')
const roleNames = computed(() => store.roles.map((r) => r.role_name).join(' / ') || '无角色')

async function onCommand(cmd: string) {
  if (cmd === 'profile') {
    router.push('/profile')
  } else if (cmd === 'logout') {
    await store.logout()
    router.replace({ name: 'Login' })
  }
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="brand">
        <span class="brand-mark">KB</span>
        <span>知识库管理平台</span>
      </div>
      <el-scrollbar>
        <el-menu :default-active="activeMenu" router class="menu">
          <template v-for="(group, gi) in menus" :key="gi">
            <div v-if="group.title" class="group-title">{{ group.title }}</div>
            <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path">
              <el-icon><component :is="iconOf(item.icon)" /></el-icon>
              <span>{{ item.title }}</span>
            </el-menu-item>
          </template>
        </el-menu>
      </el-scrollbar>
    </el-aside>

    <el-container>
      <el-header class="header">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item v-if="route.meta.group">{{ route.meta.group }}</el-breadcrumb-item>
          <el-breadcrumb-item>{{ route.meta.title }}</el-breadcrumb-item>
        </el-breadcrumb>
        <el-dropdown trigger="click" @command="onCommand">
          <div class="user">
            <el-avatar :size="30">{{ displayName.slice(0, 1) }}</el-avatar>
            <div class="user-meta">
              <span class="name">{{ displayName }}</span>
              <span class="sub">{{ departmentName }} · {{ roleNames }}</span>
            </div>
            <el-icon><Icons.ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">个人中心</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="main">
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100%;
}
.aside {
  background: #1f2d3d;
  display: flex;
  flex-direction: column;
}
.brand {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  color: #fff;
  font-weight: 600;
  padding: 0 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.brand-mark {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: var(--el-color-primary);
  font-size: 13px;
}
.menu {
  border-right: none;
  background: transparent;
}
.menu :deep(.el-menu-item) {
  color: #c0ccda;
}
.menu :deep(.el-menu-item.is-active) {
  color: #fff;
  background: var(--el-color-primary);
}
.group-title {
  color: #7b8a9c;
  font-size: 12px;
  padding: 14px 20px 6px;
}
.header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid var(--el-border-color-light);
}
.user {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}
.user-meta .name {
  font-size: 14px;
}
.user-meta .sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.main {
  background: var(--el-bg-color-page);
}
</style>
