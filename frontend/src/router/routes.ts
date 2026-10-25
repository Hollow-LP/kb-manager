import type { RouteRecordRaw } from 'vue-router'

/**
 * 业务路由：meta.permissions 决定是否出现在菜单并可进入（满足任一即可）。
 * 路由本身静态注册，守卫按权限拦截，避免动态 addRoute 带来的刷新时序问题。
 */
export const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'Login', component: () => import('@/views/login/LoginView.vue'), meta: { public: true, title: '登录' } },
  {
    path: '/',
    component: () => import('@/layouts/AppLayout.vue'),
    redirect: '/profile',
    children: [
      { path: 'profile', name: 'Profile', component: () => import('@/views/profile/ProfileView.vue'), meta: { title: '个人中心' } },
      {
        path: 'dashboard', name: 'Dashboard', component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: { title: '数据看板', icon: 'DataLine', permissions: ['dashboard:view'] },
      },
      {
        path: 'org/users', name: 'OrgUsers', component: () => import('@/views/org/UsersView.vue'),
        meta: { title: '用户管理', group: '组织架构', icon: 'User', permissions: ['org:user:view'] },
      },
      {
        path: 'org/roles', name: 'OrgRoles', component: () => import('@/views/org/RolesView.vue'),
        meta: { title: '角色管理', group: '组织架构', icon: 'Avatar', permissions: ['org:role:view'] },
      },
      {
        path: 'org/departments', name: 'OrgDepartments', component: () => import('@/views/org/DepartmentsView.vue'),
        meta: { title: '部门管理', group: '组织架构', icon: 'OfficeBuilding', permissions: ['org:dept:view'] },
      },
      {
        path: 'knowledge/import', name: 'KnowledgeImport', component: () => import('@/views/knowledge/ImportView.vue'),
        meta: { title: '知识导入中心', icon: 'Upload', permissions: ['knowledge:import:view'] },
      },
      {
        path: 'knowledge/units', name: 'KnowledgeUnits', component: () => import('@/views/knowledge/UnitsView.vue'),
        meta: { title: '可访问知识库', icon: 'Document', permissions: ['knowledge:unit:view'] },
      },
      {
        path: 'knowledge/units/new', name: 'KnowledgeUnitNew', component: () => import('@/views/knowledge/UnitDetailView.vue'),
        meta: { title: '新建知识单元', group: '知识管理', permissions: ['knowledge:unit:create'], hidden: true },
      },
      {
        path: 'knowledge/units/:id', name: 'KnowledgeUnitDetail',
        component: () => import('@/views/knowledge/UnitDetailView.vue'),
        meta: { title: '知识单元详情', group: '知识管理', permissions: ['knowledge:unit:view'], hidden: true },
      },
      {
        path: 'ai/chat', name: 'AiChat', component: () => import('@/views/ai/ChatWorkbench.vue'),
        meta: { title: 'AI 对话工作台', icon: 'ChatDotRound', permissions: ['ai:chat:view'] },
      },
      {
        path: 'settlement/faqs', name: 'SettlementFaqs', component: () => import('@/views/settlement/FaqReviewView.vue'),
        meta: { title: 'FAQ 推荐与审核', group: '知识沉淀', icon: 'Star', permissions: ['settlement:faq:view'] },
      },
      {
        path: 'settlement/published', name: 'SettlementPublished', component: () => import('@/views/settlement/PublishedFaqView.vue'),
        meta: { title: '已发布 FAQ 库', group: '知识沉淀', icon: 'Collection', permissions: ['settlement:faq:manage'] },
      },
      {
        path: 'settlement/gaps', name: 'SettlementGaps', component: () => import('@/views/settlement/KnowledgeGapView.vue'),
        meta: { title: '知识缺口', group: '知识沉淀', icon: 'Warning', permissions: ['settlement:gap:view'] },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('@/views/NotFoundView.vue'), meta: { public: true } },
]
