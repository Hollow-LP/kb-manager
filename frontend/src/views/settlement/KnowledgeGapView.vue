<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import type { ApiError } from '@/api/http'
import {
  apiGapCreateUnit,
  apiGaps,
  apiRunMining,
  apiSetGapStatus,
  type GapItem,
} from '@/api/settlement'

const router = useRouter()
const loading = ref(false)
const running = ref(false)
const list = ref<GapItem[]>([])
const total = ref(0)
const query = reactive({ status: 'unresolved' as string, keyword: '', page: 1, page_size: 10 })

const statusMeta: Record<string, { label: string; type: 'warning' | 'success' | 'info' }> = {
  unresolved: { label: '待处理', type: 'warning' },
  resolved: { label: '已解决', type: 'success' },
  ignored: { label: '已忽略', type: 'info' },
}

async function load() {
  loading.value = true
  try {
    const res = await apiGaps({ status: query.status || undefined, keyword: query.keyword || undefined, page: query.page, page_size: query.page_size })
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

async function runMining() {
  running.value = true
  try {
    const res = await apiRunMining()
    ElMessage.success(`缺口识别完成：新增 ${res.gap.created} 个、归并更新 ${res.gap.updated} 个`)
    await load()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '执行失败')
  } finally {
    running.value = false
  }
}

async function setStatus(row: GapItem, status: GapItem['status']) {
  try {
    if (status === 'ignored') {
      await ElMessageBox.confirm('忽略后该问题不再出现在待处理列表中，确认忽略？', '忽略确认', { type: 'warning' })
    }
    await apiSetGapStatus(row.id, status)
    ElMessage.success('状态已更新')
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error((e as ApiError)?.message || '操作失败')
  }
}

// ------------------------------------------------------------------ 一键建档
const dialog = reactive({ visible: false, gap: null as GapItem | null, mode: 'create' as 'create' })
const form = reactive({ mode: 'create', title: '', category: '知识补全', content: '' })
const submitting = ref(false)

function openCreate(row: GapItem) {
  dialog.gap = row
  Object.assign(form, {
    mode: 'create',
    title: row.question_pattern.slice(0, 60),
    category: '知识补全',
    content: `## 相关知识说明\n\n> 补全问题：${row.question_pattern}\n\n请补充制度依据、适用范围与具体处理方式。\n`,
  })
  dialog.visible = true
}

function generateFromSamples() {
  if (!dialog.gap) return
  const lens = dialog.gap.sample_questions ?? []
  form.content = `## 相关知识说明\n\n常见提问：\n${lens.map((s) => `- ${s}`).join('\n')}\n\n## 回答要点\n\n1. \n2. \n`
}

async function submit() {
  if (!dialog.gap) return
  if (!form.title.trim() || !form.content.trim()) return ElMessage.warning('标题与正文不能为空')
  submitting.value = true
  try {
    const res = await apiGapCreateUnit(dialog.gap.id, { title: form.title, content: form.content, category: form.category || null })
    ElMessage.success(`已创建知识单元 ${res.unit_code}`)
    dialog.visible = false
    await load()
    router.push(`/knowledge/units/${res.unit_id}?edit=1`)
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '创建失败')
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
          <b>知识缺口列表</b>
          <span class="muted ml">AI 检索未命中或置信度过低的提问，按语义聚类并统计频次</span>
        </div>
        <div class="actions">
          <el-button :loading="running" icon="MagicStick" @click="runMining">重新识别缺口</el-button>
          <el-button :loading="loading" icon="Refresh" @click="load">刷新</el-button>
        </div>
      </div>
    </template>

    <div class="toolbar">
      <el-radio-group v-model="query.status" @change="search">
        <el-radio-button value="unresolved">待处理</el-radio-button>
        <el-radio-button value="resolved">已解决</el-radio-button>
        <el-radio-button value="ignored">已忽略</el-radio-button>
        <el-radio-button value="">全部</el-radio-button>
      </el-radio-group>
      <el-input v-model="query.keyword" placeholder="搜索问题" clearable class="w220" @keyup.enter="search" />
      <el-button @click="search">查询</el-button>
    </div>

    <el-table v-loading="loading" :data="list" size="small">
      <el-table-column label="问题" min-width="240">
        <template #default="{ row }">
          <div class="q">{{ row.question_pattern }}</div>
          <div v-if="row.sample_questions?.length" class="muted">样例：{{ row.sample_questions.slice(0, 3).join(' / ') }}</div>
        </template>
      </el-table-column>
      <el-table-column label="提问频次" width="95" align="center">
        <template #default="{ row }"><el-tag type="warning" effect="plain">{{ row.ask_count }}</el-tag></template>
      </el-table-column>
      <el-table-column label="最近提问" width="165">
        <template #default="{ row }">
          {{ row.last_asked_at ? new Date(row.last_asked_at).toLocaleString('zh-CN') : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="statusMeta[row.status]?.type">{{ statusMeta[row.status]?.label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.status === 'unresolved'" v-permission="'settlement:gap:handle'" link type="primary" @click="openCreate(row)">
            一键建档
          </el-button>
          <el-button v-if="row.status === 'unresolved'" v-permission="'settlement:gap:handle'" link type="info" @click="setStatus(row, 'ignored')">
            忽略
          </el-button>
          <el-button v-if="row.status !== 'unresolved'" v-permission="'settlement:gap:handle'" link type="primary" @click="setStatus(row, 'unresolved')">
            重新打开
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !list.length" description="暂无知识缺口" />

    <el-pagination
      v-model:current-page="query.page"
      v-model:page-size="query.page_size"
      :total="total"
      :page-sizes="[10, 20, 50]"
      layout="total, sizes, prev, pager, next"
      class="pager"
      @current-change="load"
      @size-change="search"
    />

    <el-dialog v-model="dialog.visible" :title="`一键建档：${dialog.gap?.question_pattern ?? ''}`" width="720px">
      <el-alert type="info" :closable="false" show-icon class="mb"
                title="创建后自动切分为知识单元并生成向量，缺口标记为已解决；正文建议使用“一、”等标题组织，便于检索。" />
      <el-form label-position="top">
        <el-form-item label="知识标题" required>
          <el-input v-model="form.title" maxlength="255" />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="form.category" class="w220" />
        </el-form-item>
        <el-form-item label="正文" required>
          <div class="gen">
            <el-button size="small" text type="primary" @click="generateFromSamples">插入样例问题模板</el-button>
          </div>
          <el-input v-model="form.content" type="textarea" :rows="14" class="mono" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">创建知识单元</el-button>
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
.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.ml {
  margin-left: 8px;
  font-weight: normal;
}
.mb {
  margin-bottom: 12px;
}
.w220 {
  width: 220px;
}
.q {
  font-weight: 500;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.gen {
  margin-bottom: 4px;
}
.mono :deep(textarea) {
  font-family: ui-monospace, 'Cascadia Code', Consolas, monospace;
  font-size: 13px;
  line-height: 1.7;
}
</style>
