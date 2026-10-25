import { request } from './http'
import type { Page } from './org'

export type FaqStatus = 'pending_review' | 'published' | 'rejected'

export interface FaqItem {
  id: number
  question: string
  answer: string
  category: string | null
  related_unit_id: number | null
  related_unit_title: string | null
  source_type: 'manual' | 'auto_mined'
  status: FaqStatus
  answer_edited: boolean
  hit_count: number
  review_note: string | null
  reviewer_id: number | null
  reviewed_at: string | null
  published_at: string | null
  cached: boolean
  created_at: string
  updated_at: string
}

export interface GapItem {
  id: number
  question_pattern: string
  sample_questions: string[]
  ask_count: number
  last_asked_at: string | null
  status: 'unresolved' | 'resolved' | 'ignored'
  resolved_unit_id: number | null
  created_at: string
  updated_at: string
}

export interface MiningResult {
  faq: { clusters: number; created: number; updated: number; considered: number }
  gap: { considered: number; created: number; updated: number }
  ran_at: string
}

export const apiFaqList = (params: { status?: FaqStatus | ''; keyword?: string; source_type?: string; page: number; page_size: number }) =>
  request<Page<FaqItem>>({ url: '/settlement/faqs', params: { ...params, status: params.status || undefined } })
export const apiFaqRecommendations = (page = 1, page_size = 20) =>
  request<Page<FaqItem>>({ url: '/settlement/faqs/recommendations', params: { page, page_size } })
export const apiFaqCacheStats = () =>
  request<{ cached: number; exact_keys: number; redis: string }>({ url: '/settlement/faqs/cache-stats' })
export const apiCreateFaq = (data: { question: string; answer: string; category?: string | null; related_unit_id?: number | null; publish: boolean }) =>
  request<FaqItem>({ url: '/settlement/faqs', method: 'post', data })
export const apiUpdateFaq = (id: number, data: { question?: string; answer?: string; category?: string | null }) =>
  request<FaqItem>({ url: `/settlement/faqs/${id}`, method: 'put', data })
export const apiReviewFaq = (id: number, action: 'approve' | 'reject', edited_answer?: string, note?: string) =>
  request<FaqItem>({ url: `/settlement/faqs/${id}/review`, method: 'post', data: { action, edited_answer, note } })
export const apiUnpublishFaq = (id: number) =>
  request<FaqItem>({ url: `/settlement/faqs/${id}/unpublish`, method: 'post' })

export const apiGaps = (params: { status?: string; keyword?: string; page: number; page_size: number }) =>
  request<Page<GapItem>>({ url: '/settlement/knowledge-gaps', params })
export const apiSetGapStatus = (id: number, status: GapItem['status']) =>
  request<{ id: number; status: string }>({ url: `/settlement/knowledge-gaps/${id}`, method: 'put', params: { status } })
export const apiGapCreateUnit = (id: number, data: { title: string; content: string; category?: string | null }) =>
  request<{ gap_id: number; unit_id: number; unit_code: string; title: string }>({
    url: `/settlement/knowledge-gaps/${id}/create-unit`, method: 'post', data,
  })

export const apiRunMining = () => request<MiningResult>({ url: '/settlement/mining/run', method: 'post' })
export const apiMiningStatus = () =>
  request<{ running: boolean; next_run: string | null }>({ url: '/settlement/mining/status' })
