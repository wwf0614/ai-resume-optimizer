/* ══════════════════════════════════════════════════════════════════
   resume-render.js — 参数化 A4 简历渲染引擎
   ──────────────────────────────────────────────────────────────────
   取代旧 editor.js 里"11 套手写布局 × 硬编码模板 ID"的做法。

   模型：
     data  = 结构化简历数据（basic / intention / modules / order / visible）
     style = 外观参数（family / theme / font / fontSize / lineHeight / gap / padding / ...）

   两条路径：
     render(data, style)        → 重渲染 DOM（换版式族 / 内容变化时用）
     applyVars(el, style)       → 只写 CSS 变量（调字体/间距/配色时用，毫秒级）

   导出：window.ResumeRender
   ══════════════════════════════════════════════════════════════════ */
(function (global) {
  'use strict';

  var A4 = { w: 794, h: 1123 };

  /* ── 版式族：决定 DOM 结构与内容分区 ── */
  var FAMILIES = {
    single:    { name: '单栏经典', hint: '自上而下单列，最通用稳妥' },
    sidebar:   { name: '左侧栏',   hint: '左栏放联系与技能，右侧主内容' },
    headerBar: { name: '顶部横幅', hint: '顶部色带突出姓名与求职意向' },
    twoCol:    { name: '双栏紧凑', hint: '正文分两栏，适合经历较多' }
  };

  /* ── 配色主题 ──
     id 刻意与 editor.js 的 SKIN_PRESETS 对齐，使旧草稿里的 skin 字段可直用，无需映射 */
  var THEMES = {
    default: { name: '靛青',     accent: '#34549B', deep: '#27406F', soft: '#EDF1F8' },
    blue:    { name: '商务蓝',   accent: '#1E5AE8', deep: '#123FA8', soft: '#EAF1FE' },
    green:   { name: '清新绿',   accent: '#1FA67A', deep: '#12775A', soft: '#E7F7F1' },
    orange:  { name: '活力橙',   accent: '#E2691A', deep: '#A84A0F', soft: '#FDF0E6' },
    gray:    { name: '沉稳灰',   accent: '#4B5563', deep: '#1F2937', soft: '#F0F2F5' },
    wine:    { name: '酒红',     accent: '#A03A52', deep: '#6E2338', soft: '#FBEAF0' },
    teal:    { name: '青碧',     accent: '#0F766E', deep: '#0B5049', soft: '#E4F5F2' }
  };

  /* ── 字体预设 ──
     id 同样对齐 editor.js 的 FONT_PRESETS */
  var FONTS = {
    yahei:    { name: '微软雅黑', css: '"Microsoft YaHei","PingFang SC",sans-serif' },
    songti:   { name: '宋体',     css: '"SimSun","Songti SC",serif' },
    heiti:    { name: '黑体',     css: '"SimHei","Heiti SC",sans-serif' },
    kai:      { name: '楷体',     css: '"KaiTi","Kaiti SC",serif' },
    pingfang: { name: '苹方',     css: '"PingFang SC","Microsoft YaHei",sans-serif' }
  };

  /* ── 模块元数据（与 editor.js 的 MODULES 对应，此处自包含一份）── */
  var MODULE_META = {
    education:  { label: '教育背景', icon: '🎓', dataKey: 'education_info', kind: 'edu' },
    work:       { label: '工作经验', icon: '💼', dataKey: 'work_history',   kind: 'work' },
    internship: { label: '实习经验', icon: '🏢', dataKey: 'internship_info', kind: 'work' },
    project:    { label: '项目经验', icon: '🚀', dataKey: 'projects',        kind: 'project' },
    campus:     { label: '校园经历', icon: '🏛️', dataKey: 'campus_exp',     kind: 'project' },
    skill:      { label: '技能特长', icon: '⚡', dataKey: 'skill_info',      kind: 'skill' },
    honor:      { label: '荣誉证书', icon: '🏆', dataKey: 'honor_cert',      kind: 'honor' },
    self:       { label: '自我评价', icon: '✨', dataKey: 'self_evaluate',   kind: 'text' },
    hobby:      { label: '兴趣爱好', icon: '💡', dataKey: 'hobby',           kind: 'tags' },
    custom:     { label: '自定义',   icon: '📝', dataKey: 'custom',          kind: 'text' }
  };

  /* ── 默认外观参数 ── */
  var DEFAULT_STYLE = {
    family: 'single',
    theme: 'default',
    font: 'yahei',
    fontSize: 13,
    lineHeight: 1.72,
    gap: 20,
    padding: 44,
    nameSize: 30,
    photoSize: 92,
    photoShape: 'rect',
    sectionStyle: 'underline',
    fontScale: 1
  };

  /* 联系方式字段（进头部一行）与网格字段 */
  var CONTACT_KEYS  = ['phone', 'email', 'wechat', 'city'];
  var CONTACT_LABEL = { phone: '电话', email: '邮箱', wechat: '微信', city: '现居' };
  var SKIP_IN_GRID  = ['name', 'position'].concat(CONTACT_KEYS);
  var FIELD_LABEL = {
    gender: '性别', height: '身高', hometown: '籍贯', political_status: '政治面貌',
    birth_date: '出生日期', age: '年龄/工作年限', marriage: '婚姻状况',
    nation: '民族', education_degree: '学历', school: '毕业院校', major: '专业'
  };

  /* ══════════ 工具 ══════════ */

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function hasText(v) {
    if (v == null) return false;
    if (Array.isArray(v)) return v.length > 0;
    return String(v).trim() !== '';

  }

  function rangeText(x) {
    if (!x) return '';
    var s = x.start || x.begin || '';
    var e = x.current ? '至今' : (x.end || '');
    if (!s && !e) return x.period || '';
    if (!s) return e;
    if (!e) return s;
    return s + ' ~ ' + e;
  }

  function pick(o, keys) {
    if (!o) return '';
    for (var i = 0; i < keys.length; i++) {
      if (hasText(o[keys[i]])) return String(o[keys[i]]).trim();
    }
    return '';
  }

  /* ══════════ 数据规范化 ══════════ */

  /** 把一条记录规范化为统一条目：{ title, meta, sub, desc } */
  function normItem(x, kind) {
    if (typeof x === 'string') return { title: x, meta: '', sub: '', desc: '' };
    if (!x || typeof x !== 'object') return null;

    if (kind === 'edu') {
      var deg = [pick(x, ['degree']), pick(x, ['major'])].filter(Boolean).join(' · ');
      return { title: pick(x, ['school', 'name']), meta: rangeText(x), sub: deg, desc: pick(x, ['content', 'desc']) };
    }
    if (kind === 'work') {
      return { title: pick(x, ['company', 'name']), meta: rangeText(x), sub: pick(x, ['position', 'role']), desc: pick(x, ['content', 'desc']) };
    }
    if (kind === 'project') {
      return { title: pick(x, ['name', 'title']), meta: rangeText(x) || pick(x, ['period']), sub: pick(x, ['role', 'position']), desc: pick(x, ['content', 'desc']) };
    }
    if (kind === 'skill') {
      return { title: pick(x, ['name']), meta: pick(x, ['level']), sub: '', desc: pick(x, ['content', 'desc']) };
    }
    if (kind === 'honor') {
      return { title: pick(x, ['name']), meta: pick(x, ['time', 'date']), sub: pick(x, ['issuer']), desc: pick(x, ['content', 'desc']) };
    }
    /* 兜底：尽量抓常见字段 */
    return {
      title: pick(x, ['name', 'title', 'school', 'company']),
      meta: rangeText(x) || pick(x, ['period', 'time', 'date']),
      sub: pick(x, ['position', 'role', 'major', 'issuer']),
      desc: pick(x, ['content', 'desc'])
    };
  }

  /** 生成要渲染的区块列表（按 order/visible 过滤） */
  function buildSections(data) {
    var mods = data.modules || {};
    var visible = data.visible || {};
    var order = data.order || Object.keys(MODULE_META);
    var out = [];

    for (var i = 0; i < order.length; i++) {
      var key = order[i];
      if (key === 'basic' || key === 'intention') continue;   // 由头部承载
      if (visible[key] === false) continue;

      var meta = MODULE_META[key];
      if (!meta) continue;

      var raw = mods[meta.dataKey];
      var section = { key: key, label: meta.label, icon: meta.icon, kind: meta.kind, items: [], tags: [], text: '' };

      if (meta.kind === 'tags') {
        var arr = Array.isArray(raw) ? raw : String(raw || '').split(/[、,，\s]+/);
        section.tags = arr.map(function (t) { return String(t).trim(); }).filter(Boolean);
        if (!section.tags.length) continue;
      } else if (meta.kind === 'text') {
        section.text = String(raw == null ? '' : raw).trim();
        if (!section.text) continue;
      } else {
        var list = Array.isArray(raw) ? raw : (hasText(raw) ? String(raw).split('\n') : []);
        section.items = list.map(function (x) { return normItem(x, meta.kind); }).filter(function (it) {
          return it && (hasText(it.title) || hasText(it.desc));
        });
        if (!section.items.length) continue;
      }
      out.push(section);
    }
    return out;
  }

  /** 求职意向文本 */
  function buildIntention(data) {
    var it = data.intention;
    if (typeof it === 'string') return it.trim();
    if (it && typeof it === 'object') {
      var parts = [pick(it, ['position', 'job', 'target']), pick(it, ['city']), pick(it, ['salary'])];
      return parts.filter(Boolean).join(' · ');
    }
    return pick(data.basic || {}, ['position', 'intention']);
  }

  /* ══════════ 片段渲染 ══════════ */

  function photoHtml(data, style, inSidebar) {
    if (data.showPhoto === false) return '';
    var cls = 'rr-photo' + (style.photoShape === 'circle' ? ' is-circle' : '');
    var url = data.photo || '';
    var inner = url
      ? '<img src="' + esc(url) + '" alt="">'
      : '<div class="rr-photo-ph">照片</div>';
    return '<div class="' + cls + '">' + inner + '</div>';
  }

  function contactHtml(data) {
    var b = data.basic || {};
    var parts = [];
    for (var i = 0; i < CONTACT_KEYS.length; i++) {
      var k = CONTACT_KEYS[i];
      if (hasText(b[k])) parts.push('<span>' + esc(CONTACT_LABEL[k]) + '：' + esc(b[k]) + '</span>');
    }
    return parts.length ? '<div class="rr-contact">' + parts.join('') + '</div>' : '';
  }

  function basicGridHtml(data) {
    var b = data.basic || {};
    var fv = data.fieldVisible || {};
    var rows = [];
    Object.keys(FIELD_LABEL).forEach(function (k) {
      if (fv[k] === false) return;
      if (hasText(b[k])) {
        rows.push('<div class="rr-basic-row"><b>' + FIELD_LABEL[k] + '：</b>' + esc(b[k]) + '</div>');
      }
    });
    if (!rows.length) return '';
    var cls = 'rr-basic-grid' + (rows.length >= 9 ? ' is-3' : '');
    return '<div class="' + cls + '">' + rows.join('') + '</div>';
  }

  function sectionTitleHtml(sec, style) {
    var styleCls = style.sectionStyle && style.sectionStyle !== 'underline'
      ? ' is-' + style.sectionStyle : '';
    return '<div class="rr-sec-title' + styleCls + '">' +
      (sec.icon ? '<span class="rr-sec-ico">' + sec.icon + '</span>' : '') +
      '<span>' + esc(sec.label) + '</span></div>';
  }

  function itemHtml(it) {
    var head = '';
    if (hasText(it.title) || hasText(it.meta)) {
      head = '<div class="rr-item-head">' +
        (hasText(it.title) ? '<span class="rr-item-title">' + esc(it.title) + '</span>' : '<span></span>') +
        (hasText(it.meta) ? '<span class="rr-item-meta">' + esc(it.meta) + '</span>' : '') +
        '</div>';
    }
    if (hasText(it.sub)) {
      head += '<div class="rr-item-sub"><span>' + esc(it.sub) + '</span></div>';
    }
    var desc = hasText(it.desc) ? '<div class="rr-item-desc">' + esc(it.desc) + '</div>' : '';
    return '<div class="rr-item">' + head + desc + '</div>';
  }

  function sectionBodyHtml(sec) {
    if (sec.kind === 'tags') {
      return '<div class="rr-tags">' + sec.tags.map(function (t) {
        return '<span class="rr-tag">' + esc(t) + '</span>';
      }).join('') + '</div>';
    }
    if (sec.kind === 'text') {
      return '<div class="rr-item-desc">' + esc(sec.text) + '</div>';
    }
    return sec.items.map(itemHtml).join('');
  }

  function sectionsHtml(sections, style) {
    return sections.map(function (sec) {
      return '<section class="rr-sec" data-sec="' + sec.key + '">' +
        sectionTitleHtml(sec, style) + sectionBodyHtml(sec) + '</section>';
    }).join('');
  }

  /* ══════════ 各族 DOM 组装 ══════════ */

  function renderHead(data, style) {
    var b = data.basic || {};
    var intention = buildIntention(data);
    return '<div class="rr-head">' +
      '<div class="rr-head-main">' +
        '<div class="rr-name">' + esc(b.name || '姓名') + '</div>' +
        (intention ? '<div class="rr-intent">求职意向：' + esc(intention) + '</div>' : '') +
        contactHtml(data) +
      '</div>' +
      photoHtml(data, style) +
    '</div>';
  }

  function buildFamily(data, style, sections) {
    var fam = style.family || 'single';
    var body = sectionsHtml(sections, style);

    if (fam === 'sidebar') {
      /* 侧栏承载：照片 + 联系方式 + 基本信息 + 技能/兴趣 */
      var sideKeys = { skill: 1, hobby: 1 };
      var sideSecs = sections.filter(function (s) { return sideKeys[s.key]; });
      var mainSecs = sections.filter(function (s) { return !sideKeys[s.key]; });
      var b = data.basic || {};
      var sideHtml = '';
      if (data.showPhoto !== false) sideHtml += photoHtml(data, style, true);
      sideHtml += '<div class="rr-side-sec"><div class="rr-side-title">联系方式</div>' +
        CONTACT_KEYS.filter(function (k) { return hasText(b[k]); })
          .map(function (k) { return '<div class="rr-side-line">' + esc(CONTACT_LABEL[k]) + '：' + esc(b[k]) + '</div>'; })
          .join('') + '</div>';
      var otherRows = Object.keys(FIELD_LABEL).filter(function (k) {
        return hasText(b[k]) && (data.fieldVisible || {})[k] !== false;
      });
      if (otherRows.length) {
        sideHtml += '<div class="rr-side-sec"><div class="rr-side-title">基本信息</div>' +
          otherRows.map(function (k) {
            return '<div class="rr-side-line">' + FIELD_LABEL[k] + '：' + esc(b[k]) + '</div>';
          }).join('') + '</div>';
      }
      sideHtml += sectionsHtml(sideSecs, style);
      return '<div class="rr-page fam-sidebar">' +
        '<aside class="rr-side">' + sideHtml + '</aside>' +
        '<main class="rr-main">' +
          '<div class="rr-head" style="border-bottom:2px solid var(--rr-accent);padding-bottom:12px;margin-bottom:0">' +
            '<div class="rr-head-main">' +
              '<div class="rr-name">' + esc(b.name || '姓名') + '</div>' +
              (buildIntention(data) ? '<div class="rr-intent">求职意向：' + esc(buildIntention(data)) + '</div>' : '') +
            '</div>' +
          '</div>' +
          sectionsHtml(mainSecs, style) +
        '</main>' +
      '</div>';
    }

    if (fam === 'headerBar') {
      var b2 = data.basic || {};
      return '<div class="rr-page fam-headerBar">' +
        '<div class="rr-banner">' +
          '<div class="rr-head-main">' +
            '<div class="rr-name">' + esc(b2.name || '姓名') + '</div>' +
            (buildIntention(data) ? '<div class="rr-intent">' + esc(buildIntention(data)) + '</div>' : '') +
            contactHtml(data) +
          '</div>' +
          photoHtml(data, style) +
        '</div>' +
        basicGridHtml(data) +
        body +
      '</div>';
    }

    if (fam === 'twoCol') {
      return '<div class="rr-page fam-twoCol">' +
        renderHead(data, style) +
        (basicGridHtml(data) ? '<section class="rr-sec">' + basicGridHtml(data) + '</section>' : '') +
        '<div class="rr-cols">' + body + '</div>' +
      '</div>';
    }

    /* single */
    return '<div class="rr-page fam-single">' +
      renderHead(data, style) +
      (basicGridHtml(data) ? '<section class="rr-sec">' + basicGridHtml(data) + '</section>' : '') +
      body +
    '</div>';
  }

  /* ══════════ 对外 API ══════════ */

  /** 完整渲染：返回 A4 版面的 HTML 字符串 */
  function render(data, style) {
    data = data || {};
    style = normalizeStyle(style);
    var sections = buildSections(data);
    if (!sections.length && !hasText((data.basic || {}).name)) {
      return '<div class="rr-page rr-empty-page"><div class="rr-empty">' +
        '还没有内容<br>在左侧打开模块填写，预览会即时更新</div></div>';
    }
    var html = buildFamily(data, style, sections);
    return html;
  }

  function normalizeStyle(style) {
    var s = {};
    Object.keys(DEFAULT_STYLE).forEach(function (k) { s[k] = DEFAULT_STYLE[k]; });
    Object.keys(style || {}).forEach(function (k) { if (style[k] != null) s[k] = style[k]; });
    return s;
  }

  /** 主色直定：由 hex 派生 accent/deep/soft 三色（v3 自定义主色用） */
  function mixTheme(hex) {
    var m = /^#?([0-9a-fA-F]{6})$/.exec(String(hex || ''));
    if (!m) return THEMES.default;
    var v = m[1];
    function ch(i, f) {
      var c = parseInt(v.substr(i * 2, 2), 16);
      if (f <= 1) c = Math.round(c * f);
      else { var k = Math.min(f - 1, 1); c = Math.round(c + (255 - c) * k); }
      return ('0' + Math.max(0, Math.min(255, c)).toString(16)).slice(-2);
    }
    return {
      accent: '#' + v,
      deep: '#' + ch(0, 0.72) + ch(1, 0.72) + ch(2, 0.72),
      soft: '#' + ch(0, 1.88) + ch(1, 1.88) + ch(2, 1.88)
    };
  }

  /** 只更新外观变量（不重渲染 DOM）—— 调字体/间距/配色走这里，毫秒级 */
  function applyVars(el, style) {
    if (!el) return;
    var s = normalizeStyle(style);
    var th = s.accent ? mixTheme(s.accent) : (THEMES[s.theme] || THEMES.default);
    var ft = FONTS[s.font] || FONTS.yahei;
    var sc = s.fontScale || 1;
    el.style.setProperty('--rr-accent', th.accent);
    el.style.setProperty('--rr-accent-deep', th.deep);
    el.style.setProperty('--rr-accent-soft', th.soft);
    el.style.setProperty('--rr-font', ft.css);
    el.style.setProperty('--rr-fs', (s.fontSize * sc).toFixed(2) + 'px');
    el.style.setProperty('--rr-lh', s.lineHeight);
    el.style.setProperty('--rr-gap', s.gap + 'px');
    el.style.setProperty('--rr-pad', s.padding + 'px');
    el.style.setProperty('--rr-name-size', (s.nameSize * sc).toFixed(1) + 'px');
    el.style.setProperty('--rr-photo-size', s.photoSize + 'px');
    el.style.setProperty('--rr-radius', s.photoShape === 'circle' ? '999px' : '4px');
  }

  /** 渲染 + 应用变量的便捷封装 */
  function mount(container, data, style) {
    if (!container) return;
    var s = normalizeStyle(style);
    container.innerHTML = render(data, s);
    var page = container.querySelector('.rr-page');
    applyVars(page, s);
    return page;
  }

  /** 估算内容高度（用于提示"可能超过一页"），粗略但够用 */
  function estimatePages(pageEl) {
    if (!pageEl) return 1;
    var inner = pageEl.scrollHeight;
    return Math.max(1, Math.ceil(inner / A4.h));
  }

  global.ResumeRender = {
    A4: A4,
    FAMILIES: FAMILIES,
    THEMES: THEMES,
    FONTS: FONTS,
    DEFAULT_STYLE: DEFAULT_STYLE,
    render: render,
    applyVars: applyVars,
    mount: mount,
    normalizeStyle: normalizeStyle,
    buildSections: buildSections,
    mixTheme: mixTheme,
    estimatePages: estimatePages
  };
})(window);
