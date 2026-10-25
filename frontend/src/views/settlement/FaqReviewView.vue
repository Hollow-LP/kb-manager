<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import type { ApiError } from '@/api/http'
import { apiFaqRecommendations, apiMiningStatus, apiReviewFaq, apiRunMining, type FaqItem } from '@/api/settlement'

const loading = ref(false)
const running = ref(false)
const list = ref<FaqItem[]>([])
const total = ref(0)
const page = reactive({ page: 1, page_size: 10 })
const miningStatus = ref<{ running: boolean; next_run: string | null } | null>(null)

async function load() {
  loading.value = true
  try {
    const res = await apiFaqRecommendations(page.page, page.page_size)
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadStatus() {
  miningStatus.value = await apiMiningStatus().catch(() => null)
}

async function runMining() {
  running.value = true
  try {
    const res = await apiRunMining()
    ElMessage.success(
      `挖掘完成：生成 ${res.faq.created} 条候选、更新 ${res.faq.updated} 条；更新知识缺口 ${res.gap.created} 个`,
    )
    await Promise.all([load(), loadStatus()])
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '挖掘失败')
  } finally {
    running.value = false
  }
}

// ------------------------------------------------------------------ 审核
const dialog = reactive({ visible: false, mode: 'approve' as 'approve' | 'reject', item: null as FaqItem | null })
const form = reactive({ answer: '', note: '' })
const submitting = ref(false)

function openReview(item: FaqItem, mode: 'approve' | 'reject') {
  dialog.item = item
  dialog.mode = mode
  form.answer = item.answer
  form.note = ''
  dialog.visible = true
}

async function submitReview() {
  if (!dialog.item) return
  if (dialog.mode === 'approve' && !form.answer.trim()) return ElMessage.warning('答案不能为空')
  submitting.value = true
  try {
    const edited = form.answer.trim() !== dialog.item.answer ? form.answer : undefined
    await apiReviewFaq(dialog.item.id, dialog.mode, edited, form.note || undefined)
    ElMessage.success(dialog.mode === 'approve' ? '已发布并写入缓存' : '已驳回')
    dialog.visible = false
    await load()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '操作失败')
  } finally {
    submitting.value = false
  }
}

const answerChanged = () => dialog.item !== null && form.answer.trim() !== dialog.item.answer

onMounted(async () => {
  await Promise.all([load(), loadStatus()])
})
</script>

<template>
  <el-card>
    <template #header>
      <div class="head">
        <div>
          <b>FAQ 自动推荐与审核</b>
          <span class="muted ml">
            系统从历史问答中挖掘高频相似问题（阈值见 FAQ_MINE_THRESHOLD），审核通过后发布并写入缓存
          </span>
        </div>
        <div class="actions">
          <span v-if="miningStatus" class="muted">
            定时挖掘：{{ miningStatus.running ? '运行中' : '未启用' }}
            <template v-if="miningStatus.next_run">· 下次 {{ new Date(miningStatus.next_run).toLocaleString('zh-CN') }}</template>
          </span>
          <el-button :loading="running" icon="MagicStick" @click="runMining">立即挖掘</el-button>
          <el-button :loading="loading" icon="Refresh" @click="load">刷新</el-button>
        </div>
      </div>
    </template>

    <el-alert type="info" :closable="false" show-icon class="mb"
              title="审核时可编辑标准化答案；通过后立即发布并写入高速缓存，用户再次提出相同问题将直接返回标准答案（不调用模型）。" />

    <el-table v-loading="loading" :data="list" size="small">
      <el-table-column label="推荐问题" min-width="220">
        <template #default="{ row }">
          <div class="q">{{ row.question }}</div>
          <div class="muted">{{ row.review_note }}</div>
        </template>
      </el-table-column>
      <el-table-column label="推荐频次" width="90" align="center">
        <template #default="{ row }"><el-tag type="warning" effect="plain">{{ row.hit_count }}</el-tag></template>
      </el-table-column>
      <el-table-column label="关联知识单元" min-width="160">
        <template #default="{ row }">
          <span v-if="row.related_unit_title">{{ row.related_unit_title }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="建议答案" min-width="280">
        <template #default="{ row }">
          <div class="answer">{{ row.answer }}</div>
        </template>
      </el-table-column>
      <el-table-column label="生成时间" width="150">
        <template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button v-permission="'settlement:faq:review'" link type="primary" @click="openReview(row, 'approve')">通过</el-button>
          <el-button v-permission="'settlement:faq:review'" link type="danger" @click="openReview(row, 'reject')">驳回</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !list.length" description="暂无待审核推荐，可点击「立即挖掘」从历史问答中生成" />

    <el-pagination
      v-model:current-page="page.page"
      v-model:page-size="page.page_size"
      :total="total"
      :page-sizes="[10, 20, 50]"
      layout="total, sizes, prev, pager, next"
      class="pager"
      @current-change="load"
      @size-change="load"
    />

    <el-dialog v-model="dialog.visible" :title="dialog.mode === 'approve' ? '审核通过并发布' : '驳回推荐'" width="640px">
      <div v-if="dialog.item" class="dlg">
        <div class="dlg-label">问题</div>
        <div class="dlg-q">{{ dialog.item.question }}</div>
        <template v-if="dialog.mode === 'approve'">
          <div class="dlg-label">标准化答案（可编辑）</div>
          <el-input v-model="form.answer" type="textarea" :rows="8" placeholder="请确认或改写标准答案" />
          <div v-if="answerChanged()" class="muted mt">答案已修改，发布后将标记为「人工编辑」。</div>
          <div class="dlg-label mt">审核备注（可选）</div>
          <el-input v-model="form.note" placeholder="例如：已按公司最新制度修订" />
        </template>
        <template v-else>
          <div class="dlg-label">驳回原因</div>
          <el-input v-model="form.note" type="textarea" :rows="3" placeholder="例如：答案不准确 / 问题不够典型" />
        </template>
      </div>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button :type="dialog.mode === 'approve' ? 'primary' : 'danger'" :loading="submitting" @click="submitReview">
          {{ dialog.mode === 'approve' ? '确认发布' : '确认驳回' }}
        </el-button>
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
  align-items: center;
  gap: 8px;
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
.mt {
  margin-top: 8px;
}
.q {
  font-weight: 500;
  margin-bottom: 2px;
}
.answer {
  white-space: pre-wrap;
  color: var(--el-text-color-regular);
  max-height: 80px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.dlg-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}
.dlg-q {
  font-weight: 600;
  margin-bottom: 12px;
}
</style>
