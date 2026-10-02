<template>
  <el-dialog v-model="visible" title="基本信息" width="640px" destroy-on-close>
    <div class="ed-form-grid">
      <div class="ed-field"><label>姓名</label><input v-model="form.name" /></div>
      <div class="ed-field"><label>性别</label>
        <el-select v-model="form.gender" style="width:100%"><el-option label="男" value="男" /><el-option label="女" value="女" /></el-select>
      </div>
      <div class="ed-field"><label>出生日期</label><input v-model="form.birthday" placeholder="1995-01" /></div>
      <div class="ed-field"><label>手机号</label><input v-model="form.phone" /></div>
      <div class="ed-field"><label>邮箱</label><input v-model="form.email" /></div>
      <div class="ed-field"><label>民族</label><input v-model="form.nation" /></div>
      <div class="ed-field"><label>籍贯</label><input v-model="form.birthPlace" /></div>
      <div class="ed-field"><label>婚姻状况</label><input v-model="form.maritalStatus" /></div>
      <div class="ed-field"><label>工作年限</label><input v-model="form.workYears" /></div>
      <div class="ed-field"><label>政治面貌</label><input v-model="form.politicalStatus" /></div>
      <div class="ed-field"><label>身高</label><input v-model="form.height" /></div>
      <div class="ed-field"><label>体重</label><input v-model="form.weight" /></div>
      <div class="ed-field full"><label>头像</label><input v-model="form.avatar" placeholder="头像图片 URL" /></div>
    </div>
    <div style="margin-top:14px">
      <div style="font-size:13px;font-weight:600;margin-bottom:8px">自定义信息</div>
      <div v-for="(cf, i) in form.customFields" :key="i" style="display:flex;gap:8px;margin-bottom:8px">
        <input v-model="cf.label" placeholder="字段名" style="flex:1;height:34px;padding:0 10px;border:1px solid #e5e7eb;border-radius:6px" />
        <input v-model="cf.value" placeholder="字段值" style="flex:2;height:34px;padding:0 10px;border:1px solid #e5e7eb;border-radius:6px" />
        <button class="ed-btn" @click="store.removeCustomField(i)">删除</button>
      </div>
      <button class="ed-btn" @click="store.addCustomField()">+ 添加自定义信息</button>
    </div>
    <template #footer>
      <button class="ed-btn" @click="visible = false">取消</button>
      <button class="ed-btn ed-btn-primary" @click="save">保存</button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useResumeStore } from '../../store/resumeStore'

const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue'])
const store = useResumeStore()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v)
})
const form = ref({})

watch(() => props.modelValue, (v) => {
  if (v) form.value = JSON.parse(JSON.stringify(store.basicInfo))
})

function save() {
  store.updateBasic(form.value)
  visible.value = false
}
</script>
