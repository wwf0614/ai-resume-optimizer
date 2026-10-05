/* ════════════════════════════════════════════════════════════════════
 * WPS 风格文档直接编辑模式（富文本模式）
 * ──────────────────────────────────────────────────────────────────
 * 结构：GET /api/richtext-structure/{tid}
 *   → { page_w, page_h, boxes[{id,x,y,w,h,font,paras,role,placeholders}],
 *       photo_boxes[], bg_url（无字装饰底图） }
 * 交互：盒子直接 contenteditable，点进文档即可修改，WPS 浮动工具栏
 *       提供字体/字号/加粗/颜色/对齐/撤销重做。
 * 导出：POST /api/richtext-export/{tid}（edits 富文本写回模板 docx，
 *       保留模板设计，支持 docx / pdf / png）。
 * 兼容：409（首次解析中）→ 倒计时自动重试；422（复杂版式）→ 回退
 *       经典热区模式；旧草稿 realBoxTexts 自动迁移为富文本编辑。
 * 依赖：editor.js 先加载并暴露 window.__edBridge（renderPreview /
 *       persistLocal / setDirtyTip / loadRealStructure / State 等）。
 * ════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  /* ── 基础工具（不依赖 editor.js 内部符号） ── */
  const $ = id => document.getElementById(id);
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function toast(msg, type) {
    const t = $('toast');
    if (!t) { console.log('[toast]', msg); return; }
    t.textContent = msg;
    t.className = 'ed-toast' + (type ? ' ' + type : '');
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { t.hidden = true; }, 2600);
  }
  function authHeader() {
    const t = localStorage.getItem('rz_token') || sessionStorage.getItem('rz_token')
      || localStorage.getItem('resume_planet_token') || sessionStorage.getItem('resume_planet_token');
    return t ? { Authorization: 'Bearer ' + t } : {};
  }
  async function apiGet(url) {
    const r = await fetch(url, { headers: authHeader() });
    const text = await r.text();
    let data = null; try { data = JSON.parse(text); } catch (e) {}
    if (!r.ok) throw new Error((data && data.detail) || ('HTTP ' + r.status));
    return data;
  }
  function bridge() { return window.__edBridge || null; }
  function cleanBoxText(raw) {
    return String(raw || '')
      .replace(/\{\{[^}]*\}\}/g, '')
      .replace(/^\s*\n+/, '')
      .replace(/\n{3,}/g, '\n\n')
      .trimEnd();
  }

  /* ── 模块状态 ── */
  let rtStructure = null;    // richtext 结构（boxes / photo_boxes / bg_url）
  let rtTemplateId = null;   // 结构所属模板 id（防换模板串数据）
  let rtEdits = {};          // 用户编辑 { boxId: {paragraphs:[...]} }
  let rtActive = false;      // 是否处于富文本模式
  let rtReqId = 0;           // 请求序号（竞态防护）
  let rtPollTimer = null;    // 409 构建中轮询定时器
  let rtPollLeft = 0;        // 剩余重试秒数
  let _boxDebounce = {};     // 每盒子输入防抖
  let _toolbarBuilt = false;
  let _activeBox = null;     // 当前聚焦盒子

  const ROLE_LABELS = {
    basic: '基本信息', education: '教育经历', work: '工作经历', internship: '实习经历',
    project: '项目经历', campus: '校园经历', skill: '技能特长', honor: '荣誉证书',
    self: '自我评价', hobby: '兴趣爱好', custom: '其他内容'
  };

  function isActive() { return !!(rtActive && rtStructure && rtTemplateId === stateTemplateId()); }
  function stateTemplateId() {
    const b = bridge();
    return b && b.State ? b.State.templateId : null;
  }

  function reset() {
    rtStructure = null; rtTemplateId = null; rtEdits = {}; rtActive = false;
    if (rtPollTimer) { clearTimeout(rtPollTimer); rtPollTimer = null; }
    rtHideToolbar();
    _activeBox = null;
  }

  /* ════════════════ 加载结构 ════════════════ */

  async function load(tid, opts) {
    opts = opts || {};
    if (!tid) return;
    const b = bridge();
    if (!b) return;
    const reqId = ++rtReqId;
    if (rtPollTimer) { clearTimeout(rtPollTimer); rtPollTimer = null; }
    try {
      const st = await apiGet('/api/richtext-structure/' + tid);
      if (reqId !== rtReqId || tid !== stateTemplateId()) return;  // 过期响应丢弃
      rtStructure = st;
      rtTemplateId = tid;
      rtActive = true;
      b.State.editorMode = 'richtext';
      seedFromClassic();          // 旧「真实模板热区」草稿迁移为富文本编辑
      render();
      renderNavPanel();
      b.persistLocal();
      if (!opts.silent) toast('已启用文档直接编辑：点进内容即可修改', 'success');
    } catch (e) {
      if (reqId !== rtReqId || tid !== stateTemplateId()) return;
      const msg = String(e.message || '');
      if (msg.indexOf('409') >= 0 || msg.indexOf('解析中') >= 0) {
        showBuildingPaper(msg);   // 首次解析 10~40 秒：倒计时自动重试
        return;
      }
      /* 422（复杂版式）或其他失败 → 回退经典热区模式 */
      rtActive = false;
      b.loadRealStructure(tid);
      if (msg.indexOf('422') >= 0 || msg.indexOf('复杂版式') >= 0) {
        toast('该模板为复杂版式，已切换为热区编辑模式', '');
      }
    }
  }

  /* 用户在模板弹窗点了缩略图：立即给出纸面反馈，再异步加载结构 */
  function switched(t) {
    reset();
    const b = bridge();
    if (b) b.persistLocal();
    showSwitchingPaper(t && t.name);
    load(t.id);
  }

  /* 旧真实模板草稿（realBoxTexts 纯文本）→ 富文本编辑，保住老用户内容 */
  function seedFromClassic() {
    const b = bridge();
    const classic = b ? (b.realBoxTexts || {}) : {};
    const keys = Object.keys(classic);
    if (!keys.length || Object.keys(rtEdits).length) return;
    keys.forEach(k => {
      const text = cleanBoxText(classic[k]);
      rtEdits[k] = { paragraphs: [{ align: null, line: null, runs: [{ text: text }] }] };
    });
  }

  /* ════════════════ 纸面渲染 ════════════════ */

  function boxHint(b) {
    const m = (b.placeholders && b.placeholders[0]) ||
      (String(b.text || '').match(/\{\{([^}]*)\}\}/) || [])[1];
    if (m) return '点击输入' + String(m).replace(/^(请输入|请填写)/, '');
    if (b.role && ROLE_LABELS[b.role]) return '点击输入' + ROLE_LABELS[b.role];
    return '点击输入内容';
  }

  function pt2px(pt) { return Math.round(parseFloat(pt || 12) * 4 / 3 * 10) / 10; }

  function paraStyle(p, bf) {
    const f = p.font || bf || {};
    let s = '';
    if (p.align && p.align !== 'left') s += 'text-align:' + p.align + ';';
    if (p.line) s += 'line-height:' + p.line + ';';
    if (f.family) s += 'font-family:"' + f.family + '";';
    if (f.size) s += 'font-size:' + pt2px(f.size) + 'px;';
    if (f.color) s += 'color:' + f.color + ';';
    if (f.bold) s += 'font-weight:700;';
    if (f.italic) s += 'font-style:italic;';
    return s;
  }

  function boxInnerHtml(b) {
    const paras = (b.paras && b.paras.length) ? b.paras : null;
    if (!paras) {
      const txt = cleanBoxText(b.text);
      return txt ? esc(txt).replace(/\n/g, '<br>') : '';
    }
    return paras.map(p => {
      const style = paraStyle(p, b.font);
      const text = cleanBoxText(p.text || '');
      const inner = text ? esc(text).replace(/\n/g, '<br>') : '';
      return style ? '<div style="' + style + '">' + inner + '</div>' : inner;
    }).join('');
  }

  function render() {
    const b = bridge();
    const paper = $('previewPaper');
    if (!paper || !rtStructure || !b) return;
    const st = rtStructure;
    const pw = st.page_w || 794, ph = st.page_h || 1123;

    /* 换模式必须先交还宽度控制权（与经典模式 rr-host 同一套约定） */
    paper.className = 'ed-paper rp-paper rt-host';
    paper.style.background = '';
    paper.innerHTML =
      '<div class="rtp-pages">' +
        '<div class="rtp-page" style="width:' + pw + 'px;min-height:' + ph + 'px;">' +
          (st.bg_url ? '<img class="rtp-bg" draggable="false" src="' + esc(st.bg_url) + '" alt="">' : '') +
          '<div class="rtp-layer">' +
            (st.boxes || []).map(boxHtml).join('') +
            (st.photo_boxes || []).map(photoBoxHtml).join('') +
          '</div>' +
        '</div>' +
      '</div>';

    paper.querySelectorAll('.rt-box[data-bid]').forEach(bindBox);
    paper.querySelectorAll('.rt-box-photo[data-pid]').forEach(bindPhotoBox);
    applyEdits(rtEdits);
    updateOverflowHint();
  }

  function boxHtml(b) {
    const f = b.font || {};
    const p0 = (b.paras && b.paras[0]) || {};
    let style = 'left:' + Math.round(b.x) + 'px;top:' + Math.round(b.y) + 'px;'
      + 'width:' + Math.round(b.w) + 'px;min-height:' + Math.round(b.h) + 'px;';
    if (f.family) style += 'font-family:"' + f.family + '";';
    if (f.size) style += 'font-size:' + pt2px(f.size) + 'px;';
    if (f.color) style += 'color:' + f.color + ';';
    if (f.bold) style += 'font-weight:700;';
    if (f.italic) style += 'font-style:italic;';
    style += 'text-align:' + (p0.align || 'left') + ';';
    if (p0.line) style += 'line-height:' + p0.line + ';';
    return '<div class="rt-box" data-bid="' + b.id + '" data-ph="' + esc(boxHint(b)) +
      '" style="' + style + '">' + boxInnerHtml(b) + '</div>';
  }

  function photoBoxHtml(pb) {
    const pid = pb.id != null ? pb.id : pb.rid;
    return '<div class="rt-box rt-box-photo" data-pid="' + esc(pid) +
      '" title="点击上传照片" style="left:' + Math.round(pb.x) + 'px;top:' + Math.round(pb.y) +
      'px;width:' + Math.round(pb.w) + 'px;height:' + Math.round(pb.h) + 'px;">' +
      '<span class="rt-photo-plus">＋</span></div>';
  }

  /* 切换模板骨架：即时反馈，避免「点了没反应」的等待感 */
  function showSwitchingPaper(name) {
    const paper = $('previewPaper');
    if (!paper) return;
    paper.className = 'ed-paper rp-paper rt-host';
    paper.innerHTML =
      '<div class="rt-loading-wrap">' +
        '<div class="rt-spinner"></div>' +
        '<div class="rt-loading-title">正在打开「' + esc(name || '模板') + '」</div>' +
        '<div class="rt-loading-sub">解析模板可编辑区域，通常只需几秒…</div>' +
      '</div>';
  }

  /* 首次解析（10~40 秒）：倒计时 + 自动重试，明确告知而不是干等 */
  function showBuildingPaper(msg) {
    const paper = $('previewPaper');
    if (!paper) return;
    rtPollLeft = 96;
    const paint = () => {
      const p = $('previewPaper');
      if (!p || !p.querySelector('.rt-building')) return;
      p.querySelector('.rt-count').textContent = Math.max(0, rtPollLeft) + ' 秒';
    };
    paper.className = 'ed-paper rp-paper rt-host';
    paper.innerHTML =
      '<div class="rt-loading-wrap rt-building">' +
        '<div class="rt-spinner"></div>' +
        '<div class="rt-loading-title">首次打开该模板，正在解析可编辑区域</div>' +
        '<div class="rt-loading-sub">需要把 Word 原件转成可编辑骨架，约需半分钟，请稍候（自动重试中，剩余 <b class="rt-count">-- 秒</b>）</div>' +
        (msg ? '<div class="rt-loading-err">' + esc(msg) + '</div>' : '') +
      '</div>';
    paint();
    if (rtPollTimer) clearInterval(rtPollTimer);
    rtPollTimer = setInterval(() => {
      rtPollLeft -= 4;
      paint();
      const tid = stateTemplateId();
      if (rtPollLeft <= 0 || !tid) {
        clearInterval(rtPollTimer); rtPollTimer = null;
        if (tid) {
          toast('模板解析超时，已切换为热区编辑模式', '');
          rtActive = false;
          const b = bridge(); if (b) b.loadRealStructure(tid);
        }
        return;
      }
      load(tid, { silent: true });
    }, 4000);
  }

  /* 内容溢出一页时的诚实提示（导出时后端会自动缩字，不丢内容） */
  function updateOverflowHint() {
    const page = document.querySelector('#previewPaper .rtp-page');
    if (!page) return;
    const ph = (rtStructure && rtStructure.page_h) || 1123;
    let hint = document.querySelector('#previewPaper .rt-overflow-chip');
    const over = page.scrollHeight > ph + 8;
    if (!over) { if (hint) hint.remove(); return; }
    if (!hint) {
      hint = document.createElement('div');
      hint.className = 'rt-overflow-chip';
      hint.textContent = '内容超出一页 A4，导出时将自动微缩字号';
      page.parentElement.appendChild(hint);
    }
  }

  /* ════════════════ 盒子事件（直接编辑） ════════════════ */

  function bindBox(box) {
    box.setAttribute('contenteditable', 'plaintext-only');
    try { if (box.contentEditable !== 'plaintext-only') box.setAttribute('contenteditable', 'true'); } catch (e) {}
    box.addEventListener('focus', () => {
      _activeBox = box;
      box.classList.add('rt-active');
      rtStyleWithCss();
      rtShowToolbar(box);
    });
    box.addEventListener('blur', () => {
      box.classList.remove('rt-active');
      serializeBox(box, true);
      /* 延迟隐藏：给工具栏按钮的 mousedown 留时间 */
      setTimeout(() => { if (!_activeBox) rtHideToolbar(); }, 180);
    });
    box.addEventListener('input', () => {
      ensureEmptyPlaceholder(box);
      scheduleBoxSerialize(box);
      updateOverflowHint();
    });
    box.addEventListener('paste', e => {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData('text/plain');
      document.execCommand('insertText', false, text || '');
    });
    box.addEventListener('keydown', e => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const k = String(e.key || '').toLowerCase();
      if (k === 'z') { e.preventDefault(); document.execCommand('undo'); }
      else if (k === 'y' || (k === 'z' && e.shiftKey)) { e.preventDefault(); document.execCommand('redo'); }
    });
  }

  function bindPhotoBox(box) {
    box.addEventListener('click', () => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*';
      input.onchange = () => {
        const file = input.files && input.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => {
          box.style.backgroundImage = 'url(' + reader.result + ')';
          box.classList.add('rt-photo-filled');
          const b = bridge();
          if (b) { b.setDirtyTip('已修改', 'dirty'); b.persistLocal(); }
        };
        reader.readAsDataURL(file);
      };
      input.click();
    });
  }

  function ensureEmptyPlaceholder(box) {
    if (!box.innerText.trim() && box.querySelectorAll('img').length === 0) {
      if (box.innerHTML !== '') box.innerHTML = '';
    }
  }

  function scheduleBoxSerialize(box) {
    const bid = box.dataset.bid;
    clearTimeout(_boxDebounce[bid]);
    _boxDebounce[bid] = setTimeout(() => serializeBox(box, true), 350);
  }

  function serializeBox(box, persist) {
    const bid = box.dataset.bid;
    if (bid == null) return;
    rtEdits[bid] = serializeBoxDom(box);
    if (persist) {
      const b = bridge();
      if (b) { b.setDirtyTip('已修改', 'dirty'); b.persistLocal(); }
    }
  }

  /* ════════════════ DOM ↔ 富文本序列化 ════════════════ */

  function rtStyleOf(elm) {
    const cs = getComputedStyle(elm);
    const td = String(cs.textDecorationLine || cs.textDecoration || '');
    return {
      bold: Number(cs.fontWeight) >= 600,
      italic: cs.fontStyle === 'italic',
      underline: td.indexOf('underline') >= 0,
      sizePx: parseFloat(cs.fontSize) || null,
      color: cs.color || null,
      family: String(cs.fontFamily || '').split(',')[0].replace(/["']/g, '').trim()
    };
  }
  function rtSameStyle(a, b2) {
    return a && b2 && a.bold === b2.bold && a.italic === b2.italic && a.underline === b2.underline
      && a.sizePx === b2.sizePx && a.color === b2.color && a.family === b2.family;
  }
  function rgbToHex(rgb) {
    const m = String(rgb || '').match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (!m) return null;
    return '#' + [m[1], m[2], m[3]].map(x => ('0' + Number(x).toString(16)).slice(-2)).join('').toUpperCase();
  }
  function runFromStyle(st, text) {
    return {
      text: text,
      bold: st.bold || null, italic: st.italic || null, underline: st.underline || null,
      size: st.sizePx ? Math.round(st.sizePx * 3 / 4 * 10) / 10 : null,   // px → pt
      color: rgbToHex(st.color), font: st.family || null
    };
  }

  /** 盒子 DOM → {paragraphs:[{align,line,runs:[...]}]}（导出格式） */
  function serializeBoxDom(box) {
    const st = rtStructure;
    const b0 = st ? (st.boxes || []).find(x => String(x.id) === String(box.dataset.bid)) : null;
    const baseLine = (b0 && b0.paras && b0.paras[0] && b0.paras[0].line) || null;
    const boxAlign = getComputedStyle(box).textAlign;
    const paras = [];
    let cur = null;
    function flush() {
      if (!cur) return;
      if (!cur.runs.length) cur.runs.push({ text: '' });
      paras.push({ align: cur.align || boxAlign || 'left', line: cur.line || baseLine, runs: cur.runs });
      cur = null;
    }
    function startFor(elm) {
      if (!cur) cur = { runs: [], align: null, line: null };
      if (cur.align == null && elm) {
        const cs = getComputedStyle(elm);
        cur.align = cs.textAlign && cs.textAlign !== 'start' ? cs.textAlign : null;
        const lh = parseFloat(cs.lineHeight);
        const fs = parseFloat(cs.fontSize);
        if (lh && fs && cs.lineHeight !== 'normal') cur.line = Math.round(lh / fs * 100) / 100;
      }
    }
    function addText(text, elm) {
      const parts = String(text).split('\n');
      parts.forEach((p, i) => {
        if (i > 0) flush();
        if (!p) return;
        startFor(elm);
        const stl = rtStyleOf(elm);
        const last = cur.runs[cur.runs.length - 1];
        if (last && last._st && rtSameStyle(last._st, stl)) { last.text += p; return; }
        const run = runFromStyle(stl, p);
        run._st = stl;
        cur.runs.push(run);
      });
    }
    function walk(node) {
      if (node.nodeType === 3) { addText(node.nodeValue, node.parentElement || box); return; }
      if (node.nodeType !== 1) return;
      const tag = node.tagName;
      if (tag === 'BR') { flush(); return; }
      if (tag === 'DIV' || tag === 'P') {
        flush();
        const before = paras.length;
        Array.from(node.childNodes).forEach(walk);
        flush();
        if (paras.length === before) {           // 空段（空行）
          cur = { runs: [{ text: '' }], align: getComputedStyle(node).textAlign, line: null };
          flush();
        }
        return;
      }
      Array.from(node.childNodes).forEach(walk);
    }
    Array.from(box.childNodes).forEach(walk);
    flush();
    if (!paras.length) paras.push({ align: boxAlign || 'left', line: baseLine, runs: [{ text: '' }] });
    /* 清掉序列化辅助字段 */
    paras.forEach(p => p.runs.forEach(r => { delete r._st; }));
    return { paragraphs: paras };
  }

  /** 已保存编辑 → 盒子 DOM（草稿恢复用） */
  function applyEditsToBox(box, payload) {
    if (!payload || !Array.isArray(payload.paragraphs)) return;
    box.innerHTML = '';
    payload.paragraphs.forEach(p => {
      const div = document.createElement('div');
      if (p.align && p.align !== 'left') div.style.textAlign = p.align;
      if (p.line) div.style.lineHeight = String(p.line);
      (p.runs && p.runs.length ? p.runs : [{ text: '' }]).forEach(r => {
        let node;
        const text = String(r.text || '');
        if (r.bold || r.italic || r.underline || r.size || r.color || r.font) {
          const span = document.createElement('span');
          if (r.bold) span.style.fontWeight = '700';
          if (r.italic) span.style.fontStyle = 'italic';
          if (r.underline) span.style.textDecoration = 'underline';
          if (r.size) span.style.fontSize = pt2px(r.size) + 'px';
          if (r.color) span.style.color = r.color;
          if (r.font) span.style.fontFamily = '"' + r.font + '"';
          span.textContent = text;
          node = span;
        } else {
          node = document.createTextNode(text);
        }
        div.appendChild(node);
      });
      box.appendChild(div);
    });
  }

  function applyEdits(edits) {
    const paper = $('previewPaper');
    if (!paper) return;
    Object.keys(edits || {}).forEach(bid => {
      const box = paper.querySelector('.rt-box[data-bid="' + bid + '"]');
      if (box) applyEditsToBox(box, edits[bid]);
    });
  }

  /* 导出用：全部盒子的完整富文本（未编辑的盒子用模板原文，保格式） */
  function collectEdits() {
    const paper = $('previewPaper');
    const edits = {};
    (rtStructure.boxes || []).forEach(b => {
      const box = paper ? paper.querySelector('.rt-box[data-bid="' + b.id + '"]') : null;
      if (box) { edits[b.id] = serializeBoxDom(box); return; }
      const paras = (b.paras && b.paras.length ? b.paras
        : [{ text: cleanBoxText(b.text), align: 'left', line: null }]).map(p => ({
          align: p.align || 'left', line: p.line || null,
          runs: [{
            text: cleanBoxText(p.text || ''),
            bold: !!(p.font && p.font.bold) || null,
            italic: !!(p.font && p.font.italic) || null,
            size: (p.font && p.font.size) || null,
            color: (p.font && p.font.color) || null,
            font: (p.font && p.font.family) || null
          }]
        }));
      edits[b.id] = { paragraphs: paras };
    });
    return edits;
  }

  function getEdits() { return rtEdits; }
  function getPhotoDataUrl() {
    const el2 = document.querySelector('#previewPaper .rt-box-photo.rt-photo-filled');
    if (!el2) return '';
    const m = String(el2.style.backgroundImage || '').match(/url\("?([^")]+)"?\)/);
    return m ? m[1] : '';
  }

  /* ════════════════ WPS 风格浮动工具栏 ════════════════ */

  function rtStyleWithCss() { try { document.execCommand('styleWithCSS', false, true); } catch (e) {} }

  function buildToolbar() {
    if (_toolbarBuilt || !$('body')) return;
    const bar = document.createElement('div');
    bar.id = 'rtToolbar';
    bar.className = 'rt-toolbar';
    bar.hidden = true;
    const sep = '<i class="rt-tb-sep"></i>';
    bar.innerHTML =
      '<button type="button" data-cmd="undo" title="撤销 (Ctrl+Z)">↶</button>' +
      '<button type="button" data-cmd="redo" title="重做 (Ctrl+Y)">↷</button>' +
      sep +
      '<select id="rtFontFamily" title="字体">' +
        '<option value="">字体</option>' +
        '<option value="微软雅黑">微软雅黑</option>' +
        '<option value="宋体">宋体</option>' +
        '<option value="黑体">黑体</option>' +
        '<option value="楷体">楷体</option>' +
        '<option value="仿宋">仿宋</option>' +
      '</select>' +
      '<select id="rtFontSize" title="字号">' +
        '<option value="">字号</option>' +
        [9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36].map(s =>
          '<option value="' + s + '">' + s + '</option>').join('') +
      '</select>' +
      '<button type="button" data-cmd="bold" title="加粗"><b>B</b></button>' +
      '<button type="button" data-cmd="italic" title="斜体"><i>I</i></button>' +
      '<button type="button" data-cmd="underline" title="下划线"><u>U</u></button>' +
      sep +
      '<label class="rt-tb-color" title="字体颜色">A<input type="color" id="rtColorInput" value="#333333"></label>' +
      sep +
      '<button type="button" data-cmd="justifyLeft" title="左对齐">⇤</button>' +
      '<button type="button" data-cmd="justifyCenter" title="居中">☰</button>' +
      '<button type="button" data-cmd="justifyRight" title="右对齐">⇥</button>' +
      sep +
      '<button type="button" data-cmd="removeFormat" title="清除格式">⌫</button>';
    document.body.appendChild(bar);

    bar.addEventListener('mousedown', e => {
      /* 防止工具栏抢焦点丢选区 */
      if (e.target.closest('select') || e.target.closest('input')) return;
      e.preventDefault();
    });
    bar.addEventListener('click', e => {
      const btn = e.target.closest('button[data-cmd]');
      if (!btn) return;
      e.preventDefault();
      execCmd(btn.dataset.cmd);
    });
    $('rtFontFamily').addEventListener('change', function () {
      if (!this.value) return;
      document.execCommand('fontName', false, this.value);
      this.value = '';
      touchActiveBox();
    });
    $('rtFontSize').addEventListener('change', function () {
      const pt = this.value;
      if (!pt) return;
      applyFontSize(pt + 'pt');
      this.value = '';
      touchActiveBox();
    });
    $('rtColorInput').addEventListener('input', function () {
      document.execCommand('foreColor', false, this.value);
      touchActiveBox();
    });
    document.addEventListener('selectionchange', () => {
      syncToolbarState();
      const sel = window.getSelection();
      const box = sel && sel.rangeCount && sel.anchorNode
        ? (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement).closest('.rt-box')
        : null;
      if (box && box.isContentEditable) {
        _activeBox = box;
        rtShowToolbar(box);
      } else if (!document.activeElement || !document.activeElement.closest || !document.activeElement.closest('.rt-box')) {
        /* 点击纸面空白处收起 */
        if (_activeBox && !document.hasFocus(_activeBox)) { /* 留给 blur 处理 */ }
      }
    });
    window.addEventListener('resize', () => { if (_activeBox) rtShowToolbar(_activeBox); });
    _toolbarBuilt = true;
  }

  function applyFontSize(ptCss) {
    /* execCommand fontSize 只有 1~7 档：先打 7 号再替换成精确 pt */
    document.execCommand('fontSize', false, '7');
    const box = _activeBox;
    if (!box) return;
    box.querySelectorAll('font[size="7"]').forEach(f => {
      const span = document.createElement('span');
      span.style.fontSize = ptCss;
      while (f.firstChild) span.appendChild(f.firstChild);
      f.replaceWith(span);
    });
  }

  function execCmd(cmd) {
    try { document.execCommand(cmd, false, null); } catch (e) {}
    syncToolbarState();
    touchActiveBox();
  }
  function touchActiveBox() {
    if (_activeBox) { serializeBox(_activeBox, true); updateOverflowHint(); }
  }

  function rtShowToolbar(box) {
    buildToolbar();
    const bar = $('rtToolbar');
    if (!bar) return;
    bar.hidden = false;
    const r = box.getBoundingClientRect();
    const top = r.top - 48 + window.scrollY;
    let left = r.left + window.scrollX;
    left = Math.max(12, Math.min(left, window.scrollX + window.innerWidth - bar.offsetWidth - 12));
    bar.style.top = Math.max(6, top) + 'px';
    bar.style.left = left + 'px';
    syncToolbarState();
  }
  function rtHideToolbar() {
    const bar = $('rtToolbar');
    if (bar) bar.hidden = true;
    _activeBox = null;
  }
  function syncToolbarState() {
    const bar = $('rtToolbar');
    if (!bar || bar.hidden) return;
    ['bold', 'italic', 'underline', 'justifyLeft', 'justifyCenter', 'justifyRight'].forEach(c => {
      const btn = bar.querySelector('button[data-cmd="' + c + '"]');
      if (!btn) return;
      let on = false;
      try { on = document.queryCommandState(c); } catch (e) {}
      btn.classList.toggle('on', on);
    });
  }

  /* 点击纸面空白处：收起工具栏 */
  document.addEventListener('mousedown', e => {
    if (!e.target.closest('.rt-box') && !e.target.closest('.rt-toolbar')) {
      rtHideToolbar();
    }
  });

  /* ════════════════ 右侧面板：文档导航 ════════════════ */

  function renderNavPanel() {
    const list = $('moduleList');
    if (!list || !rtStructure) return;
    list.innerHTML = '';
    const note = document.createElement('div');
    note.className = 'ed-nav-note';
    note.innerHTML = '<b>文档直接编辑模式</b><span>直接点击左侧文档内容即可修改，' +
      '选中文字可用浮动工具栏调字体、字号、颜色与对齐。右侧板块用于快速定位。</span>';
    list.appendChild(note);

    const boxes = rtStructure.boxes || [];
    const done = {};
    /* 有 role 的标题盒子 → 分组：标题 + 其后紧随的正文盒子 */
    const groups = [];
    boxes.forEach(b => {
      if (b.role && ROLE_LABELS[b.role]) {
        groups.push({ role: b.role, label: ROLE_LABELS[b.role], boxes: [b] });
      } else if (groups.length) {
        groups[groups.length - 1].boxes.push(b);
      } else {
        groups.push({ role: 'basic', label: '基本信息', boxes: [b] });
      }
    });
    groups.forEach(g => {
      const card = document.createElement('div');
      card.className = 'ed-nav-card';
      const filled = g.boxes.some(x => {
        const box = document.querySelector('#previewPaper .rt-box[data-bid="' + x.id + '"]');
        return box && String(box.innerText || '').trim().length > 0;
      });
      card.innerHTML = '<div class="ed-nav-head"><b>' + esc(g.label) + '</b>' +
        '<span class="' + (filled ? 'ok' : 'todo') + '">' + (filled ? '已填写' : '待填写') + '</span></div>' +
        '<div class="ed-nav-sub">' + g.boxes.length + ' 个可编辑区域 · 点击定位</div>';
      card.addEventListener('click', () => {
        const target = g.boxes.map(x =>
          document.querySelector('#previewPaper .rt-box[data-bid="' + x.id + '"]')).find(Boolean);
        if (!target) return;
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.classList.remove('rt-flash');
        void target.offsetWidth;
        target.classList.add('rt-flash');
        setTimeout(() => { try { target.focus(); } catch (e) {} }, 350);
      });
      list.appendChild(card);
    });
  }

  /* ════════════════ 导出 ════════════════ */

  async function exportAs(format) {
    const b = bridge();
    if (!b || !rtStructure) return;
    showLoadingRt(format === 'pdf' ? '正在生成 PDF…' : format === 'png' ? '正在生成长图…' : '正在生成 Word…');
    try {
      const fd = new FormData();
      fd.append('edits', JSON.stringify(collectEdits()));
      fd.append('format', format === 'pdf' ? 'pdf' : format === 'png' ? 'png' : 'docx');
      const photo = getPhotoDataUrl();
      if (photo) {
        const pb = (rtStructure.photo_boxes || [])[0];
        fd.append('photo_rid', String((pb && (pb.id != null ? pb.id : pb.rid)) || ''));
        fd.append('photo', photo.split(',')[1] || '');
      }
      const r = await fetch('/api/richtext-export/' + rtTemplateId, {
        method: 'POST', headers: authHeader(), body: fd
      });
      if (!r.ok) {
        const t = await r.text();
        let d = {}; try { d = JSON.parse(t); } catch (e) {}
        throw new Error(d.detail || d.error || ('HTTP ' + r.status));
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = format === 'pdf' ? '简历.pdf' : format === 'png' ? '简历.png' : '简历.docx';
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 120);
      toast((format === 'pdf' ? 'PDF' : format === 'png' ? '长图' : 'Word') + ' 已开始下载', 'success');
      if ((format === 'pdf' || format === 'docx') && typeof b.runAtsCheck === 'function') {
        b.runAtsCheck(blob, format);
      }
    } catch (e) {
      toast('导出失败：' + e.message, 'error');
    } finally {
      hideLoadingRt();
    }
  }
  function showLoadingRt(text) {
    const el3 = $('loadingMask'), t = $('loadingText');
    if (t) t.textContent = text || '处理中…';
    if (el3) el3.hidden = false;
  }
  function hideLoadingRt() { const el3 = $('loadingMask'); if (el3) el3.hidden = true; }

  /* ════════════════ 草稿持久化（与 editor.js 对接） ════════════════ */

  function snapshot() {
    return {
      rtActive: rtActive, rtStructure: rtStructure, rtTemplateId: rtTemplateId, rtEdits: rtEdits
    };
  }
  function restoreSnap(s) {
    if (!s) return;
    rtActive = !!s.rtActive;
    rtStructure = s.rtStructure || null;
    rtTemplateId = s.rtTemplateId || null;
    rtEdits = s.rtEdits || {};
  }
  function restoreLocal(s) {
    if (!s) return;
    if (s.rtEdits && typeof s.rtEdits === 'object') rtEdits = s.rtEdits;
    if (s.rtMode) { rtActive = true; rtTemplateId = s.rtTemplateId || s.templateId || null; }
  }
  function restoreCloud(d) {
    if (!d) return;
    if (d.richtext_edits && typeof d.richtext_edits === 'object') rtEdits = d.richtext_edits;
    if (d.richtext_mode) { rtActive = true; rtTemplateId = d.real_template_id || d.template_id || null; }
  }
  function editsForSave() { return rtEdits || {}; }
  function modeForSave() { return !!rtActive; }

  /* ════════════════ 模块对外 API ════════════════ */
  window.RichtextMode = {
    load, switched, render, isActive, reset,
    collectEdits, getEdits, exportAs,
    snapshot, restoreSnap, restoreLocal, restoreCloud,
    editsForSave, modeForSave, renderNavPanel
  };
})();
