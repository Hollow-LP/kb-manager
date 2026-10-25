import { request } from './http'
import type { Page } from './org'

export type TargetType = 'global' | 'department' | 'role' | 'user'
export type UnitStatus = 'parsing' | 'active' | 'disabled' | 'parse_failed' | 'archived'

export interface PermissionTarget {
  target_type: TargetType
  target_id: number
  target_name?: string | null
}

export interface UnitItem {
  id: number
  unit_code: string
  title: string
  summary: string | null
  category: string | null
  tags: string[]
  source_file_name: string | null
  file_type: string | null
  file_size: number | null
  status: UnitStatus
  creator_id: number | null
  creator_name: string | null
  permissions: PermissionTarget[]
  chunk_count: number
  created_at: string
  updated_at: string
}

export interface UnitDetail extends UnitItem {
  content: string
}

export interface ImportJobItem {
  id: number
  batch_id: string
  file_name: string
  file_type: string
  file_size: number
  status: 'pending' | 'parsing' | 'embedding' | 'success' | 'failed'
  progress: number
  unit_id: number | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface UnitQuery {
  page: number
  page_size: number
  keyword?: string
  category?: string
  status?: UnitStatus | ''
  file_type?: string
  include_deleted?: boolean
  scope?: 'all' | 'mine'
}

export const apiImport = async (files: File[], onProgress?: (percent: number) => void) => {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  return request<{ batch_id: string; jobs: ImportJobItem[] }>({ url: '/knowledge/import', method: 'post', data: form,
    onUploadProgress: (e) => e.total && onProgress?.(Math.round((e.loaded / e.total) * 100)) })
}

export const apiImportJobs = (batchId?: string) =>
  request<ImportJobItem[]>({ url: '/knowledge/import/jobs', params: batchId ? { batch_id: batchId } : {} })

export const apiRetryImport = (jobId: number) =>
  request<ImportJobItem>({ url: `/knowledge/import/jobs/${jobId}/retry`, method: 'post' })

export const apiUnits = (params: UnitQuery) => request<Page<UnitItem>>({ url: '/knowledge/units', params })
export const apiCategories = () => request<string[]>({ url: '/knowledge/units/categories' })
export const apiUnit = (id: number, includeDeleted = false) =>
  request<UnitDetail>({ url: `/knowledge/units/${id}`, params: includeDeleted ? { include_deleted: true } : {} })
export const apiCreateUnit = (data: { title: string; content: string; summary?: string | null; category?: string | null; tags: string[] }) =>
  request<UnitDetail>({ url: '/knowledge/units', method: 'post', data })
export const apiUpdateUnit = (id: number, data: Partial<Pick<UnitItem, 'title' | 'summary' | 'category' | 'tags' | 'status'> & { content: string }>) =>
  request<UnitDetail>({ url: `/knowledge/units/${id}`, method: 'put', data })
export const apiDeleteUnits = (unitIds: number[]) =>
  request<{ deleted_unit_ids: number[]; blocked_unit_ids: number[]; not_found_unit_ids: number[] }>({
    url: '/knowledge/units', method: 'delete', data: { unit_ids: unitIds },
  })
export const apiRestoreUnits = (unitIds: number[]) =>
  request<number[]>({ url: '/knowledge/units/restore', method: 'post', data: { unit_ids: unitIds } })
export const apiAssignUnitPermissions = (id: number, targets: PermissionTarget[]) =>
  request<PermissionTarget[]>({ url: `/knowledge/units/${id}/permissions`, method: 'post', data: { targets } })
export const apiCheckPermissions = (userId: number, unitIds: number[]) =>
  request<{ authorized_unit_ids: number[]; unauthorized_unit_ids: number[] }>({
    url: '/knowledge/check-permissions', method: 'post', data: { user_id: userId, unit_ids: unitIds },
  })

export const apiAccessibleUnits = () =>
  request<{ unit_ids: number[]; count: number }>({ url: '/knowledge/accessible-units' })
