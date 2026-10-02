/* ============================================================
 * 新版编辑器（模板骨架 + 就地富文本编辑）
 * 页面 = 无字装饰底图 + 可编辑文字层（794px 模板坐标系，整体缩放）
 * 编辑：点击直接打字；选中文字浮现格式工具栏
 * 数据：盒子富文本序列化 → 草稿云端保存；换模板内容自动跟随
 * 导出：写回模板原 docx → 原生 Word / PDF / 长图
 * ============================================================ */
(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  const PAGE_W = 794, PAGE_H = 1123;

  const State = {
    templateId: null,
    draftId: null,
    pageW: PAGE_W, pageH: PAGE_H,
    boxes: [],            // 结构里的编辑盒（含 meta）
    photoBoxes: [],
    bgUrl: '',
    photo: null,          // {rid, data(raw b64)}
    content: {},          // box_id -> {paragraphs:[...]} 用户编辑结果
    dirty: false,
  };

  const ROLE_LABELS = {
    basic: '基本信息', education: '教育背景', work: '工作经验',
    internship: '实习经验', project: '项目经验', campus: '校园经历',
    skill: '技能特长', honor: '荣誉证书', self: '自我评价',
    hobby: '兴趣爱好', custom: '其他'
  };
  const FIELD_LABELS = ['姓名', '名字', '性别', '年龄', '生日', '出生日期', '出生年月',
    '籍贯', '民族', '身高', '体重', '婚姻状况', '政治面貌', '现居', '现居地址', '现居城市',
    '所在城市', '地址', '住址', '学历', '专业', '毕业院校', '毕业学校', '手机', '手机号码',
    '电话', '联系电话', '邮箱', '电子邮箱', '微信', '微博', 'QQ', '工作经验', '工作年限',
    '求职意向', '应聘岗位', '期望职位'];

  /* ─────────────── 基础工具 ─────────────── */
  function toast(msg, type) {
    const t = $('toast');
    t.textContent = msg;
    t.className = 'ed-toast' + (type ? ' ' + type : '');
    t.hidden = false;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { t.hidden = true; }, 2400);
  }
  function showLoading(text) { $('loadingText').textContent = text || '处理中…'; $('loadingMask').hidden = false; }
  function hideLoading() { $('loadingMask').hidden = true; }

  function authHeader() {
    const t = localStorage.getItem('rz_token') || sessionStorage.getItem('rz_token')
      || localStorage.getItem('resume_planet_token') || sessionStorage.getItem('resume_planet_token');
    return t ? { Authorization: 'Bearer ' + t } : {};
  }
  async function apiGet(url) {
    const r = await fetch(url, { headers: authHeader() });
    if (!r.ok) {
      let d = {};
      try { d = await r.json(); } catch (e) {}
      throw new Error(d.detail || ('HTTP ' + r.status));
    }
    return r.json();
  }
  async function apiPostForm(url, fd) {
    const r = await fetch(url, { method: 'POST', headers: authHeader(), body: fd });
    if (!r.ok) {
      let d = {}; try { d = await r.json(); } catch (e) {}
      throw new Error(d.detail || ('HTTP ' + r.status));
    }
    return r;
  }

  function cleanTemplateText(s) {
    return String(s || '').replace(/\{\{[^}]*\}\}/g, '').replace(/\n{3,}/g, '\n\n');
  }
  function rgbToHex(color) {
    const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(color || '');
    if (!m) return '';
    return '#' + [1, 2, 3].map(i => (+m[i]).toString(16).padStart(2, '0')).join('').toUpperCase();
  }
  function ptFromPx(px) { return Math.round(px * 0.75 * 10) / 10; }

  /* ─────────────── 启动 ─────────────── */
  async function init() {
    if (!(await checkAuth())) return;
    bindUI();
    document.execCommand('defaultParagraphSeparator', false, 'div');

    const params = new URLSearchParams(location.search);
    const urlDraft = params.get('draft_id');
    const urlTpl = parseInt(params.get('template_id'), 10);

    if (urlDraft) {
      try {
        const d = await apiGet('/api/draft/' + urlDraft);
        State.draftId = d.id;
        if (d.data && d.data.richtext) {
          applySavedState(d.data.richtext);
          toast('已加载云端草稿', 'success');
        } else if (d.template_id) {
          State.templateId = d.template_id;
          toast('该草稿为经典版创建，已在新版中打开', '');
        }
      } catch (e) { console.warn(e); }
    }
    if (!State.templateId && Number.isInteger(urlTpl) && urlTpl > 0) {
      State.templateId = urlTpl;
    }
    if (!State.templateId) {
      const local = restoreLocal();
      if (!local) {
        toast('请先从模板中心或经典版选择模板', '');
        openTplModal();
      }
    }
    if (State.templateId) await loadTemplate(State.templateId);
  }

  async function checkAuth() {
    try { await apiGet('/api/me'); return true; }
    catch (e) {
      document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:14px;color:#666">' +
        '<div style="font-size:44px">🔐</div><div>请先登录后使用编辑器</div>' +
        '<a class="ed-btn ed-btn-primary" href="/login" style="text-decoration:none">去登录</a></div>';
      return false;
    }
  }

  function applySavedState(rt) {
    if (rt.template_id) State.templateId = rt.template_id;
    State.content = rt.boxes || {};
    State.photo = rt.photo || null;
  }

  /* ─────────────── 模板加载与渲染 ─────────────── */
  async function loadTemplate(tid) {
    State.templateId = tid;
    const paper = $('paper');
    $('rt2Loading').hidden = false;
    paper.querySelectorAll('.rt2-page').forEach(n => n.remove());
    try {
      const st = await apiGet('/api/richtext-structure/' + tid);
      State.pageW = st.page_w || PAGE_W;
      State.pageH = st.page_h || PAGE_H;
      State.boxes = st.boxes || [];
      State.photoBoxes = st.photo_boxes || [];
      State.bgUrl = st.bg_url || '';
      renderPage();
      renderNav();
      persistLocal();
    } catch (e) {
      paper.querySelectorAll('.rt2-page').forEach(n => n.remove());
      paper.insertAdjacentHTML('beforeend',
        '<div class="rt2-loading" style="min-height:420px"><div style="font-size:40px">😕</div>' +
        '<div>' + (e.message || '加载失败') + '</div>' +
        '<a class="ed-btn ed-btn-primary" href="/static/editor.html?template_id=' + tid + '" style="text-decoration:none">用经典版打开</a></div>');
    } finally {
      $('rt2Loading').hidden = true;
    }
  }

  function renderPage() {
    const paper = $('paper');
    paper.querySelectorAll('.rt2-page').forEach(n => n.remove());
    const wrap = document.createElement('div');
    wrap.className = 'rt2-page';
    wrap.style.width = State.pageW + 'px';
    wrap.style.height = State.pageH + 'px';
    if (State.bgUrl) {
      const bg = document.createElement('img');
      bg.className = 'rt2-bg';
      bg.src = State.bgUrl;
      bg.draggable = false;
      wrap.appendChild(bg);
    }
    const anchorJobs = [];
    for (const meta of State.boxes) {
      const box = buildBox(meta, anchorJobs);
      wrap.appendChild(box);
    }
    State.photoBoxes.forEach((pb, i) => {
      wrap.appendChild(buildPhoto(pb, i));
    });
    paper.appendChild(wrap);
    layoutScale();
    // 盒子已入 DOM：按 PDF 实测锚点校正每段位置（消除与 Word 的排版漂移）
    anchorJobs.forEach(job => applyAnchors(job.box, job.meta));
  }

  function buildBox(meta, anchorJobs) {
    const box = document.createElement('div');
    box.className = 'rt2-box';
    box.dataset.id = meta.id;
    box.contentEditable = 'true';
    box.style.left = pct(meta.x, State.pageW);
    box.style.top = pct(meta.y, State.pageH);
    box.style.width = pct(meta.w, State.pageW);
    box.style.minHeight = pct(meta.h, State.pageH);
    const f = meta.font || {};
    box.style.fontFamily = `'${(f.family || '微软雅黑').replace(/"/g, '')}', 'Microsoft YaHei', sans-serif`;
    box.style.fontSize = (f.size || 12) * 4 / 3 + 'px';
    box.style.color = f.color || '#333333';
    box.style.fontWeight = f.bold ? 700 : 400;
    if (f.italic) box.style.fontStyle = 'italic';
    const pr = meta.props || {};
    box.style.padding = `${pr.pt || 5}px ${pr.pr || 8}px ${pr.pb || 5}px ${pr.pl || 8}px`;
    if (pr.anchor === 'ctr') { box.style.display = 'flex'; box.style.flexDirection = 'column'; box.style.justifyContent = 'center'; }
    else if (pr.anchor === 'b') { box.style.display = 'flex'; box.style.flexDirection = 'column'; box.style.justifyContent = 'flex-end'; }

    // 内容：用户编辑过的用编辑结果，否则用模板原文（清占位符）
    const saved = State.content[meta.id];
    if (saved && saved.paragraphs) {
      fillParagraphs(box, saved.paragraphs);
    } else {
      const paras = (meta.paras && meta.paras.length) ? meta.paras : [{ text: meta.text || '' }];
      fillParagraphs(box, paras.map(p => ({ text: p.text, align: p.align, line: p.line, font: p.font })));
      // 模板原文 + 有 PDF 实测锚点 → 入 DOM 后精确对位
      if (meta.anchors && meta.anchors.some(a => a != null) && anchorJobs) {
        anchorJobs.push({ box, meta });
      }
    }
    attachBoxEvents(box, meta);
    return box;
  }

  /* 按 PDF 实测锚点校正段落位置：先统一实测行距，再测量流式位置，
     用相对偏移把每段精确放到 Word 渲染的位置上（不影響文档流） */
  function applyAnchors(box, meta) {
    const anchors = meta.anchors || [];
    const pitches = meta.pitches || [];
    const divs = Array.from(box.children).filter(d => d.tagName === 'DIV');
    divs.forEach((d, i) => {
      const lh = pitches[i] || meta.pitch;
      if (lh) d.style.lineHeight = lh + 'px';
    });
    divs.forEach((div, i) => {
      const a = anchors[i];
      if (!a || a.y == null) return;
      const cur = div.offsetTop;
      div.style.position = 'relative';
      div.style.top = Math.round(a.y - cur) + 'px';
      if (a.x) div.style.left = Math.round(a.x) + 'px';
    });
  }

  function fillParagraphs(box, paras) {
    box.innerHTML = '';
    for (const p of paras) {
      const div = document.createElement('div');
      // 段落自身字体（模板中各段字号/颜色常不同，盒子默认值只是兜底）
      if (p.font) {
        if (p.font.family) div.style.fontFamily = `'${String(p.font.family).replace(/"/g, '')}', 'Microsoft YaHei', sans-serif`;
        if (p.font.size) div.style.fontSize = p.font.size * 4 / 3 + 'px';
        if (p.font.color) div.style.color = p.font.color;
        div.style.fontWeight = p.font.bold ? 700 : 400;
        if (p.font.italic) div.style.fontStyle = 'italic';
      }
      if (p.runs && p.runs.length) {
        // 序列化格式：带样式 run
        for (const r of p.runs) {
          const span = document.createElement('span');
          span.textContent = r.text || '';
          if (r.bold) span.style.fontWeight = '700';
          if (r.italic) span.style.fontStyle = 'italic';
          if (r.underline) span.style.textDecoration = 'underline';
          if (r.size) span.style.fontSize = r.size * 4 / 3 + 'px';
          if (r.color) span.style.color = r.color;
          div.appendChild(span);
        }
      } else {
        div.textContent = cleanTemplateText(p.text || '');
      }
      if (p.align && !['left', 'auto'].includes(p.align)) {
        div.style.textAlign = p.align === 'both' ? 'justify' : p.align;
      }
      if (p.line) div.style.lineHeight = p.line;
      box.appendChild(div);
    }
    if (!box.children.length) box.appendChild(document.createElement('div'));
  }

  function buildPhoto(pb, index) {
    const layer = document.createElement('div');
    layer.className = 'rt2-photo' + (pb.shape === 'ellipse' ? ' rt2-ellipse' : '');
    layer.dataset.rid = pb.rid;
    layer.style.left = pct(pb.x, State.pageW);
    layer.style.top = pct(pb.y, State.pageH);
    layer.style.width = pct(pb.w, State.pageW);
    layer.style.height = pct(pb.h, State.pageH);
    // 仅在已替换照片时渲染 img，否则底图原生照片直接可见（避免破图图标）
    if (State.photo && State.photo.rid === pb.rid && State.photo.data) {
      const img = document.createElement('img');
      img.alt = '照片';
      img.src = 'data:image/jpeg;base64,' + State.photo.data;
      layer.appendChild(img);
    }
    const hint = document.createElement('span');
    hint.className = 'rt2-photo-hint';
    hint.textContent = '点击替换照片';
    layer.appendChild(hint);
    layer.addEventListener('click', () => {
      layer.dataset.pick = pb.rid;
      $('photoInput').click();
    });
    return layer;
  }

  function pct(v, total) { return (v / total * 100).toFixed(3) + '%'; }

  /* 页面缩放：容器宽度 → scale 因子（保持 794px 模板坐标系） */
  function layoutScale() {
    const wrapEl = $('previewWrap');
    const paper = $('paper');
    const page = paper.querySelector('.rt2-page');
    if (!page) return;
    const avail = Math.min(wrapEl.clientWidth - 40, 794);
    const scale = Math.min(1, avail / State.pageW);
    page.style.transformOrigin = 'top left';
    page.style.transform = `scale(${scale})`;
    paper.style.width = (State.pageW * scale) + 'px';
    paper.style.height = (State.pageH * scale) + 'px';
    paper.style.position = 'relative';
  }
  window.addEventListener('resize', layoutScale);

  /* ─────────────── 编辑事件 ─────────────── */
  function attachBoxEvents(box, meta) {
    box.addEventListener('focus', () => box.classList.add('rt2-active'));
    box.addEventListener('blur', () => {
      box.classList.remove('rt2-active');
      syncBox(box);          // 失焦时序列化该盒
      renderNavStates();
    });
    // 打字：只同步当前盒（不扫全文档），避免多盒子模板的打字卡顿
    box.addEventListener('input', () => { syncBox(box); markDirty(); scheduleAutosave(); });
  }

  let autosaveTimer = null;
  function scheduleAutosave() {
    clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(() => saveDraft(true), 2500);
  }
  function markDirty() {
    State.dirty = true;
  }
  /* 只序列化单个盒子 */
  function syncBox(box) {
    State.content[box.dataset.id] = serializeBox(box);
  }
  /* 全量同步（保存/导出前兜底：同步所有已聚焦改动过的盒子） */
  function syncAllBoxes() {
    document.querySelectorAll('.rt2-box').forEach(box => {
      State.content[box.dataset.id] = serializeBox(box);
    });
    State.dirty = true;
  }

  /* ─────────────── 富文本序列化 ─────────────── */
  function blockNodes(box) {
    // 标准化为块级序列：div/p/li（ul 的每项一个块）或散文本包一层
    const blocks = [];
    for (const child of Array.from(box.childNodes)) {
      if (child.nodeType === 3) {
        if (child.textContent.trim()) blocks.push({ node: child, pseudo: true });
      } else if (/^(DIV|P|H[1-6])$/.test(child.tagName)) {
        blocks.push({ node: child });
      } else if (/^(UL|OL)$/.test(child.tagName)) {
        for (const li of Array.from(child.children)) blocks.push({ node: li, bullet: true });
      } else {
        blocks.push({ node: child });
      }
    }
    return blocks;
  }

  function collectRuns(root, bullet) {
    const runs = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const text = node.textContent;
      if (!text || !text.trim()) {
        if (text && runs.length) runs[runs.length - 1].text += text.replace(/\S/, '');
        continue;
      }
      const el = node.parentElement;
      const cs = getComputedStyle(el);
      const weight = parseInt(cs.fontWeight) || 400;
      runs.push({
        text,
        bold: weight >= 600,
        italic: cs.fontStyle === 'italic',
        underline: (cs.textDecorationLine || cs.textDecoration || '').includes('underline'),
        size: ptFromPx(parseFloat(cs.fontSize)) || 12,
        color: rgbToHex(cs.color) || '#333333',
      });
    }
    if (bullet && runs.length) runs[0].text = '• ' + runs[0].text;
    // 合并相邻同格式 run
    const merged = [];
    for (const r of runs) {
      const last = merged[merged.length - 1];
      if (last && last.bold === r.bold && last.italic === r.italic && last.underline === r.underline
        && last.size === r.size && last.color === r.color) {
        last.text += r.text;
      } else merged.push(r);
    }
    return merged;
  }

  function serializeBox(box) {
    const paras = [];
    for (const blk of blockNodes(box)) {
      const el = blk.node;
      const cs = getComputedStyle(el);
      let align = cs.textAlign;
      if (align === 'start') align = 'left';
      if (align === 'end') align = 'right';
      const runs = collectRuns(el, blk.bullet);
      let line = null;
      const lh = parseFloat(cs.lineHeight);
      const fs = parseFloat(cs.fontSize);
      if (lh && fs) line = Math.round(lh / fs * 100) / 100;
      if (!runs.length) continue;   // 空段不导出，保持紧凑
      paras.push({ align: align || 'left', line, runs });
    }
    if (!paras.length) paras.push({ align: 'left', line: null, runs: [{ text: '', bold: false, italic: false, underline: false, size: 12, color: '#333333' }] });
    return { paragraphs: paras };
  }

  /* ─────────────── 格式工具栏 ─────────────── */
  function currentBox() {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return null;
    let node = sel.anchorNode;
    while (node) {
      if (node.classList && node.classList.contains('rt2-box')) return node;
      node = node.parentNode;
    }
    return null;
  }

  function onSelectionChange() {
    const sel = window.getSelection();
    const bar = $('fmtBar');
    if (!sel || sel.isCollapsed || !currentBox()) { bar.hidden = true; return; }
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    bar.hidden = false;
    const top = Math.max(64, rect.top - 46);
    const left = Math.min(window.innerWidth - 340, Math.max(8, rect.left));
    bar.style.top = top + 'px';
    bar.style.left = left + 'px';
    // 激活态反馈（B/I/U/对齐/列表）
    try {
      bar.querySelectorAll('button[data-cmd]').forEach(btn => {
        const cmd = btn.dataset.cmd;
        let on = false;
        if (['bold', 'italic', 'underline', 'justifyLeft', 'justifyCenter', 'justifyRight', 'insertUnorderedList'].includes(cmd)) {
          on = document.queryCommandState(cmd);
        }
        btn.style.background = on ? '#5B5CFF' : '';
        btn.style.color = on ? '#fff' : '';
      });
    } catch (e) {}
  }
  document.addEventListener('selectionchange', onSelectionChange);

  function exec(cmd, val) {
    document.execCommand(cmd, false, val == null ? null : val);
    const box = currentBox();
    if (box) syncBox(box);
    markDirty(); scheduleAutosave();
  }

  function bindUI() {
    $('saveBtn').addEventListener('click', () => saveDraft(false));
    $('classicBtn').addEventListener('click', () => {
      location.href = '/static/editor.html' + location.search;
    });
    $('tplBtn').addEventListener('click', openTplModal);
    document.querySelectorAll('[data-close-tpl]').forEach(b =>
      b.addEventListener('click', () => { $('tplModal').hidden = true; }));
    $('tplModal').addEventListener('click', e => { if (e.target === $('tplModal')) $('tplModal').hidden = true; });

    $('photoBtn').addEventListener('click', () => {
      if (!State.photoBoxes.length) { toast('该模板未识别到照片位', 'error'); return; }
      if (State.photoBoxes.length === 1) {
        document.querySelector('.rt2-photo').dataset.pick = State.photoBoxes[0].rid;
      } else {
        toast('页面上有 ' + State.photoBoxes.length + ' 个照片位，请直接点击要替换的那个', '');
        return;
      }
      $('photoInput').click();
    });
    $('photoInput').addEventListener('change', e => {
      const file = e.target.files[0];
      e.target.value = '';
      if (!file) return;
      const layer = document.querySelector(`.rt2-photo[data-pick]`) || document.querySelector('.rt2-photo');
      const rid = (layer && layer.dataset.pick) || (State.photoBoxes[0] || {}).rid;
      if (!rid) return;
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = reader.result;
        let img = layer.querySelector('img');
        if (!img) {
          img = document.createElement('img');
          layer.insertBefore(img, layer.firstChild);
        }
        img.src = dataUrl;
        State.photo = { rid, data: dataUrl.split(',')[1] };
        markDirty(); scheduleAutosave();
        toast('照片已替换，导出时生效', 'success');
      };
      reader.readAsDataURL(file);
    });

    const exportBtn = $('exportBtn'), exportMenu = $('exportMenu');
    exportBtn.addEventListener('click', e => { e.stopPropagation(); exportMenu.hidden = !exportMenu.hidden; });
    document.addEventListener('click', () => { exportMenu.hidden = true; });
    exportMenu.querySelectorAll('button[data-fmt]').forEach(b =>
      b.addEventListener('click', () => { exportMenu.hidden = true; doExport(b.dataset.fmt); }));

    document.querySelectorAll('.ed-tab').forEach(t => {
      t.addEventListener('click', () => {
        document.querySelectorAll('.ed-tab').forEach(x => x.classList.remove('active'));
        document.querySelectorAll('.ed-tab-pane').forEach(x => x.classList.remove('active'));
        t.classList.add('active');
        const pane = $('tab-' + t.dataset.tab);
        if (pane) pane.classList.add('active');
      });
    });

    // 格式工具栏
    const bar = $('fmtBar');
    bar.querySelectorAll('button[data-cmd]').forEach(btn => {
      btn.addEventListener('mousedown', e => e.preventDefault()); // 保持选区
      btn.addEventListener('click', () => exec(btn.dataset.cmd));
    });
    $('fmtSize').addEventListener('change', e => {
      const v = e.target.value;
      e.target.value = '';
      if (!v) return;
      applyFontSize(parseFloat(v));
    });
    $('fmtColor').addEventListener('input', e => {
      exec('foreColor', e.target.value);
      normalizeFontTags();
    });
    $('fmtLine').addEventListener('change', e => {
      const box = currentBox();
      if (!box) return;
      box.style.lineHeight = e.target.value || '';
      syncBox(box); markDirty(); scheduleAutosave();
    });

    window.addEventListener('beforeunload', e => {
      if (State.dirty) { e.preventDefault(); e.returnValue = ''; }
    });
  }

  function applyFontSize(pt) {
    // execCommand fontSize 只支持 1-7：先置 7，再把 font[size] 换成 span 样式
    exec('fontSize', '7');
    normalizeFontTags(`font-size: ${pt * 4 / 3}px`);
  }
  function normalizeFontTags(styleText) {
    document.querySelectorAll('font[size], font[color], font[face]').forEach(f => {
      const span = document.createElement('span');
      let style = styleText || '';
      if (f.getAttribute('size')) {
        const map = { '1': 10, '2': 13, '3': 16, '4': 18, '5': 24, '6': 32, '7': 48 };
        style += `; font-size: ${map[f.getAttribute('size')] || 16}px`;
      }
      if (f.getAttribute('color')) style += `; color: ${f.getAttribute('color')}`;
      if (f.getAttribute('face')) style += `; font-family: ${f.getAttribute('face')}`;
      span.setAttribute('style', style);
      while (f.firstChild) span.appendChild(f.firstChild);
      f.replaceWith(span);
    });
    const cb = currentBox();
    if (cb) syncBox(cb);
    markDirty(); scheduleAutosave();
  }

  /* ─────────────── 草稿 ─────────────── */
  const DRAFT_KEY = 'rz_editor2_draft';

  function persistLocal() {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(localPayload()));
    } catch (e) {}
  }
  function localPayload() {
    return { draftId: State.draftId, templateId: State.templateId,
      content: State.content, photo: State.photo };
  }
  function restoreLocal() {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (!raw) return false;
      const s = JSON.parse(raw);
      if (!s.templateId) return false;
      State.draftId = s.draftId || null;
      State.templateId = s.templateId;
      State.content = s.content || {};
      State.photo = s.photo || null;
      return true;
    } catch (e) { return false; }
  }

  function draftTitle() {
    // 取姓名盒的文字做标题
    for (const meta of State.boxes) {
      if (meta.role === 'basic' && /姓名/.test(cleanTemplateText(meta.text) + (State.content[meta.id] ? JSON.stringify(State.content[meta.id]) : ''))) {
        const c = State.content[meta.id];
        if (c) {
          const t = (c.paragraphs || []).map(p => p.runs.map(r => r.text).join('')).join(' ').trim();
          if (t) return t.slice(0, 20) + ' 的简历';
        }
      }
    }
    return '未命名简历';
  }

  async function saveDraft(silent) {
    syncAllBoxes();
    if (!silent) showLoading('正在保存…');
    try {
      const resp = await fetch('/api/draft/save', {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, authHeader()),
        body: JSON.stringify({
          draft_id: State.draftId,
          template_id: State.templateId,
          title: draftTitle(),
          data: { richtext: { template_id: State.templateId, boxes: State.content, photo: State.photo } },
        }),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const d = await resp.json();
      if (d.draft_id) State.draftId = d.draft_id;
      State.dirty = false;
      persistLocal();
      if (!silent) { toast('已保存到我的简历', 'success'); }
    } catch (e) {
      if (!silent) toast('保存失败：' + e.message, 'error');
      persistLocal();
    } finally {
      hideLoading();
    }
  }

  /* ─────────────── 导出 ─────────────── */
  async function doExport(fmt) {
    syncAllBoxes();
    await saveDraft(true);
    showLoading(fmt === 'docx' ? '正在生成 Word…' : fmt === 'pdf' ? '正在生成 PDF…' : '正在生成长图…');
    try {
      const fd = new FormData();
      fd.append('edits', JSON.stringify(State.content));
      if (State.photo && State.photo.rid && State.photo.data) {
        fd.append('photo_rid', State.photo.rid);
        fd.append('photo', State.photo.data);
      }
      fd.append('format', fmt);
      const r = await apiPostForm('/api/richtext-export/' + State.templateId, fd);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = fmt === 'docx' ? '简历.docx' : fmt === 'pdf' ? '简历.pdf' : '简历.png';
      document.body.appendChild(a); a.click();
      setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 150);
      toast('已开始下载', 'success');
    } catch (e) {
      toast('导出失败：' + e.message, 'error');
    } finally {
      hideLoading();
    }
  }

  /* ─────────────── 更换模板（内容跟随） ─────────────── */
  async function openTplModal() {
    $('tplModal').hidden = false;
    const grid = $('tplGrid');
    grid.innerHTML = '<p style="color:#999;font-size:13px">加载中…</p>';
    try {
      const tpls = await apiGet('/templates');
      grid.innerHTML = '';
      tpls.forEach(t => {
        const tile = document.createElement('div');
        tile.className = 'ed-tpl-mini' + (t.id === State.templateId ? ' active' : '');
        tile.innerHTML = `<img loading="lazy" src="${t.preview_url}" alt=""><div class="name"></div>`;
        tile.querySelector('.name').textContent = t.name;
        tile.addEventListener('click', async () => {
          if (t.id === State.templateId) return;
          markDirty();
          await saveDraft(true);
          showLoading('正在切换模板…');
          try {
            transferToTemplate(t.id);
          } finally { hideLoading(); }
          $('tplModal').hidden = true;
        });
        grid.appendChild(tile);
      });
    } catch (e) {
      grid.innerHTML = '<p style="color:#999;font-size:13px">模板列表加载失败</p>';
    }
  }

  /* 从当前盒子提取可迁移内容 → 灌入新模板 */
  function transferToTemplate(newTid) {
    syncAllBoxes();
    const oldMeta = State.boxes;
    const oldContent = State.content;

    // ① 从旧模板提取基础信息 profile + 各板块内容
    const profile = {};         // 标准键 -> 值
    const sectionParas = {};    // role -> [段落文本数组...]
    for (const meta of oldMeta) {
      const c = oldContent[meta.id];
      const lines = currentLines(meta.id, meta);
      if (!lines.length) continue;
      if (meta.kind === 'field') {
        for (const ln of lines) {
          const m = ln.match(/^([^：:]{1,12})[：:]\s*(.+)$/);
          if (m) {
            const std = stdKey(m[1]);
            if (std && m[2].trim()) profile[std] = m[2].trim();
          }
        }
        // 单值盒：姓名/求职意向等
        const plain = lines.join(' ').trim();
        if (lines.length === 1 && plain) {
          if (/\{\{姓名\}\}|^[\u4e00-\u9fa5]{2,4}$/.test(meta.text + plain)) profile.name = profile.name || plain;
        }
      } else if (meta.kind === 'content' && meta.role && meta.role !== 'basic') {
        if (!sectionParas[meta.role]) sectionParas[meta.role] = [];
        sectionParas[meta.role].push(lines);
      }
    }

    // 加载新模板结构后灌入
    console.log('[transfer] profile=', JSON.stringify(profile),
      '| sections=', JSON.stringify(Object.keys(sectionParas)),
      '| oldBoxes=', oldMeta.length);
    showLoading('正在解析新模板…');
    apiGet('/api/richtext-structure/' + newTid).then(st => {
      State.pageW = st.page_w || PAGE_W;
      State.pageH = st.page_h || PAGE_H;
      State.boxes = st.boxes || [];
      State.photoBoxes = st.photo_boxes || [];
      State.bgUrl = st.bg_url || '';
      State.content = {};   // 新模板从模板原文开始，逐步覆盖
      State.templateId = newTid;

      // ② 灌入：字段盒/基本信息盒按语义替换，内容盒按板块顺序填入
      const consumed = {};    // role -> 已使用的组数
      let filledFields = 0, filledContents = 0;
      for (const meta of State.boxes) {
        if (meta.kind === 'field' || (meta.kind === 'content' && meta.role === 'basic')) {
          const filled = fillFieldBox(meta, profile);
          if (filled) { State.content[meta.id] = filled; filledFields++; }
        } else if (meta.kind === 'content' && meta.role && meta.role !== 'basic') {
          const groups = sectionParas[meta.role] || [];
          const idx = consumed[meta.role] || 0;
          if (idx < groups.length) {
            State.content[meta.id] = toParas(groups[idx], meta);
            consumed[meta.role] = idx + 1;
            filledContents++;
          }
        }
      }
      console.log('[transfer] filledFields=', filledFields, 'filledContents=', filledContents);
      // 姓名特殊处理：基本信息区里「样例名是 2-4 个汉字」的盒子识别为姓名位
      if (profile.name) {
        for (const meta of State.boxes) {
          if (State.content[meta.id]) continue;
          if (meta.role === 'basic' && meta.kind === 'content') {
            const sample = cleanTemplateText(meta.text).trim();
            if (/^[\u4e00-\u9fa5]{2,4}$/.test(sample)) {
              State.content[meta.id] = toParas([profile.name], meta);
              break;
            }
          }
        }
      }
      renderPage();
      renderNav();
      persistLocal();
      scheduleAutosave();
      toast('已切换模板，内容已跟随', 'success');
    }).catch(e => {
      toast('新模板不支持新版编辑：' + e.message, 'error');
    }).finally(() => hideLoading());
  }

  function currentLines(boxId, meta) {
    const c = State.content[boxId];
    if (c && c.paragraphs) {
      return c.paragraphs.map(p => p.runs.map(r => r.text).join('')).filter(t => t.trim());
    }
    return cleanTemplateText(meta.text).split('\n').filter(t => t.trim());
  }

  function stdKey(label) {
    label = label.replace(/\s+/g, '').trim();
    for (const k of FIELD_LABELS) {
      if (label === k || label.includes(k)) {
        return { '姓名': 'name', '名字': 'name', '性别': 'gender', '年龄': 'age', '生日': 'birth_date',
          '出生日期': 'birth_date', '出生年月': 'birth_date', '籍贯': 'hometown', '民族': 'nation',
          '身高': 'height', '婚姻状况': 'marriage', '政治面貌': 'political_status', '现居': 'city',
          '现居地址': 'city', '现居城市': 'city', '所在城市': 'city', '地址': 'city', '住址': 'city',
          '学历': 'education_degree', '专业': 'major', '毕业院校': 'school', '毕业学校': 'school',
          '手机': 'phone', '手机号码': 'phone', '电话': 'phone', '联系电话': 'phone', '邮箱': 'email',
          '电子邮箱': 'email', '微信': 'wechat', '微博': 'weibo', 'QQ': 'qq', '工作经验': 'work_years',
          '工作年限': 'work_years', '求职意向': 'intention_job', '应聘岗位': 'intention_job',
          '期望职位': 'intention_job' }[k] || null;
      }
    }
    return null;
  }

  function fillFieldBox(meta, profile) {
    // 用新模板样例文字（含 {{占位符}}）推断该盒的字段类型，再以 profile 值替换
    const orig = meta.text || '';
    const lines = orig.split('\n');   // 原始行：保留占位符供替换
    const out = [];
    let changed = false;
    for (const ln of lines) {
      const m = ln.match(/^([^：:]{1,14})[：:]\s*(.*)$/);
      let newLine = ln;
      if (m) {
        const std = stdKey(m[1]);
        if (std && profile[std]) { newLine = m[1] + '：' + profile[std]; changed = true; }
      } else {
        const phs = [...orig.matchAll(/\{\{([^}]*)\}\}/g)].map(x => x[1]);
        for (const ph of phs) {
          const std = stdKey(ph);
          if (std && profile[std] && ln.includes('{{' + ph + '}}')) {
            newLine = ln.replace('{{' + ph + '}}', profile[std]);
            changed = true;
          }
        }
        // 单值盒按样例语义推断
        if (!changed && lines.length === 1) {
          const std = inferFieldBySample(ln);
          if (std && profile[std]) { newLine = profile[std]; changed = true; }
        }
      }
      out.push(newLine);
    }
    if (!changed) return null;
    return toParas(out, meta);
  }

  function inferFieldBySample(sample) {
    const s = (sample || '').trim();
    if (!s) return null;
    if (s.includes('@')) return 'email';
    if (/^[\d\s+\-()]{7,}$/.test(s)) return 'phone';
    if (/\d+\s*岁/.test(s)) return 'age';
    if (/^(男|女)$/.test(s)) return 'gender';
    if (/(大学|学院|学校)$/.test(s)) return 'school';
    return null;
  }

  function toParas(lines, meta) {
    const baseAlign = (meta.paras && meta.paras[0] && meta.paras[0].align) || 'left';
    return { paragraphs: lines.map(t => ({
      align: baseAlign, line: null,
      runs: [{ text: t, bold: false, italic: false, underline: false,
               size: (meta.font && meta.font.size) || 12,
               color: (meta.font && meta.font.color) || '#333333' }],
    })) };
  }

  /* ─────────────── 板块导航 ─────────────── */
  function renderNav() {
    const list = $('navList');
    list.innerHTML = '';
    const groups = {};
    for (const meta of State.boxes) {
      if (!meta.role) continue;
      (groups[meta.role] = groups[meta.role] || []).push(meta);
    }
    for (const role in groups) {
      const metas = groups[role];
      const titleMeta = metas.find(m => m.kind === 'title');
      const groupEl = document.createElement('div');
      groupEl.className = 'rt2-nav-group';
      const head = document.createElement('div');
      head.className = 'rt2-nav-head';
      head.textContent = (titleMeta ? cleanTemplateText(titleMeta.text).trim() : '') || ROLE_LABELS[role] || role;
      groupEl.appendChild(head);
      for (const meta of metas.filter(m => m.kind !== 'title')) {
        const item = document.createElement('button');
        item.className = 'rt2-nav-item';
        const snippet = (currentLines(meta.id, meta)[0] || '').trim();
        item.innerHTML = `<span class="txt"></span><span class="st"></span>`;
        item.querySelector('.txt').textContent = snippet.slice(0, 14) || (meta.kind === 'field' ? '待填写' : '内容区');
        const st = item.querySelector('.st');
        if (snippet) { st.textContent = '已填'; st.classList.add('filled'); }
        else st.textContent = '待填写';
        item.addEventListener('click', () => locateBox(meta.id));
        groupEl.appendChild(item);
      }
      list.appendChild(groupEl);
    }
  }
  function renderNavStates() { renderNav(); }

  function locateBox(boxId) {
    const box = document.querySelector(`.rt2-box[data-id="${boxId}"]`);
    if (!box) return;
    box.scrollIntoView({ behavior: 'smooth', block: 'center' });
    box.classList.add('rt2-flash');
    setTimeout(() => box.classList.remove('rt2-flash'), 1900);
    setTimeout(() => { box.focus(); }, 400);
  }

  /* ─────────────── 启动 ─────────────── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
