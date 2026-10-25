<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, reactive, ref, watch } from 'vue'

import type { ApiError } from '@/api/http'
import { apiAssignUnitPermissions, type PermissionTarget, type UnitDetail } from '@/api/knowledge'
import { apiDeptOptions, apiRoleOptions, apiUserOptions, type DeptOption, type RoleOption, type UserOption } from '@/api/org'
import { targetTypeLabel, targetTypeTag } from '@/utils/knowledge'

const props = defineProps<{ unit: Pick<UnitDetail, 'id' | 'title' | 'permissions'> | null }>()
const visible = defineModel<boolean>({ default: false })
const emit = defineEmits<{ saved: [targets: PermissionTarget[]] }>()

const loading = ref(false)
const saving = ref(false)
const departments = ref<DeptOption[]>([])
const roles = ref<RoleOption[]>([])
const users = ref<UserOption[]>([])

const form = reactive({
  isGlobal: false,
  departmentIds: [] as number[],
  roleIds: [] as number[],
  userIds: [] as number[],
})

watch(visible, async (open) => {
  if (!open || !props.unit) return
  syncFromUnit()
  await loadOptions()
})

function syncFromUnit() {
  const perms = props.unit?.permissions ?? []
  form.isGlobal = perms.some((p) => p.target_type === 'global')
  form.departmentIds = perms.filter((p) => p.target_type === 'department').map((p) => p.target_id)
  form.roleIds = perms.filter((p) => p.target_type === 'role').map((p) => p.target_id)
  form.userIds = perms.filter((p) => p.target_type === 'user').map((p) => p.target_id)
}

async function loadOptions() {
  loading.value = true
  try {
    const [d, r, u] = await Promise.all([apiDeptOptions(), apiRoleOptions(), apiUserOptions()])
    departments.value = d
    roles.value = r
    users.value = u
  } finally {
    loading.value = false
  }
}

/** 扁平部门（含层级）转 el-tree-select 所需的树结构 */
const deptTree = computed(() => {
  interface Node { value: number; label: string; children: Node[] }
  const map = new Map<number, Node>()
  const roots: Node[] = []
  for (const d of departments.value) {
    map.set(d.id, { value: d.id, label: d.depth ? `${'　'.repeat(d.depth)}${d.name}` : d.name, children: [] })
  }
  for (const d of departments.value) {
    const node = map.get(d.id)!
    const parent = d.parent_id ? map.get(d.parent_id) : undefined
    ;(parent ? parent.children : roots).push(node)
  }
  return roots
})

const summary = computed(() => {
  const parts: string[] = []
  if (form.isGlobal) parts.push('全局公开')
  if (form.departmentIds.length) parts.push(`${form.departmentIds.length} 个部门`)
  if (form.roleIds.length) parts.push(`${form.roleIds.length} 个角色`)
  if (form.userIds.length) parts.push(`${form.userIds.length} 名个人`)
  return parts.length ? parts.join(' + ') : '未配置（默认无人可访问）'
})


async function submit() {
  if (!props.unit) return
  const targets: PermissionTarget[] = [
    ...(form.isGlobal ? [{ target_type: 'global' as const, target_id: 0 }] : []),
    ...form.departmentIds.map((id) => ({ target_type: 'department' as const, target_id: id })),
    ...form.roleIds.map((id) => ({ target_type: 'role' as const, target_id: id })),
    ...form.userIds.map((id) => ({ target_type: 'user' as const, target_id: id })),
  ]
  saving.value = true
  try {
    const saved = await apiAssignUnitPermissions(props.unit.id, targets)
    ElMessage.success('数据权限已保存并立即生效')
    emit('saved', saved)
    visible.value = false
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="`配置数据权限：${unit?.title ?? ''}`" width="640px" destroy-on-close
             :close-on-press-escape="false">
    <el-alert type="info" :closable="false" show-icon class="hint"
              title="满足以下任一实体即可访问（OR 逻辑）；全部不勾选表示默认无任何访问权限。" />
    <div class="current">
      <span class="muted">当前单元已有权限：</span>
      <template v-if="unit?.permissions.length">
        <el-tag v-for="p in unit.permissions" :key="`${p.target_type}-${p.target_id}`" size="small" :type="targetTypeTag[p.target_type]" class="tag">
          {{ targetTypeLabel[p.target_type] }}：{{ p.target_name ?? p.target_id }}
        </el-tag>
      </template>
      <span v-else class="muted">无</span>
    </div>

    <el-form v-loading="loading" label-width="96px" class="form">
      <el-form-item label="全局公开">
        <el-switch v-model="form.isGlobal" active-text="所有登录用户可访问" />
      </el-form-item>
      <el-form-item label="指定部门">
        <el-tree-select v-model="form.departmentIds" :data="deptTree" multiple show-checkbox check-strictly
                        default-expand-all collapse-tags collapse-tags-tooltip clearable placeholder="可多选（不含下级，需单独勾选）" style="width: 100%"
                        popper-class="perm-tree-popper" :teleported="false" />
      </el-form-item>
      <el-form-item label="指定角色">
        <el-select v-model="form.roleIds" multiple placeholder="可多选" style="width: 100%"
                   popper-class="perm-option-popper" :teleported="false">
          <el-option v-for="r in roles" :key="r.id" :label="`${r.role_name}（${r.role_code}）`" :value="r.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="指定人员">
        <el-select v-model="form.userIds" multiple filterable placeholder="按姓名或用户名搜索" style="width: 100%"
                   popper-class="perm-option-popper" :teleported="false">
          <el-option v-for="u in users" :key="u.id" :label="`${u.display_name}（${u.username}${u.department_name ? ' · ' + u.department_name : ''}）`" :value="u.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="保存后">
        <span class="summary">{{ summary }}</span>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存并生效</el-button>
    </template>
  </el-dialog>
</template>

<style>
/* 权限配置的部门树下拉：给树一个稳定的宽度与高度（不能依赖局部宽度继承） */
.perm-tree-popper .el-tree {
  width: 100%;
  min-height: 200px;
  max-height: 280px;
  overflow: auto;
}
.perm-tree-popper .el-select-dropdown__item {
  padding: 0;
}
/* 下拉不再传送到 body（teleported=false），在弹窗内展开时限制高度，避免撑出弹窗外 */
.perm-tree-popper .el-scrollbar {
  max-height: 280px;
}
.perm-option-popper .el-select-dropdown {
  max-height: 280px;
}
</style>

<style scoped>
.hint {
  margin-bottom: 12px;
}
.current {
  margin-bottom: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  min-height: 24px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.tag {
  margin-right: 4px;
}
.summary {
  color: var(--el-color-primary);
}
</style>
