<script setup lang="ts">
import { computed } from 'vue'

import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ content: string; streaming?: boolean }>()
const html = computed(() => renderMarkdown(props.content))
</script>

<template>
  <div class="markdown" :class="{ streaming }" v-html="html" />
</template>

<style scoped>
.markdown {
  line-height: 1.75;
  word-break: break-word;
  font-size: 14px;
}
.markdown :deep(p) {
  margin: 0 0 10px;
}
.markdown :deep(ul),
.markdown :deep(ol) {
  margin: 6px 0 10px;
  padding-left: 22px;
}
.markdown :deep(code) {
  background: var(--el-fill-color-light);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 12.5px;
}
.markdown :deep(pre.hljs) {
  background: #282c34;
  color: #abb2bf;
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
}
.markdown :deep(pre.hljs code) {
  background: transparent;
  padding: 0;
  color: inherit;
}
.markdown :deep(blockquote) {
  border-left: 3px solid var(--el-color-primary-light-5);
  margin: 8px 0;
  padding: 2px 12px;
  color: var(--el-text-color-secondary);
}
.markdown :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
}
.markdown :deep(th),
.markdown :deep(td) {
  border: 1px solid var(--el-border-color);
  padding: 4px 8px;
}
.markdown :deep(a) {
  color: var(--el-color-primary);
}
.streaming :deep(p:last-child)::after {
  content: '▍';
  animation: blink 1s steps(2, start) infinite;
  color: var(--el-color-primary);
}
@keyframes blink {
  to {
    visibility: hidden;
  }
}
</style>
