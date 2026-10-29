import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router' 
import HomeView from '@/views/HomeView.vue'


// Definimos las rutas usando el tipo RouteRecordRaw de TypeScript
const routes: Array<RouteRecordRaw> = [
  {
    path: '/',
    name: 'home',
    component: HomeView
  },
  {
    path: '/workers',
    name: 'workers',
    // Carga perezosa (Lazy loading): Excelente para optimizar el peso de la app
    component: () => import('@/views/WorkersView.vue')
  },
  {
    path: '/reports',
    name: 'reports',
    // Carga perezosa (Lazy loading): Excelente para optimizar el peso de la app
    component: () => import('@/views/ReportsView.vue')
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

export default router
