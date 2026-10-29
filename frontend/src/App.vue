<script setup lang="ts">
import { onMounted } from 'vue'
import { useLiveStore } from '@/stores/live'

const live = useLiveStore()
onMounted(() => live.start())
</script>

<template>
  <nav>
    <router-link to="/">Inicio</router-link> | 
    <router-link to="/workers">Trabajadores</router-link> | 
    <router-link to="/reports">Reportes</router-link>
  </nav>

  <router-view />
</template>

<style scoped>
nav { padding: 1rem; }
a { margin: 0 0.5rem; color: #42b983; text-decoration: none; }
.router-link-active { font-weight: bold; text-decoration: underline; }
</style>
