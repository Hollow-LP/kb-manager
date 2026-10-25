<script setup lang="ts">
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import type { ApiError } from '@/api/http'
import {
  apiCreateUser,
  apiDeleteUser,
  apiDepartments,
  apiResetPassword,
  apiRoles,
  apiToggleUser,
  apiUpdateUser,
  apiUsers,
  type DepartmentNode,
  type RoleItem,
  type UserItem,
} from '@/api/org'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const loading = ref(false)
const list = ref<UserItem[]>([])
const total = ref(0)
const roles = ref<RoleItem[]>([])
const departments = ref<DepartmentNode[]>([])

const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  department_id: null as number | null,
  status: '' as '' | 'active' | 'disabled',
})

/** 部门树 -> el-tree-select 数据 */
interface DeptOption {
  value: number
  label: string
  children: DeptOption[]
}
const deptTreeData = ref<DeptOption[]>([])
function toOptions(nodes: DepartmentNode[]): DeptOption[] {
  return nodes.map((n) => ({ value: n.id, label: `${n.name}（${n.member_count}）`, children: toOptions(n.children) }))
}

async function load() {
  loading.value = true
  try {
    const res = await apiUsers({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      department_id: query.department_id ?? undefined,
      status: query.status || undefined,
    })
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadRefs() {
  ;[roles.value, departments.value] = await Promise.all([apiRoles(), apiDepartments()])
  deptTreeData.value = toOptions(departments.value)
}

function search() {
  query.page = 1
  load()
}

function reset() {
  Object.assign(query, { page: 1, keyword: '', department_id: null, status: '' })
  load()
}

// ------------------------------------------------------------------ 新增 / 编辑

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({
  username: '',
  password: '',
  display_name: '',
  department_id: null as number | null,
  role_ids: [] as number[],
  status: 'active' as 'active' | 'disabled',
})
const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { pattern: /^[a-zA-Z0-9_.-]{2,64}$/, message: '2-64 位字母、数字或 _ . -', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入初始密码', trigger: 'blur' },
    { min: 6, message: '至少 6 位', trigger: 'blur' },
  ],
  display_name: [{ required: true, message: '请输入显示名', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { username: '', password: '', display_name: '', department_id: null, role_ids: [], status: 'active' })
  dialogVisible.value = true
}

function openEdit(row: UserItem) {
  editingId.value = row.id
  Object.assign(form, {
    username: row.username,
    password: '',
    display_name: row.display_name,
    department_id: row.department_id,
    role_ids: row.roles.map((r) => r.id),
    status: row.status,
  })
  dialogVisible.value = true
}

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  submitting.value = true
  try {
    if (editingId.value === null) {
      await apiCreateUser({
        username: form.username.trim(),
        password: form.password,
        display_name: form.display_name.trim(),
        department_id: form.department_id,
        role_ids: form.role_ids,
        status: form.status,
      })
      ElMessage.success('用户已创建')
    } else {
      await apiUpdateUser(editingId.value, {
        display_name: form.display_name.trim(),
        department_id: form.department_id,
        role_ids: form.role_ids,
        status: form.status,
      })
      ElMessage.success('用户已更新')
    }
    dialogVisible.value = false
    await Promise.all([load(), loadRefs()])
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '保存失败')
  } finally {
    submitting.value = false
  }
}

// ------------------------------------------------------------------ 行操作

async function toggle(row: UserItem) {
  try {
    const res = await apiToggleUser(row.id)
    ElMessage.success(res.status === 'active' ? '已启用' : '已停用')
    await load()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '操作失败')
  }
}

async function remove(row: UserItem) {
  try {
    await ElMessageBox.confirm(`确认删除用户「${row.display_name}（${row.username}）」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await apiDeleteUser(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '删除失败')
  }
}

const pwdVisible = ref(false)
const pwdTarget = ref<UserItem | null>(null)
const pwd = reactive({ password: '', confirm: '' })

function openReset(row: UserItem) {
  pwdTarget.value = row
  Object.assign(pwd, { password: '', confirm: '' })
  pwdVisible.value = true
}

async function submitReset() {
  if (!pwd.password || pwd.password.length < 6) return ElMessage.warning('密码至少 6 位')
  if (pwd.password !== pwd.confirm) return ElMessage.warning('两次输入的密码不一致')
  try {
    await apiResetPassword(pwdTarget.value!.id, pwd.password)
    ElMessage.success('密码已重置')
    pwdVisible.value = false
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '重置失败')
  }
}

onMounted(async () => {
  await Promise.all([load(), loadRefs()])
})
</script>

<template>
  <div>
    <el-card>
      <div class="toolbar">
        <el-input v-model="query.keyword" placeholder="用户名 / 姓名" clearable class="w220" @keyup.enter="search" />
        <el-tree-select
          v-model="query.department_id"
          :data="deptTreeData"
          check-strictly
          clearable
          placeholder="所属部门（含下级）"
          class="w220"
        />
        <el-select v-model="query.status" placeholder="状态" clearable class="w120">
          <el-option label="启用" value="active" />
          <el-option label="停用" value="disabled" />
        </el-select>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="reset">重置</el-button>
        <div class="spacer" />
        <el-button v-permission="'org:user:create'" type="primary" icon="Plus" @click="openCreate">新增用户</el-button>
      </div>

      <el-table v-loading="loading" :data="list" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" width="140" />
        <el-table-column prop="display_name" label="姓名" width="130" />
        <el-table-column label="部门" width="140">
          <template #default="{ row }">{{ row.department_name ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="角色" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="r in row.roles" :key="r.id" size="small" class="tag">{{ r.role_name }}</el-tag>
            <span v-if="!row.roles.length" class="muted">未分配</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
              {{ row.status === 'active' ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ new Date(row.updated_at).toLocaleString('zh-CN') }}</template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button v-permission="'org:user:update'" link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button v-permission="'org:user:reset_pwd'" link type="primary" @click="openReset(row)">重置密码</el-button>
            <el-button
              v-permission="'org:user:toggle'"
              link
              :type="row.status === 'active' ? 'warning' : 'success'"
              :disabled="row.id === store.userInfo?.id"
              @click="toggle(row)"
            >
              {{ row.status === 'active' ? '停用' : '启用' }}
            </el-button>
            <el-button
              v-permission="'org:user:delete'"
              link
              type="danger"
              :disabled="row.id === store.userInfo?.id"
              @click="remove(row)"
            >
              删除
            </el-button>
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

    <el-dialog v-model="dialogVisible" :title="editingId === null ? '新增用户' : '编辑用户'" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="editingId !== null" placeholder="登录账号" />
        </el-form-item>
        <el-form-item v-if="editingId === null" label="初始密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="姓名" prop="display_name">
          <el-input v-model="form.display_name" placeholder="显示名称" />
        </el-form-item>
        <el-form-item label="所属部门">
          <el-tree-select v-model="form.department_id" :data="deptTreeData" check-strictly clearable style="width: 100%" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role_ids" multiple class="full" placeholder="可多选">
            <el-option v-for="r in roles" :key="r.id" :label="r.role_name" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio value="active">启用</el-radio>
            <el-radio value="disabled">停用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pwdVisible" :title="`重置密码：${pwdTarget?.display_name ?? ''}`" width="420px">
      <el-form label-width="90px">
        <el-form-item label="新密码">
          <el-input v-model="pwd.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="pwd.confirm" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" @click="submitReset">确认重置</el-button>
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
}
.spacer {
  flex: 1;
}
.w120 {
  width: 120px;
}
.w220 {
  width: 220px;
}
.tag {
  margin-right: 4px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.pager {
  margin-top: 14px;
  justify-content: flex-end;
}
</style>
