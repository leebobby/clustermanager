import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '仪表盘' }
  },
  {
    path: '/nodes',
    name: 'Nodes',
    component: () => import('@/views/Nodes.vue'),
    meta: { title: '节点管理' }
  },
  {
    path: '/pxe',
    name: 'PXEDeploy',
    component: () => import('@/views/PXEDeploy.vue'),
    meta: { title: 'PXE部署' }
  },
  {
    path: '/alerts',
    name: 'Alerts',
    component: () => import('@/views/Alerts.vue'),
    meta: { title: '告警中心' }
  },
  // 巡检管理暂未实现, 先注释掉, 后续想清楚交互再恢复
  // {
  //   path: '/patrol',
  //   name: 'Patrol',
  //   component: () => import('@/views/Patrol.vue'),
  //   meta: { title: '巡检管理' }
  // },
  {
    path: '/diagnose',
    name: 'Diagnose',
    component: () => import('@/views/Diagnose.vue'),
    meta: { title: '故障诊断' }
  },
  {
    path: '/network',
    name: 'NetworkMap',
    component: () => import('@/views/NetworkMap.vue'),
    meta: { title: '组网图' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  document.title = `${to.meta.title || '集群管理系统'} - Cluster Manager`
  next()
})

export default router