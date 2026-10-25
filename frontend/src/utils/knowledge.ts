import type { PermissionTarget } from '@/api/knowledge'

/** 权限摘要：将单元的数据权限列表渲染为简短文本与标签（列表/详情共用） */
export const targetTypeLabel: Record<string, string> = {
  global: '全局',
  department: '部门',
  role: '角色',
  user: '个人',
}

export const targetTypeTag: Record<string, 'success' | 'primary' | 'warning' | 'danger'> = {
  global: 'success',
  department: 'primary',
  role: 'warning',
  user: 'danger',
}

export function permissionSummary(perms: PermissionTarget[]) {
  if (!perms.length) return { text: '未配置权限', type: 'info' as const }
  return { text: perms.map((p) => `${targetTypeLabel[p.target_type]}·${p.target_name ?? p.target_id}`).join('、'), type: 'success' as const }
}

export const unitStatusLabel: Record<string, string> = {
  parsing: '解析中',
  active: '生效',
  disabled: '停用',
  parse_failed: '解析失败',
  archived: '已删除',
}

export const unitStatusTag: Record<string, 'info' | 'success' | 'warning' | 'danger'> = {
  parsing: 'warning',
  active: 'success',
  disabled: 'info',
  parse_failed: 'danger',
  archived: 'info',
}

export const fileTypeLabel: Record<string, string> = {
  pdf: 'PDF',
  docx: 'Word',
  md: 'Markdown',
  txt: 'TXT',
}

export function formatSize(bytes: number | null | undefined) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
