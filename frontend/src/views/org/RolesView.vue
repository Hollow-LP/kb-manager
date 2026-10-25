<script setup lang="ts">
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import type { ApiError } from '@/api/http'
import {
  apiAssignPermissions,
  apiCreateRole,
  apiDeleteRole,
  apiPermissionTree,
  apiRoles,
  apiUpdateRole,
  type PermissionNode,
  type RoleItem,
} from '@/api/org'

const loading = ref(false)
const roles = ref<RoleItem[]>([])
const tree = ref<PermissionNode[]>([])
const treeRef = ref()
const current = ref<RoleItem | null>(null)
const saving = ref(false)

async function load() {
  loading.value = true
  try {
    ;[roles.value, tree.value] = await Promise.all([apiRoles(), apiPermissionTree()])
    if (!current.value && roles.value.length) select(roles.value[0])
  } finally {
    loading.value = false
  }
}

function select(role: RoleItem) {
  current.value = role
  // 只设置叶子节点，避免父节点全选/半选状态与权限码混淆
  const leaves = role.permission_codes
  setTimeout(() => treeRef.value?.setCheckedKeys(leaves), 0)
}

const isSysAdmin = computed(() => current.value?.role_code === 'sys_admin')

const checkedCount = ref(0)
function updateCount() {
  checkedCount.value = treeRef.value?.getCheckedKeys(true).length ?? 0
}

async function savePermissions() {
  if (!current.value) return
  // el-tree 的叶子 key 即权限码
  const codes: string[] = (treeRef.value?.getCheckedKeys(true) ?? []).filter(
    (k: string) => !String(k).startsWith('group:'),
  )
  saving.value = true
  try {
    await apiAssignPermissions(current.value.id, codes)
    ElMessage.success(`已保存 ${codes.length} 项权限`)
    await load()
    select(roles.value.find((r) => r.id === current.value!.id) ?? roles.value[0])
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

// ------------------------------------------------------------------ 角色 CRUD

const dialogVisible = ref(false)
const editing = ref<RoleItem | null>(null)
const formRef = ref<FormInstance>()
const form = reactive({ role_name: '', role_code: '', description: '' })
const rules: FormRules = {
  role_name: [{ required: true, message: '请输入角色名称', trigger: 'blur' }],
  role_code: [
    { required: true, message: '请输入角色编码', trigger: 'blur' },
    { pattern: /^[a-z][a-z0-9_]{1,63}$/, message: '小写字母开头，可含数字与下划线', trigger: 'blur' },
  ],
}

function openCreate() {
  editing.value = null
  Object.assign(form, { role_name: '', role_code: '', description: '' })
  dialogVisible.value = true
}

function openEdit(role: RoleItem) {
  editing.value = role
  Object.assign(form, { role_name: role.role_name, role_code: role.role_code, description: role.description ?? '' })
  dialogVisible.value = true
}

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  try {
    if (editing.value) {
      await apiUpdateRole(editing.value.id, { role_name: form.role_name, description: form.description || null })
      ElMessage.success('角色已更新')
    } else {
      await apiCreateRole({ role_name: form.role_name, role_code: form.role_code, description: form.description || null })
      ElMessage.success('角色已创建')
    }
    dialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '保存失败')
  }
}

async function remove(role: RoleItem) {
  try {
    await ElMessageBox.confirm(`确认删除角色「${role.role_name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await apiDeleteRole(role.id)
    ElMessage.success('已删除')
    if (current.value?.id === role.id) current.value = null
    await load()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '删除失败')
  }
}

onMounted(load)
</script>

<template>
  <div class="wrap">
    <div class="left">
      <el-card>
        <template #header>
          <div class="card-head">
            <span>角色列表</span>
            <el-button v-permission="'org:role:create'" size="small" type="primary" icon="Plus" @click="openCreate">
              新增角色
            </el-button>
          </div>
        </template>
        <el-table v-loading="loading" :data="roles" highlight-current-row row-key="id" @current-change="(r: RoleItem) => r && select(r)">
          <el-table-column prop="role_name" label="角色名称" min-width="110">
            <template #default="{ row }">
              {{ row.role_name }}
              <el-tag v-if="row.is_builtin" size="small" type="info" class="tag">内置</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="role_code" label="编码" min-width="100" />
          <el-table-column prop="user_count" label="用户数" width="76" align="center" />
          <el-table-column label="操作" width="110" align="right">
            <template #default="{ row }">
              <el-button v-permission="'org:role:update'" link type="primary" @click.stop="openEdit(row)">编辑</el-button>
              <el-button
                v-permission="'org:role:delete'"
                link
                type="danger"
                :disabled="row.is_builtin"
                @click.stop="remove(row)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>

    <div class="right">
      <el-card v-if="current">
        <template #header>
          <div class="card-head">
            <span>
              权限配置：<b>{{ current.role_name }}</b>
              <span class="muted">（已选 {{ current.permission_codes.length }} 项）</span>
            </span>
            <el-button
              v-permission="'org:role:assign_permission'"
              type="primary"
              :loading="saving"
              :disabled="isSysAdmin"
              @click="savePermissions"
            >
              保存权限
            </el-button>
          </div>
        </template>
        <el-alert v-if="isSysAdmin" type="info" :closable="false" show-icon class="mb"
                  title="系统管理员拥有全部权限，不可修改" />
        <el-tree
          ref="treeRef"
          :data="tree"
          show-checkbox
          node-key="key"
          default-expand-all
          :props="{ label: 'label', children: 'children' }"
          :disabled="isSysAdmin"
          @check="updateCount"
        >
          <template #default="{ data }">
            <span class="node">
              {{ data.label }}
              <el-tag v-if="data.type === 'button'" size="small" effect="plain" type="primary">按钮</el-tag>
              <el-tag v-else-if="data.type === 'ai'" size="small" effect="plain" type="warning">AI</el-tag>
              <span v-if="!data.key.startsWith('group:')" class="code">{{ data.key }}</span>
            </span>
          </template>
        </el-tree>
      </el-card>
      <el-empty v-else description="请选择左侧角色查看权限" />
    </div>
  </div>

  <el-dialog v-model="dialogVisible" :title="editing ? '编辑角色' : '新增角色'" width="480px">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="角色名称" prop="role_name">
        <el-input v-model="form.role_name" />
      </el-form-item>
      <el-form-item label="角色编码" prop="role_code">
        <el-input v-model="form.role_code" :disabled="!!editing" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.wrap {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(380px, 1fr);
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
.tag {
  margin-left: 6px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: normal;
}
.node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.code {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
  font-family: ui-monospace, monospace;
}
.mb {
  margin-bottom: 12px;
}
</style>
