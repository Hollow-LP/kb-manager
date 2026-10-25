<script setup lang="ts">
import { computed } from 'vue'

import { useUserStore } from '@/stores/user'

const store = useUserStore()
const info = computed(() => store.userInfo)
</script>

<template>
  <el-card v-if="info">
    <template #header>
      <div class="head">
        <el-avatar :size="44">{{ info.display_name.slice(0, 1) }}</el-avatar>
        <div>
          <div class="name">{{ info.display_name }}</div>
          <div class="sub">@{{ info.username }}</div>
        </div>
        <el-tag :type="info.status === 'active' ? 'success' : 'info'" class="status">
          {{ info.status === 'active' ? '正常' : '已停用' }}
        </el-tag>
      </div>
    </template>
    <el-descriptions :column="2" border>
      <el-descriptions-item label="所属部门">{{ info.department?.name ?? '未分配' }}</el-descriptions-item>
      <el-descriptions-item label="拥有角色">
        <el-tag v-for="r in info.roles" :key="r.id" size="small" class="tag">{{ r.role_name }}</el-tag>
        <span v-if="!info.roles.length">无</span>
      </el-descriptions-item>
    </el-descriptions>

    <h3 class="section">我的操作权限（{{ store.permissions.length }} 项）</h3>
    <div class="perms">
      <el-tag v-for="p in store.permissions" :key="p" type="info" effect="plain">{{ p }}</el-tag>
    </div>
  </el-card>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.name {
  font-size: 18px;
  font-weight: 600;
}
.sub {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.status {
  margin-left: auto;
}
.section {
  margin: 24px 0 12px;
  font-size: 15px;
}
.perms {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.tag {
  margin-right: 6px;
}
</style>
