import { createRouter, createWebHistory } from 'vue-router'

/*
 * 四项导航, 以一键诊断为落地页。
 *
 * 原来的「仪表盘」并进了一键诊断 —— 现场要的是"这台机台有没有问题", 而不是
 * 一屏看板; 原来的「节点管理」并进「集群管理」, 节点本来就是集群的一部分;
 * 「故障诊断」里那套脚本维护挪到「告警与日志」, 它是给配脚本的人用的, 不是
 * 现场每天点的东西。
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
    path: '/clusters',
    name: 'Clusters',
    component: () => import('@/views/Clusters.vue'),
    meta: { title: '集群管理' }
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

  // 未匹配到的路径(含 /nodes、/diagnose 这些旧书签)统一兜回一键诊断, 避免白屏
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
