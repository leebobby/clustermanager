import { createRouter, createWebHistory } from 'vue-router'

/*
 * 四项导航, 以一键诊断为落地页。
 *
 * 没有"集群"页 —— 本工具一次只对着一台机台, 打开时选机台类型, 节点按模板加载。
 * 模板的修改入口在「机台与模板」里。
 *
 * PXE 部署与巡检管理仍然保留组件和后端路由, 前端不挂 —— 想恢复把注释放开即可。
 */
const routes = [
  {
    path: '/',
    name: 'Checkup',
    component: () => import('@/views/Checkup.vue'),
    meta: { title: '一键诊断' }
  },
  {
    path: '/network',
    name: 'NetworkMap',
    component: () => import('@/views/NetworkMap.vue'),
    meta: { title: '组网图' }
  },
  {
    path: '/machines',
    name: 'Machines',
    component: () => import('@/views/Machines.vue'),
    meta: { title: '机台与模板' }
  },
  {
    path: '/logs',
    name: 'Logs',
    component: () => import('@/views/Diagnose.vue'),
    meta: { title: '告警与日志' }
  },
  {
    path: '/alerts',
    name: 'Alerts',
    component: () => import('@/views/Alerts.vue'),
    meta: { title: '告警中心' }
  },
  // PXE 部署 / 巡检管理: 暂不展示, 恢复时放开这里和 App.vue 的 NAV
  // { path: '/pxe',    name: 'PXEDeploy', component: () => import('@/views/PXEDeploy.vue'), meta: { title: 'PXE部署' } },
  // { path: '/patrol', name: 'Patrol',    component: () => import('@/views/Patrol.vue'),    meta: { title: '巡检管理' } },

  // 未匹配到的路径(含 /clusters、/nodes 这些旧书签)统一兜回一键诊断, 避免白屏
  {
    path: '/:pathMatch(.*)*',
    redirect: '/'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  document.title = `${to.meta.title || '集群运维'} - Cluster Manager`
  next()
})

export default router
