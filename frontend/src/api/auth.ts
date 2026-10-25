import { request } from './http'

export interface DepartmentBrief {
  id: number
  name: string
  parent_id: number | null
}

export interface RoleBrief {
  id: number
  role_name: string
  role_code: string
}

export interface UserInfo {
  id: number
  username: string
  display_name: string
  department_id: number | null
  department: DepartmentBrief | null
  roles: RoleBrief[]
  status: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  user_info: UserInfo
  permissions: string[]
}

export interface MeResponse {
  user_info: UserInfo
  permissions: string[]
}

export const apiLogin = (username: string, password: string) =>
  request<LoginResponse>({ url: '/auth/login', method: 'post', data: { username, password } })

export const apiMe = () => request<MeResponse>({ url: '/auth/me' })

export const apiLogout = () => request<{ ok: boolean }>({ url: '/auth/logout', method: 'post' })
