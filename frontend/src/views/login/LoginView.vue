<script setup lang="ts">
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import type { ApiError } from '@/api/http'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const router = useRouter()
const route = useRoute()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: '', password: '' })
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

/** 登录后的落地页：只接受站内路径，且不回到 403 或无权限页面 */
function resolveRedirect(): string {
  const raw = typeof route.query.redirect === 'string' ? route.query.redirect : ''
  if (!raw.startsWith('/') || raw.startsWith('/login') || raw.startsWith('/403')) return '/'
  try {
    const resolved = router.resolve(raw)
    const required = (resolved.meta.permissions as string[] | undefined) ?? []
    if (required.length && !store.hasAny(required)) return '/'
  } catch {
    return '/'
  }
  return raw
}

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  loading.value = true
  try {
    await store.login(form.username.trim(), form.password)
    ElMessage.success(`欢迎回来，${store.userInfo?.display_name ?? ''}`)
    router.replace(resolveRedirect())
  } catch (e) {
    ElMessage.error((e as ApiError)?.message || '登录失败')
  } finally {
    loading.value = false
  }
}

const demoAccounts = [
  { username: 'admin', label: '系统管理员' },
  { username: 'kbadmin', label: '知识管理员' },
  { username: 'user_tech', label: '普通用户（技术中心）' },
  { username: 'user_fin', label: '普通用户（财务中心）' },
]

function fill(username: string) {
  form.username = username
  form.password = 'Admin@123'
}
</script>

<template>
  <div class="login-page">
    <div class="panel">
      <div class="intro">
        <div class="logo">KB</div>
        <h1>知识库管理平台</h1>
        <p>知识维护 · 四维数据权限 · AI 鉴权问答 · 数据看板 · 知识沉淀</p>
      </div>
      <el-card class="card" shadow="always">
        <h2>账号登录</h2>
        <el-form ref="formRef" :model="form" :rules="rules" size="large" @submit.prevent="submit">
          <el-form-item prop="username">
            <el-input v-model="form.username" placeholder="用户名" prefix-icon="User" autocomplete="username" />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              prefix-icon="Lock"
              show-password
              autocomplete="current-password"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button type="primary" class="submit" :loading="loading" native-type="submit">登 录</el-button>
        </el-form>
        <div class="demo">
          <span>演示账号（密码均为 Admin@123）：</span>
          <el-link v-for="a in demoAccounts" :key="a.username" type="primary" underline="never" @click="fill(a.username)">
            {{ a.label }}
          </el-link>
        </div>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100%;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #1f2d3d 0%, #2b5876 60%, #4e4376 100%);
  padding: 24px;
}
.panel {
  width: min(960px, 100%);
  display: grid;
  grid-template-columns: 1.1fr 1fr;
  gap: 32px;
  align-items: center;
}
.intro {
  color: #fff;
}
.intro .logo {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: var(--el-color-primary);
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 18px;
}
.intro h1 {
  font-size: 30px;
  margin: 18px 0 10px;
}
.intro p {
  opacity: 0.75;
  line-height: 1.8;
}
.card h2 {
  margin: 4px 0 20px;
  font-size: 20px;
}
.submit {
  width: 100%;
}
.demo {
  margin-top: 16px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
}
@media (max-width: 760px) {
  .panel {
    grid-template-columns: 1fr;
  }
  .intro {
    text-align: center;
  }
  .intro .logo {
    margin: 0 auto;
  }
}
</style>
