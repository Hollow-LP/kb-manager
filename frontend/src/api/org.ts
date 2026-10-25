import { request } from './http'
import type { RoleBrief } from './auth'

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface DepartmentNode {
  id: number
  parent_id: number | null
  name: string
  leader_id: number | null
  leader_name: string | null
  sort_order: number
  member_count: number
  children: DepartmentNode[]
}

export interface DepartmentPayload {
  name: string
  parent_id: number | null
  leader_id: number | null
  sort_order: number
}

export interface UserItem {
  id: number
  username: string
  display_name: string
  department_id: number | null
  department_name: string | null
  status: 'active' | 'disabled'
  roles: RoleBrief[]
  created_at: string
  updated_at: string
}

export interface UserQuery {
  page: number
  page_size: number
  keyword?: string
  department_id?: number | null
  status?: '' | 'active' | 'disabled'
}

export interface UserCreatePayload {
  username: string
  password: string
  display_name: string
  department_id: number | null
  role_ids: number[]
  status: 'active' | 'disabled'
}

export interface UserUpdatePayload {
  display_name?: string
  department_id?: number | null
  role_ids?: number[]
  status?: 'active' | 'disabled'
}

export interface RoleItem {
  id: number
  role_name: string
  role_code: string
  description: string | null
  permission_codes: string[]
  user_count: number
  is_builtin: boolean
  created_at: string
  updated_at: string
}

export interface PermissionNode {
  key: string
  label: string
  type: 'menu' | 'button' | 'ai'
  children: PermissionNode[]
}

export const apiDepartments = () => request<DepartmentNode[]>({ url: '/org/departments' })
export const apiCreateDepartment = (data: DepartmentPayload) =>
  request<DepartmentNode>({ url: '/org/departments', method: 'post', data })
export const apiUpdateDepartment = (id: number, data: DepartmentPayload) =>
  request<DepartmentNode>({ url: `/org/departments/${id}`, method: 'put', data })
export const apiDeleteDepartment = (id: number) =>
  request<{ ok: boolean }>({ url: `/org/departments/${id}`, method: 'delete' })

export const apiUsers = (params: UserQuery) => request<Page<UserItem>>({ url: '/org/users', params })
export const apiCreateUser = (data: UserCreatePayload) => request<UserItem>({ url: '/org/users', method: 'post', data })
export const apiUpdateUser = (id: number, data: UserUpdatePayload) =>
  request<UserItem>({ url: `/org/users/${id}`, method: 'put', data })
export const apiResetPassword = (id: number, password: string) =>
  request<{ ok: boolean }>({ url: `/org/users/${id}/reset-password`, method: 'post', data: { password } })
export const apiToggleUser = (id: number) =>
  request<{ ok: boolean; status: string }>({ url: `/org/users/${id}/toggle`, method: 'post' })
export const apiDeleteUser = (id: number) => request<{ ok: boolean }>({ url: `/org/users/${id}`, method: 'delete' })

export const apiRoles = () => request<RoleItem[]>({ url: '/org/roles' })
export const apiCreateRole = (data: { role_name: string; role_code: string; description?: string | null }) =>
  request<RoleItem>({ url: '/org/roles', method: 'post', data })
export const apiUpdateRole = (id: number, data: { role_name?: string; description?: string | null }) =>
  request<RoleItem>({ url: `/org/roles/${id}`, method: 'put', data })
export const apiDeleteRole = (id: number) => request<{ ok: boolean }>({ url: `/org/roles/${id}`, method: 'delete' })
export const apiPermissionTree = () => request<PermissionNode[]>({ url: '/org/permissions/tree' })
export const apiAssignPermissions = (id: number, permission_codes: string[]) =>
  request<string[]>({ url: `/org/roles/${id}/permissions`, method: 'post', data: { permission_codes } })

// ---------------------------------------------------------------- 权限配置选项（知识管理员可用）

export interface DeptOption { id: number; name: string; parent_id: number | null; depth: number }
export interface RoleOption { id: number; role_name: string; role_code: string }
export interface UserOption { id: number; username: string; display_name: string; department_id: number | null; department_name: string | null }

export const apiDeptOptions = () => request<DeptOption[]>({ url: '/org/options/departments' })
export const apiRoleOptions = () => request<RoleOption[]>({ url: '/org/options/roles' })
export const apiUserOptions = (keyword?: string) =>
  request<UserOption[]>({ url: '/org/options/users', params: keyword ? { keyword } : {} })
