import { request, TOKEN_KEY } from './http'

export interface SessionItem {
  id: number
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface Citation {
  unit_id: number
  unit_code: string
  title: string
  score: number
}

export interface ChatMessageItem {
  id: number
  role: 'user' | 'assistant'
  content: string
  status?: string
  citations: Citation[]
  missing_unit_ids: number[]
  faq_id?: number | null
  created_at: string
}

export const apiSessions = () => request<SessionItem[]>({ url: '/ai/sessions' })
export const apiSessionMessages = (id: number) =>
  request<ChatMessageItem[]>({ url: `/ai/sessions/${id}/messages` })
export const apiDeleteSession = (id: number) => request<{ ok: boolean }>({ url: `/ai/sessions/${id}`, method: 'delete' })

export interface StreamHandlers {
  onMeta?: (d: { session_id: number; message_id: number; faq_hit: boolean; faq_id?: number }) => void
  onCitation?: (d: Citation) => void
  onMissing?: (d: { unit_ids: number[]; items: Array<{ unit_id: number; unit_code: string; title: string }>; message: string | null }) => void
  onDelta?: (text: string) => void
  onDone?: (d: Record<string, unknown>) => void
  onError?: (d: { code: string; message: string }) => void
}

/** 调用 SSE 问答接口；返回中止函数（停止生成） */
export function streamChat(question: string, sessionId: number | null, handlers: StreamHandlers) {
  const controller = new AbortController()

  ;(async () => {
    let resp: Response
    try {
      resp = await fetch('/api/ai/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY) ?? ''}`,
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({ question, session_id: sessionId }),
        signal: controller.signal,
      })
    } catch (e) {
      if ((e as Error).name !== 'AbortError') handlers.onError?.({ code: 'NETWORK', message: '网络异常，请稍后重试' })
      return
    }
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}))
      handlers.onError?.({ code: body.code ?? String(resp.status), message: body.message ?? `请求失败（${resp.status}）` })
      return
    }
    const reader = resp.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        // SSE 以空行分隔事件
        let sep: number
        while ((sep = buffer.indexOf('\n\n')) >= 0) {
          const raw = buffer.slice(0, sep)
          buffer = buffer.slice(sep + 2)
          let event = 'message'
          const dataLines: string[] = []
          for (const line of raw.split('\n')) {
            if (line.startsWith('event:')) event = line.slice(6).trim()
            else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
          }
          if (!dataLines.length) continue
          const data = JSON.parse(dataLines.join('\n'))
          if (event === 'meta') handlers.onMeta?.(data)
          else if (event === 'citation') handlers.onCitation?.(data)
          else if (event === 'missing') handlers.onMissing?.(data)
          else if (event === 'delta') handlers.onDelta?.(data.content ?? '')
          else if (event === 'done') handlers.onDone?.(data)
          else if (event === 'error') handlers.onError?.(data)
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') handlers.onError?.({ code: 'STREAM', message: '回答中断，请重试' })
    }
  })()

  return () => controller.abort()
}
