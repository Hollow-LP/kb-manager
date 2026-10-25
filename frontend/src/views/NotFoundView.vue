<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <el-result icon="error" title="404 页面不存在" sub-title="请检查地址是否正确。">
    <template #extra>
      <el-button type="primary" @click="router.replace('/')">回到首页</el-button>
    </template>
  </el-result>
</template>
