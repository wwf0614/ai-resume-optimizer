/* ══════════════════════════════════════════════════════════════════
   editor-v3.js — 结构化简历编辑器（三栏所见即所得）
   ──────────────────────────────────────────────────────────────────
   统一 JSON 数据模型（中文字段语义）：
     resume = { basic, modules{education,work,...}, order[], hidden[], showPhoto }
     theme  = { family, theme, primary, font, fontSize, lineHeight, gap,
                padding, nameSize, photoSize, photoShape, sectionStyle }
   模板/主题只是渲染层：更换 preset 只改 theme，内容零丢失。
   渲染复用 resume-render.js（view 层做 v3 key → dataKey 映射）；
   A4 所见即所得支持点击直改（contenteditable + 写回 state）。
   导出走 /api/export/{docx|pdf|png}（utils/resume_docx.py 生成）。
   ══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var A4 = { w: 794, h: 1123 };

  /* ───────── 元数据 ───────── */

  var MODULE_META = {
    education:  { label: '教育背景', icon: '🎓' },
    internship: { label: '实习经历', icon: '🏢' },
    work:       { label: '工作经验', icon: '💼' },
    project:    { label: '项目经验', icon: '🚀' },
    campus:     { label: '校园经历', icon: '🏛️' },
    skill:      { label: '技能特长', icon: '⚡' },
    honor:      { label: '荣誉证书', icon: '🏆' },
    self:       { label: '自我评价', icon: '✨' },
    hobby:      { label: '兴趣爱好', icon: '💡' },
    custom:     { label: '自定义',   icon: '📝' }
  };
  var DEFAULT_ORDER = ['education', 'internship', 'work', 'project', 'campus', 'skill', 'honor', 'self', 'hobby', 'custom'];

  /* 渲染层 dataKey 映射（resume-render 的 MODULE_META.dataKey） */
  var DATA_KEY = {
    education: 'education_info', internship: 'internship_info', work: 'work_history',
    project: 'projects', campus: 'campus_exp', skill: 'skill_info',
    honor: 'honor_cert', self: 'self_evaluate', hobby: 'hobby', custom: 'custom'
  };
  var OLD_KEY_MAP = {
    education_info: 'education', internship_info: 'internship', work_history: 'work',
    projects: 'project', campus_exp: 'campus', skill_info: 'skill',
    honor_cert: 'honor', self_evaluate: 'self', hobby: 'hobby', custom: 'custom'
  };

  /* 条目标题字段（与渲染器 normItem pick 对齐） */
  var TITLE_KEY = { education: 'school', work: 'company', internship: 'company', project: 'name', campus: 'name', skill: 'name', honor: 'name' };
  /* 决定一条记录是否会被渲染（renderer 过滤条件 title||desc 的镜像） */
  var RENDER_KEYS = {
    education: ['school', 'content'], work: ['company', 'content'], internship: ['company', 'content'],
    project: ['name', 'content'], campus: ['name', 'content'], skill: ['name', 'content'], honor: ['name', 'content']
  };
  var LIST_KINDS = ['education', 'internship', 'work', 'project', 'campus', 'skill', 'honor'];

  var CONTACT_KEYS = ['phone', 'email', 'wechat', 'city'];
  var CONTACT_LABEL = { phone: '电话', email: '邮箱', wechat: '微信', city: '现居' };
  var CONTACT_BY_LABEL = { '电话': 'phone', '邮箱': 'email', '微信': 'wechat', '现居': 'city' };
  var FIELD_LABEL = {
    gender: '性别', height: '身高', hometown: '籍贯', political_status: '政治面貌',
    birth_date: '出生日期', age: '年龄/工作年限', marriage: '婚姻状况',
    nation: '民族', education_degree: '学历', school: '毕业院校', major: '专业'
  };
  var FIELD_BY_LABEL = {};
  Object.keys(FIELD_LABEL).forEach(function (k) { FIELD_BY_LABEL[FIELD_LABEL[k]] = k; });

  /* 模块条目表单字段规格 */
  var DATE_FIELDS = [
    { k: 'start', l: '开始', t: 'date', ph: '点击选择年月' },
    { k: 'end', l: '结束', t: 'date', ph: '点击选择年月' }
  ];
  var FIELD_SPECS = {
    education: [
      { k: 'school', l: '学校' }, { k: 'degree', l: '学历', ph: '本科/硕士' },
      { k: 'major', l: '专业' }
    ].concat(DATE_FIELDS, [{ k: 'current', l: '至今', t: 'check' }, { k: 'content', l: '主修课程 / 校园表现', t: 'area' }]),
    internship: [{ k: 'company', l: '公司' }, { k: 'position', l: '岗位' }]
      .concat(DATE_FIELDS, [{ k: 'current', l: '至今', t: 'check' }, { k: 'content', l: '工作内容', t: 'area' }]),
    work: [{ k: 'company', l: '公司' }, { k: 'position', l: '职位' }]
      .concat(DATE_FIELDS, [{ k: 'current', l: '至今', t: 'check' }, { k: 'content', l: '工作内容', t: 'area' }]),
    project: [{ k: 'name', l: '项目名称' }, { k: 'role', l: '担任角色' },
      { k: 'period', l: '时间段', t: 'period' }, { k: 'content', l: '项目描述', t: 'area' }],
    campus: [{ k: 'name', l: '经历名称' }, { k: 'role', l: '担任角色' },
      { k: 'period', l: '时间段', t: 'period' }, { k: 'content', l: '经历描述', t: 'area' }],
    skill: [{ k: 'name', l: '技能' }, { k: 'level', l: '程度', ph: '精通/熟练/了解' }, { k: 'content', l: '说明', t: 'area' }],
    honor: [{ k: 'time', l: '时间', t: 'period' }, { k: 'name', l: '荣誉 / 证书' }, { k: 'issuer', l: '颁发单位' }]
  };

  var THEMES_ORDER = ['default', 'blue', 'green', 'orange', 'gray', 'wine', 'teal'];
  var FONTS = ResumeRender.FONTS;

  var PRESETS = [
    { key: 'classic-indigo', name: '经典单栏 · 靛青', family: 'single', theme: 'default' },
    { key: 'classic-blue', name: '经典单栏 · 商务蓝', family: 'single', theme: 'blue' },
    { key: 'classic-orange', name: '经典单栏 · 活力橙', family: 'single', theme: 'orange' },
    { key: 'banner-wine', name: '顶部横幅 · 酒红', family: 'headerBar', theme: 'wine' },
    { key: 'banner-blue', name: '顶部横幅 · 商务蓝', family: 'headerBar', theme: 'blue' },
    { key: 'sidebar-green', name: '左侧栏 · 清新绿', family: 'sidebar', theme: 'green' },
    { key: 'sidebar-teal', name: '左侧栏 · 青碧', family: 'sidebar', theme: 'teal' },
    { key: 'twocol-gray', name: '双栏紧凑 · 沉稳灰', family: 'twoCol', theme: 'gray' }
  ];
  var FAMILIES = ResumeRender.FAMILIES;

  var SAMPLE = {
    basic: { name: '李小华', intention: '产品经理', phone: '138-0000-0000', email: 'li@mail.com', city: '上海' },
    modules: {
      education_info: [{ school: '复旦大学', degree: '本科', major: '工商管理', start: '2018-09', end: '2022-06', content: '主修市场营销、数据分析' }],
      work_history: [{ company: '某互联网公司', position: '产品助理', start: '2022-07', current: true, content: '负责用户增长模块\n推动转化率提升 30%' }],
      skill_info: [{ name: 'Axure', level: '熟练' }, { name: 'SQL', level: '掌握' }],
      self_evaluate: '两年产品经验，擅长数据驱动迭代。'
    },
    order: ['education', 'work', 'skill', 'self'],
    visible: {}
  };

  var DEFAULT_THEME = {
    family: 'single', theme: 'default', primary: '#34549B',
    font: 'yahei', fontSize: 13, lineHeight: 1.72, gap: 20, padding: 44,
    nameSize: 30, photoSize: 92, photoShape: 'rect', sectionStyle: 'underline'
  };

  /* ───────── 状态 ───────── */

  var S = {
    user: null,
    draftId: null,
    title: '',
    resume: blankResume(),
    theme: Object.assign({}, DEFAULT_THEME),
    ui: { folded: {}, zoom: 1 },
    dirty: false,
    saving: false
  };
  var LS_KEY = 'zjl_editor_v3_draft';
  var DRAFT_SAVE_TIMER = null, LOCAL_SAVE_TIMER = null, RENDER_TIMER = null;

  function blankResume() {
    var mods = {};
    LIST_KINDS.forEach(function (k) { mods[k] = []; });
    mods.self = ''; mods.custom = ''; mods.hobby = [];
    return { basic: { name: '', intention: '' }, modules: mods, order: DEFAULT_ORDER.slice(), hidden: [], showPhoto: true };
  }

  /* ───────── 工具 ───────── */

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function hasText(v) {
    if (v == null) return false;
    if (Array.isArray(v)) return v.length > 0;
    return String(v).trim() !== '';
  }
  function getPath(p) {
    return p.split('.').reduce(function (o, k) { return o == null ? undefined : o[k]; }, S.resume);
  }
  function setPath(p, v) {
    var ks = p.split('.'), o = S.resume;
    for (var i = 0; i < ks.length - 1; i++) o = o[ks[i]];
    o[ks[ks.length - 1]] = v;
  }
  function toast(msg, isErr) {
    var t = $('toast');
    t.textContent = msg; t.hidden = false;
    t.className = 'v3-toast' + (isErr ? ' is-err' : '');
    clearTimeout(t.__timer);
    t.__timer = setTimeout(function () { t.hidden = true; }, isErr ? 4200 : 2400);
  }
  function showLoading(text) { $('loadingText').textContent = text || '处理中…'; $('loadingMask').hidden = false; }
  function hideLoading() { $('loadingMask').hidden = true; }
  function debounce(fn, ms) {
    return function () {
      var args = arguments, self = this;
      clearTimeout(fn.__t);
      fn.__t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  }

  /* ───────── API ───────── */

  function token() {
    return localStorage.getItem('resume_planet_token') || sessionStorage.getItem('resume_planet_token')
      || localStorage.getItem('rz_token') || sessionStorage.getItem('rz_token') || '';
  }
  function authHeaders(extra) {
    var h = { 'Authorization': 'Bearer ' + token() };
    if (extra) { Object.keys(extra).forEach(function (k) { h[k] = extra[k]; }); }
    return h;
  }
  function apiGet(url) {
    return fetch(url, { headers: authHeaders() }).then(function (r) {
      if (r.status === 401 || r.status === 403) return null;
      return r.json().then(function (d) { return r.ok ? d : Promise.reject(new Error(d.detail || '请求失败')); });
    });
  }
  function apiPost(url, body) {
    return fetch(url, {
      method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().then(function (d) { return r.ok ? d : Promise.reject(new Error(d.detail || '请求失败')); });
    });
  }

  /* ───────── 数据规范化与旧草稿迁移 ───────── */

  function normalizeData(data) {
    if (data && data.v === 3 && data.resume && typeof data.resume === 'object') {
      return { resume: mergeResume(data.resume), theme: mergeTheme(data.theme) };
    }
    /* 旧模型（editor.js：basic / modules.education_info / style.skin ...）尽力迁移 */
    if (data && (data.basic || data.modules)) {
      var out = blankResume();
      var b = Object.assign({}, data.basic || {});
      if (data.photoDataUrl) b.photo = data.photoDataUrl;
      out.basic = b;
      var oldMods = data.modules || {};
      Object.keys(OLD_KEY_MAP).forEach(function (ok) {
        var nk = OLD_KEY_MAP[ok];
        if (!hasText(oldMods[ok])) return;
        if (Array.isArray(oldMods[ok])) out.modules[nk] = oldMods[ok];
        else out.modules[nk] = String(oldMods[ok]);
      });
      if (Array.isArray(data.order) && data.order.length) {
        var mapped = data.order.map(function (k) { return OLD_KEY_MAP[k] || k; })
          .filter(function (k) { return MODULE_META[k]; });
        DEFAULT_ORDER.forEach(function (k) { if (mapped.indexOf(k) < 0) mapped.push(k); });
        out.order = mapped;
      }
      if (data.visible) {
        out.hidden = Object.keys(data.visible).filter(function (k) {
          return data.visible[k] === false && MODULE_META[OLD_KEY_MAP[k] || k];
        }).map(function (k) { return OLD_KEY_MAP[k] || k; });
      }
      if (data.showPhoto === false) out.showPhoto = false;
      var st = data.style || {};
      var skin = st.skin && ResumeRender.THEMES[st.skin] ? st.skin : 'default';
      var th = mergeTheme({
        family: FAMILIES[st.family] ? st.family : 'single',
        theme: skin, primary: ResumeRender.THEMES[skin].accent,
        font: FONTS[st.font] ? st.font : 'yahei',
        fontSize: st.fontSize, lineHeight: st.lineHeight,
        gap: st.gap || undefined, padding: st.padding || undefined,
        nameSize: st.nameSize, photoSize: st.photoSize,
        photoShape: st.photoShape, sectionStyle: st.sectionStyle
      });
      return { resume: out, theme: th };
    }
    return { resume: blankResume(), theme: Object.assign({}, DEFAULT_THEME) };
  }

  function mergeResume(r) {
    var out = blankResume();
    r = r || {};
    out.basic = Object.assign({}, r.basic || {});
    if (!hasText(out.basic.name)) out.basic.name = '';
    if (r.modules && typeof r.modules === 'object') {
      Object.keys(out.modules).forEach(function (k) {
        var v = r.modules[k];
        if (k === 'self' || k === 'custom') out.modules[k] = String(v == null ? '' : v);
        else if (Array.isArray(v)) out.modules[k] = v.filter(function (x) { return x && typeof x === 'object'; });
        else if (k === 'hobby' && typeof v === 'string' && v.trim()) {
          out.modules[k] = v.split(/[、,，\s]+/).filter(Boolean);
        }
      });
    }
    if (Array.isArray(r.order)) {
      var ord = r.order.filter(function (k) { return MODULE_META[k]; });
      DEFAULT_ORDER.forEach(function (k) { if (ord.indexOf(k) < 0) ord.push(k); });
      out.order = ord;
    }
    if (Array.isArray(r.hidden)) out.hidden = r.hidden.filter(function (k) { return MODULE_META[k]; });
    if (r.showPhoto === false) out.showPhoto = false;
    return out;
  }

  function mergeTheme(t) {
    var th = Object.assign({}, DEFAULT_THEME);
    Object.keys(th).forEach(function (k) {
      if (t && t[k] != null && t[k] !== '') th[k] = t[k];
    });
    if (!/^#?[0-9a-fA-F]{6}$/.test(String(th.primary || ''))) th.primary = DEFAULT_THEME.primary;
    if (!FAMILIES[th.family]) th.family = 'single';
    if (!FONTS[th.font]) th.font = 'yahei';
    if (!ResumeRender.THEMES[th.theme]) th.theme = 'default';
    return th;
  }

  /* 渲染层视图：v3 key → dataKey */
  function buildView() {
    var mods = {};
    Object.keys(DATA_KEY).forEach(function (k) { mods[DATA_KEY[k]] = S.resume.modules[k]; });
    var visible = {};
    S.resume.order.forEach(function (k) { visible[k] = S.resume.hidden.indexOf(k) < 0; });
    return {
      basic: S.resume.basic,
      photo: S.resume.basic.photo || '',
      intention: S.resume.basic.intention || '',
      modules: mods,
      order: S.resume.order,
      visible: visible,
      showPhoto: S.resume.showPhoto !== false
    };
  }
  function buildStyle() {
    var st = Object.assign({}, S.theme);
    st.accent = S.theme.primary;
    return st;
  }

  /* 与渲染器过滤条件对齐的「会被渲染的记录」列表 */
  function alignedRecords(key) {
    var arr = S.resume.modules[key];
    if (!Array.isArray(arr)) return [];
    var ks = RENDER_KEYS[key] || ['name', 'content'];
    return arr.filter(function (rec) {
      if (!rec || typeof rec !== 'object') return false;
      for (var i = 0; i < ks.length; i++) {
        if (hasText(rec[ks[i]])) return true;
      }
      return false;
    });
  }

  /* ═════════ 渲染中心 ═════════ */

  function renderCenter() {
    var view = buildView();
    var paper = $('paper');
    ResumeRender.mount(paper, view, buildStyle());
    annotate(paper, ResumeRender.buildSections(view));
    layoutPaper();
    updatePageHint();
  }
  var renderCenterSoon = debounce(function () { renderCenter(); }, 120);

  function layoutPaper() {
    var center = $('centerWrap'), box = $('pageBox'), paper = $('paper');
    var z = Math.min(1, Math.max(0.4, (center.clientWidth - 44) / A4.w));
    S.ui.zoom = z;
    paper.style.transform = 'scale(' + z + ')';
    box.style.width = Math.round(A4.w * z) + 'px';
    var page = paper.querySelector('.rr-page');
    box.style.height = Math.round((page ? page.offsetHeight : A4.h) * z) + 'px';
  }

  function updatePageHint() {
    var page = $('paper').querySelector('.rr-page');
    var hint = $('pageHint');
    if (!page) { hint.textContent = ''; return; }
    var extra = page.scrollHeight - A4.h;
    if (extra > 8) {
      var pages = Math.ceil(page.scrollHeight / A4.h);
      hint.textContent = '内容约 ' + pages + ' 页（超出 A4 单页，Word 导出将自动分页）';
      hint.className = 'v3-pagehint is-overflow';
    } else {
      hint.textContent = 'A4 · 794 × 1123 px';
      hint.className = 'v3-pagehint';
    }
  }

  /* ───────── 内联编辑：DOM ↔ state 写回 ───────── */

  function makeEditable(el, onSet, multiline) {
    if (!el) return;
    el.contentEditable = 'true';
    el.__onSet = onSet;
    if (!multiline) el.__single = true;
  }

  function bindInline(paper) {
    paper.addEventListener('input', function (e) {
      var el = e.target.closest && e.target.closest('[contenteditable="true"]');
      if (!el || !el.__onSet) return;
      el.__onSet(el.innerText.replace(/\u00a0/g, ' '));
      markDirty();
    });
    paper.addEventListener('paste', function (e) {
      var el = e.target.closest && e.target.closest('[contenteditable="true"]');
      if (!el) return;
      e.preventDefault();
      var txt = (e.clipboardData || window.clipboardData).getData('text/plain');
      document.execCommand('insertText', false, txt);
    });
    paper.addEventListener('keydown', function (e) {
      var el = e.target.closest && e.target.closest('[contenteditable="true"]');
      if (!el) return;
      if (el.__single && e.key === 'Enter') { e.preventDefault(); el.blur(); }
    });
  }

  function annotate(paper, sections) {
    var page = paper.querySelector('.rr-page');
    if (!page) return;
    var secByKey = {};
    sections.forEach(function (s) { secByKey[s.key] = s; });

    /* 头部 */
    makeEditable(page.querySelector('.rr-name'), function (v) {
      S.resume.basic.name = v.trim();
      syncForm('basic.name');
    });
    var intent = page.querySelector('.rr-intent');
    if (intent) makeEditable(intent, function (v) {
      S.resume.basic.intention = v.replace(/^求职意向[:：]\s*/, '').trim();
      syncForm('basic.intention');
    });

    /* 联系方式行 */
    Array.prototype.forEach.call(page.querySelectorAll('.rr-contact > span'), function (sp) {
      var m = /^([^：:]+)[:：]/.exec(sp.textContent || '');
      var k = m && CONTACT_BY_LABEL[m[1].trim()];
      if (!k) return;
      makeEditable(sp, function (v) {
        S.resume.basic[k] = v.replace(/^[^：:]*[:：]\s*/, '').trim();
        syncForm('basic.' + k);
      });
    });

    /* 基本信息网格行（值部分包一层可编辑 span） */
    Array.prototype.forEach.call(page.querySelectorAll('.rr-basic-row'), function (row) {
      var b = row.querySelector('b');
      var label = b ? b.textContent.replace(/[:：]\s*$/, '').trim() : '';
      var k = FIELD_BY_LABEL[label];
      if (!k) return;
      var ve = row.ownerDocument.createElement('span');
      ve.className = 'rr-ve';
      while (row.childNodes.length) {
        var n = row.childNodes[row.childNodes.length - 1];
        if (n === b) break;
        ve.insertBefore(n, ve.firstChild);
      }
      row.appendChild(ve);
      makeEditable(ve, function (v) {
        S.resume.basic[k] = v.trim();
        syncForm('basic.' + k);
      });
    });

    /* 左侧栏族的联系/基本信息行 */
    Array.prototype.forEach.call(page.querySelectorAll('.rr-side-line'), function (line) {
      var m = /^([^：:]+)[:：]/.exec(line.textContent || '');
      if (!m) return;
      var k = CONTACT_BY_LABEL[m[1].trim()] || FIELD_BY_LABEL[m[1].trim()];
      if (!k) return;
      var ve = line.ownerDocument.createElement('span');
      ve.className = 'rr-ve';
      var started = false;
      Array.prototype.slice.call(line.childNodes).forEach(function (n) {
        if (n.nodeType === 3 && !started && n.nodeValue.indexOf('：') >= 0) {
          started = true;
          var tail = n.nodeValue.split(/[:：]/).slice(1).join('：');
          n.nodeValue = n.nodeValue.split(/[:：]/)[0] + '：';
          if (tail) ve.appendChild(line.ownerDocument.createTextNode(tail));
          return;
        }
        if (started) ve.appendChild(n);
      });
      if (started) {
        line.appendChild(ve);
        makeEditable(ve, function (v) {
          S.resume.basic[k] = v.trim();
          syncForm('basic.' + k);
        });
      }
    });

    /* 各模块 */
    Array.prototype.forEach.call(page.querySelectorAll('.rr-sec[data-sec]'), function (secEl) {
      var key = secEl.dataset.sec;
      var sec = secByKey[key];
      if (!sec) return;

      if (sec.kind === 'text') {
        makeEditable(secEl.querySelector('.rr-item-desc'), function (v) {
          S.resume.modules[key] = v.replace(/\n{3,}/g, '\n\n').trim();
          syncForm('modules.' + key);
        }, true);
        return;
      }
      if (sec.kind === 'tags') {
        var hobby = Array.isArray(S.resume.modules.hobby) ? S.resume.modules.hobby : [];
        var live = hobby.filter(function (t) { return hasText(t); });
        Array.prototype.forEach.call(secEl.querySelectorAll('.rr-tag'), function (tagEl, i) {
          makeEditable(tagEl, function (v) {
            if (i < live.length) {
              var abs = hobby.indexOf(live[i]);
              if (abs >= 0) hobby[abs] = v.trim();
            }
            syncForm('modules.hobby');
          });
        });
        return;
      }

      var recs = alignedRecords(key);
      Array.prototype.forEach.call(secEl.querySelectorAll('.rr-item'), function (itemEl, i) {
        var rec = recs[i];
        if (!rec) return;
        var titleEl = itemEl.querySelector('.rr-item-title');
        var metaEl = itemEl.querySelector('.rr-item-meta');
        var subEl = itemEl.querySelector('.rr-item-sub > span') || itemEl.querySelector('.rr-item-sub');
        var descEl = itemEl.querySelector('.rr-item-desc');

        if (titleEl && TITLE_KEY[key]) {
          makeEditable(titleEl, function (v) {
            rec[TITLE_KEY[key]] = v.trim();
            syncForm('modules.' + key + '.' + recIndex(key, rec) + '.' + TITLE_KEY[key]);
          });
        }
        if (metaEl && (hasText(rec.start) || hasText(rec.end) || rec.current || hasText(rec.period))) {
          var origMeta = { start: rec.start, end: rec.end, current: rec.current, period: rec.period };
          makeEditable(metaEl, function (v) { writeBackMeta(rec, origMeta, v); });
        }
        if (subEl) {
          if (key === 'education') {
            var origSub = { degree: hasText(rec.degree), major: hasText(rec.major) };
            if (origSub.degree || origSub.major) {
              makeEditable(subEl, function (v) { writeBackEduSub(rec, origSub, v); });
            }
          } else {
            var subKey = key === 'work' || key === 'internship' ? 'position' : 'role';
            makeEditable(subEl, function (v) {
              rec[subKey] = v.trim();
              syncForm('modules.' + key + '.' + recIndex(key, rec) + '.' + subKey);
            });
          }
        }
        if (descEl) {
          makeEditable(descEl, function (v) {
            rec.content = v.replace(/\n{3,}/g, '\n\n').trim();
            syncForm('modules.' + key + '.' + recIndex(key, rec) + '.content');
          }, true);
        }
      });
    });
  }

  function recIndex(key, rec) {
    var arr = S.resume.modules[key];
    return arr ? arr.indexOf(rec) : -1;
  }

  function writeBackMeta(rec, orig, text) {
    text = String(text || '').trim();
    if (hasText(orig.period) && !hasText(orig.start) && !hasText(orig.end) && !orig.current) {
      rec.period = text;
      return;
    }
    var parts = text.split('~');
    var start = (parts[0] || '').trim();
    var end = (parts[1] || '').trim();
    if (parts.length === 2) {
      rec.start = start;
      if (end === '至今') { rec.current = true; rec.end = ''; }
      else { rec.current = false; rec.end = end; }
    } else {
      if (orig.current && hasText(orig.start)) { rec.start = text.replace(/至至今$/, '').trim() || start; rec.current = true; }
      else if (hasText(orig.end) && !hasText(orig.start)) rec.end = text;
      else if (!hasText(orig.start) && !hasText(orig.end)) { rec.start = text; rec.end = ''; rec.current = false; }
      else { rec.start = text; rec.end = ''; rec.current = false; }
    }
    syncForm('modules.' + findModuleKeyOfRec(rec) + '.' + recIndex(findModuleKeyOfRec(rec), rec) + '.start');
    syncForm('modules.' + findModuleKeyOfRec(rec) + '.' + recIndex(findModuleKeyOfRec(rec), rec) + '.end');
    syncForm('modules.' + findModuleKeyOfRec(rec) + '.' + recIndex(findModuleKeyOfRec(rec), rec) + '.current');
  }

  function writeBackEduSub(rec, orig, text) {
    text = String(text || '').trim();
    if (orig.degree && orig.major) {
      var ps = text.split('·');
      rec.degree = (ps[0] || '').trim();
      rec.major = (ps[1] || '').trim();
    } else if (orig.degree) rec.degree = text;
    else rec.major = text;
    var key = findModuleKeyOfRec(rec), i = recIndex(key, rec);
    syncForm('modules.' + key + '.' + i + '.degree');
    syncForm('modules.' + key + '.' + i + '.major');
  }

  function findModuleKeyOfRec(rec) {
    var keys = Object.keys(RENDER_KEYS);
    for (var i = 0; i < keys.length; i++) {
      var arr = S.resume.modules[keys[i]];
      if (Array.isArray(arr) && arr.indexOf(rec) >= 0) return keys[i];
    }
    return 'work';
  }

  /* 左栏表单控件值同步（data-path 定位） */
  function syncForm(path) {
    var els = document.querySelectorAll('.v3-left [data-path="' + path + '"]');
    Array.prototype.forEach.call(els, function (el) {
      if (document.activeElement === el) return;
      var v = getPath(path);
      if (path === 'modules.hobby') v = Array.isArray(v) ? v.filter(hasText).join('、') : '';
      if (el.type === 'checkbox') el.checked = !!v; else el.value = v == null ? '' : v;
    });
  }

  /* ───────── 年月选择器（开始/结束时间，格式 YYYY-MM） ───────── */

  var DP = { el: null, input: null, y: 0, m: 0 };   /* m: 0-11 */
  var MON_NAMES = ['一月', '二月', '三月', '四月', '五月', '六月',
                   '七月', '八月', '九月', '十月', '十一月', '十二月'];

  function fmtYM(y, m) { return y + '-' + ('0' + (m + 1)).slice(-2); }
  function parseYM(v) {
    var m = /^(\d{4})\s*[-/年.]?\s*(\d{1,2})?/.exec(String(v || '').trim());
    if (!m) return null;
    var mo = m[2] ? parseInt(m[2], 10) - 1 : new Date().getMonth();
    return { y: parseInt(m[1], 10), m: Math.min(11, Math.max(0, mo)) };
  }
  /* 时间段（单字段存 "起 ~ 止"）的拆装 */
  function splitPeriod(v) {
    var parts = String(v || '').split(/[~～]/);
    return { a: (parts[0] || '').trim(), b: parts.length > 1 ? (parts[1] || '').trim() : '' };
  }
  function joinPeriod(a, b) {
    a = (a || '').trim(); b = (b || '').trim();
    return (a && b) ? a + ' ~ ' + b : (a || b);
  }
  function setPeriodSide(inp, v) {
    var path = inp.dataset.path;
    var parts = splitPeriod(getPath(path));
    if (inp.dataset.period === 'start') parts.a = v; else parts.b = v;
    var joined = joinPeriod(parts.a, parts.b);
    if (getPath(path) === joined) return false;
    setPath(path, joined);
    var np = splitPeriod(joined);
    var wrap = inp.closest('.v3-field');
    ['start', 'end'].forEach(function (side) {
      var el = wrap.querySelector('input[data-period="' + side + '"]');
      if (el) el.value = side === 'start' ? np.a : np.b;
    });
    return true;
  }
  function ensureDatePicker() {
    if (DP.el) return DP.el;
    DP.el = document.createElement('div');
    DP.el.id = 'v3DatePicker';
    DP.el.className = 'v3-dp';
    document.body.appendChild(DP.el);
    DP.el.addEventListener('click', function (e) {
      /* 面板内点击不冒泡：innerHTML 重绘会断开旧按钮的祖先链，
         冒泡到 document 的关闭监听时会误判为面板外点击 */
      e.stopPropagation();
      var btn = e.target.closest('[data-dp]');
      if (!btn) return;
      var act = btn.dataset.dp;
      if (act === 'py') DP.y--;
      else if (act === 'ny') DP.y++;
      else if (act === 'thisyear') { DP.y = new Date().getFullYear(); renderDatePicker(); return; }
      else if (act === 'mon') { applyDate(fmtYM(DP.y, parseInt(btn.dataset.m, 10))); return; }
      else if (act === 'clear') { applyDate(''); return; }
      renderDatePicker();
    });
    return DP.el;
  }
  function applyDate(v) {
    var inp = DP.input;
    closeDatePicker();
    if (!inp) return;
    var changed;
    if (inp.dataset.period) {
      changed = setPeriodSide(inp, v);
    } else if (inp.value !== v) {
      inp.value = v;
      setPath(inp.dataset.path, v);
      changed = true;
    }
    if (changed) {
      markDirty();
      renderCenterSoon();
    }
  }
  function closeDatePicker() {
    if (DP.el) DP.el.style.display = 'none';
    DP.input = null;
  }
  function renderDatePicker() {
    var now = new Date();
    var cur = DP.input ? String(DP.input.value || '') : '';
    var h = '<div class="v3-dp-head">' +
      '<button data-dp="py" type="button" title="上一年">«</button>' +
      '<span class="v3-dp-title">' + DP.y + '年</span>' +
      '<button data-dp="ny" type="button" title="下一年">»</button></div>';
    h += '<div class="v3-dp-mons">';
    for (var i = 0; i < 12; i++) {
      var v = fmtYM(DP.y, i);
      var cls = 'v3-dp-mon' + (v === cur ? ' is-sel' : '') +
        (DP.y === now.getFullYear() && i === now.getMonth() ? ' is-now' : '');
      h += '<button type="button" class="' + cls + '" data-dp="mon" data-m="' + i + '">' + MON_NAMES[i] + '</button>';
    }
    h += '</div>';
    h += '<div class="v3-dp-foot"><button type="button" class="v3-dp-link" data-dp="thisyear">今年</button>' +
      '<button type="button" class="v3-dp-link" data-dp="clear">清除</button></div>';
    DP.el.innerHTML = h;
  }
  function openDatePicker(inp) {
    var el = ensureDatePicker();
    if (DP.input === inp && DP.el.style.display !== 'none') { closeDatePicker(); return; }
    DP.input = inp;
    var cur = inp.dataset.period ? splitPeriod(getPath(inp.dataset.path))[inp.dataset.period] : inp.value;
    var pv = parseYM(cur) || { y: new Date().getFullYear(), m: new Date().getMonth() };
    DP.y = pv.y; DP.m = pv.m;
    renderDatePicker();
    el.style.display = 'block';
    var r = inp.getBoundingClientRect();
    var w = el.offsetWidth || 240, h = el.offsetHeight || 220;
    var left = Math.min(Math.max(8, r.left), window.innerWidth - w - 8);
    var top = r.bottom + 6;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 6);
    el.style.left = left + 'px';
    el.style.top = top + 'px';
  }
  document.addEventListener('click', function (e) {
    if (DP.el && DP.el.style.display !== 'none' &&
        !e.target.closest('#v3DatePicker') && !e.target.closest('input[data-date]')) {
      closeDatePicker();
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeDatePicker();
  });

  /* ═════════ 左栏：内容表单 ═════════ */

  function fieldHtml(path, label, opts) {
    opts = opts || {};
    if (opts.t === 'area') {
      return '<div class="v3-field v3-field-col"><label>' + esc(label) + '</label>' +
        '<textarea class="v3-textarea" rows="3" data-path="' + path + '" placeholder="' + esc(opts.ph || '') + '">' + esc(getPath(path) || '') + '</textarea></div>';
    }
    if (opts.t === 'check') {
      return '<div class="v3-field"><label>' + esc(label) + '</label>' +
        '<label class="v3-chk"><input type="checkbox" data-path="' + path + '"' + (getPath(path) ? ' checked' : '') + '>在职/在读至今</label></div>';
    }
    if (opts.t === 'date') {
      return '<div class="v3-field"><label>' + esc(label) + '</label>' +
        '<input class="v3-input" type="text" data-path="' + path + '" data-date value="' + esc(getPath(path) || '') + '" placeholder="' + esc(opts.ph || '点击选择年月') + '"></div>';
    }
    if (opts.t === 'period') {
      var pp = splitPeriod(getPath(path));
      return '<div class="v3-field"><label>' + esc(label) + '</label>' +
        '<input class="v3-input v3-input-half" type="text" data-path="' + path + '" data-date data-period="start" value="' + esc(pp.a) + '" placeholder="开始年月">' +
        '<span class="v3-period-sep">~</span>' +
        '<input class="v3-input v3-input-half" type="text" data-path="' + path + '" data-date data-period="end" value="' + esc(pp.b) + '" placeholder="结束年月"></div>';
    }
    return '<div class="v3-field"><label>' + esc(label) + '</label>' +
      '<input class="v3-input" type="text" data-path="' + path + '" value="' + esc(getPath(path) || '') + '" placeholder="' + esc(opts.ph || '') + '"></div>';
  }

  function buildLeftPanel() {
    closeDatePicker();
    var body = $('leftBody');
    var scroll = body.scrollTop;
    var h = '';

    /* 基本信息 */
    h += '<div class="v3-mod-card' + (S.ui.folded.basic ? ' is-folded' : '') + '" data-modkey="basic">';
    h += '<div class="v3-mod-head" data-fold="basic"><span class="v3-mod-ico">👤</span><span class="v3-mod-name">基本信息</span></div>';
    h += '<div class="v3-mod-body">';
    h += '<div class="v3-basic-photo-row">';
    h += '<div class="v3-basic-photo" id="basicPhoto" title="点击上传证件照">';
    h += hasText(S.resume.basic.photo) ? '<img src="' + esc(S.resume.basic.photo) + '">' : '照片';
    h += '</div>';
    h += '<div style="flex:1">';
    h += fieldHtml('basic.name', '姓名', { ph: '姓名' });
    h += fieldHtml('basic.intention', '求职意向', { ph: '目标岗位' });
    h += '</div></div>';
    h += '<div class="v3-frow2">';
    h += fieldHtml('basic.phone', '电话', { ph: '手机号' });
    h += fieldHtml('basic.email', '邮箱', { ph: '邮箱' });
    h += fieldHtml('basic.wechat', '微信', { ph: '选填' });
    h += fieldHtml('basic.city', '现居', { ph: '城市' });
    h += '</div>';
    h += '<details class="v3-more"><summary>更多字段（选填）</summary><div class="v3-frow2" style="margin-top:6px">';
    ['gender', 'birth_date', 'age', 'political_status', 'hometown', 'nation', 'marriage', 'education_degree'].forEach(function (k) {
      h += fieldHtml('basic.' + k, FIELD_LABEL[k]);
    });
    h += '</div></details>';
    h += '</div></div>';

    /* 模块卡片（按 order） */
    S.resume.order.forEach(function (key) {
      var meta = MODULE_META[key];
      var isHidden = S.resume.hidden.indexOf(key) >= 0;
      var folded = S.ui.folded[key];
      h += '<div class="v3-mod-card' + (folded ? ' is-folded' : '') + (isHidden ? ' is-hiddenmod' : '') + '" data-modkey="' + key + '">';
      h += '<div class="v3-mod-head" data-fold="' + key + '">';
      h += '<span class="v3-mod-grip" title="拖拽排序">⋮⋮</span>';
      h += '<span class="v3-mod-ico">' + meta.icon + '</span>';
      h += '<span class="v3-mod-name">' + esc(meta.label) + (isHidden ? '（已隐藏）' : '') + '</span>';
      h += '<span class="v3-mod-ops">';
      h += '<button class="v3-mop" data-mv="up" title="上移">↑</button>';
      h += '<button class="v3-mop" data-mv="down" title="下移">↓</button>';
      h += '<button class="v3-mop' + (isHidden ? ' is-off' : '') + '" data-hide title="' + (isHidden ? '显示该模块' : '隐藏该模块') + '">' + (isHidden ? '🚫' : '👁') + '</button>';
      if (key !== 'self' && key !== 'custom' && key !== 'hobby') {
        h += '<button class="v3-mop" data-rm title="从列表移除（可从下方再添加）">🗑</button>';
      }
      h += '</span></div>';
      h += '<div class="v3-mod-body">';

      if (key === 'self' || key === 'custom') {
        h += fieldHtml('modules.' + key, key === 'self' ? '自我评价' : '内容', { t: 'area', ph: key === 'self' ? '用 3~5 句话概括你的优势…' : '自定义内容…' });
      } else if (key === 'hobby') {
        h += fieldHtml('modules.hobby', '爱好', { ph: '用顿号分隔：阅读、羽毛球、摄影' });
      } else {
        var arr = S.resume.modules[key];
        (arr || []).forEach(function (rec, i) {
          h += '<div class="v3-item-card">';
          h += '<button class="v3-item-del" data-delitem="' + i + '" title="删除此条">✕</button>';
          var specs = FIELD_SPECS[key] || [];
          var idx = 0;
          while (idx < specs.length) {
            var f = specs[idx];
            if (f.k === 'start') {
              h += '<div class="v3-frow2">' + fieldHtml('modules.' + key + '.' + i + '.start', f.l, f) +
                fieldHtml('modules.' + key + '.' + i + '.end', specs[idx + 1].l, specs[idx + 1]) + '</div>';
              idx += 2; continue;
            }
            h += fieldHtml('modules.' + key + '.' + i + '.' + f.k, f.l, f);
            idx++;
          }
          h += '</div>';
        });
        h += '<button class="v3-addbtn" data-additem>＋ 添加一条' + esc(meta.label.replace(/(背景|经验|经历|特长|证书)$/, '')) + '</button>';
      }
      h += '</div></div>';
    });

    /* 添加模块 */
    var missing = DEFAULT_ORDER.filter(function (k) { return S.resume.order.indexOf(k) < 0; });
    h += '<div class="v3-addmod"><button class="v3-addbtn" id="addModBtn">＋ 添加模块</button>';
    h += '<div class="v3-addmod-menu" id="addModMenu" hidden>';
    if (missing.length) {
      missing.forEach(function (k) {
        h += '<button data-addmod="' + k + '">' + MODULE_META[k].icon + ' ' + esc(MODULE_META[k].label) + '</button>';
      });
    } else {
      h += '<div class="v3-addmod-empty">全部模块都已添加</div>';
    }
    h += '</div></div>';

    body.innerHTML = h;
    body.scrollTop = scroll;
  }

  /* 左栏事件（委托） */
  function bindLeftPanel() {
    var body = $('leftBody');

    body.addEventListener('input', function (e) {
      var el = e.target.closest('[data-path]');
      if (!el || el.type === 'checkbox') return;
      var p = el.dataset.path;
      if (p === 'modules.hobby') {
        S.resume.modules.hobby = String(el.value).split(/[、,，\s]+/).filter(Boolean);
      } else if (el.dataset.period) {
        /* 时间段半段手输：只改本侧，保留另一侧 */
        var ps = splitPeriod(getPath(p));
        if (el.dataset.period === 'start') ps.a = el.value; else ps.b = el.value;
        setPath(p, joinPeriod(ps.a, ps.b));
      } else {
        setPath(p, el.value);
      }
      markDirty();
      renderCenterSoon();
    });
    body.addEventListener('change', function (e) {
      var el = e.target.closest('[data-path]');
      if (el && el.type === 'checkbox') {
        setPath(el.dataset.path, el.checked);
        markDirty();
        renderCenterSoon();
      }
    });
    /* 折叠 + 条目/模块操作（按钮统一走 click 委托） */
    body.addEventListener('click', function (e) {
      var op = e.target.closest('[data-hide],[data-rm],[data-additem],[data-delitem],[data-addmod],[data-mv]');
      if (op) {
        var key = op.closest('.v3-mod-card').dataset.modkey;
        if (op.hasAttribute('data-hide')) toggleHide(key);
        else if (op.hasAttribute('data-rm')) removeModule(key);
        else if (op.hasAttribute('data-additem')) addItem(key);
        else if (op.hasAttribute('data-delitem')) removeItem(key, parseInt(op.dataset.delitem, 10));
        else if (op.hasAttribute('data-addmod')) addModule(op.dataset.addmod);
        else if (op.hasAttribute('data-mv')) moveModule(key, op.dataset.mv);
        return;
      }
      var head = e.target.closest('.v3-mod-head[data-fold]');
      if (head && !e.target.closest('.v3-mod-grip')) {
        var k = head.dataset.fold;
        S.ui.folded[k] = !S.ui.folded[k];
        head.closest('.v3-mod-card').classList.toggle('is-folded', !!S.ui.folded[k]);
        return;
      }
      if (e.target.closest && e.target.closest('#addModBtn')) {
        var m = $('addModMenu');
        if (m) m.hidden = !m.hidden;
      } else if (!e.target.closest('#addModMenu')) {
        var mm = $('addModMenu');
        if (mm) mm.hidden = true;
      }
    });

    /* 照片上传 */
    body.addEventListener('click', function (e) {
      if (e.target.closest('#basicPhoto')) $('photoInput').click();
    });

    /* 日期字段：点击弹出日历 */
    body.addEventListener('click', function (e) {
      var dinp = e.target.closest('input[data-date]');
      if (dinp) openDatePicker(dinp);
    });

    /* 拖拽排序（按住 ⋮⋮ 手柄才可拖，避免影响输入框选字） */
    var dragKey = null;
    body.addEventListener('mousedown', function (e) {
      var grip = e.target.closest('.v3-mod-grip');
      var card = grip && grip.closest('.v3-mod-card[data-modkey]');
      if (card) {
        e.preventDefault();
        card.draggable = true;
      }
    });
    body.addEventListener('mouseup', function () {
      Array.prototype.forEach.call(body.querySelectorAll('.v3-mod-card[draggable="true"]'), function (c) { c.draggable = false; });
    });
    body.addEventListener('dragstart', function (e) {
      var card = e.target.closest('.v3-mod-card[data-modkey]');
      if (!card || card.dataset.modkey === 'basic') { e.preventDefault(); return; }
      dragKey = card.dataset.modkey;
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', dragKey); } catch (err) { /* IE */ }
    });
    body.addEventListener('dragend', function () {
      dragKey = null;
      Array.prototype.forEach.call(body.querySelectorAll('.v3-mod-card[draggable="true"]'), function (c) { c.draggable = false; });
    });
    body.addEventListener('dragover', function (e) { e.preventDefault(); });
    body.addEventListener('drop', function (e) {
      e.preventDefault();
      var card = e.target.closest('.v3-mod-card[data-modkey]');
      if (!card || !dragKey || card.dataset.modkey === dragKey || card.dataset.modkey === 'basic') return;
      var order = S.resume.order.slice();
      order.splice(order.indexOf(dragKey), 1);
      order.splice(order.indexOf(card.dataset.modkey), 0, dragKey);
      S.resume.order = order;
      dragKey = null;
      markDirty(); buildLeftPanel(); renderCenter();
    });
  }

  function toggleHide(key) {
    var i = S.resume.hidden.indexOf(key);
    if (i >= 0) S.resume.hidden.splice(i, 1);
    else S.resume.hidden.push(key);
    markDirty(); buildLeftPanel(); renderCenter();
  }
  function moveModule(key, dir) {
    var order = S.resume.order.slice();
    var i = order.indexOf(key);
    var j = dir === 'up' ? i - 1 : i + 1;
    if (j < 0 || j >= order.length) return;
    order.splice(j, 0, order.splice(i, 1)[0]);
    S.resume.order = order;
    markDirty(); buildLeftPanel(); renderCenter();
  }
  function removeModule(key) {
    S.resume.order = S.resume.order.filter(function (k) { return k !== key; });
    markDirty(); buildLeftPanel(); renderCenter();
  }
  function addModule(key) {
    if (S.resume.order.indexOf(key) >= 0 || !MODULE_META[key]) return;
    S.resume.order.push(key);
    markDirty(); buildLeftPanel(); renderCenter();
  }
  function newRecord(key) {
    var spec = FIELD_SPECS[key] || [];
    var rec = {};
    spec.forEach(function (f) { rec[f.k] = f.t === 'check' ? false : ''; });
    if (key === 'education') { rec.degree = rec.degree || ''; }
    return rec;
  }
  function addItem(key) {
    if (!Array.isArray(S.resume.modules[key])) S.resume.modules[key] = [];
    S.resume.modules[key].push(newRecord(key));
    markDirty(); buildLeftPanel(); renderCenter();
    /* 聚焦新条目第一个输入框 */
    var cards = document.querySelectorAll('.v3-mod-card[data-modkey="' + key + '"] .v3-item-card');
    var last = cards[cards.length - 1];
    if (last) {
      var inp = last.querySelector('input.v3-input');
      if (inp) inp.focus();
      last.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }
  function removeItem(key, idx) {
    var arr = S.resume.modules[key];
    if (arr && arr[idx]) { arr.splice(idx, 1); markDirty(); buildLeftPanel(); renderCenter(); }
  }

  /* ═════════ 右栏：设计面板 ═════════ */

  var FAM_FIGS = {
    single: '<i style="left:8%;top:10%;width:30%;height:22%"></i><i style="left:8%;bottom:12%;width:84%;height:8%"></i><i style="left:8%;bottom:28%;width:70%;height:8%"></i>',
    sidebar: '<i style="left:0;top:0;bottom:0;width:30%"></i><i style="left:38%;top:10%;width:52%;height:12%"></i><i style="left:38%;bottom:12%;width:52%;height:8%"></i>',
    headerBar: '<i style="left:0;top:0;right:0;height:34%"></i><i style="left:8%;bottom:14%;width:84%;height:8%"></i><i style="left:8%;bottom:30%;width:64%;height:8%"></i>',
    twoCol: '<i style="left:6%;top:10%;width:38%;height:70%"></i><i style="left:54%;top:10%;width:38%;height:40%"></i>'
  };

  function buildRightPanel() {
    /* 版式族 */
    var fg = $('famGrid');
    fg.innerHTML = Object.keys(FAMILIES).map(function (f) {
      return '<button class="v3-fam-btn' + (S.theme.family === f ? ' sel' : '') + '" data-fam="' + f + '" title="' + esc(FAMILIES[f].hint) + '">' +
        '<div class="v3-fam-fig">' + FAM_FIGS[f] + '</div><div class="v3-fam-name">' + esc(FAMILIES[f].name) + '</div></button>';
    }).join('');
    fg.onclick = function (e) {
      var btn = e.target.closest('[data-fam]');
      if (!btn) return;
      S.theme.family = btn.dataset.fam;
      markDirty(); buildRightPanel(); renderCenter();
    };

    /* 主色 */
    var sw = $('swatches');
    sw.innerHTML = THEMES_ORDER.map(function (tid) {
      var c = ResumeRender.THEMES[tid];
      return '<span class="v3-swatch' + (S.theme.theme === tid && !isCustomPrimary() ? ' sel' : '') + '" data-theme="' + tid + '" title="' + esc(c.name) + '" style="background:' + c.accent + '"></span>';
    }).join('');
    sw.onclick = function (e) {
      var el = e.target.closest('[data-theme]');
      if (!el) return;
      var tid = el.dataset.theme;
      S.theme.theme = tid;
      S.theme.primary = ResumeRender.THEMES[tid].accent;
      markDirty(); buildRightPanel(); applyStyleVars();
    };
    var cc = $('customColor');
    cc.value = /^#[0-9a-fA-F]{6}$/.test(S.theme.primary) ? S.theme.primary : DEFAULT_THEME.primary;
    cc.oninput = function () {
      S.theme.primary = cc.value;
      S.theme.theme = 'custom';
      markDirty(); buildRightPanel(); applyStyleVars();
    };

    /* 字体 */
    var fs = $('fontSel');
    fs.innerHTML = Object.keys(FONTS).map(function (fid) {
      return '<option value="' + fid + '"' + (S.theme.font === fid ? ' selected' : '') + '>' + esc(FONTS[fid].name) + '</option>';
    }).join('');
    fs.onchange = function () { S.theme.font = fs.value; markDirty(); applyStyleVars(); };

    bindSlider('fontSize', function (v) { S.theme.fontSize = v; }, function (v) { return v + 'px'; });
    bindSlider('lineHeight', function (v) { S.theme.lineHeight = v; }, function (v) { return Number(v).toFixed(2); });
    bindSlider('nameSize', function (v) { S.theme.nameSize = v; }, function (v) { return v + 'px'; });
    bindSlider('gap', function (v) { S.theme.gap = v; }, function (v) { return v + 'px'; });
    bindSlider('padding', function (v) { S.theme.padding = v; }, function (v) { return v + 'px'; });
    bindSlider('photoSize', function (v) { S.theme.photoSize = v; }, function (v) { return v + 'px'; });

    var ss = $('sectionStyle');
    ss.value = S.theme.sectionStyle;
    ss.onchange = function () { S.theme.sectionStyle = ss.value; markDirty(); renderCenter(); };

    /* 头像 */
    var sp = $('showPhoto');
    sp.checked = S.resume.showPhoto !== false;
    sp.onchange = function () {
      S.resume.showPhoto = sp.checked;
      markDirty(); syncPhotoUI(); renderCenter();
    };
    Array.prototype.forEach.call(document.querySelectorAll('.v3-shape-btn'), function (b) {
      b.classList.toggle('sel', S.theme.photoShape === b.dataset.shape);
      b.onclick = function () {
        S.theme.photoShape = b.dataset.shape;
        markDirty(); buildRightPanel(); renderCenter();
      };
    });
    $('photoInput').onchange = function () {
      var file = this.files && this.files[0];
      if (!file) return;
      downscaleImage(file, function (dataUrl) {
        S.resume.basic.photo = dataUrl;
        S.resume.showPhoto = true;
        markDirty(); syncPhotoUI(); buildLeftPanel(); renderCenter();
        toast('照片已更新');
      });
      this.value = '';
    };
    syncPhotoUI();
  }

  function isCustomPrimary() {
    return !ResumeRender.THEMES[S.theme.theme] || S.theme.theme === 'custom';
  }

  function bindSlider(id, setter, fmt) {
    var el = $(id), val = $(id + 'Val');
    el.value = S.theme[id];
    if (val) val.textContent = fmt(S.theme[id]);
    el.oninput = function () {
      var v = parseFloat(el.value);
      setter(v);
      if (val) val.textContent = fmt(v);
      markDirty(); applyStyleVars();
    };
  }

  function applyStyleVars() {
    var page = $('paper').querySelector('.rr-page');
    if (page) ResumeRender.applyVars(page, buildStyle());
  }

  function syncPhotoUI() {
    var has = hasText(S.resume.basic.photo) && S.resume.showPhoto !== false;
    var img = $('photoPrevImg'), txt = $('photoPrevTxt');
    if (has) { img.src = S.resume.basic.photo; img.hidden = false; txt.hidden = true; }
    else { img.hidden = true; txt.hidden = false; txt.textContent = S.resume.showPhoto === false ? '已隐藏' : '无照片'; }
  }

  function downscaleImage(file, cb) {
    var reader = new FileReader();
    reader.onload = function () {
      var img = new Image();
      img.onload = function () {
        var max = 480;
        var w = img.width, h = img.height;
        if (Math.max(w, h) > max) {
          var k = max / Math.max(w, h);
          w = Math.round(w * k); h = Math.round(h * k);
        }
        var cv = document.createElement('canvas');
        cv.width = w; cv.height = h;
        cv.getContext('2d').drawImage(img, 0, 0, w, h);
        cb(cv.toDataURL('image/jpeg', 0.82));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }

  /* ═════════ 顶栏 / 模板库 ═════════ */

  function setSavedTip(state, text) {
    var t = $('savedTip');
    t.textContent = text;
    t.className = 'v3-saved' + (state ? ' ' + state : '');
  }

  function markDirty() {
    S.dirty = true;
    setSavedTip('is-dirty', '编辑中…');
    clearTimeout(LOCAL_SAVE_TIMER);
    LOCAL_SAVE_TIMER = setTimeout(saveLocal, 800);
    clearTimeout(DRAFT_SAVE_TIMER);
    DRAFT_SAVE_TIMER = setTimeout(function () { saveCloud(false); }, 3000);
  }

  function saveLocal() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({
        draftId: S.draftId, title: S.title,
        resume: S.resume, theme: S.theme, ts: Date.now()
      }));
    } catch (e) { /* 存储满等异常忽略 */ }
  }

  function saveCloud(manual) {
    if (!S.user || S.saving) { if (manual) toast('请先登录后再保存'); return; }
    S.saving = true;
    var name = (S.resume.basic.name || '').trim();
    var title = name ? name + '的简历' : (S.title || '未命名简历');
    apiPost('/api/draft/save', {
      draft_id: S.draftId,
      template_id: null,
      title: title,
      data: { v: 3, resume: S.resume, theme: S.theme }
    }).then(function (resp) {
      S.saving = false;
      S.dirty = false;
      if (resp && resp.draft_id) S.draftId = resp.draft_id;
      saveLocal();
      var t = new Date();
      setSavedTip('is-ok', '已同步云端 ' + ('0' + t.getHours()).slice(-2) + ':' + ('0' + t.getMinutes()).slice(-2));
      if (manual) toast('已保存到云端');
    }).catch(function (e) {
      S.saving = false;
      setSavedTip('is-dirty', '云端保存失败');
      if (manual) toast('保存失败：' + e.message, true);
    });
  }

  function bindTopbar() {
    $('saveBtn').onclick = function () { saveCloud(true); };

    /* 下载菜单 */
    var menu = $('downloadMenu');
    $('downloadBtn').onclick = function (e) { e.stopPropagation(); menu.hidden = !menu.hidden; };
    document.addEventListener('click', function () { menu.hidden = true; });
    menu.addEventListener('click', function (e) {
      var b = e.target.closest('[data-fmt]');
      if (b) { menu.hidden = true; download(b.dataset.fmt); }
    });

    /* 更换模板 */
    $('tplBtn').onclick = function () { openTplModal(); };
    $('tplModal').addEventListener('click', function (e) {
      if (e.target === $('tplModal') || e.target.closest('[data-close-tpl]')) $('tplModal').hidden = true;
    });
  }

  function currentPresetKey() {
    for (var i = 0; i < PRESETS.length; i++) {
      var p = PRESETS[i];
      if (p.family === S.theme.family && p.theme === S.theme.theme) return p.key;
    }
    return null;
  }

  function openTplModal() {
    var grid = $('tplGrid');
    grid.innerHTML = '';
    var curKey = currentPresetKey();
    PRESETS.forEach(function (p) {
      var style = mergeTheme(Object.assign({}, S.theme, { family: p.family, theme: p.theme, primary: ResumeRender.THEMES[p.theme].accent }));
      var card = document.createElement('div');
      card.className = 'v3-tpl-card' + (curKey === p.key ? ' sel' : '');
      card.innerHTML = '<div class="v3-tpl-thumb"></div><div class="v3-tpl-name">' + esc(p.name) + '</div>';
      var thumb = card.querySelector('.v3-tpl-thumb');
      card.__preset = p;
      card.addEventListener('click', function () {
        S.theme.family = p.family;
        S.theme.theme = p.theme;
        S.theme.primary = ResumeRender.THEMES[p.theme].accent;
        $('tplModal').hidden = true;
        markDirty(); buildRightPanel(); renderCenter();
        toast('已更换模板「' + p.name + '」，内容未丢失');
      });
      grid.appendChild(card);
      thumb.innerHTML = ResumeRender.render(SAMPLE, style);
      var page = thumb.querySelector('.rr-page');
      ResumeRender.applyVars(page, style);
    });
    /* 缩略图按宽度缩放 */
    requestAnimationFrame(function () {
      Array.prototype.forEach.call(grid.querySelectorAll('.v3-tpl-thumb'), function (th) {
        var page = th.querySelector('.rr-page');
        if (!page) return;
        var z = th.clientWidth / A4.w;
        page.style.transform = 'scale(' + z + ')';
        page.style.transformOrigin = 'top left';
      });
    });
    $('tplModal').hidden = false;
  }

  /* ═════════ 导出 ═════════ */

  function exportPayload() {
    var resume = JSON.parse(JSON.stringify(S.resume));
    if (resume.showPhoto === false) resume.basic.photo = '';
    return { resume: resume, theme: S.theme };
  }

  function download(fmt) {
    showLoading(fmt === 'png' ? '正在生成长图…' : fmt === 'pdf' ? '正在生成 PDF…' : '正在生成 Word…');
    fetch('/api/export/' + fmt, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(exportPayload())
    }).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (d) {
          throw new Error(d.detail || ('HTTP ' + r.status));
        });
      }
      return r.blob().then(function (blob) {
        var cd = r.headers.get('Content-Disposition') || '';
        var fname = '简历.' + fmt;
        var m = /filename\*=UTF-8''([^;]+)/.exec(cd);
        if (m) { try { fname = decodeURIComponent(m[1]); } catch (e2) { /* keep */ } }
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = fname;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
        toast('已开始下载「' + fname + '」');
      });
    }).catch(function (e) {
      toast('导出失败：' + e.message, true);
    }).then(function () { hideLoading(); });
  }

  /* ═════════ 草稿载入 ═════════ */

  function loadInitial() {
    var m = /(?:^|[?&])draft_id=(\d+)/.exec(location.search);
    if (m) {
      return apiGet('/api/draft/' + m[1]).then(function (d) {
        if (d && d.data) {
          var n = normalizeData(d.data);
          S.resume = n.resume; S.theme = n.theme;
          S.draftId = d.id; S.title = d.title || '';
          setSavedTip('is-ok', '已打开云端草稿');
          return;
        }
        toast('草稿不存在或已删除，已新建空白简历', true);
      }).catch(function () {
        toast('草稿加载失败，已新建空白简历', true);
      });
    }
    /* 本地自动保存恢复 */
    try {
      var raw = localStorage.getItem(LS_KEY);
      if (raw) {
        var s = JSON.parse(raw);
        if (s && s.resume) {
          var n2 = normalizeData({ v: 3, resume: s.resume, theme: s.theme });
          S.resume = n2.resume; S.theme = n2.theme;
          S.draftId = s.draftId || null; S.title = s.title || '';
          setSavedTip('is-ok', '已恢复本地编辑');
        }
      }
    } catch (e) { /* ignore */ }
    return Promise.resolve();
  }

  /* ═════════ 启动 ═════════ */

  function boot() {
    apiGet('/api/me').then(function (me) {
      if (!me) { location.href = '/login'; return null; }
      S.user = me;
      return loadInitial().then(function () {
        bindInline($('paper'));
        bindLeftPanel();
        buildLeftPanel();
        buildRightPanel();
        renderCenter();
        bindTopbar();
        window.addEventListener('resize', debounce(layoutPaper, 150));
        setSavedTip(S.draftId ? 'is-ok' : '', S.draftId ? '已同步云端' : '自动保存已开启');
      });
    }).catch(function (e) {
      document.body.innerHTML = '<div style="padding:60px;text-align:center;color:#8A93A6;font-size:14px">编辑器加载失败：' + esc(e.message) + '</div>';
    });
  }

  boot();
})();
