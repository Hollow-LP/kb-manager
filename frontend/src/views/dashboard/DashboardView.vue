<script setup lang="ts">
import {
  ChatDotRound, Coin, Collection, Refresh, Timer, User,
} from '@element-plus/icons-vue'
import { computed, onMounted, ref, type Component } from 'vue'

import { apiOverview, type DashboardOverview, type Granularity } from '@/api/dashboard'
import BaseChart from '@/components/BaseChart.vue'

const days = ref(30)
const granularity = ref<Granularity>('day')
const loading = ref(false)
const data = ref<DashboardOverview | null>(null)

const rangeOptions = [
  { label: '近 7 天', value: 7 },
  { label: '近 30 天', value: 30 },
  { label: '近 90 天', value: 90 },
  { label: '近 365 天', value: 365 },
]

async function load() {
  loading.value = true
  try {
    data.value = await apiOverview(days.value, granularity.value)
  } finally {
    loading.value = false
  }
}

onMounted(load)

const fmt = (n: number) => n.toLocaleString('zh-CN')
const fmtMs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`)
const pct = (v: number) => `${(v * 100).toFixed(0)}%`

/** 指标卡：图标、标题、值、说明 */
/** 指标卡：直接引用组件对象，避免字符串名在 script setup 中无法解析 */
const cards = computed<Array<{ key: string; icon: Component; color: string; label: string; value: string; sub: string }>>(() => {
  const m = data.value?.metrics
  if (!m) return []
  return [
    { key: 'visits', icon: ChatDotRound, color: '#409eff', label: 'Agent 访问次数', value: fmt(m.total_visits), sub: `近 ${m.days} 天问答总次数` },
    { key: 'uv', icon: User, color: '#67c23a', label: '独立访问人数（UV）', value: fmt(m.unique_visitors), sub: '按用户去重' },
    { key: 'units', icon: Collection, color: '#e6a23c', label: '知识单元总数', value: fmt(m.total_units), sub: '状态为生效' },
    { key: 'tokens', icon: Coin, color: '#f56c6c', label: '总 Token 消耗', value: fmt(m.total_tokens), sub: `FAQ 命中 ${m.faq_hits} 次` },
    { key: 'rt', icon: Timer, color: '#909399', label: '平均响应时间', value: fmtMs(m.avg_response_ms), sub: `P95 ${fmtMs(data.value?.response_time.p95 ?? 0)}` },
  ]
})

const baseGrid = { left: 40, right: 20, top: 40, bottom: 30 }

const trendOption = computed(() => {
  const t = data.value?.trend ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['访问次数', '独立人数'], right: 0, top: 0 },
    grid: baseGrid,
    xAxis: { type: 'category', data: t.map((p) => p.bucket.slice(5)), axisLabel: { hideOverlap: true } },
    yAxis: [{ type: 'value', name: '次数', minInterval: 1 }],
    series: [
      { name: '访问次数', type: 'bar', data: t.map((p) => p.visits), itemStyle: { color: '#409eff', borderRadius: [4, 4, 0, 0] } },
      { name: '独立人数', type: 'line', smooth: true, data: t.map((p) => p.uv), itemStyle: { color: '#67c23a' } },
    ],
  }
})

const tokenOption = computed(() => {
  const t = data.value?.tokens ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Prompt Tokens', 'Completion Tokens'], right: 0, top: 0 },
    grid: baseGrid,
    xAxis: { type: 'category', data: t.map((p) => p.bucket.slice(5)), axisLabel: { hideOverlap: true } },
    yAxis: { type: 'value', name: 'Tokens', axisLabel: { formatter: (v: number) => (v >= 10000 ? `${v / 10000}万` : String(v)) } },
    series: [
      { name: 'Prompt Tokens', type: 'bar', stack: 'tokens', data: t.map((p) => p.prompt_tokens), itemStyle: { color: '#a0cfff' } },
      { name: 'Completion Tokens', type: 'bar', stack: 'tokens', data: t.map((p) => p.completion_tokens), itemStyle: { color: '#409eff', borderRadius: [4, 4, 0, 0] } },
    ],
  }
})

const responseOption = computed(() => {
  const r = data.value?.response_time
  return {
    tooltip: { trigger: 'axis' },
    grid: baseGrid,
    xAxis: { type: 'category', data: r?.labels ?? [] },
    yAxis: { type: 'value', name: '次数', minInterval: 1 },
    series: [
      {
        name: '响应次数', type: 'bar', data: r?.counts ?? [],
        itemStyle: {
          borderRadius: [4, 4, 0, 0],
          color: (params: { dataIndex: number }) => (params.dataIndex >= 5 ? '#f56c6c' : '#79bbff'),
        },
      },
    ],
  }
})

const maxAsk = computed(() => Math.max(1, ...(data.value?.questions ?? []).map((q) => q.ask_count)))
</script>

<template>
  <div v-loading="loading" class="dashboard">
    <div class="toolbar">
      <el-segmented v-model="days" :options="rangeOptions" @change="load" />
      <el-radio-group v-model="granularity" @change="load">
        <el-radio-button value="day">按日</el-radio-button>
        <el-radio-button value="week">按周</el-radio-button>
      </el-radio-group>
      <span class="muted">统计口径：引用/告警为问答访问日志；时间按北京时间自然日。</span>
      <div class="spacer" />
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <el-row :gutter="16" class="cards">
      <el-col v-for="c in cards" :key="c.key" :xs="12" :sm="12" :md="Math.floor(24 / Math.max(cards.length, 1))">
        <el-card shadow="hover" class="metric-card">
          <div class="metric">
            <div class="metric-icon" :style="{ background: c.color + '1a', color: c.color }">
              <el-icon :size="22"><component :is="c.icon" /></el-icon>
            </div>
            <div class="metric-body">
              <div class="metric-label">{{ c.label }}</div>
              <div class="metric-value">{{ c.value }}</div>
              <div class="metric-sub">{{ c.sub }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mt">
      <el-col :xs="24" :lg="12">
        <el-card>
          <template #header><b>常见问题 TOP</b></template>
          <el-empty v-if="!data?.questions.length" :image-size="60" description="暂无问答数据" />
          <div v-else class="rank">
            <div v-for="(q, i) in data.questions" :key="q.question" class="rank-row" :title="q.question">
              <span class="rank-no" :class="`top${i + 1}`">{{ i + 1 }}</span>
              <span class="rank-text">{{ q.question }}</span>
              <span class="rank-bar">
                <span :style="{ width: `${(q.ask_count / maxAsk) * 100}%` }" />
              </span>
              <span class="rank-count">{{ q.ask_count }}</span>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12">
        <el-card>
          <template #header>
            <b>知识单元热度 TOP</b>
            <span class="muted ml">数值为被用于回答的次数</span>
          </template>
          <el-empty v-if="!data?.units.length" :image-size="60" description="暂无访问数据" />
          <el-table v-else :data="data.units" size="small" max-height="360">
            <el-table-column type="index" width="44" />
            <el-table-column label="单元" min-width="180">
              <template #default="{ row }">
                <div>{{ row.title }}</div>
                <div class="muted">{{ row.unit_code }} · {{ row.category ?? '未分类' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="引用次数" width="92" align="right">
              <template #default="{ row }"><b>{{ row.hit_count }}</b></template>
            </el-table-column>
            <el-table-column label="权限拦截" width="92" align="right">
              <template #default="{ row }">
                <el-tag v-if="row.denied_count" size="small" type="warning">{{ row.denied_count }}</el-tag>
                <span v-else class="muted">0</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mt">
      <el-col :xs="24" :lg="12">
        <el-card>
          <template #header><b>访问趋势</b></template>
          <BaseChart :option="trendOption" />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12">
        <el-card>
          <template #header><b>Token 消耗趋势</b></template>
          <BaseChart :option="tokenOption" />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mt">
      <el-col :xs="24" :lg="14">
        <el-card>
          <template #header><b>响应时间分布</b></template>
          <BaseChart :option="responseOption" />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="10">
        <el-card>
          <template #header><b>响应时间分位数</b></template>
          <div class="rt-stats">
            <div class="rt-item">
              <div class="rt-label">平均</div>
              <div class="rt-value">{{ fmtMs(data?.response_time.avg ?? 0) }}</div>
            </div>
            <div class="rt-item">
              <div class="rt-label">P50</div>
              <div class="rt-value">{{ fmtMs(data?.response_time.p50 ?? 0) }}</div>
            </div>
            <div class="rt-item">
              <div class="rt-label">P95</div>
              <div class="rt-value warn">{{ fmtMs(data?.response_time.p95 ?? 0) }}</div>
            </div>
            <div class="rt-item">
              <div class="rt-label">样本数</div>
              <div class="rt-value">{{ fmt(data?.response_time.samples ?? 0) }}</div>
            </div>
          </div>
          <el-divider />
          <el-descriptions :column="1" size="small">
            <el-descriptions-item label="FAQ 命中率">{{ pct(data?.metrics.faq_hit_rate ?? 0) }}</el-descriptions-item>
            <el-descriptions-item label="识别为知识缺口的提问">{{ fmt(data?.metrics.gap_questions ?? 0) }} 次</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.spacer {
  flex: 1;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.ml {
  margin-left: 8px;
  font-weight: normal;
}
.mt {
  margin-top: 16px;
}
.metric-card {
  margin-bottom: 12px;
}
.metric {
  display: flex;
  gap: 12px;
  align-items: center;
}
.metric-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.metric-label {
  color: var(--el-text-color-secondary);
  font-size: 12.5px;
}
.metric-value {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.3;
}
.metric-sub {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.rank {
  max-height: 380px;
  overflow-y: auto;
}
.rank-row {
  display: grid;
  grid-template-columns: 22px 1fr 120px 40px;
  gap: 8px;
  align-items: center;
  padding: 6px 0;
  font-size: 13px;
}
.rank-no {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  text-align: center;
  line-height: 20px;
  font-size: 12px;
  background: var(--el-fill-color);
  color: var(--el-text-color-secondary);
}
.rank-no.top1 {
  background: #f56c6c;
  color: #fff;
}
.rank-no.top2 {
  background: #e6a23c;
  color: #fff;
}
.rank-no.top3 {
  background: #909399;
  color: #fff;
}
.rank-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rank-bar {
  height: 6px;
  border-radius: 3px;
  background: var(--el-fill-color);
  overflow: hidden;
}
.rank-bar span {
  display: block;
  height: 100%;
  background: var(--el-color-primary);
  border-radius: 3px;
}
.rank-count {
  text-align: right;
  font-weight: 600;
}
.rt-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  text-align: center;
}
.rt-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.rt-value {
  font-size: 18px;
  font-weight: 600;
  margin-top: 4px;
}
.rt-value.warn {
  color: var(--el-color-warning);
}
</style>
