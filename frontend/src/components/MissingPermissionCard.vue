<script setup lang="ts">
defineProps<{
  message: string | null
  items: Array<{ unit_id: number; unit_code: string; title: string }>
}>()
</script>

<template>
  <el-alert type="warning" :closable="false" show-icon class="missing">
    <template #title>
      部分相关知识无权访问
      <el-tag v-if="items.length" size="small" type="warning" effect="plain" class="count">{{ items.length }} 个单元</el-tag>
    </template>
    <div v-if="message" class="msg">{{ message }}</div>
    <div v-if="items.length" class="items">
      <el-tag v-for="i in items" :key="i.unit_id" size="small" type="info" effect="plain">
        {{ i.title }}（{{ i.unit_code }}）
      </el-tag>
    </div>
  </el-alert>
</template>

<style scoped>
.missing {
  margin: 10px 0;
}
.count {
  margin-left: 6px;
}
.msg {
  line-height: 1.6;
}
.items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
</style>
