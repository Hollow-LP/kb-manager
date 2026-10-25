<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onMounted, ref } from 'vue'

import {
  apiDeleteSession,
  apiSessionMessages,
  apiSessions,
  streamChat,
  type ChatMessageItem,
  type Citation,
  type SessionItem,
} from '@/api/chat'
import CitationCard from '@/components/CitationCard.vue'
import MissingPermissionCard from '@/components/MissingPermissionCard.vue'
import StreamMarkdown from '@/components/StreamMarkdown.vue'

interface MissingInfo {
  unit_ids: number[]
  items: Array<{ unit_id: number; unit_code: string; title: string }>
  message: string | null
}

interface Turn extends ChatMessageItem {
  missing?: MissingInfo | null
}

const sessions = ref<SessionItem[]>([])
const activeId = ref<number | null>(null)
const turns = ref<Turn[]>([])
const question = ref('')
const streaming = ref(false)
const stopFn = ref<(() => void) | null>(null)
const scrollRef = ref<HTMLElement>()
const loadingMessages = ref(false)
const faqHit = ref(false)

const canSend = computed(() => question.value.trim().length > 0 && !streaming.value)

async function loadSessions() {
  sessions.value = await apiSessions()
}

async function openSession(id: number) {
  if (streaming.value) stop()
  activeId.value = id
  loadingMessages.value = true
  try {
    const msgs = await apiSessionMessages(id)
    turns.value = msgs.map((m) => ({ ...m, missing: null }))
  } finally {
    loadingMessages.value = false
  }
  await nextTick()
  scrollToBottom()
}

function newChat() {
  if (streaming.value) stop()
  activeId.value = null
  turns.value = []
  question.value = ''
}

async function removeSession(s: SessionItem) {
  try {
    await ElMessageBox.confirm(`删除会话「${s.title}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  await apiDeleteSession(s.id)
  if (activeId.value === s.id) newChat()
  await loadSessions()
}

function scrollToBottom() {
  const el = scrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function send() {
  const text = question.value.trim()
  if (!text || streaming.value) return
  question.value = ''
  turns.value.push({
    id: -Date.now(), role: 'user', content: text, citations: [], missing_unit_ids: [], created_at: new Date().toISOString(),
  })
  const answer: Turn = {
    id: -Date.now() - 1, role: 'assistant', content: '', status: 'streaming', citations: [],
    missing_unit_ids: [], created_at: new Date().toISOString(), missing: null,
  }
  turns.value.push(answer)
  streaming.value = true
  faqHit.value = false
  scrollToBottom()

  stopFn.value = streamChat(text, activeId.value, {
    onMeta: (d) => {
      activeId.value = d.session_id
      faqHit.value = d.faq_hit
      if (d.faq_hit) answer.faq_id = d.faq_id ?? null
    },
    onCitation: (c: Citation) => answer.citations.push(c),
    onMissing: (m) => {
      answer.missing = m
      answer.missing_unit_ids = m.unit_ids
    },
    onDelta: (delta) => {
      answer.content += delta
      scrollToBottom()
    },
    onDone: (d) => {
      answer.status = 'done'
      answer.id = Number(d.message_id ?? answer.id)
      if (d.warning) ElMessage.warning(String(d.warning))
      streaming.value = false
      stopFn.value = null
      loadSessions()
    },
    onError: (e) => {
      answer.status = 'failed'
      answer.content = answer.content || ''
      ElMessage.error(e.message)
      streaming.value = false
      stopFn.value = null
    },
  })
}

function stop() {
  stopFn.value?.()
  streaming.value = false
  stopFn.value = null
  const last = turns.value[turns.value.length - 1]
  if (last && last.status === 'streaming') last.status = 'stopped'
}

function onKeydown(e: KeyboardEvent) {
  // Enter 发送，Shift+Enter 换行
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}

const suggestions = ['出差住宿标准是多少？', '报销单被财务退回怎么办？', '年假有几天？', '入职第一周需要做什么？']

onMounted(async () => {
  await loadSessions()
  if (sessions.value.length) await openSession(sessions.value[0].id)
})
</script>

<template>
  <div class="workbench">
    <!-- 会话列表 -->
    <el-card class="sessions" body-class="sessions-body">
      <template #header>
        <div class="sessions-head">
          <span>历史对话</span>
          <el-button size="small" type="primary" icon="Plus" @click="newChat">新对话</el-button>
        </div>
      </template>
      <el-scrollbar class="sessions-scroll">
        <el-empty v-if="!sessions.length" :image-size="60" description="暂无对话" />
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session"
          :class="{ active: s.id === activeId }"
          @click="openSession(s.id)"
        >
          <div class="session-title">{{ s.title }}</div>
          <div class="session-meta">
            <span>{{ s.message_count }} 条 · {{ new Date(s.updated_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }}</span>
            <el-button link type="danger" size="small" @click.stop="removeSession(s)">删除</el-button>
          </div>
        </div>
      </el-scrollbar>
    </el-card>

    <!-- 对话区 -->
    <el-card class="chat" body-class="chat-body">
      <template #header>
        <div class="chat-head">
          <b>AI 知识问答</b>
          <div class="head-tags">
            <el-tag v-if="faqHit" size="small" type="success">FAQ 缓存命中</el-tag>
            <el-tag size="small" type="info" effect="plain">回答仅基于您有权访问的知识单元</el-tag>
          </div>
        </div>
      </template>

      <div ref="scrollRef" v-loading="loadingMessages" class="messages">
        <el-empty v-if="!turns.length" description="输入问题，开始基于知识库的智能问答">
          <div class="suggests">
            <el-button v-for="s in suggestions" :key="s" round size="small" @click="question = s; send()">{{ s }}</el-button>
          </div>
        </el-empty>

        <div v-for="t in turns" :key="t.id" class="turn" :class="t.role">
          <el-avatar v-if="t.role === 'assistant'" :size="30" class="avatar ai">AI</el-avatar>
          <div class="bubble" :class="t.role">
            <template v-if="t.role === 'user'">
              <div class="user-text">{{ t.content }}</div>
            </template>
            <template v-else>
              <MissingPermissionCard v-if="t.missing" :message="t.missing.message" :items="t.missing.items" />
              <StreamMarkdown v-if="t.content" :content="t.content" :streaming="t.status === 'streaming'" />
              <div v-else-if="t.status === 'streaming'" class="typing">正在检索知识库并生成回答…</div>
              <el-alert v-if="t.status === 'failed'" type="error" :closable="false" show-icon class="failed"
                        title="回答生成失败，请稍后重试" />
              <div v-if="t.status === 'stopped'" class="muted">（已停止生成）</div>
              <div v-if="t.faq_id && !t.citations.length" class="sources">
                <div class="sources-title">来源：已审核发布的 FAQ 标准答案（缓存命中）</div>
              </div>
              <div v-if="t.citations.length" class="sources">
                <div class="sources-title">引用来源</div>
                <CitationCard v-for="(c, i) in t.citations" :key="c.unit_id" :unit-code="c.unit_code" :title="c.title"
                              :score="c.score" :index="i + 1" />
              </div>
            </template>
          </div>
          <el-avatar v-if="t.role === 'user'" :size="30" class="avatar me">我</el-avatar>
        </div>
      </div>

      <div class="composer">
        <el-input
          v-model="question"
          type="textarea"
          :rows="3"
          resize="none"
          maxlength="2000"
          placeholder="请输入问题，Enter 发送，Shift+Enter 换行"
          @keydown="onKeydown"
        />
        <div class="composer-actions">
          <span class="muted">{{ question.length }}/2000</span>
          <el-button v-if="streaming" type="danger" plain @click="stop">停止生成</el-button>
          <el-button v-else type="primary" :disabled="!canSend" icon="Promotion" @click="send">发送</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.workbench {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
  height: calc(100vh - 56px - 40px);
}
.sessions {
  display: flex;
  flex-direction: column;
}
.sessions :deep(.sessions-body) {
  padding: 8px;
  flex: 1;
  overflow: hidden;
}
.sessions-scroll {
  height: 100%;
}
.sessions-head,
.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.session {
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 6px;
}
.session:hover {
  background: var(--el-fill-color-light);
}
.session.active {
  background: var(--el-color-primary-light-9);
}
.session-title {
  font-size: 13.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}
.chat {
  display: flex;
  flex-direction: column;
}
.chat :deep(.chat-body) {
  display: flex;
  flex-direction: column;
  flex: 1;
  padding: 0;
  overflow: hidden;
}
.head-tags {
  display: flex;
  gap: 8px;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}
.suggests {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}
.turn {
  display: flex;
  gap: 10px;
  margin-bottom: 18px;
  align-items: flex-start;
}
.turn.user {
  justify-content: flex-end;
}
.avatar.ai {
  background: var(--el-color-primary);
  font-size: 12px;
}
.avatar.me {
  background: var(--el-color-success);
  font-size: 12px;
}
.bubble {
  max-width: 82%;
  border-radius: 10px;
  padding: 10px 14px;
}
.bubble.assistant {
  background: var(--el-fill-color-lighter);
}
.bubble.user {
  background: var(--el-color-primary);
  color: #fff;
}
.user-text {
  white-space: pre-wrap;
  line-height: 1.7;
}
.typing {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.sources {
  margin-top: 12px;
  border-top: 1px dashed var(--el-border-color);
  padding-top: 8px;
}
.sources-title {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}
.failed {
  margin-top: 8px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.composer {
  border-top: 1px solid var(--el-border-color-light);
  padding: 12px 16px;
}
.composer :deep(.el-textarea__inner) {
  box-shadow: none;
  background: var(--el-fill-color-lighter);
}
.composer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}
@media (max-width: 1000px) {
  .workbench {
    grid-template-columns: 1fr;
    height: auto;
  }
  .sessions {
    display: none;
  }
}
</style>
