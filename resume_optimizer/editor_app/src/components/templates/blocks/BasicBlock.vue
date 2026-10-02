<template>
  <div class="tpl-block basic-block">
    <div class="tpl-head"><span>{{ label }}</span></div>
    <div class="basic-body">
      <div class="basic-main">
        <div class="basic-name">{{ data.basicInfo.name || '（姓名待填写）' }}</div>
        <div class="basic-grid">
          <div v-for="f in basicFields" :key="f.key" class="basic-item">
            <span class="basic-label">{{ f.label }}：</span>
            <span class="basic-value">{{ f.value || '—' }}</span>
          </div>
          <div v-for="(cf, i) in data.basicInfo.customFields" :key="'cf' + i" class="basic-item">
            <span class="basic-label">{{ cf.label }}：</span>
            <span class="basic-value">{{ cf.value }}</span>
          </div>
        </div>
      </div>
      <div v-if="data.basicInfo.showAvatar && data.basicInfo.avatar" class="basic-avatar">
        <img :src="data.basicInfo.avatar" alt="头像" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ data: Object, label: String })

const basicFields = computed(() => {
  const b = props.data.basicInfo || {}
  const defs = [
    { key: 'gender', label: '性别' }, { key: 'birthday', label: '出生日期' },
    { key: 'phone', label: '手机' }, { key: 'email', label: '邮箱' },
    { key: 'nation', label: '民族' }, { key: 'birthPlace', label: '籍贯' },
    { key: 'maritalStatus', label: '婚姻状况' }, { key: 'workYears', label: '工作年限' },
    { key: 'politicalStatus', label: '政治面貌' }, { key: 'height', label: '身高' },
    { key: 'weight', label: '体重' }
  ]
  return defs.map(d => ({ key: d.key, label: d.label, value: b[d.key] }))
    .filter(f => (f.value || '').toString().trim())
})
</script>

<style scoped>
.basic-body { display: flex; gap: 14px; }
.basic-main { flex: 1; min-width: 0; }
.basic-name { font-size: 24px; font-weight: 700; color: var(--theme-color); margin-bottom: 8px; }
.basic-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 22px; }
.basic-item { font-size: 13px; }
.basic-label { color: #666; }
.basic-value { color: #222; }
.basic-avatar { width: 90px; height: 110px; border-radius: 4px; overflow: hidden; flex-shrink: 0; }
.basic-avatar img { width: 100%; height: 100%; object-fit: cover; }
</style>
