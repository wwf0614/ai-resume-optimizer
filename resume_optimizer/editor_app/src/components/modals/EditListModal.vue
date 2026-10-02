<template>
  <el-dialog v-model="visible" :title="sectionLabel" width="760px" destroy-on-close>
    <!-- 列表类模块：教育/工作/项目/实习/校园 -->
    <div v-if="isListSection" class="list-modal">
      <div class="list-side">
        <div v-for="(it, i) in list" :key="it.id" class="list-side-item"
             :class="{ active: current === i }" @click="current = i">
          <span>{{ sideTitle(it) }}</span>
          <button class="side-del" @click.stop="store.removeModuleItem(listKey, it.id)">✕</button>
        </div>
        <button class="ed-btn" style="width:100%;margin-top:10px" @click="addItem">+ 添加</button>
      </div>
      <div class="list-form" v-if="current !== null && list[current]">
        <div class="ed-form-grid">
          <template v-for="f in formDefs" :key="f.key">
            <div class="ed-field" :class="{ full: f.full }">
              <label>{{ f.label }}</label>
              <el-select v-if="f.key === 'degree'" v-model="list[current][f.key]" style="width:100%">
                <el-option v-for="d in ['大专','本科','硕士','博士']" :key="d" :label="d" :value="d" />
              </el-select>
              <input v-else v-model="list[current][f.key]" :placeholder="f.placeholder || ''" />
            </div>
          </template>
          <div class="ed-field full">
            <label>开始时间</label>
            <input type="date" v-model="list[current].startDate" />
          </div>
          <div class="ed-field full" v-if="!list[current].isCurrent">
            <label>结束时间</label>
            <input type="date" v-model="list[current].endDate" />
          </div>
          <div class="ed-field full">
            <el-checkbox v-model="list[current].isCurrent">至今</el-checkbox>
          </div>
          <div class="ed-field full">
            <label>详细描述</label>
            <TiptapEditor v-model="list[current].description" placeholder="输入工作内容、成果…" />
          </div>
        </div>
        <div style="display:flex;gap:8px;margin-top:10px">
          <button class="ed-btn" @click="move(-1)">↑ 上移</button>
          <button class="ed-btn" @click="move(1)">↓ 下移</button>
          <button class="ed-btn" style="margin-left:auto;color:#e5484d" @click="removeCurrent">删除当前</button>
        </div>
      </div>
    </div>

    <!-- 意向职位 -->
    <div v-else-if="sectionKey === 'job'" class="ed-form-grid">
      <div class="ed-field" v-for="f in jobFields" :key="f.key">
        <label>{{ f.label }}</label>
        <input v-model="store.jobIntention[f.key]" :placeholder="f.placeholder || ''" />
      </div>
    </div>

    <!-- 文本类：自我评价 / 自定义 -->
    <div v-else-if="sectionKey === 'selfEval' || sectionKey === 'custom'" class="ed-form-grid">
      <div v-if="sectionKey === 'custom'" class="ed-field full">
        <label>模块标题</label>
        <input v-model="store.custom.title" />
      </div>
      <div class="ed-field full">
        <label>内容</label>
        <TiptapEditor :model-value="textValue" @update:model-value="updateText" placeholder="输入内容…" />
      </div>
    </div>

    <!-- 标签类：技能 / 荣誉 / 兴趣 -->
    <div v-else class="ed-form-grid">
      <div class="ed-field full">
        <label>标签（回车添加）</label>
        <el-tag v-for="(t, i) in tags" :key="i" closable @close="removeTag(i)" style="margin:0 6px 6px 0">{{ t }}</el-tag>
        <el-input v-model="tagInput" placeholder="输入后按回车" @keyup.enter="addTag" style="margin-top:6px" />
      </div>
      <div class="ed-field full">
        <label>补充说明</label>
        <TiptapEditor :model-value="tagDesc" @update:model-value="updateTagDesc" placeholder="选填" />
      </div>
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
import { emptyItemFor } from '../../utils/resumeHelpers'
import TiptapEditor from '../editor/TiptapEditor.vue'

const props = defineProps({
  modelValue: Boolean,
  sectionKey: { type: String, default: 'workExp' },
  index: { type: Number, default: 0 }
})
const emit = defineEmits(['update:modelValue'])
const store = useResumeStore()

const visible = computed({ get: () => props.modelValue, set: v => emit('update:modelValue', v) })
const current = ref(0)
const tagInput = ref('')

const SECTION_LABELS = {
  education: '教育背景', work: '工作经验', project: '项目经历',
  internship: '实习经历', campus: '校园经历', job: '意向职位',
  skills: '特长技能', honors: '荣誉证书', selfEval: '自我评价',
  hobbies: '兴趣爱好', custom: '自定义'
}
const sectionLabel = computed(() => SECTION_LABELS[props.sectionKey] || '编辑')

const LIST_MAP = {
  education: 'educationExp', work: 'workExp', project: 'projectExp',
  internship: 'internshipExp', campus: 'campusExp'
}
const listKey = computed(() => LIST_MAP[props.sectionKey] || '')
const isListSection = computed(() => !!listKey.value)
const list = computed(() => store[listKey.value] || [])

const formDefs = computed(() => {
  const k = props.sectionKey
  if (k === 'education') {
    return [
      { key: 'school', label: '学校' }, { key: 'major', label: '专业' },
      { key: 'degree', label: '学历' }
    ]
  }
  if (k === 'work' || k === 'internship') {
    return [{ key: 'company', label: '公司' }, { key: 'position', label: '职位' }]
  }
  if (k === 'project') {
    return [{ key: 'name', label: '项目名称' }, { key: 'role', label: '担任角色' }]
  }
  if (k === 'campus') {
    return [{ key: 'title', label: '活动/组织' }, { key: 'role', label: '担任角色' }]
  }
  return []
})

function sideTitle(it) {
  return it.company || it.school || it.name || it.title || '（未命名）'
}
function addItem() {
  const item = store.addModuleItem(listKey.value)
  current.value = store[listKey.value].length - 1
}
function removeCurrent() {
  if (current.value === null) return
  const id = list.value[current.value].id
  store.removeModuleItem(listKey.value, id)
  current.value = Math.max(0, current.value - 1)
}
function move(dir) {
  if (current.value === null) return
  store.moveModuleItem(listKey.value, current.value, dir)
  current.value += dir
}

const jobFields = [
  { key: 'position', label: '期望职位' }, { key: 'city', label: '期望城市' },
  { key: 'salary', label: '期望薪资' }, { key: 'entryTime', label: '到岗时间' }
]

const textValue = computed(() =>
  props.sectionKey === 'custom' ? (store.custom.description || '') : (store.selfEvaluation.description || ''))
function updateText(v) {
  if (props.sectionKey === 'custom') store.updateTextSection('custom', { description: v })
  else store.updateTextSection('selfEvaluation', { description: v })
}

const tags = computed(() => (store[props.sectionKey] || {}).tags || [])
const tagDesc = computed(() => (store[props.sectionKey] || {}).description || '')
function addTag() {
  const t = tagInput.value.trim()
  if (!t) return
  store[props.sectionKey].tags.push(t)
  store.save()
  tagInput.value = ''
}
function removeTag(i) {
  store[props.sectionKey].tags.splice(i, 1)
  store.save()
}
function updateTagDesc(v) {
  store.updateTextSection(props.sectionKey, { description: v })
}

watch(() => props.modelValue, v => {
  if (v) {
    current.value = 0
    tagInput.value = ''
    if (isListSection.value && !list.value.length) store.addModuleItem(listKey.value)
  }
})

function save() {
  store.save()
  visible.value = false
}
</script>

<style scoped>
.list-modal { display: flex; gap: 14px; min-height: 380px; }
.list-side { width: 180px; flex-shrink: 0; border-right: 1px solid #f0f0f0; padding-right: 12px; }
.list-side-item {
  display: flex; align-items: center; padding: 9px 10px; border-radius: 6px;
  cursor: pointer; font-size: 13px; color: #555; margin-bottom: 6px; background: #f7f8fa;
}
.list-side-item.active { background: #5340f5; color: #fff; }
.list-side-item .side-del { margin-left: auto; border: none; background: transparent; color: inherit; cursor: pointer; }
.list-form { flex: 1; min-width: 0; }
</style>
