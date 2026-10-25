<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const title = computed(() => String(route.meta.title ?? '功能'))
</script>

<template>
  <el-card>
    <el-result icon="info" :title="`${title}（建设中）`" sub-title="该模块将在后续里程碑中实现，当前仅保留菜单占位。">
      <template #extra>
        <el-tag type="warning" effect="plain">M3 ~ M7</el-tag>
      </template>
    </el-result>
  </el-card>
</template>
