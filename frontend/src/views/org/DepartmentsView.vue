<script setup lang="ts">
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import type { ApiError } from '@/api/http'
import {
  apiCreateDepartment,
  apiDeleteDepartment,
  apiDepartments,
  apiUpdateDepartment,
  apiUsers,
  type DepartmentNode,
  type UserItem,
} from '@/api/org'

const loading = ref(false)
const tree = ref<DepartmentNode[]>([])
const selected = ref<DepartmentNode | null>(null)
const flat = ref<UserItem[]>([])

async function load() {
  loading.value = true
  try {
    tree.value = await apiDepartments()
    if (selected.value) {
      selected.value = findNode(tree.value, selected.value.id)
    }
  } finally {
    loading.value = false
  }
}

function findNode(nodes: DepartmentNode[], id: number): DepartmentNode | null {
  for (const n of nodes) {
    if (n.id === id) return n
    const hit = findNode(n.children, id)
    if (hit) return hit
  }
  return null
}

function flatten(nodes: DepartmentNode[], depth = 0, out: Array<DepartmentNode & { depth: number }> = []) {
  for (const n of nodes) {
    out.push({ ...n, depth })
    flatten(n.children, depth + 1, out)
  }
  return out
}

async function onSelect(node: DepartmentNode) {
  selected.value = node
  const res = await apiUsers({ page: 1, page_size: 100, department_id: node.id })
  flat.value = res.items
}

// ------------------------------------------------------------------ 新增 / 编辑

const dialogVisible = ref(false)
const editing = ref<DepartmentNode | null>(null)
const formRef = ref<FormInstance>()
const form = reactive({ name: '', parent_id: null as number | null, leader_id: null as number | null, sort_order: 0 })
const rules: FormRules = { name: [{ required: true, message: '请输入部门名称', trigger: 'blur' }] }

/** 候选人列表：用于选择负责人 */
const people = ref<UserItem[]>([])
async function loadPeople() {
  const res = await apiUsers({ page: 1, page_size: 100 })
  people.value = res.items
}

function parentOptions() {
  // 编辑时排除自己及下级，避免形成环
  const excluded = editing.value ? collectIds(editing.value) : new Set<number>()
  return flatten(tree.value)
    .filter((n) => !excluded.has(n.id))
    .map((n) => ({ value: n.id, label: '　'.repeat(n.depth) + n.name }))
}

function collectIds(node: DepartmentNode): Set<number> {
  return new Set([node.id, ...node.children.flatMap((c) => [...collectIds(c)])])
}

async function openCreate(parent?: DepartmentNode) {
  editing.value = null
  Object.assign(form, { name: '', parent_id: parent?.id ?? null, leader_id: null, sort_order: 0 })
  await loadPeople()
  dialogVisible.value = true
}

async function openEdit(node: DepartmentNode) {
  editing.value = node
  Object.assign(form, { name: node.name, parent_id: node.parent_id, leader_id: node.leader_id, sort_order: node.sort_order })
  await loadPeople()
  dialogVisible.value = true
}

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  try {
    if (editing.value) {
      await apiUpdateDepartment(editing.value.id, { ...form, name: form.name.trim() })
      ElMessage.success('部门已更新')
    } else {
      await apiCreateDepartment({ ...form, name: form.name.trim() })
      ElMessage.success('部门已创建')
    }
    dialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '保存失败')
  }
}

async function remove(node: DepartmentNode) {
  try {
    await ElMessageBox.confirm(`确认删除部门「${node.name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await apiDeleteDepartment(node.id)
    ElMessage.success('已删除')
    if (selected.value?.id === node.id) {
      selected.value = null
      flat.value = []
    }
    await load()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '删除失败')
  }
}

onMounted(load)
</script>

<template>
  <div class="wrap">
    <el-card>
      <template #header>
        <div class="card-head">
          <span>部门树</span>
          <el-button v-permission="'org:dept:create'" size="small" type="primary" icon="Plus" @click="openCreate()">
            新增根部门
          </el-button>
        </div>
      </template>
      <el-tree
        v-loading="loading"
        :data="tree"
        node-key="id"
        default-expand-all
        highlight-current
        :expand-on-click-node="false"
        :props="{ label: 'name', children: 'children' }"
        @node-click="onSelect"
      >
        <template #default="{ data }">
          <div class="row">
            <span class="label">
              {{ data.name }}
              <span class="muted">
                {{ data.member_count }} 人<template v-if="data.leader_name"> · 负责人 {{ data.leader_name }}</template>
              </span>
            </span>
            <span class="ops" @click.stop>
              <el-button v-permission="'org:dept:create'" link type="primary" @click="openCreate(data)">添加下级</el-button>
              <el-button v-permission="'org:dept:update'" link type="primary" @click="openEdit(data)">编辑</el-button>
              <el-button v-permission="'org:dept:delete'" link type="danger" @click="remove(data)">删除</el-button>
            </span>
          </div>
        </template>
      </el-tree>
    </el-card>

    <el-card>
      <template #header>
        <span v-if="selected">
          「{{ selected.name }}」成员（含下级，共 {{ flat.length }} 人）
        </span>
        <span v-else>成员</span>
      </template>
      <el-empty v-if="!selected" description="点击左侧部门查看成员" />
      <el-table v-else :data="flat" size="small" stripe>
        <el-table-column prop="username" label="用户名" width="130" />
        <el-table-column prop="display_name" label="姓名" width="110" />
        <el-table-column prop="department_name" label="所属部门" width="120" />
        <el-table-column label="角色" min-width="160">
          <template #default="{ row }">
            <el-tag v-for="r in row.roles" :key="r.id" size="small" class="tag">{{ r.role_name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">{{ row.status === 'active' ? '启用' : '停用' }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑部门' : '新增部门'" width="460px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="部门名称" prop="name">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="上级部门">
          <el-select v-model="form.parent_id" clearable placeholder="不选则为根部门" class="full">
            <el-option v-for="o in parentOptions()" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="form.leader_id" clearable filterable class="full">
            <el-option v-for="u in people" :key="u.id" :label="`${u.display_name}（${u.username}）`" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.wrap {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(420px, 1fr);
  gap: 16px;
  align-items: start;
}
@media (max-width: 1100px) {
  .wrap {
    grid-template-columns: 1fr;
  }
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.row {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-right: 8px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-left: 6px;
}
.ops {
  opacity: 0.85;
}
.tag {
  margin-right: 4px;
}
.full {
  width: 100%;
}
</style>
