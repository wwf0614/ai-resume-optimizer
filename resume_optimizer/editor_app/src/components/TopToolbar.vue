<template>
  <header class="ed-header">
    <a class="ed-logo" href="/">
      <div class="ed-logo-mark">✦</div>
      <div>
        <div class="ed-logo-name">简历星球</div>
        <span class="ed-logo-tag">AI 智能优化</span>
      </div>
    </a>
    <a class="ed-btn-back" href="/my-resumes" title="返回我的简历">
      <span class="arr">←</span><span>我的简历</span>
    </a>

    <div class="ed-header-center">
      <div class="ed-toolbar">
        <el-popover placement="bottom" trigger="click" :width="280">
          <template #reference><button class="ed-tb-item">间距设置</button></template>
          <div>
            <div class="set-block">
              <div class="label">模块间距 {{ store.meta.moduleGap }}px</div>
              <el-slider :min="0" :max="20" v-model="metaDraft.moduleGap" @change="applyMeta" />
            </div>
            <div class="set-block">
              <div class="label">行距 {{ store.meta.lineHeight }}</div>
              <el-slider :min="1" :max="2" :step="0.05" v-model="metaDraft.lineHeight" @change="applyMeta" />
            </div>
            <div class="set-block">
              <div class="label">页面边距 {{ store.meta.pageMargin }}px</div>
              <el-slider :min="15" :max="60" v-model="metaDraft.pageMargin" @change="applyMeta" />
            </div>
          </div>
        </el-popover>

        <el-popover placement="bottom" trigger="click" :width="300">
          <template #reference><button class="ed-tb-item">皮肤设置</button></template>
          <div class="skin-grid">
            <div v-for="c in skins" :key="c" class="skin-cell" :class="{ active: store.meta.themeColor === c }"
                 :style="{ background: c }" @click="store.updateMeta({ themeColor: c })"></div>
          </div>
        </el-popover>

        <el-popover placement="bottom" trigger="click" :width="260">
          <template #reference><button class="ed-tb-item">Aa 正文字体</button></template>
          <div>
            <div class="set-block">
              <div class="label">字体</div>
              <el-select v-model="store.meta.fontFamily" style="width:100%" @change="save">
                <el-option v-for="f in fonts" :key="f" :label="f" :value="f" />
              </el-select>
            </div>
            <div class="set-block">
              <div class="label">字号 {{ store.meta.fontSize }}px</div>
              <el-slider :min="10" :max="20" v-model="store.meta.fontSize" @change="save" />
            </div>
          </div>
        </el-popover>

        <el-popover placement="bottom" trigger="click" :width="220">
          <template #reference><button class="ed-tb-item">标题封面</button></template>
          <div>
            <el-checkbox v-model="store.meta.cover" @change="save">启用封面页</el-checkbox>
          </div>
        </el-popover>

        <el-popover placement="bottom" trigger="click" :width="420">
          <template #reference><button class="ed-tb-item">更换模板</button></template>
          <div class="tpl-pop">
            <div v-if="!real.vipTemplates.length" class="tpl-empty">暂无 VIP 模板，请联系管理员在管理端上传</div>
            <div v-for="t in real.vipTemplates" :key="t.id" class="tpl-mini"
                 :class="{ active: real.templateId === t.id }" @click="pickTemplate(t)">
              <div class="tpl-mini-preview">
                <img v-if="t.preview_url" :src="t.preview_url" :alt="t.name" loading="lazy" />
                <div v-else class="no-preview">暂无预览</div>
                <span class="vip-badge">👑 VIP</span>
              </div>
              <div class="tpl-mini-name">{{ t.name }}</div>
            </div>
          </div>
        </el-popover>
      </div>
    </div>

    <div class="ed-header-right">
      <button class="ed-btn" @click="store.save()">💾 保存</button>
      <el-dropdown @command="exportFmt">
        <button class="ed-btn ed-btn-primary">📥 下载简历 ▾</button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="png">🖼️ 导出为图片 (.png)</el-dropdown-item>
            <el-dropdown-item command="pdf">📕 导出为 PDF (.pdf)</el-dropdown-item>
            <el-dropdown-item command="print">🖨️ 打印 / 另存 PDF</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <button class="ed-btn ed-btn-vip">开通VIP</button>
    </div>
  </header>
</template>

<script setup>
import { reactive, onMounted } from 'vue'
import { useResumeStore } from '../store/resumeStore'
import { useRealTemplateStore } from '../store/realTemplateStore'
import { exportResume } from '../utils/export'
import { exportRealTemplate } from '../utils/export'

const store = useResumeStore()
const real = useRealTemplateStore()
const metaDraft = reactive({
  moduleGap: store.meta.moduleGap,
  lineHeight: store.meta.lineHeight,
  pageMargin: store.meta.pageMargin
})
const skins = ['#5340f5', '#2f4f4f', '#1f6feb', '#0e9f6e', '#b91c1c', '#7c3aed', '#d97706', '#111827']
const fonts = ['微软雅黑', '宋体', '黑体', '楷体', '仿宋', 'Arial', 'Georgia']

onMounted(() => { if (!real.vipTemplates.length) real.loadVipTemplates() })

async function pickTemplate(t) {
  await real.loadStructure(t.id)
  store.save()
}

function applyMeta() {
  store.updateMeta({
    moduleGap: metaDraft.moduleGap,
    lineHeight: metaDraft.lineHeight,
    pageMargin: metaDraft.pageMargin
  })
}
function save() { store.save() }
function exportFmt(cmd) {
  if (real.active) exportRealTemplate(cmd, real)
  else exportResume(cmd, store)
}
</script>

<style scoped>
.ed-btn-back {
  display: inline-flex; align-items: center; gap: 7px; height: 38px; padding: 0 18px;
  border-radius: 999px; text-decoration: none; font-size: 13px; font-weight: 600;
  color: #5340f5; background: #f0edff; border: 1px solid #e4dcff;
  transition: all .2s; flex-shrink: 0;
}
.ed-btn-back:hover { background: #5340f5; color: #fff; border-color: transparent; box-shadow: 0 6px 16px rgba(83, 64, 245, .3); transform: translateX(-2px); }
.ed-btn-back .arr { font-size: 15px; line-height: 1; font-weight: 700; }
.set-block { margin-bottom: 14px; }
.set-block .label { font-size: 13px; color: #666; margin-bottom: 6px; }
.skin-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.skin-cell { height: 42px; border-radius: 8px; cursor: pointer; border: 3px solid transparent; }
.skin-cell.active { border-color: #5340f5; box-shadow: 0 0 0 2px rgba(83, 64, 245, .2); }
.tpl-pop { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.tpl-mini { border: 2px solid #e5e7eb; border-radius: 8px; cursor: pointer; overflow: hidden; background: #fff; }
.tpl-mini.active { border-color: #5340f5; }
.tpl-mini-preview { height: 110px; padding: 10px; }
.tpl-mini-preview { position: relative; height: 130px; padding: 0; }
.tpl-mini-preview img { width: 100%; height: 100%; object-fit: cover; object-position: top; display: block; }
.tpl-mini-preview .no-preview { height: 100%; display: flex; align-items: center; justify-content: center; background: #f5f3ff; color: #999; font-size: 12px; }
.vip-badge { position: absolute; top: 6px; left: 6px; background: linear-gradient(135deg, #a855f7, #7c3aed); color: #fff; font-size: 10px; font-weight: 700; border-radius: 999px; padding: 2px 7px; }
.tpl-mini-bar { height: 18px; border-radius: 2px; margin-bottom: 8px; }
.tpl-mini-line { height: 6px; background: #e5e7eb; border-radius: 2px; margin-bottom: 5px; }
.tpl-mini-line.short { width: 60%; }
.tpl-mini-name { padding: 7px; font-size: 12px; text-align: center; color: #333; border-top: 1px solid #f0f0f0; }
.tpl-empty { color: #999; font-size: 13px; padding: 30px 10px; text-align: center; }
</style>
