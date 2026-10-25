<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import type { ApiError } from '@/api/http'
import {
  apiCategories,
  apiCheckPermissions,
  apiDeleteUnits,
  apiRestoreUnits,
  apiUnits,
  type UnitItem,
  type UnitStatus,
} from '@/api/knowledge'
import { apiUserOptions, type UserOption } from '@/api/org'
import PermissionDialog from '@/components/PermissionDialog.vue'
import { useUserStore } from '@/stores/user'
import { fileTypeLabel, permissionSummary, unitStatusLabel, unitStatusTag } from '@/utils/knowledge'

const router = useRouter()
const store = useUserStore()
/** 知识管理视角（全部单元 + 维护操作）仅对拥有维护权限的角色开放；其余用户按数据权限查看 */
const canManage = computed(() =>
  store.hasAny(['knowledge:unit:update', 'knowledge:permission:update', 'knowledge:unit:delete', 'knowledge:import:view']),
)
const scope = computed<'all' | 'mine'>(() => (canManage.value ? 'all' : 'mine'))
const loading = ref(false)
const list = ref<UnitItem[]>([])
const total = ref(0)
const categories = ref<string[]>([])
const selected = ref<UnitItem[]>([])
const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  category: '',
  status: '' as UnitStatus | '',
  file_type: '',
  include_deleted: false,
})

async function load() {
  loading.value = true
  try {
    const res = await apiUnits({
      page: query.page, page_size: query.page_size, keyword: query.keyword || undefined,
      category: query.category || undefined, status: query.status || undefined,
      file_type: query.file_type || undefined,
      include_deleted: canManage.value ? (query.include_deleted || undefined) : undefined,
      scope: scope.value,
    })
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

function resetQuery() {
  Object.assign(query, { page: 1, keyword: '', category: '', status: '', file_type: '', include_deleted: false })
  load()
}

// ------------------------------------------------------------------ 权限弹窗

const permVisible = ref(false)
const permTarget = ref<UnitItem | null>(null)

function openPermission(row: UnitItem) {
  permTarget.value = row
  permVisible.value = true
}

async function onPermissionsSaved() {
  await load()
}

// ------------------------------------------------------------------ 删除 / 恢复

async function removeOne(row: UnitItem) {
  try {
    await ElMessageBox.confirm(`确认删除知识单元「${row.title}」？可在“已删除”筛选下恢复。`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  const res = await apiDeleteUnits([row.id])
  if (res.blocked_unit_ids.includes(row.id)) ElMessage.warning('该单元已被已发布的 FAQ 关联，不能删除')
  else ElMessage.success('已删除')
  await load()
}

async function removeBatch() {
  if (!selected.value.length) return
  try {
    await ElMessageBox.confirm(`确认批量删除 ${selected.value.length} 个知识单元？`, '批量删除', { type: 'warning' })
  } catch {
    return
  }
  const res = await apiDeleteUnits(selected.value.map((u) => u.id))
  const blocked = res.blocked_unit_ids.length
  ElMessage[blocked ? 'warning' : 'success'](
    `已删除 ${res.deleted_unit_ids.length} 个${blocked ? `，${blocked} 个因关联 FAQ 被跳过` : ''}`,
  )
  selected.value = []
  await load()
}

async function restoreOne(row: UnitItem) {
  await apiRestoreUnits([row.id])
  ElMessage.success('已恢复')
  await load()
}

// ------------------------------------------------------------------ 鉴权预览（演示：以指定用户视角查看）

const previewVisible = ref(false)
const previewUserId = ref<number | null>(null)
const previewResult = ref<{ authorized: number[]; unauthorized: number[] } | null>(null)
const users = ref<UserOption[]>([])

async function openPreview() {
  if (!selected.value.length) {
    ElMessage.info('请先勾选要预览的知识单元')
    return
  }
  if (!users.value.length) {
    users.value = await apiUserOptions()
  }
  previewVisible.value = true
}

async function runPreview() {
  if (!previewUserId.value) return
  previewResult.value = null
  try {
    // 管理员只能查询自己；此处通过登录用户自己的鉴权接口演示，选他人时由后端返回 403
    const res = await apiCheckPermissions(previewUserId.value, selected.value.map((u) => u.id))
    previewResult.value = { authorized: res.authorized_unit_ids, unauthorized: res.unauthorized_unit_ids }
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '鉴权查询失败')
  }
}


onMounted(async () => {
  await Promise.all([load(), apiCategories().then((c) => (categories.value = c))])
})
</script>

<template>
  <div>
    <el-card>
      <div class="toolbar">
        <el-input v-model="query.keyword" placeholder="编号 / 标题 / 正文" clearable class="w220" @keyup.enter="search" />
        <el-select v-model="query.category" placeholder="分类" clearable class="w140">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <el-select v-model="query.file_type" placeholder="格式" clearable class="w110">
          <el-option v-for="(label, v) in fileTypeLabel" :key="v" :label="label" :value="v" />
        </el-select>
        <el-select v-model="query.status" placeholder="状态" clearable class="w120">
          <el-option v-for="(label, v) in unitStatusLabel" :key="v" :label="label" :value="v" />
        </el-select>
        <el-switch v-if="canManage" v-model="query.include_deleted" active-text="已删除" @change="search" />
        <el-tag v-else type="info" effect="plain">仅显示您有权访问的知识单元</el-tag>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="resetQuery">重置</el-button>
        <div class="spacer" />
        <el-button v-if="canManage" :disabled="!selected.length" @click="openPreview">鉴权预览</el-button>
        <el-button v-if="canManage" v-permission="'knowledge:unit:create'" type="primary" icon="Plus" @click="router.push('/knowledge/units/new')">
          新建单元
        </el-button>
        <el-button v-if="canManage" v-permission="'knowledge:unit:delete'" type="danger" plain :disabled="!selected.length" @click="removeBatch">
          批量删除
        </el-button>
        <el-button v-if="canManage" v-permission="'knowledge:import:view'" type="primary" plain icon="Upload" @click="router.push('/knowledge/import')">
          去导入
        </el-button>
      </div>

      <el-table v-loading="loading" :data="list" stripe @selection-change="(rows: UnitItem[]) => (selected = rows)">
        <el-table-column v-if="canManage" type="selection" width="44" />
        <el-table-column prop="unit_code" label="编号" width="96" />
        <el-table-column label="标题" min-width="200">
          <template #default="{ row }">
            <el-link type="primary" underline="never" @click="router.push(`/knowledge/units/${row.id}`)">{{ row.title }}</el-link>
            <div class="muted">{{ row.summary?.slice(0, 60) }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="category" label="分类" width="110">
          <template #default="{ row }">{{ row.category ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="格式" width="90">
          <template #default="{ row }">{{ fileTypeLabel[row.file_type ?? ''] ?? row.file_type ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="数据权限" min-width="180">
          <template #default="{ row }">
            <el-tooltip :content="permissionSummary(row.permissions).text" placement="top">
              <el-tag size="small" :type="permissionSummary(row.permissions).type">
                {{ row.permissions.length ? `${row.permissions.length} 项权限` : '未配置' }}
              </el-tag>
            </el-tooltip>
            <el-button v-permission="'knowledge:permission:update'" link type="primary" class="ml" @click="openPermission(row)">
              配置
            </el-button>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag size="small" :type="unitStatusTag[row.status]">{{ unitStatusLabel[row.status] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建人" width="100">
          <template #default="{ row }">{{ row.creator_name ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="160">
          <template #default="{ row }">{{ new Date(row.updated_at).toLocaleString('zh-CN') }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push(`/knowledge/units/${row.id}`)">查看</el-button>
            <template v-if="row.status === 'archived'">
              <el-button v-permission="'knowledge:unit:delete'" link type="success" @click="restoreOne(row)">恢复</el-button>
            </template>
            <template v-else>
              <el-button v-permission="'knowledge:unit:update'" link type="primary" @click="router.push(`/knowledge/units/${row.id}?edit=1`)">
                编辑
              </el-button>
              <el-button v-permission="'knowledge:unit:delete'" link type="danger" @click="removeOne(row)">删除</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>

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
    </el-card>

    <PermissionDialog v-model="permVisible" :unit="permTarget" @saved="onPermissionsSaved" />

    <el-dialog v-model="previewVisible" title="数据权限鉴权预览" width="560px">
      <el-alert type="info" :closable="false" show-icon class="mb"
                title="以指定用户视角模拟 AI 检索后的鉴权结果。直接选择自己账号可实时验证；其他账号需由 AI 服务内部调用。" />
      <el-select v-model="previewUserId" filterable placeholder="选择用户" class="full">
        <el-option v-for="u in users" :key="u.id" :label="`${u.display_name}（${u.username} · ${u.department_name ?? '无部门'}）`" :value="u.id" />
      </el-select>
      <div class="mt">
        <el-button type="primary" :disabled="!previewUserId" @click="runPreview">开始鉴权</el-button>
        <span v-if="previewUserId === store.userInfo?.id" class="muted ml">当前账号（可实时验证）</span>
      </div>
      <template v-if="previewResult">
        <el-divider content-position="left">结果</el-divider>
        <el-table :data="selected" size="small">
          <el-table-column prop="unit_code" label="编号" width="90" />
          <el-table-column prop="title" label="标题" show-overflow-tooltip />
          <el-table-column label="结果" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="previewResult.authorized.includes(row.id) ? 'success' : 'danger'">
                {{ previewResult.authorized.includes(row.id) ? '允许' : '拒绝' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
  align-items: center;
}
.spacer {
  flex: 1;
}
.w110 {
  width: 110px;
}
.w120 {
  width: 120px;
}
.w140 {
  width: 140px;
}
.w220 {
  width: 220px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: normal;
}
.ml {
  margin-left: 6px;
}
.mb {
  margin-bottom: 12px;
}
.mt {
  margin-top: 12px;
}
.full {
  width: 100%;
}
.pager {
  margin-top: 14px;
  justify-content: flex-end;
}
</style>
