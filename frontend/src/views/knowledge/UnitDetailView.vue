<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import type { ApiError } from '@/api/http'
import { apiCategories, apiCreateUnit, apiUnit, apiUpdateUnit, type UnitDetail } from '@/api/knowledge'
import { useUserStore } from '@/stores/user'
import PermissionDialog from '@/components/PermissionDialog.vue'
import { formatSize, permissionSummary, unitStatusLabel, unitStatusTag } from '@/utils/knowledge'

const route = useRoute()
const store = useUserStore()
const canManage = computed(() => store.hasAny(['knowledge:unit:update', 'knowledge:permission:update']))
const router = useRouter()

const unitId = computed(() => Number(route.params.id))
const isNew = computed(() => route.name === 'KnowledgeUnitNew')
const loading = ref(false)
const saving = ref(false)
const editing = ref(route.query.edit === '1' || isNew.value)
const unit = ref<UnitDetail | null>(null)
const categories = ref<string[]>([])

const form = reactive({ title: '', category: '', summary: '', tags: [] as string[], content: '' })

async function load() {
  if (isNew.value) return
  loading.value = true
  try {
    unit.value = await apiUnit(unitId.value, route.query.include_deleted === '1')
    fillForm()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '加载失败')
    router.replace('/knowledge/units')
  } finally {
    loading.value = false
  }
}

function fillForm() {
  const u = unit.value
  if (!u) return
  Object.assign(form, { title: u.title, category: u.category ?? '', summary: u.summary ?? '', tags: [...u.tags], content: u.content })
}

watch(editing, (v) => {
  if (!v) fillForm()
})

async function save() {
  if (!form.title.trim()) return ElMessage.warning('请填写标题')
  if (!form.content.trim()) return ElMessage.warning('请填写正文内容')
  saving.value = true
  try {
    if (isNew.value) {
      const created = await apiCreateUnit({
        title: form.title.trim(), content: form.content, summary: form.summary || null,
        category: form.category || null, tags: form.tags,
      })
      ElMessage.success('知识单元已创建并完成向量化')
      router.replace(`/knowledge/units/${created.id}`)
    } else {
      unit.value = await apiUpdateUnit(unitId.value, {
        title: form.title.trim(), content: form.content, summary: form.summary, category: form.category || null, tags: form.tags,
      })
      ElMessage.success('已保存（正文变更时已自动重建检索切片）')
      editing.value = false
    }
    categories.value = await apiCategories()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

const permVisible = ref(false)
async function onPermissionsSaved() {
  if (!isNew.value) unit.value = await apiUnit(unitId.value)
}

const permText = computed(() => (unit.value ? permissionSummary(unit.value.permissions) : null))

const stats = computed(() => {
  if (!unit.value) return []
  return [
    { label: '切片数量', value: unit.value.chunk_count },
    { label: '正文字数', value: unit.value.content.length },
  ]
})

onMounted(async () => {
  categories.value = await apiCategories()
  await load()
})
</script>

<template>
  <div v-loading="loading">
    <el-page-header class="mb" @back="router.push('/knowledge/units')">
      <template #content>
        <span v-if="isNew">新建知识单元</span>
        <span v-else-if="unit">
          <el-tag size="small" effect="plain">{{ unit.unit_code }}</el-tag>
          {{ unit.title }}
        </span>
      </template>
      <template #extra>
        <template v-if="!isNew && unit">
          <el-button v-if="!editing" v-permission="'knowledge:unit:update'" type="primary" @click="editing = true">编辑</el-button>
          <el-button v-if="editing" @click="editing = false">取消</el-button>
          <el-button v-if="editing" type="primary" :loading="saving" @click="save">保存</el-button>
          <template v-if="canManage">
            <el-button v-permission="'knowledge:permission:update'" @click="permVisible = true">配置数据权限</el-button>
          </template>
        </template>
        <el-button v-if="isNew" type="primary" :loading="saving" @click="save">创建</el-button>
      </template>
    </el-page-header>

    <el-row :gutter="16">
      <el-col :span="24" :lg="17">
        <el-card>
          <template #header><b>{{ editing || isNew ? '编辑内容' : '内容预览' }}</b></template>
          <el-form v-if="editing || isNew" label-position="top">
            <el-form-item label="标题" required>
              <el-input v-model="form.title" maxlength="255" show-word-limit />
            </el-form-item>
            <el-form-item label="分类">
              <el-select v-model="form.category" filterable allow-create clearable placeholder="选择或输入新分类" class="w220">
                <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
              </el-select>
            </el-form-item>
            <el-form-item label="标签">
              <el-select v-model="form.tags" multiple filterable allow-create default-first-option placeholder="回车添加标签" style="width: 100%" />
            </el-form-item>
            <el-form-item label="摘要">
              <el-input v-model="form.summary" type="textarea" :rows="2" maxlength="300" show-word-limit />
            </el-form-item>
            <el-form-item label="正文（支持 Markdown；使用“一、”“第一章”等标题可被自动切分为章节）" required>
              <el-input v-model="form.content" type="textarea" :rows="18" resize="vertical" class="mono" />
            </el-form-item>
          </el-form>
          <pre v-else class="content">{{ unit?.content }}</pre>
        </el-card>
      </el-col>

      <el-col :span="24" :lg="7">
        <el-card v-if="unit">
          <template #header><b>单元信息</b></template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="编号">{{ unit.unit_code }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag size="small" :type="unitStatusTag[unit.status]">{{ unitStatusLabel[unit.status] }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="来源文件">{{ unit.source_file_name ?? '手动创建' }}</el-descriptions-item>
            <el-descriptions-item label="格式 / 大小">
              {{ (unit.file_type ?? '—').toUpperCase() }} · {{ formatSize(unit.file_size) }}
            </el-descriptions-item>
            <el-descriptions-item label="创建人">{{ unit.creator_name ?? '—' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ new Date(unit.created_at).toLocaleString('zh-CN') }}</el-descriptions-item>
            <el-descriptions-item label="更新时间">{{ new Date(unit.updated_at).toLocaleString('zh-CN') }}</el-descriptions-item>
            <el-descriptions-item v-for="m in stats" :key="m.label" :label="m.label">{{ m.value }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <el-card v-if="unit" class="mt">
          <template #header>
            <div class="card-head">
              <b>数据权限</b>
              <el-button v-if="store.has('knowledge:permission:update')" size="small" @click="permVisible = true">配置</el-button>
            </div>
          </template>
          <el-empty v-if="!unit.permissions.length" :image-size="60" description="未配置（默认无人可访问）" />
          <div v-else class="perms">
            <el-tag v-for="p in unit.permissions" :key="`${p.target_type}-${p.target_id}`" size="small" class="tag"
                    :type="{ global: 'success', department: 'primary', role: 'warning', user: 'danger' }[p.target_type]">
              {{ { global: '全局', department: '部门', role: '角色', user: '个人' }[p.target_type] }}：{{ p.target_name ?? p.target_id }}
            </el-tag>
            <div class="muted mt8">{{ permText?.text }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <PermissionDialog v-model="permVisible" :unit="unit" @saved="onPermissionsSaved" />
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 16px;
}
.mt {
  margin-top: 16px;
}
.mt8 {
  margin-top: 8px;
}
.w220 {
  width: 220px;
}
.mono :deep(textarea) {
  font-family: ui-monospace, 'Cascadia Code', Consolas, monospace;
  font-size: 13px;
  line-height: 1.7;
}
.content {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  line-height: 1.8;
  margin: 0;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.tag {
  margin: 0 6px 6px 0;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.perms {
  display: flex;
  flex-wrap: wrap;
}
</style>
