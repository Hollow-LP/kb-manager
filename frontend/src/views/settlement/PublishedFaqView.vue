<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import type { ApiError } from '@/api/http'
import {
  apiCreateFaq,
  apiFaqCacheStats,
  apiFaqList,
  apiUnpublishFaq,
  apiUpdateFaq,
  type FaqItem,
} from '@/api/settlement'

const loading = ref(false)
const list = ref<FaqItem[]>([])
const total = ref(0)
const page = reactive({ page: 1, page_size: 10 })
const keyword = ref('')
const cache = ref<{ cached: number; exact_keys: number; redis: string } | null>(null)

async function load() {
  loading.value = true
  try {
    const res = await apiFaqList({ status: 'published', keyword: keyword.value || undefined, page: page.page, page_size: page.page_size })
    list.value = res.items
    total.value = res.total
    cache.value = await apiFaqCacheStats().catch(() => null)
  } finally {
    loading.value = false
  }
}

function search() {
  page.page = 1
  load()
}

async function unpublish(row: FaqItem) {
  try {
    await ElMessageBox.confirm(`下架后该问题将不再走缓存，用户提问会重新经过知识库检索。确认下架？`, '下架确认', { type: 'warning' })
  } catch {
    return
  }
  await apiUnpublishFaq(row.id)
  ElMessage.success('已下架并移出缓存')
  await load()
}

// ------------------------------------------------------------------ 编辑 / 新建
const dialog = reactive({ visible: false, mode: 'edit' as 'edit' | 'create', item: null as FaqItem | null })
const form = reactive({ question: '', answer: '', category: '', publish: true })
const submitting = ref(false)

function openEdit(row: FaqItem) {
  dialog.mode = 'edit'
  dialog.item = row
  Object.assign(form, { question: row.question, answer: row.answer, category: row.category ?? '', publish: true })
  dialog.visible = true
}

function openCreate() {
  dialog.mode = 'create'
  dialog.item = null
  Object.assign(form, { question: '', answer: '', category: '', publish: true })
  dialog.visible = true
}

async function submit() {
  if (!form.question.trim() || !form.answer.trim()) return ElMessage.warning('问题与答案不能为空')
  submitting.value = true
  try {
    if (dialog.mode === 'edit' && dialog.item) {
      await apiUpdateFaq(dialog.item.id, { question: form.question, answer: form.answer, category: form.category || null })
      ElMessage.success('已保存，缓存已同步')
    } else {
      await apiCreateFaq({ question: form.question, answer: form.answer, category: form.category || null, publish: form.publish })
      ElMessage.success(form.publish ? '已创建并发布' : '已创建，等待审核')
    }
    dialog.visible = false
    await load()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <el-card>
    <template #header>
      <div class="head">
        <div>
          <b>已发布 FAQ 库</b>
          <el-tag v-if="cache" size="small" :type="cache.redis === 'ok' ? 'success' : 'danger'" class="ml">
            缓存 {{ cache.redis === 'ok' ? '正常' : '异常' }} · 已缓存 {{ cache.cached }} 条
          </el-tag>
        </div>
        <div class="actions">
          <el-input v-model="keyword" placeholder="搜索问题 / 答案" clearable class="w220" @keyup.enter="search" />
          <el-button @click="search">查询</el-button>
          <el-button v-permission="'settlement:faq:manage'" type="primary" icon="Plus" @click="openCreate">新建 FAQ</el-button>
        </div>
      </div>
    </template>

    <el-table v-loading="loading" :data="list" size="small">
      <el-table-column label="问题" min-width="220">
        <template #default="{ row }"><div class="q">{{ row.question }}</div></template>
      </el-table-column>
      <el-table-column label="标准答案" min-width="300">
        <template #default="{ row }"><div class="answer">{{ row.answer }}</div></template>
      </el-table-column>
      <el-table-column label="分类" width="100">
        <template #default="{ row }">{{ row.category ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="来源" width="96">
        <template #default="{ row }">
          <el-tag size="small" :type="row.source_type === 'auto_mined' ? 'warning' : 'info'" effect="plain">
            {{ row.source_type === 'auto_mined' ? '自动挖掘' : '手工创建' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="缓存" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.cached ? 'success' : 'info'">{{ row.cached ? '已缓存' : '未缓存' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="hit_count" label="命中次数" width="90" align="center" />
      <el-table-column label="发布时间" width="150">
        <template #default="{ row }">
          {{ row.published_at ? new Date(row.published_at).toLocaleString('zh-CN') : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button v-permission="'settlement:faq:manage'" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-permission="'settlement:faq:manage'" link type="danger" @click="unpublish(row)">下架</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !list.length" description="暂无已发布 FAQ" />

    <el-pagination
      v-model:current-page="page.page"
      v-model:page-size="page.page_size"
      :total="total"
      :page-sizes="[10, 20, 50]"
      layout="total, sizes, prev, pager, next"
      class="pager"
      @current-change="load"
      @size-change="search"
    />

    <el-dialog v-model="dialog.visible" :title="dialog.mode === 'edit' ? '编辑 FAQ' : '新建 FAQ'" width="640px">
      <el-form label-position="top">
        <el-form-item label="问题" required>
          <el-input v-model="form.question" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="标准答案" required>
          <el-input v-model="form.answer" type="textarea" :rows="7" maxlength="5000" show-word-limit />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="form.category" placeholder="可选，例如：人事制度" />
        </el-form-item>
        <el-form-item v-if="dialog.mode === 'create'">
          <el-checkbox v-model="form.publish">创建后直接发布（写入缓存）</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.actions {
  display: flex;
  gap: 8px;
}
.ml {
  margin-left: 8px;
}
.w220 {
  width: 220px;
}
.q {
  font-weight: 500;
}
.answer {
  white-space: pre-wrap;
  color: var(--el-text-color-regular);
  max-height: 72px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
