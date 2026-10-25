<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import type { ApiError } from '@/api/http'
import { apiImport, apiImportJobs, apiRetryImport, type ImportJobItem } from '@/api/knowledge'
import { fileTypeLabel, formatSize } from '@/utils/knowledge'

const router = useRouter()
const ACCEPT = '.pdf,.docx,.md,.markdown,.txt'
const MAX_SIZE_MB = 50

const files = ref<File[]>([])
const uploading = ref(false)
const uploadPercent = ref(0)
const batchId = ref('')
const jobs = ref<ImportJobItem[]>([])
const history = ref<ImportJobItem[]>([])
const polling = ref(false)
const dragActive = ref(false)
let timer: number | undefined

const canImport = computed(() => files.value.length > 0 && !uploading.value)
const summary = reactive({ success: 0, failed: 0, running: 0 })

function addFiles(incoming: File[]) {
  const known = new Set(files.value.map((f) => `${f.name}-${f.size}`))
  const rejected: string[] = []
  for (const f of incoming) {
    if (!ACCEPT.split(',').some((ext) => f.name.toLowerCase().endsWith(ext))) {
      rejected.push(`${f.name}（格式不支持）`)
      continue
    }
    if (f.size > MAX_SIZE_MB * 1024 * 1024) {
      rejected.push(`${f.name}（超过 ${MAX_SIZE_MB}MB）`)
      continue
    }
    const key = `${f.name}-${f.size}`
    if (!known.has(key)) {
      files.value.push(f)
      known.add(key)
    }
  }
  if (rejected.length) ElMessage.warning(`已忽略：${rejected.join('；')}`)
}

/** 拖拽：同时支持文件夹（递归读取）与多文件 */
async function onDrop(e: DragEvent) {
  dragActive.value = false
  const items = e.dataTransfer?.items
  if (!items) return
  const entries: FileSystemEntry[] = []
  for (const item of Array.from(items)) {
    const entry = item.webkitGetAsEntry?.()
    if (entry) entries.push(entry)
  }
  if (!entries.length) {
    addFiles(Array.from(e.dataTransfer?.files ?? []))
    return
  }
  const collected: File[] = []
  for (const entry of entries) await walkEntry(entry, collected)
  addFiles(collected)
}

function walkEntry(entry: FileSystemEntry, out: File[]): Promise<void> {
  return new Promise((resolve) => {
    if (entry.isFile) {
      ;(entry as FileSystemFileEntry).file((f) => {
        out.push(f)
        resolve()
      }, () => resolve())
      return
    }
    const reader = (entry as FileSystemDirectoryEntry).createReader()
    const readBatch = () =>
      reader.readEntries(async (batch) => {
        if (!batch.length) return resolve()
        await Promise.all(batch.map((c) => walkEntry(c, out)))
        readBatch()
      }, () => resolve())
    readBatch()
  })
}

function removeFile(index: number) {
  files.value.splice(index, 1)
}

async function startImport() {
  if (!canImport.value) return
  uploading.value = true
  uploadPercent.value = 0
  try {
    const res = await apiImport(files.value, (p) => (uploadPercent.value = p))
    batchId.value = res.batch_id
    jobs.value = res.jobs
    ElMessage.success(`已提交 ${res.jobs.length} 个文件，解析中…`)
    files.value = []
    startPolling()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

function startPolling() {
  stopPolling()
  polling.value = true
  timer = window.setInterval(poll, 1500)
  poll()
}

function stopPolling() {
  if (timer) window.clearInterval(timer)
  timer = undefined
  polling.value = false
}

async function poll() {
  try {
    const list = await apiImportJobs(batchId.value)
    jobs.value = list
    if (list.every((j) => j.status === 'success' || j.status === 'failed')) {
      stopPolling()
      const ok = list.filter((j) => j.status === 'success').length
      const bad = list.length - ok
      ElMessage[bad ? 'warning' : 'success'](`本批次完成：成功 ${ok} 个${bad ? `，失败 ${bad} 个` : ''}`)
      await loadHistory()
    }
  } catch {
    /* 网络抖动时继续轮询 */
  }
}

async function loadHistory() {
  const list = await apiImportJobs()
  history.value = list
  summary.success = list.filter((j) => j.status === 'success').length
  summary.failed = list.filter((j) => j.status === 'failed').length
  summary.running = list.filter((j) => ['pending', 'parsing', 'embedding'].includes(j.status)).length
}

async function retry(job: ImportJobItem) {
  try {
    await apiRetryImport(job.id)
    ElMessage.info('已重新提交解析')
    batchId.value = job.batch_id
    startPolling()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '重试失败')
  }
}

function viewUnit(job: ImportJobItem) {
  if (job.unit_id) router.push(`/knowledge/units/${job.unit_id}`)
}

const statusMeta: Record<string, { label: string; type: 'info' | 'success' | 'warning' | 'danger' }> = {
  pending: { label: '排队中', type: 'info' },
  parsing: { label: '解析中', type: 'warning' },
  embedding: { label: '向量化', type: 'warning' },
  success: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
}

onMounted(loadHistory)
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="page">
    <el-row :gutter="16">
      <el-col :span="24" :lg="10">
        <el-card>
          <template #header><b>上传知识文档</b></template>
          <div
            class="drop"
            :class="{ active: dragActive }"
            @dragover.prevent="dragActive = true"
            @dragleave.prevent="dragActive = false"
            @drop.prevent="onDrop"
            @click="($refs.picker as HTMLInputElement)?.click()"
          >
            <el-icon :size="36" color="var(--el-color-primary)"><UploadFilled /></el-icon>
            <p>拖拽<b>单个 / 多个文件</b>或<b>整个文件夹</b>到此处</p>
            <p class="muted">支持 PDF、Word(.docx)、Markdown、TXT，单个文件 ≤ {{ MAX_SIZE_MB }}MB</p>
            <el-button type="primary" plain>选择文件</el-button>
            <input
              ref="picker"
              type="file"
              multiple
              :accept="ACCEPT"
              class="hidden"
              @change="(e: Event) => { const t = e.target as HTMLInputElement; addFiles(Array.from(t.files ?? [])); t.value = '' }"
            />
          </div>

          <el-table v-if="files.length" :data="files.map((f, i) => ({ ...f, index: i }))" size="small" class="mt">
            <el-table-column label="文件" min-width="200">
              <template #default="{ row }">{{ row.name }}</template>
            </el-table-column>
            <el-table-column label="大小" width="90">
              <template #default="{ row }">{{ formatSize(row.size) }}</template>
            </el-table-column>
            <el-table-column width="60" align="right">
              <template #default="{ row }">
                <el-button link type="danger" @click="removeFile(row.index)">移除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-progress v-if="uploading" :percentage="uploadPercent" :stroke-width="6" class="mt" />
          <div class="actions">
            <span class="muted">已选择 {{ files.length }} 个文件</span>
            <el-button type="primary" :disabled="!canImport" :loading="uploading" @click="startImport">
              开始导入
            </el-button>
          </div>
        </el-card>
      </el-col>

      <el-col :span="24" :lg="14">
        <el-card>
          <template #header>
            <div class="card-head">
              <b>本批次解析进度</b>
              <span v-if="batchId" class="muted">
                <el-icon v-if="polling" class="is-loading"><Loading /></el-icon>
                批次 {{ batchId }}
              </span>
            </div>
          </template>
          <el-empty v-if="!jobs.length" description="提交导入后在此查看解析进度" />
          <el-table v-else :data="jobs" size="small">
            <el-table-column prop="file_name" label="文件" min-width="160" show-overflow-tooltip />
            <el-table-column label="格式" width="80">
              <template #default="{ row }">{{ fileTypeLabel[row.file_type] ?? row.file_type }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="statusMeta[row.status]?.type">{{ statusMeta[row.status]?.label ?? row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="进度" width="150">
              <template #default="{ row }">
                <el-progress :percentage="row.progress" :status="row.status === 'failed' ? 'exception' : row.status === 'success' ? 'success' : undefined" :stroke-width="8" />
              </template>
            </el-table-column>
            <el-table-column label="结果" min-width="160">
              <template #default="{ row }">
                <span v-if="row.status === 'success'" class="link" @click="viewUnit(row)">查看知识单元</span>
                <el-tooltip v-else-if="row.status === 'failed'" :content="row.error_message || '解析失败'" placement="top">
                  <span class="error">失败原因</span>
                </el-tooltip>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column width="70" align="right">
              <template #default="{ row }">
                <el-button v-if="row.status === 'failed'" link type="primary" @click="retry(row)">重试</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="mt">
      <template #header>
        <div class="card-head">
          <b>导入历史</b>
          <span class="muted">成功 {{ summary.success }} · 失败 {{ summary.failed }} · 进行中 {{ summary.running }}</span>
        </div>
      </template>
      <el-table :data="history" size="small" max-height="420">
        <el-table-column prop="file_name" label="文件" min-width="200" show-overflow-tooltip />
        <el-table-column label="格式" width="90">
          <template #default="{ row }">{{ fileTypeLabel[row.file_type] ?? row.file_type }}</template>
        </el-table-column>
        <el-table-column label="大小" width="90">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusMeta[row.status]?.type">{{ statusMeta[row.status]?.label ?? row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="单元" width="110">
          <template #default="{ row }">
            <span v-if="row.unit_id" class="link" @click="viewUnit(row)">#{{ row.unit_id }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="失败原因" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.error_message || '' }}</template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</template>
        </el-table-column>
        <el-table-column width="70" align="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'failed'" link type="primary" @click="retry(row)">重试</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.drop {
  border: 1.5px dashed var(--el-border-color);
  border-radius: 10px;
  padding: 28px 16px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}
.drop.active,
.drop:hover {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.drop p {
  margin: 8px 0;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.hidden {
  display: none;
}
.mt {
  margin-top: 16px;
}
.actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.link {
  color: var(--el-color-primary);
  cursor: pointer;
}
.error {
  color: var(--el-color-danger);
  cursor: help;
}
</style>
