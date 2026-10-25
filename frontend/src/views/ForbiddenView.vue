<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <el-result icon="warning" title="403 无访问权限" sub-title="当前账号没有该页面所需的权限，请联系管理员分配。">
    <template #extra>
      <el-button type="primary" @click="router.replace('/profile')">返回个人中心</el-button>
    </template>
  </el-result>
</template>
