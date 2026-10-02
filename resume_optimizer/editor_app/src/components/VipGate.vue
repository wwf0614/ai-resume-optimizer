<template>
  <div v-if="!passed" class="vip-gate">
    <div class="vip-gate-box">
      <div class="vip-gate-icon">🔐</div>
      <h3>请先登录</h3>
      <p>{{ msg }}</p>
      <div class="vip-gate-btns">
        <a class="ed-btn" href="/">返回首页</a>
        <a class="ed-btn ed-btn-primary" href="/login">去登录</a>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const passed = ref(false)
const msg = ref('正在校验登录状态…')

onMounted(async () => {
  const t = localStorage.getItem('resume_planet_token') || sessionStorage.getItem('resume_planet_token')
  try {
    const r = await fetch('/api/me', { headers: t ? { Authorization: 'Bearer ' + t } : {} })
    if (r.ok) { passed.value = true; return }
    msg.value = '请先登录后再使用在线编辑器。'
  } catch (e) {
    msg.value = '请先登录后再使用在线编辑器。'
  }
})
</script>
