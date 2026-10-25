<script setup lang="ts">
defineProps<{
  unitCode: string
  title: string
  score: number
  index: number
}>()
</script>

<template>
  <div class="citation">
    <el-tag size="small" effect="plain" round class="idx">[{{ index }}]</el-tag>
    <span class="title">{{ title }}</span>
    <span class="code">{{ unitCode }}</span>
    <el-tooltip content="检索相似度（0~1，越高越相关）" placement="top">
      <span class="score">{{ Math.round(score * 100) }}%</span>
    </el-tooltip>
  </div>
</template>

<style scoped>
.citation {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 12.5px;
}
.idx {
  color: var(--el-color-primary);
}
.title {
  font-weight: 500;
}
.code {
  color: var(--el-text-color-placeholder);
  font-family: ui-monospace, monospace;
}
.score {
  margin-left: auto;
  color: var(--el-color-success);
}
</style>
