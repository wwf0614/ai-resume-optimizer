/* ============================================================
 * 简历编辑器（简历星球 AI 智能优化系统）
 * 路径：/static/editor.js
 * 核心：每份模板有完全不同的视觉布局（tukuppt 风格）
 * 支持：creative-border / dark-sidebar / clean-minimal /
 *        color-header / circle-photo / icon-minimal / academic /
 *        warm / tech / elegant 共 10 种独立布局
 * ============================================================ */

(function () {
  'use strict';

  /* 暴露给 HTML onclick 的接口 */
  window.__editor = null;

  /* 工具：HTML 转义 */
  function esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  /* ============ 状态 ============ */
  const State = {
    draftId: null,
    templateId: null,
    templates: [],
    vipTemplates: [],
    freeTemplates: [],
    basic: {},
    modules: {
      education_info:    [],
      work_history:      [],
      internship_info:   [],
      projects:          [],
      /* 三个模块采用结构化多记录，兼容旧草稿中的纯文本内容 */
      campus_exp:        [],
      skill_info:        [],
      honor_cert:        [],
      self_evaluate:     '',
      hobby:             [],
      custom:            ''
    },
    order: ['basic','intention','education','work','internship','project','campus','skill','honor','self','hobby','custom'],
    visible: {
      basic: true, intention: true, education: true, work: true,
      internship: false, project: false, campus: false, skill: false,
      honor: false, self: true, hobby: false, custom: false
    },
    activeModule: null,
    photoDataUrl: null,
    showPhoto: true,
    /* 外观参数：数据驱动渲染的全部可调项。
       spacing 是旧的粗粒度档位，gap/padding 由它派生默认值，
       一旦用户手动拖过滑杆就写死具体数值（gap/padding 优先）。 */
    style: {
      family: 'single',           // 版式族：single / sidebar / headerBar / twoCol
      skin: 'default',            // 配色主题
      font: 'yahei',              // 正文字体
      fontSize: 13,               // 正文字号 px
      lineHeight: 1.72,           // 行距倍数
      spacing: 'normal',          // 间距档位（紧凑/标准/宽松）
      gap: null,                  // 模块间距 px；null = 跟随 spacing 档位
      padding: null,              // 版心留白 px；null = 跟随 spacing 档位
      nameSize: 30,                // 姓名字号 px
      photoSize: 92,               // 照片尺寸 px
      photoShape: 'rect',          // rect / circle
      sectionStyle: 'underline',   // 小节标题样式：underline / bar / plain
      cover: false
    },
    /* 预览模式：'doc' = 数据驱动 HTML 预览（快，可即时改样式）
                 'exact' = Word 成品图 + 热区（慢，版式与导出像素级一致） */
    previewMode: 'doc',
    /* 基本信息字段级显示控制：编辑数据不受显示状态影响 */
    fieldVisible: {},
    /* 质量引擎：匹配度评分 / ATS 校验 共用的最近一次目标岗位与 JD（免费功能，非 VIP） */
    quality: { target_job: '', jd: '' }
  };

  /* ============ 模块元数据 ============ */
  const MODULES = [
    { key:'basic',       label:'基本信息', icon:'👤' },
    { key:'intention',   label:'求职意向', icon:'🎯' },
    { key:'education',   label:'教育背景', icon:'🎓', dataKey:'education_info',    defaultOn:true },
    { key:'work',        label:'工作经验', icon:'💼', dataKey:'work_history',      defaultOn:true },
    { key:'internship',  label:'实习经验', icon:'🏢', dataKey:'internship_info' },
    { key:'project',     label:'项目经验', icon:'🚀', dataKey:'projects' },
    { key:'campus',      label:'校园经历', icon:'🏛️', dataKey:'campus_exp', listKind:'campus' },
    { key:'skill',       label:'技能特长', icon:'⚡', dataKey:'skill_info', listKind:'skill' },
    { key:'honor',       label:'荣誉证书', icon:'🏆', dataKey:'honor_cert', listKind:'honor' },
    { key:'self',        label:'自我评价', icon:'✨', dataKey:'self_evaluate',     defaultOn:true },
    { key:'hobby',       label:'兴趣爱好', icon:'💡', dataKey:'hobby' },
    { key:'custom',      label:'自定义',   icon:'📝', dataKey:'custom' }
  ];

  /* ============ 基本信息字段定义 ============ */
  const BASIC_FIELDS_LEFT = [
    { key:'name',           label:'姓名' },
    { key:'gender',         label:'性别' },
    { key:'height',         label:'身高' },
    { key:'hometown',       label:'籍贯' },
    { key:'political_status',label:'政治面貌' },
    { key:'city',           label:'现居城市' }
  ];
  const BASIC_FIELDS_RIGHT = [
    { key:'birth_date',     label:'出生日期' },
    { key:'age',            label:'年龄（工作年限）' },
    { key:'marriage',       label:'婚姻状况' },
    { key:'phone',          label:'手机号码' },
    { key:'email',          label:'邮箱' },
    { key:'wechat',         label:'微信号' }
  ];
  const BASIC_FIELDS_EXTRA = [
    { key:'nation',         label:'民族' },
    { key:'education_degree',label:'学历' },
    { key:'school',         label:'毕业院校' },
    { key:'major',          label:'专业' }
  ];

  /* ============ 图标行基本信息字段（用于 icon-row 布局） ============ */
  const ICON_BASIC_FIELDS = [
    { key:'birth_date', label:'出生日期', icon:'📅' },
    { key:'phone',      label:'手机号码', icon:'📱' },
    { key:'email',      label:'邮箱',     icon:'✉️' },
    { key:'height',     label:'身高',     icon:'👔' },
    { key:'hometown',   label:'籍贯',     icon:'🏠' },
    { key:'nation',     label:'民族',     icon:'👥' }
  ];

  /* ═══════════════════════════════════════════════════════════════
   * 模板布局系统 — 每份模板完全不同的视觉结构
   * layoutType 决定 DOM 排版方式，其他参数控制配色和细节
   * ═══════════════════════════════════════════════════════════════ */

  const TEMPLATE_LAYOUTS = {

    /* ─── Template 1: 创意边框式（Screenshot 1 风格）─── */
    1: {
      name: '创意边框',
      layoutType: 'creative-border',
      primary: '#2A7C6F',
      headerBg: '#2A7C6F',
      headerColor: '#FFF',
      accent: '#3D9B8C',
      bodyBg: '#FFFEFA',
      sectionStyle: 'icon-tab',
      headerStyle: 'ribbon',
      nameSize: 28,
      photoPos: 'right',
      photoShape: 'rect',
      decoStyle: 'stripe-border',
      borderRadius: 0,
      fontFamily: '"Microsoft YaHei",sans-serif'
    },

    /* ─── Template 2: 暗色侧栏式（Screenshot 2 风格）─── */
    2: {
      name: '暗色侧栏',
      layoutType: 'dark-sidebar',
      primary: '#2C3E50',
      headerBg: '#2C3E50',
      headerColor: '#FFF',
      accent: '#34495E',
      bodyBg: '#FFFFFF',
      sectionStyle: 'underline-dark',
      headerStyle: 'sidebar-title',
      nameSize: 26,
      photoPos: 'sidebar',
      photoShape: 'rect',
      decoStyle: 'none',
      borderRadius: 0,
      fontFamily: '"Microsoft YaHei",sans-serif',
      sidebarWidth: '34%',
      sidebarBg: '#34495E'
    },

    /* ─── Template 3: 简约灰白（Screenshot 3 风格）─── */
    3: {
      name: '简约灰白',
      layoutType: 'clean-minimal',
      primary: '#4A90A4',
      headerBg: '#D8D8D8',
      headerColor: '#333',
      accent: '#4A90A4',
      bodyBg: '#FFFFFF',
      sectionStyle: 'flat-bar',
      headerStyle: 'gray-bar',
      nameSize: 30,
      photoPos: 'right',
      photoShape: 'rect',
      decoStyle: 'none',
      borderRadius: 2,
      fontFamily: '"Microsoft YaHei",sans-serif'
    },

    /* ─── Template 4: 彩色顶栏（Screenshot 4 风格）─── */
    4: {
      name: '彩色顶栏',
      layoutType: 'color-header',
      primary: '#3B7A8E',
      headerBg: '#3B7A8E',
      headerColor: '#FFF',
      accent: '#5BA3B8',
      bodyBg: '#FFFFFF',
      sectionStyle: 'color-tab',
      headerStyle: 'full-bar-name',
      nameSize: 24,
      photoPos: 'header-right',
      photoShape: 'rect',
      decoStyle: 'none',
      borderRadius: 2,
      fontFamily: '"Microsoft YaHei",sans-serif',
      basicStyle: 'icon-row'
    },

    /* ─── Template 5: 圆形照片（Screenshot 5 风格）─── */
    5: {
      name: '圆形照片',
      layoutType: 'circle-photo',
      primary: '#468B9A',
      headerBg: '#468B9A',
      headerColor: '#FFF',
      accent: '#5DAAB8',
      bodyBg: '#FFFFFF',
      sectionStyle: 'deco-tab',
      headerStyle: 'bar-name-left',
      nameSize: 26,
      photoPos: 'top-left',
      photoShape: 'circle',
      decoStyle: 'diagonal',
      borderRadius: 2,
      fontFamily: '"Microsoft YaHei",sans-serif',
      basicStyle: 'icon-row'
    },

    /* ─── Template 6: 极简图标（Screenshot 6 风格）─── */
    6: {
      name: '极简图标',
      layoutType: 'icon-minimal',
      primary: '#5B8DBE',
      headerBg: 'transparent',
      headerColor: '#333',
      accent: '#7AA8D4',
      bodyBg: '#FFFFFF',
      sectionStyle: 'circle-icon',
      headerStyle: 'plain-text',
      nameSize: 32,
      photoPos: 'right',
      photoShape: 'rect',
      decoStyle: 'none',
      borderRadius: 2,
      fontFamily: '"Microsoft YaHei",sans-serif',
      basicStyle: 'icon-row'
    },

    /* ─── Template 7: 学术严谨 ─── */
    7: {
      name: '学术严谨',
      layoutType: 'academic',
      primary: '#6B4C8E',
      headerBg: '#6B4C8E',
      headerColor: '#FFF',
      accent: '#8B6BBE',
      bodyBg: '#FEFCFF',
      sectionStyle: 'double-line',
      headerStyle: 'serif-bar',
      nameSize: 24,
      photoPos: 'right',
      photoShape: 'rect',
      decoStyle: 'corner',
      borderRadius: 3,
      fontFamily: '"SimSun","宋体",serif'
    },

    /* ─── Template 8: 暖色调 ─── */
    8: {
      name: '暖色调',
      layoutType: 'warm',
      primary: '#B8693E',
      headerBg: '#B8693E',
      headerColor: '#FFF',
      accent: '#D4956A',
      bodyBg: '#FFFDF8',
      sectionStyle: 'warm-tab',
      headerStyle: 'warm-bar',
      nameSize: 26,
      photoPos: 'right',
      photoShape: 'rect',
      decoStyle: 'none',
      borderRadius: 4,
      fontFamily: '"Microsoft YaHei",sans-serif'
    },

    /* ─── Template 9: 科技蓝 ─── */
    9: {
      name: '科技蓝',
      layoutType: 'tech',
      primary: '#1A5276',
      headerBg: '#1A5276',
      headerColor: '#FFF',
      accent: '#2980B9',
      bodyBg: '#F5F9FC',
      sectionStyle: 'tech-line',
      headerStyle: 'tech-bar',
      nameSize: 25,
      photoPos: 'right',
      photoShape: 'rect',
      decoStyle: 'circuit',
      borderRadius: 2,
      fontFamily: '"Consolas","Microsoft YaHei",monospace'
    },

    /* ─── Template 10: 优雅商务 ─── */
    10: {
      name: '优雅商务',
      layoutType: 'elegant',
      primary: '#1C2833',
      headerBg: '#1C2833',
      headerColor: '#FFF',
      accent: '#2E4053',
      bodyBg: '#FFFFFF',
      sectionStyle: 'elegant-bar',
      headerStyle: 'elegant-center',
      nameSize: 28,
      photoPos: 'right',
      photoShape: 'rect',
      decoStyle: 'gold-line',
      borderRadius: 0,
      fontFamily: '"Georgia","Microsoft YaHei",serif'
    }
  };

  const DEFAULT_LAYOUT = TEMPLATE_LAYOUTS[1];

  function getTplLayout() {
    const tid = State.templateId;
    return (tid && TEMPLATE_LAYOUTS[tid]) ? TEMPLATE_LAYOUTS[tid] : DEFAULT_LAYOUT;
  }

  /**
   * 应用模板布局 — 核心函数，根据 layoutType 完全改变视觉结构
   */
  function applyTplLayout() {
    const cfg = getTplLayout();
    const paper = $('previewPaper');
    if (!paper) return;

    // 设置布局类型类名（决定整体排版）
    paper.className = 'ed-paper rp-paper rp-lt-' + cfg.layoutType +
      ' rp-sec-' + cfg.sectionStyle +
      ' rp-hs-' + cfg.headerStyle +
      ' rp-photo-' + cfg.photoPos +
      ' rp-shape-' + cfg.photoShape +
      (cfg.decoStyle !== 'none' ? ' rp-deco-' + cfg.decoStyle : '');

    paper.style.background = cfg.bodyBg;
    paper.style.borderRadius = (cfg.borderRadius || 0) + 'px';
    paper.style.fontFamily = cfg.fontFamily || '"Microsoft YaHei",sans-serif';

    const root = document.documentElement.style;
    root.setProperty('--rp-primary', cfg.primary);
    root.setProperty('--rp-header-bg', cfg.headerBg);
    root.setProperty('--rp-header-color', cfg.headerColor);
    root.setProperty('--rp-accent', cfg.accent);
    root.setProperty('--rp-name-size', cfg.nameSize + 'px');

    // 侧栏布局特殊处理
    if (cfg.layoutType === 'dark-sidebar') {
      root.setProperty('--rp-sidebar-bg', cfg.sidebarBg || '#34495E');
      root.setProperty('--rp-sidebar-width', cfg.sidebarWidth || '34%');
    }

    // 装饰元素显隐
    const deco = document.querySelector('.rp-deco-icons');
    if (deco) deco.style.display = ['ribbon','sidebar-title'].includes(cfg.headerStyle) ? '' : 'none';

    console.log('[editor] 应用模板布局:', cfg.name, '| 类型:', cfg.layoutType);
  }

  /* ============ DOM 工具 ============ */
  const $ = id => document.getElementById(id);
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === 'class') node.className = attrs[k];
        else if (k === 'style') node.setAttribute('style', attrs[k]);
        else if (k === 'html') node.innerHTML = attrs[k];
        else if (k.startsWith('on') && typeof attrs[k] === 'function') {
          node.addEventListener(k.slice(2), attrs[k]);
        } else if (attrs[k] === true) node.setAttribute(k, '');
        else if (attrs[k] !== false && attrs[k] != null) node.setAttribute(k, attrs[k]);
      }
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return node;
  }

  /* ============ Toast & Loading ============ */
  let toastTimer;
  function toast(msg, type) {
    const t = $('toast');
    t.textContent = msg;
    t.className = 'ed-toast' + (type ? ' ' + type : '');
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 2200);
  }
  function showLoading(text) {
    $('loadingText').textContent = text || '处理中…';
    $('loadingMask').hidden = false;
  }
  function hideLoading() { $('loadingMask').hidden = true; }

  /* ============ API ============ */
  function authHeader() {
    // 兼容登录页实际存储的 resume_planet_token（编辑器早期用的 rz_token 也保留）
    const t = localStorage.getItem('rz_token') || sessionStorage.getItem('rz_token')
      || localStorage.getItem('resume_planet_token') || sessionStorage.getItem('resume_planet_token');
    return t ? { Authorization: 'Bearer ' + t } : {};
  }
  async function apiGet(url) {
    const r = await fetch(url, { headers: authHeader() });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }
  async function apiPost(url, body) {
    const isForm = body instanceof FormData;
    const r = await fetch(url, {
      method: 'POST',
      headers: isForm ? authHeader() : Object.assign({ 'Content-Type': 'application/json' }, authHeader()),
      body: isForm ? body : JSON.stringify(body)
    });
    const text = await r.text();
    let data = null;
    try { data = JSON.parse(text); } catch (e) { data = { raw: text }; }
    if (!r.ok) throw new Error(data.detail || data.error || ('HTTP ' + r.status));
    return data;
  }

  /* ============ 登录门禁（VIP 付费门禁已暂停，后续恢复） ============ */
  async function ensureVipAccess() {
    const gate = $('vipGate');
    const openBtn = $('vipGateOpenBtn');
    const showGate = (msg) => {
      if (gate) {
        const p = $('vipGateMsg');
        if (p && msg) p.textContent = msg;
        gate.hidden = false;
      }
    };
    try {
      await apiGet('/api/me');
      return true;
    } catch (e) {
      showGate('请先登录后再使用在线编辑器。');
      return false;
    }
  }

  /* ============ VIP 身份校验（仅用于 AI 编辑等付费能力，不影响登录用户进入编辑器） ============ */
  let _vipCache = null; // null=尚未获取, true/false
  async function isVipUser() {
    if (_vipCache !== null) return _vipCache;
    try {
      const me = await apiGet('/api/me');
      _vipCache = !!(me && me.is_vip);
    } catch (e) {
      _vipCache = false;
    }
    return _vipCache;
  }
  async function requireVip() {
    if (await isVipUser()) return true;
    toast('AI 智能编辑为 VIP 会员专属，敬请期待', '');
    return false;
  }

  /* ============ 实时预览（后端 Word 渲染 → PNG） ============ */
  let _previewTimer = null;
  let _previewReqId = 0;
  function scheduleLivePreview(delay) {
    if (_previewTimer) clearTimeout(_previewTimer);
    _previewTimer = setTimeout(() => livePreview().catch(()=>{}), delay || 1200);
  }
  async function livePreview() {
    if (!State.templateId) return;
    const reqId = ++_previewReqId;
    const content = buildStdContent();
    const fd = new FormData();
    fd.append('template_id', State.templateId);
    fd.append('content', JSON.stringify(content));
    try {
      const r = await apiPost('/api/render-preview', fd);
      if (reqId !== _previewReqId) return;
      console.log('[editor] 后端渲染完成, cached:', !!r.cached);
    } catch (e) {
      if (reqId !== _previewReqId) return;
      console.warn('[editor] 后端渲染失败:', e.message);
    }
  }
  function buildStdContent() {
    const c = {};
    Object.assign(c, State.basic || {});
    const mods = State.modules || {};
    if (mods.education_info && mods.education_info.length) {
      c.education_info = mods.education_info.map(x =>
        [x.school, x.major, x.degree, (x.start||'')+'~'+(x.current?'至今':(x.end||'')), x.content].filter(Boolean).join(' / ')
      ).join('\n');
    }
    if (mods.work_history && mods.work_history.length) {
      c.work_history = mods.work_history.map(x =>
        [x.company, x.position, (x.start||'')+'~'+(x.current?'至今':(x.end||'')), x.content].filter(Boolean).join(' / ')
      ).join('\n');
    }
    if (mods.internship_info && mods.internship_info.length) {
      c.work_history = (c.work_history ? c.work_history+'\n' : '') +
        mods.internship_info.map(x => [x.company, x.position, (x.start||'')+'~'+(x.current?'至今':(x.end||'')), x.content].filter(Boolean).join(' / ')).join('\n');
    }
    if (mods.projects && mods.projects.length) {
      c.projects = mods.projects.map(x => [x.name, x.role, x.period, x.content].filter(Boolean).join(' / ')).join('\n');
    }
    if (Array.isArray(mods.skill_info)) c.skill_info = mods.skill_info.map(x => [x.name, x.level, x.content].filter(Boolean).join('：')).join('\n');
    else if (mods.skill_info) c.skill_info = mods.skill_info;
    if (Array.isArray(mods.honor_cert)) c.honor_cert = mods.honor_cert.map(x => [x.time, x.name, x.issuer].filter(Boolean).join(' · ')).join('\n');
    else if (mods.honor_cert) c.honor_cert = mods.honor_cert;
    if (mods.self_evaluate) c.self_evaluate = mods.self_evaluate;
    if (Array.isArray(mods.campus_exp)) c.campus_exp = mods.campus_exp.map(x => [x.name, x.role, x.period, x.content].filter(Boolean).join(' · ')).join('\n');
    else if (mods.campus_exp) c.campus_exp = mods.campus_exp;
    if (Array.isArray(mods.hobby) && mods.hobby.length) c.hobby = mods.hobby.join('、');
    return c;
  }

  /* ════════════════════════════════════════════════════════
   * 核心渲染：根据模板布局类型动态渲染简历
   * ════════════════════════════════════════════════════════ */

  /* 间距档位 → 具体数值。渲染与外观面板共用同一份，避免两处走偏。 */
  const SPACING_MAP = {
    compact: { gap: 12, pad: 34, label: '紧凑' },
    normal:  { gap: 20, pad: 44, label: '标准' },
    loose:   { gap: 28, pad: 56, label: '宽松' }
  };
  function spacingValue(kind) {
    const m = SPACING_MAP[State.style.spacing] || SPACING_MAP.normal;
    return kind === 'pad' ? m.pad : m.gap;
  }
  /** 当前生效的模块间距 / 版心留白（滑杆显示值也用它） */
  function effGap() { const v = State.style.gap; return v != null ? v : spacingValue('gap'); }
  function effPad() { const v = State.style.padding; return v != null ? v : spacingValue('pad'); }

  /** 全量重新渲染左侧简历预览区 */
  function renderPreview() {
    // 「精确预览」模式：Word 成品图 + 热区（慢，但版式与导出完全一致）
    // 仅在用户显式切换时使用。默认走数据驱动的 HTML 渲染：毫秒级、可即时改样式。
    if (State.previewMode === 'exact' && isRealTemplateActive()) {
      renderRealTemplate();
    } else {
      renderDocPreview();
    }
    // 外观面板的锁定提示与顶栏按钮的开关态都依赖当前预览模式
    renderAppearancePanel();
    syncExactBtn();
  }

  /* ════════════════════════════════════════════════════════
   * 数据驱动渲染：结构化 State → 参数化 A4 版面
   * 引擎在 resume-render.js；此处只负责喂数据、喂样式
   * ════════════════════════════════════════════════════════ */

  /** State → 渲染引擎的数据契约 */
  function buildRenderData() {
    return {
      basic: State.basic || {},
      intention: State.intention || {},
      modules: State.modules || {},
      order: State.order || [],
      visible: State.visible || {},
      photo: State.photoDataUrl || null,
      showPhoto: State.showPhoto !== false,
      fieldVisible: State.fieldVisible || {}
    };
  }

  /** State.style → 渲染引擎样式参数（skin/font 的 id 已与引擎预设对齐，可直用） */
  function buildRenderStyle() {
    const sv = State.style || {};
    const base = (window.ResumeRender && window.ResumeRender.DEFAULT_STYLE) || {};
    return Object.assign({}, base, {
      family:       sv.family || 'single',
      theme:        sv.skin || 'default',
      font:         sv.font || 'yahei',
      fontSize:     sv.fontSize || 13,
      lineHeight:   sv.lineHeight || 1.72,
      gap:          effGap(),
      padding:      effPad(),
      nameSize:     sv.nameSize || 30,
      photoSize:    sv.photoSize || 92,
      photoShape:   sv.photoShape || 'rect',
      sectionStyle: sv.sectionStyle || 'underline'
    });
  }

  /** 用引擎渲染预览画布 */
  function renderDocPreview() {
    const paper = $('previewPaper');
    if (!paper || !window.ResumeRender) { renderNoTemplateGuide(); return; }
    // 清掉旧布局系统残留的类名与内联样式，避免两套样式互相干扰
    // rr-host：让外层纸壳交出宽度控制权（A4 = 794px），否则右侧会被裁掉
    paper.className = 'ed-paper rp-paper rr-host';
    paper.style.background = '';
    paper.style.borderRadius = '';
    paper.style.fontFamily = '';
    paper.style.width = '';
    paper.style.maxWidth = '';
    window.ResumeRender.mount(paper, buildRenderData(), buildRenderStyle());
    _renderedStruct = structKey();
    updatePageHint();
  }

  /* ── 影响 DOM 结构的样式项 ──
     注意：只有配色/字体/字号/行距/间距/留白/尺寸是「纯 CSS 变量」，改它们只需 applyVars。
     family / sectionStyle / photoShape 会改变元素 class，必须重渲染 DOM 才生效。
     这里用快照比对，避免把「改了但没生效」这类问题留到线上。 */
  let _renderedStruct = null;
  function structKey() {
    const s = State.style || {};
    return [s.family || 'single', s.sectionStyle || 'underline',
            s.photoShape || 'rect'].join('|');
  }

  /** 页数提示：超过一页 A4 时提醒（真实分页交给后续 Paged.js）
   *  用 fixed 定位：预览区是 flex 容器，做成普通子节点会被当成第三个 flex 项排到纸张右边 */
  let _hintResizeBound = false;
  function updatePageHint() {
    const page = document.querySelector('#previewPaper .rr-page');
    const wrap = $('previewWrap');
    if (!page || !wrap) return;
    let hint = document.getElementById('rrPageHint');
    if (!hint) {
      hint = document.createElement('div');
      hint.id = 'rrPageHint';
      hint.style.cssText = 'position:fixed;bottom:18px;padding:6px 16px;' +
        'border-radius:999px;background:#fff;border:1px solid #E4E7EE;color:#7A8391;' +
        'font-size:12px;width:max-content;transform:translateX(-50%);' +
        'box-shadow:0 2px 10px rgba(0,0,0,.07);z-index:20;pointer-events:none;' +
        'transition:left .12s ease';
      document.body.appendChild(hint);
      if (!_hintResizeBound) {
        _hintResizeBound = true;
        window.addEventListener('resize', updatePageHint);
      }
    }
    // 水平居中于预览区（不是视口），避免落到右侧模块面板上方
    const r = wrap.getBoundingClientRect();
    hint.style.left = Math.round(r.left + r.width / 2) + 'px';
    const pages = window.ResumeRender.estimatePages(page);
    hint.textContent = pages > 1 ? '当前内容约 ' + pages + ' 页 A4' : '内容在 1 页 A4 内';
    hint.style.color = pages > 1 ? '#BA7517' : '#7A8391';
  }

  /* 无真实模板引导页：提示先选择模板，附「选择模板」按钮 */
  function renderNoTemplateGuide() {
    const paper = $('previewPaper');
    if (!paper) return;
    paper.className = 'ed-paper rp-paper';
    paper.style.background = '';
    paper.style.borderRadius = '';
    paper.innerHTML = `
      <div style="height:100%;min-height:560px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;color:#8A93A3;">
        <div style="font-size:52px">📄</div>
        <div style="font-size:16px;font-weight:700;color:#5A6472">尚未加载模板原件</div>
        <div style="font-size:13px;line-height:1.8;text-align:center;max-width:360px">
          编辑器只展示管理端上传的模板原件（Word 渲染 + 热区编辑）。<br>
          请点击右上角「更换模板」选择一个模板；<br>
          若模板一直加载失败，请联系管理员检查模板文件。
        </div>
        <button id="noTplPickBtn" style="margin-top:6px;padding:10px 26px;border:none;border-radius:999px;background:linear-gradient(135deg,#5B5CFF,#7C5CFF);color:#fff;font-size:14px;font-weight:700;cursor:pointer">选择模板</button>
        ${State.templateId ? '<button id="noTplRetryBtn" style="margin-top:2px;padding:8px 20px;border:1px solid #C9CFDA;border-radius:999px;background:#fff;color:#5A6472;font-size:13px;cursor:pointer">重试加载当前模板</button>' : ''}
      </div>`;
    const btn = $('noTplPickBtn');
    if (btn) btn.addEventListener('click', function() { openSettingModal('template'); });
    const retry = $('noTplRetryBtn');
    if (retry) retry.addEventListener('click', function() { loadRealStructure(State.templateId); });
  }

  /* 标准画布骨架：特殊模板会替换 paper 内容；下次切换前必须重建。 */
  function ensureStandardPaperSkeleton() {
    const paper = $('previewPaper');
    if (!paper || paper.querySelector('#rpHeader')) return;
    paper.innerHTML = `
      <div class="rp-header" id="rpHeader">
        <div class="rp-header-left">
          <h1 class="rp-title">个人简历</h1>
          <span class="rp-title-en">Personal resume</span>
          <div class="rp-intention" id="rpIntentionText"><span class="rp-intention-label">求职意向：</span><span id="rpIntentionValue"></span></div>
        </div>
        <div class="rp-header-right"><div class="rp-deco-icons"><span class="rp-deco-icon">🎓</span><span class="rp-deco-icon">💼</span><span class="rp-deco-icon">🚀</span></div></div>
      </div>
      <div class="rp-section rp-section-basic" id="rpBasic" data-module="basic"><div class="rp-basic-content"><div class="rp-basic-grid" id="rpBasicGrid"></div><div class="rp-photo-wrap" id="rpPhotoWrap"><div class="rp-photo" id="rpPhoto" title="点击编辑基本信息"><img id="rpPhotoImg" alt="照片"><span class="rp-photo-placeholder">📷</span></div></div></div></div>
      <div class="rp-modules" id="rpModules"></div>
      <div class="rp-footer"><span>第1页/共1页</span></div>`;
  }

  /* ─── 各布局类型的渲染函数 ─── */

  /** 默认/标准布局（优雅商务等） */
  function renderDefaultLayout() {
    renderStandardHeader();
    renderBasicInfoGrid();
    renderModules();
    updatePhoto();
    renderIntentionText();
  }

  /** 暗色侧栏布局（Template 2） */
  function renderSidebarLayout() {
    const paper = $('previewPaper');
    const cfg = getTplLayout();

    // 确保有侧栏容器
    let sidebar = paper.querySelector('.rp-sidebar');
    let mainContent = paper.querySelector('.rp-main-content');
    if (!sidebar || !mainContent) {
      paper.innerHTML = '';
      sidebar = el('div', { class: 'rp-sidebar' });
      mainContent = el('div', { class: 'rp-main-content' });
      paper.appendChild(sidebar);
      paper.appendChild(mainContent);
    } else {
      sidebar.innerHTML = '';
      mainContent.innerHTML = '';
    }

    // 侧栏内容：标题 + 照片 + 姓名 + 基本信息
    sidebar.appendChild(el('div', { class: 'rp-sidebar-header' },
      el('h1', { class: 'rp-sidebar-title' }, 'PERSONAL RESUME')
    ));

    // 照片
    const photoWrap = el('div', { class: 'rp-sidebar-photo' });
    if (State.photoDataUrl && State.showPhoto !== false) {
      photoWrap.appendChild(el('img', { src: State.photoDataUrl, alt: '照片' }));
    }
    sidebar.appendChild(photoWrap);

    // 姓名
    const b = State.basic || {};
    sidebar.appendChild(el('div', { class: 'rp-sidebar-name' }, esc(b.name) || '姓名'));

    // 求职意向
    const job = (b.intention_job || '').trim();
    if (job) {
      sidebar.appendChild(el('div', { class: 'rp-sidebar-intention' },
        el('span', { class: 'label' }, '求职意向：'), esc(job)
      ));
    }

    // 侧栏基本信息
    const sideFields = ['phone','email','birth_date','height','hometown','nation'];
    const sideList = el('div', { class: 'rp-sidebar-info' });
    sideFields.forEach(key => {
      if (!isFieldVisible(key)) return;
      const v = (b[key] || '').trim();
      if (v) {
        const label = {phone:'电话',email:'邮箱',birth_date:'出生',height:'身高',hometown:'籍贯',nation:'民族'}[key] || key;
        sideList.appendChild(el('div', { class: 'rp-sidebar-row' },
          el('span', { class: 'sl' }), el('span', { class: 'll' }, label + '：'), esc(v)
        ));
      }
    });
    sidebar.appendChild(sideList);

    // 右侧主内容区：板块
    if (State.visible.basic === false) sidebar.classList.add('rp-hidden');

    const modContainer = el('div', { class: 'rp-modules' });
    State.order.forEach(key => {
      if (key === 'basic' || key === 'intention') return;
      if (State.visible[key] === false) return;
      const m = MODULES.find(x => x.key === key);
      if (!m) return;
      const sec = buildSection(key, m);
      if (sec) modContainer.appendChild(sec);
    });
    mainContent.appendChild(modContainer);

    // 页脚
    mainContent.appendChild(el('div', { class: 'rp-footer' }, el('span', '第1页/共1页')));
  }

  /** 彩色顶栏布局（Template 4） */
  function renderHeaderBarLayout() {
    const paper = $('previewPaper');
    paper.innerHTML = '';

    const b = State.basic || {};

    // 顶部彩色横幅：姓名 + 求职意向 + 照片
    const header = el('div', { class: 'rp-hb-header' },
      el('div', { class: 'rp-hb-left' },
        el('h1', { class: 'rp-hb-name' }, esc(b.name) || '姓名'),
        el('div', { class: 'rp-hb-intention' },
          el('span', { class: 'lbl' }, '求职意向：'),
          el('span', {}, esc(b.intention_job || ''))
        )
      ),
      el('div', { class: 'rp-hb-right' },
        (function() {
          const pw = el('div', { class: 'rp-hb-photo-wrap' });
          if (State.photoDataUrl && State.showPhoto !== false) {
            pw.appendChild(el('img', { src: State.photoDataUrl, alt: '' }));
          }
          return pw;
        })()
      )
    );
    paper.appendChild(header);

    // 图标行基本信息
    if (State.visible.basic !== false) {
      const basicSec = el('div', { class: 'rp-hb-basic' });
      ICON_BASIC_FIELDS.forEach(f => {
        if (!isFieldVisible(f.key)) return;
        const v = (b[f.key] || '').trim();
        if (v) {
          basicSec.appendChild(el('div', { class: 'rp-hb-basic-item' },
            el('span', { class: 'ico' }, f.icon),
            el('span', { class: 'lbl' }, f.label + '：'),
            el('span', { class: 'val' }, esc(v))
          ));
        }
      });
      // 补充额外字段
      [{key:'gender',label:'性别',icon:'👤'},{key:'city',label:'城市',icon:'🌆'},{key:'marriage',label:'婚况',icon:'💍'}].forEach(f => {
        if (!isFieldVisible(f.key)) return;
        const v = (b[f.key] || '').trim();
        if (v) basicSec.appendChild(el('div', { class: 'rp-hb-basic-item' },
          el('span', { class: 'ico' }, f.icon), el('span', { class: 'lbl' }, f.label+'：'), esc(v)
        ));
      });
      paper.appendChild(basicSec);
    }

    // 板块
    const modContainer = el('div', { class: 'rp-modules' });
    State.order.forEach(key => {
      if (key === 'basic' || key === 'intention') return;
      if (State.visible[key] === false) return;
      const m = MODULES.find(x => x.key === key);
      if (!m) return;
      const sec = buildSection(key, m);
      if (sec) modContainer.appendChild(sec);
    });
    paper.appendChild(modContainer);
    paper.appendChild(el('div', { class: 'rp-footer' }, el('span', '第1页/共1页')));
  }

  /** 创意边框布局（Template 1） */
  function renderCreativeBorderLayout() {
    renderStandardHeader();
    renderBasicInfoGrid();
    renderModules();
    updatePhoto();
    renderIntentionText();
  }

  /** 圆形照片布局（Template 5） */
  function renderCirclePhotoLayout() {
    const paper = $('previewPaper');
    paper.innerHTML = '';
    const b = State.basic || {};

    // 顶部条
    const header = el('div', { class: 'rp-cp-header' },
      el('div', { class: 'rp-cp-header-inner' },
        // 左侧：圆形照片 + 姓名 + 求职意向
        el('div', { class: 'rp-cp-left' },
          (function() {
            const pw = el('div', { class: 'rp-cp-photo-wrap rp-shape-circle' });
            if (State.photoDataUrl && State.showPhoto !== false) {
              pw.appendChild(el('img', { src: State.photoDataUrl, alt: '' }));
            } else {
              pw.appendChild(el('div', { class: 'placeholder' }, '📷'));
            }
            return pw;
          })(),
          el('div', { class: 'rp-cp-name-block' },
            el('h1', { class: 'rp-cp-name' }, esc(b.name) || '姓名'),
            el('div', { class: 'rp-cp-intention' },
              el('span', { class: 'lbl' }, '求职意向：'),
              esc(b.intention_job || '')
            )
          )
        )
      )
    );
    paper.appendChild(header);

    // 图标行基本信息
    if (State.visible.basic !== false) {
      const basicSec = el('div', { class: 'rp-cp-basic' });
      ICON_BASIC_FIELDS.forEach(f => {
        if (!isFieldVisible(f.key)) return;
        const v = (b[f.key] || '').trim();
        if (v) basicSec.appendChild(el('div', { class: 'rp-icon-row-item' },
          el('span', { class: 'ico' }, f.icon),
          el('span', { class: 'lbl' }, f.label),
          el('span', { class: 'val' }, esc(v))
        ));
      });
      [{key:'gender',label:'性别',icon:'👤'},{key:'email',label:'邮箱',icon:'✉️'},{key:'wechat',label:'微信',icon:'💬'}].forEach(f => {
        if (!isFieldVisible(f.key)) return;
        const v = (b[f.key] || '').trim();
        if (v) basicSec.appendChild(el('div', { class: 'rp-icon-row-item' },
          el('span', { class: 'ico' }, f.icon), el('span', { class: 'lbl' }, f.label), esc(v)
        ));
      });
      paper.appendChild(basicSec);
    }

    // 板块
    const modContainer = el('div', { class: 'rp-modules' });
    State.order.forEach(key => {
      if (key === 'basic' || key === 'intention') return;
      if (State.visible[key] === false) return;
      const m = MODULES.find(x => x.key === key);
      if (!m) return;
      const sec = buildSection(key, m);
      if (sec) modContainer.appendChild(sec);
    });
    paper.appendChild(modContainer);
    paper.appendChild(el('div', { class: 'rp-footer' }, el('span', '第1页/共1页')));
  }

  /** 极简图标布局（Template 6） */
  function renderIconMinimalLayout() {
    const paper = $('previewPaper');
    paper.innerHTML = '';
    const b = State.basic || {};

    // 简洁头部：大姓名
    const header = el('div', { class: 'rp-im-header' },
      el('h1', { class: 'rp-im-name' }, esc(b.name) || '姓名'),
      el('div', { class: 'rp-im-intention' }, esc(b.intention_job || ''))
    );
    paper.appendChild(header);

    // 基本信息区（图标行 + 右侧照片）
    if (State.visible.basic !== false) {
      const basicArea = el('div', { class: 'rp-im-basic-area' });
      const infoCol = el('div', { class: 'rp-im-info-col' });

      ICON_BASIC_FIELDS.forEach(f => {
        if (!isFieldVisible(f.key)) return;
        const v = (b[f.key] || '').trim();
        if (v) infoCol.appendChild(el('div', { class: 'rp-icon-row-item' },
          el('span', { class: 'ico' }, f.icon),
          el('span', { class: 'lbl' }, f.label),
          el('span', { class: 'val' }, esc(v))
        ));
      });
      [{key:'gender',label:'性别',icon:'👤'},{key:'email',label:'邮箱',icon:'✉️'},
        {key:'city',label:'城市',icon:'🌆'},{key:'marriage',label:'婚况',icon:'💍'}].forEach(f => {
        if (!isFieldVisible(f.key)) return;
        const v = (b[f.key] || '').trim();
        if (v) infoCol.appendChild(el('div', { class: 'rp-icon-row-item' },
          el('span', { class: 'ico' }, f.icon), el('span', { class: 'lbl' }, f.label), esc(v)
        ));
      });
      basicArea.appendChild(infoCol);

      // 右侧照片
      const photoWrap = el('div', { class: 'rp-im-photo-wrap' });
      if (State.photoDataUrl && State.showPhoto !== false) {
        photoWrap.appendChild(el('img', { src: State.photoDataUrl, alt: '' }));
      }
      basicArea.appendChild(photoWrap);
      paper.appendChild(basicArea);
    }

    // 板块
    const modContainer = el('div', { class: 'rp-modules' });
    State.order.forEach(key => {
      if (key === 'basic' || key === 'intention') return;
      if (State.visible[key] === false) return;
      const m = MODULES.find(x => x.key === key);
      if (!m) return;
      const sec = buildSection(key, m);
      if (sec) modContainer.appendChild(sec);
    });
    paper.appendChild(modContainer);
    paper.appendChild(el('div', { class: 'rp-footer' }, el('span', '第1页/共1页')));
  }

  /** 简约灰白布局（Template 3） */
  function renderCleanMinimalLayout() {
    const paper = $('previewPaper');
    paper.innerHTML = '';
    const b = State.basic || {};

    // 灰色标题头
    paper.appendChild(el('div', { class: 'rp-cm-header' },
      el('h1', { class: 'rp-cm-title' }, '个人简历')
    ));

    // 两列基本信息 + 照片
    if (State.visible.basic !== false) {
      const basicArea = el('div', { class: 'rp-cm-basic-area' });
      const grid = el('div', { class: 'rp-basic-grid' });

      [...BASIC_FIELDS_LEFT, ...BASIC_FIELDS_RIGHT].forEach(f => {
        if (!isFieldVisible(f.key)) return;
        const v = (b[f.key] || '').trim();
        grid.appendChild(el('div', { class: 'rp-basic-row' },
          el('span', { class: 'rp-basic-label' }, f.label),
          el('span', { class: 'rp-basic-value' + (v ? '' : ' empty') }, esc(v) || '未填写')
        ));
      });
      basicArea.appendChild(grid);

      const photoWrap = el('div', { class: 'rp-photo-wrap' });
      const photo = el('div', { class: 'rp-photo', id: 'rpPhoto' });
      if (State.photoDataUrl && State.showPhoto !== false) {
        photo.appendChild(el('img', { id: 'rpPhotoImg', src: State.photoDataUrl, alt: '' }));
        photo.classList.add('has-img');
      } else {
        photo.appendChild(el('span', { class: 'rp-photo-placeholder' }, '📷'));
      }
      photoWrap.appendChild(photo);
      basicArea.appendChild(photoWrap);
      paper.appendChild(basicArea);
    }

    // 板块
    const modContainer = el('div', { class: 'rp-modules' });
    State.order.forEach(key => {
      if (key === 'basic' || key === 'intention') return;
      if (State.visible[key] === false) return;
      const m = MODULES.find(x => x.key === key);
      if (!m) return;
      const sec = buildSection(key, m);
      if (sec) modContainer.appendChild(sec);
    });
    paper.appendChild(modContainer);
    paper.appendChild(el('div', { class: 'rp-footer' }, el('span', '第1页/共1页')));
  }

  /** 学术严谨布局（Template 7） */
  function renderAcademicLayout() {
    renderStandardHeader();
    renderBasicInfoGrid();
    renderModules();
    updatePhoto();
    renderIntentionText();
  }

  /** 暖色调布局（Template 8） */
  function renderWarmLayout() {
    renderStandardHeader();
    renderBasicInfoGrid();
    renderModules();
    updatePhoto();
    renderIntentionText();
  }

  /** 科技蓝布局（Template 9） */
  function renderTechLayout() {
    renderStandardHeader();
    renderBasicInfoGrid();
    renderModules();
    updatePhoto();
    renderIntentionText();
  }

  /** 优雅商务布局（Template 10） */
  function renderElegantLayout() {
    renderStandardHeader();
    renderBasicInfoGrid();
    renderModules();
    updatePhoto();
    renderIntentionText();
  }

  /* ─── 通用子渲染函数 ─── */

  /** 渲染标准头部（用于 classic/creative/academic/warm/tech/elegant） */
  function renderStandardHeader() {
    const header = $('rpHeader');
    if (!header) return;
    // 保持原有 HTML 结构，由 CSS 控制显示差异
    header.style.display = '';
    header.querySelector('.rp-title').textContent = '个人简历';
  }

  /** 渲染标准两列基本信息（用于 classic 系列布局） */
  function isFieldVisible(key) {
    return State.fieldVisible[key] !== false;
  }

  function renderBasicInfoGrid() {
    const grid = $('rpBasicGrid');
    const sec = $('rpBasic');
    if (!grid || !sec) return;

    const b = State.basic || {};
    let leftHtml = '', rightHtml = '', extraHtml = '';

    BASIC_FIELDS_LEFT.forEach(f => {
      if (State.fieldVisible[f.key] === false) return;
      const v = (b[f.key] || '').trim();
      leftHtml += `<div class="rp-basic-row"><span class="rp-basic-label">${esc(f.label)}</span><span class="rp-basic-value${v?'':' empty'}">${esc(v)||'未填写'}</span></div>`;
    });
    BASIC_FIELDS_RIGHT.forEach(f => {
      if (State.fieldVisible[f.key] === false) return;
      const v = (b[f.key] || '').trim();
      rightHtml += `<div class="rp-basic-row"><span class="rp-basic-label">${esc(f.label)}</span><span class="rp-basic-value${v?'':' empty'}">${esc(v)||'未填写'}</span></div>`;
    });

    const hasExtra = BASIC_FIELDS_EXTRA.some(f => isFieldVisible(f.key) && (b[f.key] || '').trim());
    if (hasExtra) {
      extraHtml = '<div style="grid-column:1/-1;border-top:1px dashed #eee;margin-top:4px;padding-top:8px">';
      BASIC_FIELDS_EXTRA.forEach(f => {
        if (!isFieldVisible(f.key)) return;
        const v = (b[f.key] || '').trim();
        if (v) extraHtml += `<div class="rp-basic-row"><span class="rp-basic-label">${esc(f.label)}</span><span class="rp-basic-value">${esc(v)}</span></div>`;
      });
      extraHtml += '</div>';
    }

    grid.innerHTML = leftHtml + rightHtml + extraHtml;
    sec.classList.toggle('rp-hidden', State.visible.basic === false);
  }

  /** 更新照片显示（标准布局用） */
  function updatePhoto() {
    const wrap = $('rpPhotoWrap');
    const photo = $('rpPhoto');
    const img = $('rpPhotoImg');
    if (!photo || !img) return;

    if (State.photoDataUrl && State.showPhoto !== false && State.visible.basic !== false) {
      img.src = State.photoDataUrl;
      photo.classList.add('has-img');
      if (wrap) wrap.style.display = '';
    } else {
      img.src = '';
      photo.classList.remove('has-img');
      if (wrap) wrap.style.display = 'none';
    }
  }

  /** 渲染顶部求职意向文字（标准布局用） */
  function renderIntentionText() {
    const el = $('rpIntentionValue');
    const wrap = $('rpIntentionText');
    if (!el || !wrap) return;
    const b = State.basic || {};
    const job = (b.intention_job || '').trim();
    wrap.style.display = job ? '' : 'none';
    el.textContent = job;
  }

  /** 渲染动态板块容器（通用） */
  function renderModules() {
    const container = $('rpModules');
    if (!container) return;
    container.innerHTML = '';

    State.order.forEach(key => {
      if (key === 'basic') return;
      if (State.visible[key] === false) return;
      const m = MODULES.find(x => x.key === key);
      if (!m) return;
      const section = buildSection(key, m);
      if (section) container.appendChild(section);
    });
  }

  /**
   * 构建单个板块 DOM（通用，适用于所有布局）
   */
  function buildSection(key, m) {
    let bodyContent = null;

    switch (key) {
      case 'intention':   bodyContent = buildIntentionBody(); break;
      case 'education':   bodyContent = buildEducationBody(); break;
      case 'work':        bodyContent = buildWorkBody(); break;
      case 'internship':  bodyContent = buildInternshipBody(); break;
      case 'project':     bodyContent = buildProjectBody(); break;
      case 'campus':      bodyContent = buildCampusBody(); break;
      case 'skill':       bodyContent = buildSkillBody(); break;
      case 'honor':       bodyContent = buildHonorBody(); break;
      case 'self':        bodyContent = buildSimpleBody(m, 'self_evaluate'); break;
      case 'hobby':       bodyContent = buildHobbyBody(); break;
      case 'custom':      bodyContent = buildCustomBody(); break;
      default: return null;
    }

    if (!bodyContent) return null;

    return el('div', { class: 'rp-section', onclick: () => openModuleModal(key), title: '点击编辑' + m.label },
      el('div', { class: 'rp-section-header' },
        el('span', { class: 'rp-section-icon' }, m.icon),
        el('span', { class: 'rp-header-title' }, m.label),
        el('button', {
          class: 'rp-edit-btn',
          onclick: event => { event.stopPropagation(); openModuleModal(key); },
          title: '编辑' + m.label
        }, '✎')
      ),
      el('div', { class: 'rp-section-body' }, bodyContent)
    );
  }

  /* ---- 各板块内容构建函数 ---- */

  function buildIntentionBody() {
    const b = State.basic || {};
    const parts = [
      b.intention_job && esc(b.intention_job),
      b.salary && ('期望薪资：' + esc(b.salary)),
      b.city && ('期望城市：' + esc(b.city)),
      b.arrive_time && ('到岗时间：' + esc(b.arrive_time))
    ].filter(Boolean);
    if (!parts.length) return el('div', { class: 'rp-text-content empty' }, '点击编辑填写求职意向…');
    return el('div', { class: 'rp-text-content' }, parts.join('　|　'));
  }

  function buildEducationBody() {
    const arr = State.modules.education_info || [];
    if (!arr.length) return el('div', { class: 'rp-text-content empty' }, '点击编辑添加教育经历…');
    const wrap = el('div');
    arr.forEach(r => {
      const time = [(r.start||''), r.current ? '至今' : (r.end||'')].filter(Boolean).join(' ~ ') || '';
      const detailParts = [r.degree, r.major].filter(Boolean);
      wrap.appendChild(el('div', { class: 'rp-edu-item' },
        time ? el('span', { class: 'rp-edu-time' }, time) : null,
        el('span', { class: 'rp-edu-school' }, esc(r.school || '未填写学校')),
        detailParts.length ? el('span', { class: 'rp-edu-detail' }, detailParts.join(' · ')) : null,
        r.content ? el('div', { class: 'rp-edu-desc', html: r.content }) : null
      ));
    });
    return wrap;
  }

  function buildWorkBody() {
    const arr = State.modules.work_history || [];
    if (!arr.length) return el('div', { class: 'rp-text-content empty' }, '点击编辑添加工作经历…');
    const wrap = el('div');
    arr.forEach(r => {
      const time = [(r.start||''), r.current ? '至今' : (r.end||'')].filter(Boolean).join(' ~ ') || '';
      wrap.appendChild(el('div', { class: 'rp-work-item' },
        el('div', { class: 'rp-work-head' },
          time ? el('span', { class: 'rp-work-time' }, time) : null,
          el('span', { class: 'rp-work-company' }, esc(r.company || '未填写公司')),
          r.position ? el('span', { class: 'rp-work-position' }, esc(r.position)) : null
        ),
        r.content ? el('div', { class: 'rp-work-content', html: r.content }) : null
      ));
    });
    return wrap;
  }

  function buildInternshipBody() {
    const arr = State.modules.internship_info || [];
    if (!arr.length) return null;
    const wrap = el('div');
    arr.forEach(r => {
      const time = [(r.start||''), r.current ? '至今' : (r.end||'')].filter(Boolean).join(' ~ ') || '';
      wrap.appendChild(el('div', { class: 'rp-work-item' },
        el('div', { class: 'rp-work-head' },
          time ? el('span', { class: 'rp-work-time' }, time) : null,
          el('span', { class: 'rp-work-company' }, esc(r.company || '未填写单位')),
          r.position ? el('span', { class: 'rp-work-position' }, esc(r.position)) : null
        ),
        r.content ? el('div', { class: 'rp-work-content', html: r.content }) : null
      ));
    });
    return wrap;
  }

  function buildProjectBody() {
    const arr = State.modules.projects || [];
    if (!arr.length) return el('div', { class: 'rp-text-content empty' }, '点击编辑添加项目经验…');
    const wrap = el('div');
    arr.forEach(r => {
      wrap.appendChild(el('div', { class: 'rp-proj-item' },
        el('div', { class: 'rp-proj-head' },
          el('span', { class: 'rp-proj-name' }, esc(r.name || '未命名项目')),
          r.role ? el('span', { class: 'rp-proj-role' }, esc(r.role)) : null,
          r.period ? el('span', { class: 'rp-proj-time' }, esc(r.period)) : null
        ),
        r.content ? el('div', { class: 'rp-proj-content', html: r.content }) : null
      ));
    });
    return wrap;
  }

  function buildCampusBody() {
    const arr = State.modules.campus_exp || [];
    if (!Array.isArray(arr)) return buildSimpleBody({ label: '校园经历' }, 'campus_exp');
    if (!arr.length) return el('div', { class: 'rp-text-content empty' }, '点击编辑添加校园经历…');
    const wrap = el('div');
    arr.forEach(r => wrap.appendChild(el('div', { class: 'rp-campus-item' },
      el('div', { class: 'rp-campus-head' },
        el('span', { class: 'rp-campus-name' }, esc(r.name || '未填写经历名称')),
        r.role ? el('span', { class: 'rp-campus-role' }, esc(r.role)) : null,
        r.period ? el('span', { class: 'rp-campus-time' }, esc(r.period)) : null
      ),
      r.content ? el('div', { class: 'rp-campus-content', html: r.content }) : null
    )));
    return wrap;
  }

  function buildSkillBody() {
    const arr = State.modules.skill_info || [];
    if (!Array.isArray(arr)) return buildSimpleBody({ label: '技能特长' }, 'skill_info');
    if (!arr.length) return el('div', { class: 'rp-text-content empty' }, '点击编辑添加技能特长…');
    const wrap = el('div', { class: 'rp-skill-list' });
    arr.forEach(r => wrap.appendChild(el('div', { class: 'rp-skill-item' },
      el('div', { class: 'rp-skill-head' },
        el('span', { class: 'rp-skill-name' }, esc(r.name || '未命名技能')),
        r.level ? el('span', { class: 'rp-skill-level' }, esc(r.level)) : null
      ),
      r.content ? el('div', { class: 'rp-skill-content' }, esc(r.content)) : null
    )));
    return wrap;
  }

  function buildHonorBody() {
    const arr = State.modules.honor_cert || [];
    if (!Array.isArray(arr)) return buildSimpleBody({ label: '荣誉证书' }, 'honor_cert');
    if (!arr.length) return el('div', { class: 'rp-text-content empty' }, '点击编辑添加荣誉证书…');
    const wrap = el('div');
    arr.forEach(r => wrap.appendChild(el('div', { class: 'rp-honor-item' },
      r.time ? el('span', { class: 'rp-honor-time' }, esc(r.time)) : null,
      el('span', { class: 'rp-honor-name' }, esc(r.name || '未填写证书名称')),
      r.issuer ? el('span', { class: 'rp-honor-issuer' }, ' · ' + esc(r.issuer)) : null
    )));
    return wrap;
  }

  function buildSimpleBody(m, dataKey) {
    const val = State.modules[dataKey] || '';
    if (!val.trim()) return el('div', { class: 'rp-text-content empty' }, '点击编辑填写' + m.label + '…');
    return el('div', { class: 'rp-text-content' }, val.replace(/\n/g, '<br>'));
  }

  function buildHobbyBody() {
    const tags = State.modules.hobby || [];
    if (!tags.length) return el('div', { class: 'rp-text-content empty' }, '点击编辑添加兴趣爱好…');
    const cloud = el('div', { class: 'rp-tag-cloud' });
    tags.forEach(t => cloud.appendChild(el('span', { class: 'rp-tag' }, t)));
    return cloud;
  }

  function buildCustomBody() {
    const html = State.modules.custom || '';
    if (!html.trim()) return el('div', { class: 'rp-text-content empty' }, '点击编辑自定义内容…');
    const div = el('div', { class: 'rp-text-content' });
    div.innerHTML = html;
    return div;
  }

  /* ============ 加载模板列表 ============ */
  /* 编辑器模板库只收管理端「启用」的模板（editable=1）；
     关闭（editable=0）的一律不出现，包括当前正在用的那套
     （当前编辑内容不受影响，State.templateId 与已加载结构照常工作）。
     首页模板中心不受影响 —— 那边展示与下载的是全部模板。 */
  function keepEditable(list) {
    return (list || []).filter(function (t) {
      if (t.editable === 0 || t.editable === false) return false;
      if (t.editable === '0') return false;
      return true;
    });
  }

  async function loadTemplates() {
    // 编辑器同时加载「免费模板库」与「VIP模板中心」，均支持真实结构就地编辑
    try {
      const free = await apiGet('/templates');
      State.freeTemplates = keepEditable(free);
    } catch (e) {
      console.warn('免费模板加载失败:', e.message);
      State.freeTemplates = [];
    }
    try {
      const vip = await apiGet('/api/vip-templates');
      State.vipTemplates = keepEditable(vip);
    } catch (e) {
      console.warn('VIP 模板加载失败:', e.message);
      State.vipTemplates = [];
    }
  }

  /* ============ 真实模板热区点击+弹窗编辑 ============
   * 页面直接展示 Word 渲染成品图（与导出像素级一致），
   * 可编辑文本框为透明热区，点击弹窗修改纯文字。
   * 格式样式 100% 由模板保留。 */
  let realStructure = null;
  let realTemplateId = null;
  let realBoxTexts = {};
  let realPreviewSrc = null;      // 兼容旧字段：第 1 页渲染图（dataURI）
  let realPreviewPages = null;    // Word 渲染成品全部页面（dataURI 数组，支持多页简历）
  let realPreviewTemplateId = null; // 渲染图所属模板，防止换模板后串图
  let _realPreviewReqId = 0;
  let _realPreviewTimer = null;
  let _realPreviewRetried = false;  // 渲染失败自动重试标记（每次会话至多重试一次）
  let _realPreviewPending = false;  // 请求锁：避免并发压后端
  let _loadStructReqId = 0;         // 结构加载请求序号：只有最后一次选择生效
  let _rtModalBoxId = null;

  /* 模板原文常含 {{占位符}}：进入编辑态时清掉，保证预览/导出不残留占位符 */
  function cleanBoxText(raw) {
    return String(raw || '')
      .replace(/\{\{[^}]*\}\}/g, '')
      .replace(/^\s*\n+/, '')
      .replace(/\n{3,}/g, '\n\n')
      .trimEnd();
  }

  async function loadRealStructure(tid) {
    if (!tid) return;
    const reqId = ++_loadStructReqId;
    try {
      const st = await apiGet('/api/template-structure/' + tid);
      /* 竞态防护：结构解析（Word 校准）可能耗时数十秒，期间用户又选了
         其他模板的话，这份过期响应必须丢弃——否则慢的旧响应晚到，
         会把预览"突然切换"成用户没有选择的模板 */
      if (reqId !== _loadStructReqId || tid !== State.templateId) return;
      realStructure = st;
      realTemplateId = tid;
      /* 换模板时丢弃上一份模板的渲染图，避免串图 */
      if (realPreviewTemplateId !== tid) {
        realPreviewSrc = null;
        realPreviewPages = null;
      }
      realBoxTexts = {};
      (st.boxes || []).forEach(function(b) {
        realBoxTexts[b.id] = cleanBoxText(b.text);
      });
      persistLocal();
      renderPreview();
      renderRightPanel();        // 面板切换为「定位编辑」模式（真实模板）
      scheduleRealPreview(150);   // 立即用当前内容渲染精确预览
    } catch (e) {
      if (reqId !== _loadStructReqId || tid !== State.templateId) return;
      console.warn('真实模板结构加载失败:', e.message);
      realStructure = null;
      toast('模板加载失败：' + e.message + '，可在「更换模板」中重试', 'error');
      renderNoTemplateGuide();
      renderRightPanel();
    }
  }

  function boxIsEditable(b) {
    if (b.editable === false || !b.h) return false;
    // 可编辑性只看后端标记与几何有效性，不看当前文字：
    // 用户清空某格后热区必须保留，否则永远无法再填写该区域
    return true;
  }

  /* 只要存在可编辑盒子就进入真实模板模式；无结构时回退标准排版渲染器 */
  function isRealTemplateActive() {
    return !!(realStructure && realTemplateId === State.templateId &&
      (realStructure.boxes || []).some(boxIsEditable));
  }

  function renderRealTemplate() {
    const paper = $('previewPaper');
    if (!paper || !realStructure) return;
    const st = realStructure;
    const pw = st.page_w || 794, ph = st.page_h || 1123;
    /* 多页支持：以最近一次 Word 渲染的实际页数为准（内容溢出 → 第 2 页） */
    const pageCount = Math.max(1, (realPreviewPages && realPreviewPages.length) || 1);
    const ts = Date.now();
    const boxes = (st.boxes || []).filter(boxIsEditable);

    /* 热区按盒子 y 落到对应页；坐标一律用百分比，任意宽度下都与底图对齐 */
    const perPage = [];
    for (let i = 0; i < pageCount; i++) perPage.push([]);
    boxes.forEach(function(b) {
      const rawPage = ph > 0 ? Math.floor(b.y / ph) : 0;
      const pg = Math.min(pageCount - 1, Math.max(0, rawPage));
      const localY = b.y - pg * ph;
      const hint = (b.placeholders && b.placeholders[0]) ||
        String(realBoxTexts[b.id] != null ? realBoxTexts[b.id] : b.text || '').split('\n')[0].slice(0, 12);
      const isEmpty = !String(realBoxTexts[b.id] != null ? realBoxTexts[b.id] : b.text || '').trim();
      perPage[pg].push('<div class="rt-hotspot' + (isEmpty ? ' rt-hotspot-empty' : '')
        + '" data-id="' + b.id
        + '" title="' + (isEmpty ? '点击填写' : '点击编辑：') + esc(hint.replace(/[{}]/g, ''))
        + '" style="left:' + (b.x / pw * 100).toFixed(3) + '%;top:' + (localY / ph * 100).toFixed(3)
        + '%;width:' + (b.w / pw * 100).toFixed(3) + '%;height:' + (b.h / ph * 100).toFixed(3) + '%;"></div>');
    });

    const parts = ['<div class="rt-pages">'];
    for (let i = 0; i < pageCount; i++) {
      parts.push('<div class="rt-page" style="aspect-ratio:' + pw + ' / ' + ph + ';">');
      const src = (realPreviewPages && realPreviewPages[i])
        || (i === 0 ? '/static/previews/t' + realTemplateId + '.png?v=4&_=' + ts : '');
      if (src) {
        parts.push('<img class="rt-page-img" draggable="false" src="' + esc(src) + '" alt="">');
      }
      if (i > 0) parts.push('<span class="rt-page-num">第 ' + (i + 1) + ' 页</span>');
      parts.push(perPage[i].join(''));
      if (i === 0) parts.push('<div class="rt-preview-loading" id="rtPreviewLoading" hidden>正在刷新预览…</div>');
      parts.push('</div>');
    }
    parts.push('</div>');
    paper.classList.remove('rr-host');   // 交还宽度控制权给真实模板样式
    paper.classList.add('rt-mode');
    paper.innerHTML = parts.join('');
    paper.querySelectorAll('.rt-hotspot').forEach(function(hs) {
      hs.addEventListener('click', function() { openRealBoxEditor(parseInt(hs.dataset.id, 10)); });
    });
  }

  /* ── 预览刷新：写回 docx → Word 重排 → PNG ── */
  function scheduleRealPreview(delay) {
    if (!realStructure || !realTemplateId) return;
    clearTimeout(_realPreviewTimer);
    if (_realPreviewPending) {
      // 后端正在渲染时，把新改动排队，稍后再试，避免并发请求压垮 Word COM
      _realPreviewTimer = setTimeout(function() { scheduleRealPreview(delay); }, 450);
      return;
    }
    _realPreviewTimer = setTimeout(refreshRealPreview, delay == null ? 800 : delay);
  }

  async function refreshRealPreview() {
    if (!realStructure || !realTemplateId) return;
    if (_realPreviewPending) { scheduleRealPreview(450); return; }
    _realPreviewPending = true;
    const reqId = ++_realPreviewReqId;
    const chip = $('rtPreviewLoading');
    if (chip) chip.hidden = false;
    try {
      const fd = new FormData();
      fd.append('edits', JSON.stringify(realBoxTexts || {}));
      const r = await apiPost('/api/template-preview/' + realTemplateId, fd);
      if (reqId !== _realPreviewReqId) return;
      if (r && (r.png_b64 || (r.pages && r.pages.length))) {
        _realPreviewRetried = false;
        realPreviewPages = (r.pages && r.pages.length) ? r.pages
          : (r.png_b64 ? [r.png_b64] : null);
        realPreviewSrc = realPreviewPages ? realPreviewPages[0] : null;
        realPreviewTemplateId = realTemplateId;
        /* 关键：只有当前真的在显示「精确预览」时才动 DOM。
           否则（HTML 预览模式）这里会把纸张内 HTML 整页替换成 Word 成品图，
           等于异步任务把用户正在编辑的预览劫持掉——表现为「模板乱」。 */
        const showingExact = State.previewMode === 'exact' && isRealTemplateActive();
        if (!showingExact) return;
        const paper = $('previewPaper');
        const imgs = paper ? paper.querySelectorAll('.rt-page-img') : [];
        const pages = realPreviewPages || [];
        /* 渲染页数与 DOM 页数不一致（内容溢出新增页）时整帧重排 */
        if (imgs.length !== pages.length) {
          renderRealTemplate();
          return;
        }
        imgs.forEach(function(img, i) { if (pages[i]) img.src = pages[i]; });
      }
    } catch (e) {
      if (reqId === _realPreviewReqId) {
        console.warn('[editor] 模板预览渲染失败:', e.message);
        /* Word COM 偶发超时/占用：自动重试一次 */
        if (!_realPreviewRetried) {
          _realPreviewRetried = true;
          setTimeout(function() {
            if (reqId === _realPreviewReqId) refreshRealPreview().catch(function() {});
          }, 2500);
          return;
        }
        _realPreviewRetried = false;
        /* 若已有旧预览图，保留旧图即可，避免打扰用户；只有首次渲染失败才提示 */
        if (!realPreviewPages || !realPreviewPages.length) {
          toast('预览刷新失败，内容已保存，可点击任意区域重试', 'error');
        }
      }
    } finally {
      _realPreviewPending = false;
      if (reqId === _realPreviewReqId && chip && chip.isConnected) chip.hidden = true;
    }
  }

  /* ── 弹窗编辑器 ── */

  /* 按盒子尺寸和字号估算该区域的建议字数（中文字符当量） */
  function boxCapacity(b) {
    if (!b || !b.w || !b.h) return null;
    const paras = b.paragraphs || [];
    let size = 12;
    for (const p of paras) {
      const r0 = (p.runs && p.runs[0]) || null;
      if (r0 && r0.size) { size = Math.max(9, Math.min(24, r0.size)); break; }
    }
    const px = size * 4 / 3;            // pt → px（96dpi）
    const perLine = Math.max(1, Math.floor((b.w - 10) / px));
    const lines = Math.max(1, Math.floor((b.h - 6) / (px * 1.35)));
    return perLine * lines;
  }

  function updateBoxCapacityHint() {
    const capEl = $('rtBoxCap');
    const ta = $('rtBoxTextarea');
    if (!capEl || !ta) return;
    const st = realStructure;
    const b = (_rtModalBoxId != null && st) ? (st.boxes || []).find(function(x) { return x.id === _rtModalBoxId; }) : null;
    const cap = boxCapacity(b);
    const len = ta.value.length;
    if (!cap) { capEl.hidden = true; return; }
    capEl.hidden = false;
    capEl.textContent = '当前 ' + len + ' 字 · 该区域建议不超过约 ' + cap + ' 字';
    capEl.className = 'rt-box-cap' + (len > cap * 1.5 ? ' over' : len > cap ? ' warn' : '');
  }

  function openRealBoxEditor(boxId) {
    if (!realStructure) return;
    const b = (realStructure.boxes || []).find(function(x) { return x.id === boxId; });
    if (!b) return;
    _rtModalBoxId = boxId;
    const hint = (b.placeholders && b.placeholders[0]) || '';
    const titleEl = $('rtBoxTitle');
    if (titleEl) titleEl.textContent = '编辑内容' + (hint ? '（' + hint.replace(/[{}]/g, '') + '）' : '');
    const ta = $('rtBoxTextarea');
    if (ta) ta.value = realBoxTexts[boxId] != null ? realBoxTexts[boxId] : cleanBoxText(b.text);
    updateBoxCapacityHint();
    const modal = $('rtBoxModal');
    if (modal) { modal.hidden = false; if (ta) setTimeout(function() { ta.focus(); }, 50); }
  }

  function closeRealBoxEditor() {
    const modal = $('rtBoxModal');
    if (modal) modal.hidden = true;
    _rtModalBoxId = null;
  }

  function applyRealBoxEditor() {
    if (_rtModalBoxId == null) { closeRealBoxEditor(); return; }
    const boxId = _rtModalBoxId;
    const ta = $('rtBoxTextarea');
    const val = ta ? ta.value : '';
    realBoxTexts[boxId] = val;
    closeRealBoxEditor();

    /* 乐观更新热区视觉：立即刷新 title、empty 状态与闪烁提示，
       让用户在后台 PNG 生成完成前就能感知改动已生效 */
    const hs = document.querySelector('.rt-hotspot[data-id="' + boxId + '"]');
    if (hs) {
      const hint = String(val || '').split('\n')[0].slice(0, 12) || '未填写';
      const isEmpty = !String(val || '').trim();
      hs.className = 'rt-hotspot' + (isEmpty ? ' rt-hotspot-empty' : '') + ' flash';
      hs.title = (isEmpty ? '点击填写' : '点击编辑：') + hint.replace(/[{}]/g, '');
    }

    persistLocal();
    setDirtyTip('已修改', 'dirty');
    scheduleRealPreview(500);
  }

  let _rtModalBound = false;
  function bindRealBoxModal() {
    if (_rtModalBound) return;
    _rtModalBound = true;
    const ta = $('rtBoxTextarea');
    if (ta) ta.addEventListener('input', updateBoxCapacityHint);
    document.addEventListener('click', function(e) {
      if (e.target.closest('[data-rt-cancel]')) closeRealBoxEditor();
      else if (e.target.id === 'rtBoxApplyBtn') applyRealBoxEditor();
      else if (e.target.id === 'rtBoxModal') closeRealBoxEditor(); // 点遮罩关闭
    });
    document.addEventListener('keydown', function(e) {
      if ($('rtBoxModal') && !$('rtBoxModal').hidden) {
        if (e.key === 'Escape') closeRealBoxEditor();
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) applyRealBoxEditor();
      }
    });
  }

  /* ============ 草稿保存/加载 ============ */
  const DRAFT_KEY = 'rz_editor_draft';
  function setDirtyTip(text, cls) {
    const tip = $('savedTip');
    if (tip) { tip.textContent = text; tip.className = 'ed-saved-tip' + (cls ? ' ' + cls : ''); }
  }
  function persistLocal(skipCloudSave) {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({
        draftId: State.draftId, templateId: State.templateId,
        basic: State.basic, modules: State.modules,
        order: State.order, visible: State.visible, fieldVisible: State.fieldVisible,
        style: State.style, photoDataUrl: State.photoDataUrl, showPhoto: State.showPhoto,
        realTemplateId: realTemplateId, realBoxTexts: realBoxTexts,
        /* 预览模式是「看的方式」而非简历内容，只存本地，跟随用户习惯 */
        previewMode: State.previewMode
      }));
      /* 用户停止输入或关闭模块编辑后，延迟同步到“我的简历”。 */
      if (!skipCloudSave && typeof scheduleCloudSave === 'function') scheduleCloudSave();
    } catch (e) {}
  }
  function restoreLocal() {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (!raw) return false;
      const s = JSON.parse(raw);
      State.draftId = s.draftId || null;
      State.templateId = s.templateId || null;
      realTemplateId = s.realTemplateId || null;
      if (s.realBoxTexts && typeof s.realBoxTexts === 'object') {
        realBoxTexts = {};
        Object.keys(s.realBoxTexts).forEach(function(k) {
          // 兼容旧草稿：清除历史版本残留的 {{占位符}}
          realBoxTexts[k] = cleanBoxText(s.realBoxTexts[k]);
        });
      }
      Object.assign(State.basic, s.basic || {});
      Object.assign(State.modules, s.modules || {});

      /* 兼容所有旧版草稿：任何列表模块都必须在打开编辑器前归一为数组。 */
      const legacyTextToRecord = {
        education_info: text => ({ school:'', major:'', degree:'', start:'', end:'', current:false, content:text }),
        work_history: text => ({ company:'', position:'', start:'', end:'', current:false, content:text }),
        internship_info: text => ({ company:'', position:'', start:'', end:'', current:false, content:text }),
        projects: text => ({ name:'', role:'', period:'', content:text }),
        campus_exp: text => ({ name:'', role:'', period:'', content:text }),
        skill_info: text => ({ name:'', level:'熟练', content:text }),
        honor_cert: text => ({ time:'', name:text, issuer:'' })
      };
      Object.keys(legacyTextToRecord).forEach(key => {
        const value = State.modules[key];
        if (Array.isArray(value)) return;
        const text = typeof value === 'string' ? value.trim() : '';
        State.modules[key] = text ? [legacyTextToRecord[key](text)] : [];
      });
      if (!Array.isArray(State.modules.hobby)) {
        State.modules.hobby = typeof State.modules.hobby === 'string'
          ? State.modules.hobby.split(/[、,，\n]/).map(x => x.trim()).filter(Boolean)
          : [];
      }
      if (s.order) State.order = s.order.filter(key => MODULES.some(m => m.key === key));
      MODULES.forEach(m => { if (!State.order.includes(m.key)) State.order.push(m.key); });
      if (s.visible) Object.assign(State.visible, s.visible);
      if (s.fieldVisible) Object.assign(State.fieldVisible, s.fieldVisible);
      if (s.style) Object.assign(State.style, s.style);
      if (s.previewMode === 'exact' || s.previewMode === 'doc') State.previewMode = s.previewMode;
      State.photoDataUrl = s.photoDataUrl || null;
      if (s.showPhoto !== undefined) State.showPhoto = s.showPhoto;
      return true;
    } catch (e) { return false; }
  }

  let _cloudSaveTimer = null;
  let _cloudSaveBusy = false;

  function buildDraftTitle() {
    const name = String((State.basic || {}).name || '').trim();
    const job = String((State.basic || {}).intention_job || '').trim();
    if (name && job) return name + ' · ' + job;
    if (name) return name + '的简历';
    return '未命名简历';
  }

  function hasDraftContent() {
    const basicFilled = Object.values(State.basic || {}).some(v => String(v || '').trim());
    const modulesFilled = Object.values(State.modules || {}).some(v => Array.isArray(v) ? v.length > 0 : String(v || '').trim());
    return basicFilled || modulesFilled || !!State.photoDataUrl;
  }

  function scheduleCloudSave() {
    if (_cloudSaveBusy || !hasDraftContent()) return;
    clearTimeout(_cloudSaveTimer);
    _cloudSaveTimer = setTimeout(() => saveDraft(true), 1400);
    setDirtyTip('正在自动保存…', 'dirty');
  }

  async function saveDraft(silent) {
    if (_cloudSaveBusy) return;
    persistLocal(true);
    if (!silent) setDirtyTip('正在保存…', 'dirty');
    _cloudSaveBusy = true;
    try {
      const resp = await apiPost('/api/draft/save', {
        draft_id: State.draftId,
        template_id: State.templateId,
        title: buildDraftTitle(),
        data: {
          basic: State.basic, modules: State.modules,
          order: State.order, visible: State.visible, field_visible: State.field_visible,
          style: State.style, photo: State.photoDataUrl,
          /* 真实模板模式：把模板 id 与各盒子文本一起存云端，
             换设备/清缓存后重新打开草稿仍能进入就地编辑 */
          real_template_id: State.templateId || null,
          real_box_texts: realBoxTexts || {}
        }
      });
      if (resp && resp.draft_id) State.draftId = resp.draft_id;
      persistLocal(true);
      setDirtyTip('已保存（云端）', 'saved');
      if (!silent) toast('草稿已保存到我的简历', 'success');
    } catch (e) {
      console.warn('云端保存失败:', e.message);
      if (!silent) toast('云端保存失败，已保留本地草稿', 'error');
    } finally {
      _cloudSaveBusy = false;
    }
  }

  /* ============ 右侧模块面板 ============ */

  /* ── 真实模板模式：模块 → 画布盒子定位 ──
     面板表单编辑的 State.modules 不参与真实模板渲染，
     改为「点击模块卡 → 滚动并打开模板上对应内容盒」的导航式编辑。 */
  const RT_SECTION_PATTERNS = {
    education: /^(教育(背景|经历)?|学历)$/,
    work: /^(工作(经验|经历|背景)?|职业(经历|履历))$/,
    internship: /^(实习(经验|经历)?|实践(经历)?)$/,
    project: /^(项目(经验|经历)?|作品(集|展示)?)$/,
    campus: /^(校园(经历|实践)?|社会实践|校内(实践|经历)?|社团(活动|经历)?|学生会|干部(经历)?)$/,
    skill: /^(技能(证书|特长|能力|清单)?|专业(技能|课程|特长)?|语言(能力|水平)?|计算机(能力|技能)?|IT技能|职业技能)$/,
    honor: /^(荣誉(证书)?|获奖(情况|经历)?|证书(奖励|荣誉)?|奖项|奖状)$/,
    self: /^(自我(评价|介绍)|个人(优势|简介|评价)|关于我|职业(优势|总结))$/,
    hobby: /^(兴趣(爱好|特长)?|爱好|特长)$/,
    custom: /^(其他|附加(信息)?|更多)$/
  };
  const RT_FIELD_LABELS = ['姓名','性别','年龄','生日','出生','学历','专业','手机','电话','邮箱','微信','现居','籍贯','身高','民族','婚姻','政治','微博','QQ'];

  function rtAllTitleBoxes(boxes) {
    const out = [];
    boxes.forEach(b => {
      const t = String(b.text || '').trim();
      if (!t || t.length > 8) return;
      for (const k in RT_SECTION_PATTERNS) {
        if (RT_SECTION_PATTERNS[k].test(t)) { out.push({ key: k, box: b }); break; }
      }
    });
    return out;
  }

  /** 返回模块对应的可编辑内容盒列表（按面积降序），映射失败返回 [] */
  function findBoxesForModule(key) {
    const st = realStructure;
    if (!st || !isRealTemplateActive()) return [];
    const boxes = (st.boxes || []);

    if (key === 'intention') {
      return boxes.filter(b => boxIsEditable(b) &&
        /^求职(意向|目标)/.test(String(b.text || '').trim()));
    }
    if (key === 'basic') {
      // 字段标签盒 + 其右侧同排的值盒（用户真正要填的格子）
      const labelBoxes = boxes.filter(b => {
        const t = String(b.text || '');
        return boxIsEditable(b) && RT_FIELD_LABELS.filter(l => t.includes(l)).length >= 2;
      });
      const out = labelBoxes.slice();
      labelBoxes.forEach(lb => {
        boxes.forEach(b => {
          if (b === lb || !boxIsEditable(b) || out.includes(b)) return;
          const sameBand = b.y < lb.y + lb.h && b.y + b.h > lb.y;
          const rightBeside = b.x >= lb.x + lb.w - 12 && b.x <= lb.x + lb.w + lb.w + 40;
          if (sameBand && rightBeside) out.push(b);
        });
      });
      return out;
    }

    const titles = rtAllTitleBoxes(boxes);
    const mine = titles.filter(t => t.key === key);
    if (!mine.length) return [];
    const titleIds = new Set(titles.map(t => t.box.id));
    const isTitleLike = b => {
      const t = String(b.text || '').trim();
      if (!t || t.length > 8) return false;
      for (const k in RT_SECTION_PATTERNS) if (RT_SECTION_PATTERNS[k].test(t)) return true;
      return false;
    };

    /* 归属优先级：
     * ① 文档相邻：多数模板的内容文本框在 XML 中紧贴自己的标题盒
     *    （前后皆有可能），PDF 校准的几何误差不影响文档顺序；
     *    每个标题只认领一个最近的未占用邻居，避免级联错位；
     * ② 几何兜底：内容盒顶边上方最近的标题（文档顺序乱时）。 */
    const ownerOf = new Map();
    const claimable = cand => cand && !ownerOf.has(cand.id) && !titleIds.has(cand.id)
      && boxIsEditable(cand) && !isTitleLike(cand);
    titles.forEach(t => {
      const i = boxes.indexOf(t.box);
      const prev = boxes[i - 1], next = boxes[i + 1];
      if (claimable(prev)) ownerOf.set(prev.id, t);
      else if (claimable(next)) ownerOf.set(next.id, t);
    });
    boxes.forEach(b => {
      if (ownerOf.has(b.id) || !boxIsEditable(b) || titleIds.has(b.id) || isTitleLike(b)) return;
      let owner = null;
      titles.forEach(t => {
        const tb = t.box;
        if (tb.y <= b.y + 6 && (owner === null || tb.y > owner.y)) owner = tb;
      });
      if (owner) ownerOf.set(b.id, titles.find(t => t.box === owner));
    });

    const out = boxes.filter(b => {
      const t = ownerOf.get(b.id);
      if (!t || t.key !== key) return false;
      return b.h * b.w >= 120;   // 过滤细碎小格
    });
    out.sort((a, b2) => (b2.w * b2.h) - (a.w * a.h));
    return out;
  }

  /** 面板模块卡点击（真实模板模式）：定位并打开对应盒子 */
  function locateModuleBoxes(key) {
    const meta = MODULES.find(m => m.key === key);
    const label = meta ? meta.label : key;
    const found = findBoxesForModule(key);
    if (!found.length) {
      toast('模板中没有「' + label + '」独立区域，请直接点击左侧简历上的文字编辑', '');
      return;
    }
    const target = found[0];
    const hs = document.querySelector('.rt-hotspot[data-id="' + target.id + '"]');
    if (hs) {
      hs.scrollIntoView({ behavior: 'smooth', block: 'center' });
      hs.classList.add('flash');
      setTimeout(() => hs.classList.remove('flash'), 1800);
    }
    openRealBoxEditor(target.id);
  }

  function renderRightPanel() {
    try {
      const list = $('moduleList');
      if (!list) return;
      list.innerHTML = '';
      const rtMode = isRealTemplateActive();
      list.classList.toggle('ed-rt-mode', rtMode);
      /* 排序页在真实模板模式下无意义：版式由模板固定 */
      const sortHint = document.querySelector('#tab-sort .ed-panel-hint');
      const sortList = $('sortList');
      if (rtMode) {
        if (sortHint) sortHint.textContent = '模板版式固定，无需排序。点击下方模块可快速定位到简历上对应的编辑区域。';
        if (sortList) sortList.style.display = 'none';
      } else {
        if (sortHint) sortHint.textContent = '拖拽模块调整在简历中的显示顺序。';
        if (sortList) sortList.style.display = '';
      }

      MODULES.forEach(m => {
        const meta = getModuleMeta(m);
        const count = meta ? meta.count() : 0;
        const isOn = State.visible[m.key] !== false;

        const sw = el('div', {
          class: 'ed-module-switch' + (isOn ? ' active' : ''),
          onclick: (ev) => {
            ev.stopPropagation();
            State.visible[m.key] = !isOn;
            renderRightPanel();
            renderPreview();
            persistLocal();
            setDirtyTip('已修改', 'dirty');
            toast(State.visible[m.key] === false ? '已隐藏「' + m.label + '」' : '已开启「' + m.label + '」，点击卡片即可填写', 'success');
          }
        });

        let stateText;
        if (rtMode) stateText = '点击定位编辑';
        else stateText = !isOn ? '未启用' : (count > 0 ? (m.key === 'basic' ? '已填写' : count + ' 项') : '待填写');

        const card = el('div', {
            class: 'ed-module-card' + (isOn || rtMode ? ' active' : ' disabled'),
            title: rtMode ? '点击定位到简历上的「' + m.label + '」区域' : '点击编辑' + m.label,
            onclick: () => {
              if (rtMode) { locateModuleBoxes(m.key); return; }
              if (State.visible[m.key] === false) {
                toast('请先开启「' + m.label + '」模块', 'error');
                return;
              }
              openModuleModal(m.key);
            }
          },
          el('span', { class: 'ed-module-icon' }, m.icon),
          el('span', { class: 'ed-module-copy' },
            el('span', { class: 'ed-module-name' }, m.label),
            el('span', { class: 'ed-module-state' + (!isOn && !rtMode ? ' off' : count > 0 ? ' filled' : '') }, stateText)
          ),
          rtMode ? null : sw
        );
        list.appendChild(card);
      });

      if (!rtMode) {
        sortList.innerHTML = '';
        State.order.forEach((key, idx) => {
          const m = MODULES.find(x => x.key === key);
          if (!m) return;
          const row = el('div', { class: 'ed-sort-row', 'data-key': key },
            el('span', { class: 'ed-drag-handle', title: '按住上下拖动排序' }, '⠿'),
            el('span', { class: 'icon' }, m.icon),
            el('span', { class: 'name' }, m.label)
          );
          sortList.appendChild(row);
        });
      }
    } catch (e) {
      console.error('[editor] renderRightPanel error:', e);
    }
  }

  /* 排序设置：按住行上下任意拖动（指针拖拽，实时换位） */
  let sortDrag = null;
  function wireSortDrag() {
    const list = $('sortList');
    if (!list) return;
    list.addEventListener('pointerdown', e => {
      const row = e.target.closest('.ed-sort-row');
      if (!row || e.button !== 0 || sortDrag) return;
      sortDrag = { list, row, startY: e.clientY, lastSwapY: e.clientY };
      row.classList.add('dragging');
      try { list.setPointerCapture(e.pointerId); } catch (err) {}
      e.preventDefault();
    });
    list.addEventListener('pointermove', e => {
      if (!sortDrag) return;
      e.preventDefault();
      const { list, row } = sortDrag;
      const rows = Array.from(list.children).filter(el => el.classList.contains('ed-sort-row'));
      // 启动阈值：先移动 10px 才开始换位，避免误触
      if (Math.abs(e.clientY - sortDrag.startY) < 10) return;
      // 灵敏度控制：相邻两次换位之间至少移动约半个行高，防止小幅抖动连跳
      const rowH = row.getBoundingClientRect().height || 36;
      const step = Math.max(14, Math.round(rowH * 0.55));
      if (Math.abs(e.clientY - sortDrag.lastSwapY) < step) return;
      let targetRow = null;
      for (const r of rows) {
        if (r === row) continue;
        const rect = r.getBoundingClientRect();
        if (e.clientY < rect.top + rect.height / 2) { targetRow = r; break; }
      }
      if (targetRow) {
        const cur = rows.indexOf(row);
        const tgt = rows.indexOf(targetRow);
        if (cur > tgt) list.insertBefore(row, targetRow);
        else list.insertBefore(row, targetRow.nextSibling);
        sortDrag.lastSwapY = e.clientY;
      } else if (rows.length > 1 && rows[rows.length - 1] !== row) {
        list.appendChild(row);
        sortDrag.lastSwapY = e.clientY;
      }
    });
    const finish = () => {
      if (!sortDrag) return;
      const { list, row } = sortDrag;
      row.classList.remove('dragging');
      sortDrag = null;
      const order = Array.from(list.children)
        .filter(el => el.classList.contains('ed-sort-row'))
        .map(el => el.dataset.key);
      if (!order.length) return;
      State.order = order;
      renderPreview();
      persistLocal();
      toast('模块顺序已更新', 'success');
    };
    list.addEventListener('pointerup', finish);
    list.addEventListener('pointercancel', finish);
  }

  function getModuleMeta(key) {
    const m = MODULES.find(x => x.key === key);
    if (!m) return null;
    const dk = m.dataKey;
    let count = 0;
    if (dk) {
      const v = State.modules[dk];
      if (Array.isArray(v)) count = v.length;
      else if (typeof v === 'string' && v.trim()) {
        if (key === 'hobby') count = v.split(/[、,，\n]/).map(x => x.trim()).filter(Boolean).length;
        else count = 1;
      }
    } else {
      const fields = key === 'basic'
        ? [...BASIC_FIELDS_LEFT, ...BASIC_FIELDS_RIGHT, ...BASIC_FIELDS_EXTRA]
        : [{key:'intention_job'}, {key:'salary'}, {key:'city'}];
      count = fields.filter(f => (State.basic[f.key] || '').trim()).length;
    }
    return { ...m, count: () => count };
  }

  /* ============ 弹窗系统 ============ */
  function closeModal() {
    State.activeModule = null;
    renderRightPanel();
    const root = $('modalRoot');
    if (root) root.innerHTML = '';
  }
  function showModal(content) {
    const root = $('modalRoot');
    if (!root) return;
    root.innerHTML = '';
    root.appendChild(content);
    root.firstChild.addEventListener('click', e => {
      if (e.target === root.firstChild) closeModal();
    });
  }
  function modalShell(title, body, footer, wide) {
    return el('div', { class: 'ed-modal-mask' },
      el('div', { class: 'ed-modal' + (wide ? ' wide' : '') },
        el('div', { class: 'ed-modal-head' },
          el('h3', null, title),
          el('button', { class: 'ed-modal-close', onclick: closeModal }, '×')
        ),
        el('div', { class: 'ed-modal-body' }, body),
        el('div', { class: 'ed-modal-foot' }, footer)
      )
    );
  }

  /* ============ 各模块弹窗 ============ */
  function openModuleModal(key) {
    State.activeModule = key;
    renderRightPanel();
    if (key === 'basic') return openBasicModal();
    if (key === 'intention') return openIntentionModal();
    if (key === 'education') return openListModal('education_info', 'education');
    if (key === 'work') return openListModal('work_history', 'work');
    if (key === 'internship') return openListModal('internship_info', 'internship');
    if (key === 'project') return openListModal('projects', 'project');
    if (key === 'campus') return openListModal('campus_exp', 'campus');
    if (key === 'skill') return openListModal('skill_info', 'skill');
    if (key === 'honor') return openListModal('honor_cert', 'honor');
    if (key === 'hobby') return openHobbyModal();
    if (key === 'custom') return openCustomModal();
    const m = MODULES.find(x => x.key === key);
    if (!m) return;
    return openSimpleModal(m);
  }

  /* ----- 基本信息弹窗 ----- */
  function openBasicModal() {
    const body = el('div', { class: 'ed-basic-body' });
    const grid = el('div', { class: 'ed-field-row two' });
    const allFields = [...BASIC_FIELDS_LEFT, ...BASIC_FIELDS_RIGHT, ...BASIC_FIELDS_EXTRA];
    const pendingFieldVisible = Object.assign({}, State.fieldVisible);
    allFields.forEach(f => grid.appendChild(makeField(f, State.basic)));
    body.appendChild(grid);
    const visibilityPanel = el('div', { class: 'ed-field-visibility' },
      el('div', { class: 'ed-field-visibility-title' }, '简历中显示的字段'),
      el('div', { class: 'ed-field-visibility-list' },
        ...allFields.map(f => el('label', { class: 'ed-field-visibility-item' },
          el('input', { type: 'checkbox', checked: pendingFieldVisible[f.key] !== false,
            onchange: e => { pendingFieldVisible[f.key] = e.target.checked; }
          }),
          el('span', null, f.label)
        ))
      )
    );
    body.appendChild(visibilityPanel);

    const photoArea = el('div', { class: 'ed-photo-area' },
      el('span', { class: 'ed-photo-label' }, '头像'),
      el('div', { class: 'ed-photo-preview', id: 'basicPhotoPreview',
        style: State.photoDataUrl ? `background-image:url(${State.photoDataUrl})` : '',
        onclick: () => { const inp=$('basicPhotoInput'); if(inp) inp.click(); },
        ondragover: (e) => { e.preventDefault(); e.currentTarget.classList.add('drag-over'); },
        ondragleave: (e) => { e.currentTarget.classList.remove('drag-over'); },
        ondrop: (e) => {
          e.preventDefault(); e.currentTarget.classList.remove('drag-over');
          const file = e.dataTransfer.files[0];
          if (file && file.type.startsWith('image/')) handlePhotoFile(file);
        }
      },
        State.photoDataUrl ? '' : el('span', { class: 'ed-photo-placeholder' }, '📷'),
      ),
      el('input', { type:'file', id:'basicPhotoInput', accept:'image/*', style:'display:none',
        onchange: (e) => { const f=e.target.files[0]; if(f) handlePhotoFile(f); }
      }),
      el('label', { class: 'ed-photo-toggle' },
        el('input', { type:'checkbox', checked: State.showPhoto !== false,
          onchange: (e) => { State.showPhoto = e.target.checked; renderPreview(); }
        }),
        ' 显示照片'
      )
    );
    body.appendChild(photoArea);

    const footer = el('div', null,
      el('button', { class: 'ed-btn ed-btn-soft', onclick: closeModal }, '取消'),
      el('button', {
        class: 'ed-btn ed-btn-primary',
        onclick: () => {
          const form = body.querySelectorAll('[name]');
          form.forEach(input => { State.basic[input.name] = input.value; });
          State.fieldVisible = pendingFieldVisible;
          closeModal(); renderPreview(); persistLocal();
          setDirtyTip('已修改', 'dirty'); scheduleLivePreview();
          toast('已暂存到本地');
        }
      }, '保存')
    );
    showModal(modalShell('基本信息 ✏️', body, footer));
  }

  function handlePhotoFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => { openPhotoCropModal(e.target.result); };
    reader.readAsDataURL(file);
  }

  function openPhotoCropModal(imgDataUrl) {
    let rotation=0, scale=1, posX=0, posY=0;
    let dragging=false, dx=0, dy=0;
    const img = new Image();
    img.onload = function() {
      var canvasWrap = el('div',{class:'ed-crop-canvas-wrap'},
        el('canvas',{id:'cropCanvas',width:320,height:360})
      );
      var controls = el('div',{class:'ed-crop-controls'},
        el('button',{class:'ed-btn ed-btn-soft ed-btn-sm',onclick:function(){rotation=(rotation-90)%360;drawCrop();}}, '↺ 左旋转'),
        el('button',{class:'ed-btn ed-btn-soft ed-btn-sm',onclick:function(){rotation=(rotation+90)%360;drawCrop();}}, '↻ 右旋转'),
        el('label',null,'缩放：',
          el('input',{type:'range',id:'cropScale',min:0.5,max:3,step:0.1,value:1,
            style:'width:100px;vertical-align:middle',oninput:function(e){scale=parseFloat(e.target.value);drawCrop();}
          })
        )
      );

      function drawCrop() {
        var cv=$('cropCanvas'); if(!cv) return;
        var ctx=cv.getContext('2d');
        ctx.clearRect(0,0,cv.width,cv.height);
        for(var y=0;y<cv.height;y+=10) for(var x=0;x<cv.width;x+=10) {
          ctx.fillStyle=((x+y)/20)%2 ? '#ccc' : '#fff'; ctx.fillRect(x,y,10,10);
        }
        ctx.save();
        ctx.translate(cv.width/2+posX, cv.height/2+posY);
        ctx.rotate(rotation*Math.PI/180); ctx.scale(scale,scale);
        var s=Math.min(280/img.width,280/img.height);
        ctx.drawImage(img,-img.width*s/2,-img.height*s/2,img.width*s,img.height*s);
        ctx.restore();
      }

      canvasWrap.addEventListener('mousedown',function(e){dragging=true;dx=e.offsetX-posX;dy=e.offsetY-posY;});
      document.addEventListener('mousemove',function(e){
        if(!dragging||!$('cropCanvas'))return;
        var rect=$('cropCanvas').getBoundingClientRect();
        posX=e.clientX-rect.left-dx; posY=e.clientY-rect.top-dy; drawCrop();
      });
      document.addEventListener('mouseup',function(){dragging=false;});

      var btnChange=el('button',{class:'ed-btn ed-btn-primary'},'更换图片');
      btnChange.onclick=function(){
        var inp=document.createElement('input'); inp.type='file'; inp.accept='image/*';
        inp.onclick=function(ev){closeModal();};
        inp.onchange=function(ev){var f=ev.target.files[0];if(f)handlePhotoFile(f);};
        inp.click();
      };
      var btnSave=el('button',{class:'ed-btn ed-btn-primary'},'保存修改');
      btnSave.onclick=function(){
        var cv=$('cropCanvas');
        State.photoDataUrl=cv.toDataURL('image/png');
        var prev=$('basicPhotoPreview');
        if(prev) prev.style.backgroundImage='url('+State.photoDataUrl+')';
        renderPreview(); scheduleLivePreview(); closeModal();
        toast('照片已更新');
      };

      showModal(modalShell('裁剪头像',el('div',null,canvasWrap,controls),el('div',null,btnChange,btnSave)));
      drawCrop();
    };
    img.src=imgDataUrl;
  }

  /* ----- 求职意向 ----- */
  function openIntentionModal() {
    const fields = [
      { key:'intention_job', label:'求职意向', type:'text' },
      { key:'salary',        label:'期望薪资', type:'text' },
      { key:'city',          label:'期望城市', type:'text' },
      { key:'arrive_time',   label:'到岗时间', type:'select',
        options:['随时','1周内','1个月内','3个月内','未定','其他'] }
    ];
    const body = el('div');
    const grid = el('div', { class: 'ed-field-row' });
    fields.forEach(f => grid.appendChild(makeField(f, State.basic)));
    body.appendChild(grid);
    const footer = el('div', null,
      el('button', { class:'ed-btn ed-btn-soft', onclick:closeModal }, '取消'),
      el('button', {
        class:'ed-btn ed-btn-primary',
        onclick:()=>{
          body.querySelectorAll('[name]').forEach(i=>State.basic[i.name]=i.value);
          closeModal(); renderPreview(); persistLocal();
          setDirtyTip('已修改','dirty'); scheduleLivePreview(); toast('已暂存');
        }
      }, '确定')
    );
    showModal(modalShell('求职意向',body,footer));
  }

  function makeField(def, targetObj) {
    const wrap = el('label', { class: 'ed-field' });
    wrap.appendChild(el('span', null, def.label));
    let input;
    if (def.type==='select') {
      input=el('select',{name:def.key});
      (def.options||[]).forEach(opt=>{
        const o=el('option',{value:opt},opt);
        if((targetObj[def.key]||'')===opt) o.setAttribute('selected','');
        input.appendChild(o);
      });
    } else {
      input=el('input',{type:def.type||'text',name:def.key,value:targetObj[def.key]||'',placeholder:'请输入'+def.label});
    }
    wrap.appendChild(input);
    return wrap;
  }

  /* ----- 多记录（教育/工作/实习/项目） ----- */
  function openListModal(dataKey, kind) {
    /* 防御性兜底：历史草稿或异常缓存不应让任何模块编辑器崩溃。 */
    const list = Array.isArray(State.modules[dataKey])
      ? State.modules[dataKey]
      : (State.modules[dataKey] = []);
    const cardsContainer = el('div', { class: 'ed-card-list' });

    function newRecord() {
      if(kind==='education') return{school:'',major:'',degree:'',start:'',end:'',current:false,content:''};
      if(kind==='work'||kind==='internship') return{company:'',position:'',start:'',end:'',current:false,content:''};
      if(kind==='project') return{name:'',role:'',period:'',content:''};
      if(kind==='campus') return{name:'',role:'',period:'',content:''};
      if(kind==='skill') return{name:'',level:'熟练',content:''};
      if(kind==='honor') return{time:'',name:'',issuer:''};
      return{};
    }

    function renderCards() {
      cardsContainer.innerHTML='';
      list.forEach((rec,i)=>{
        const card=el('div',{class:'ed-record-card'});
        const head=el('div',{class:'ed-record-card-head'},
          el('span',null,'#'+(i+1)),
          el('div',{class:'ed-record-card-actions'},
            el('button',{title:'上移',onclick:()=>{if(i>0){[list[i-1],list[i]]=[list[i],list[i-1]];renderCards();}}},'↑'),
            el('button',{title:'下移',onclick:()=>{if(i<list.length-1){[list[i+1],list[i]]=[list[i],list[i+1]];renderCards();}}},'↓'),
            el('button',{class:'del',title:'删除',onclick:()=>{list.splice(i,1);renderCards();}},'×')
          )
        );
        card.appendChild(head);

        if(kind==='education'){
          card.appendChild(el('div',{class:'ed-field-row'},makeInput('学校','school',rec.school),makeInput('专业','major',rec.major)));
          card.appendChild(el('div',{class:'ed-field-row three'},
            makeInput('开始时间','start',rec.start,'如：2018-09'),
            makeInput('结束时间','end',rec.end,'如：2022-06'),
            makeSelect('学历','degree',['本科','硕士','博士','大专','高中','其他'],rec.degree)
          ));
          card.appendChild(el('label',{class:'ed-checkbox'},
            el('input',{type:'checkbox',checked:rec.current?true:false,onchange:e=>{rec.current=e.target.checked;}}),
            el('span',{class:'box'}),el('span',null,' 至今在读')
          ));
          const rt=buildRichText('主修课程/描述',rec.content||'');
          card.appendChild(rt.wrap);
          bindInputs(card,rec,['school','major','start','end','degree']);
          rt.editor.addEventListener('input',()=>{rec.content=rt.editor.innerHTML;});

        }else if(kind==='work'){
          card.appendChild(el('div',{class:'ed-field-row'},makeInput('公司名称','company',rec.company),makeInput('职位','position',rec.position)));
          card.appendChild(el('div',{class:'ed-field-row three'},
            makeInput('开始时间','start',rec.start,'如：2020-03'),
            makeInput('结束时间','end',rec.end,'如：2022-05'),
            el('label',{class:'ed-checkbox'},
              el('input',{type:'checkbox',checked:rec.current?true:false,onchange:e=>{rec.current=e.target.checked;}}),
              el('span',{class:'box'}),el('span',null,' 至今在职')
            )
          ));
          const rt=buildRichText('工作内容/业绩描述',rec.content||'');
          card.appendChild(rt.wrap);
          bindInputs(card,rec,['company','position','start','end']);
          rt.editor.addEventListener('input',()=>{rec.content=rt.editor.innerHTML;});

        }else if(kind==='internship'){
          card.appendChild(el('div',{class:'ed-field-row'},makeInput('实习单位','company',rec.company),makeInput('实习岗位','position',rec.position)));
          card.appendChild(el('div',{class:'ed-field-row three'},
            makeInput('开始时间','start',rec.start,'如：2023-07'),
            makeInput('结束时间','end',rec.end,'如：2023-09'),
            el('label',{class:'ed-checkbox'},
              el('input',{type:'checkbox',checked:rec.current?true:false,onchange:e=>{rec.current=e.target.checked;}}),
              el('span',{class:'box'}),el('span',null,' 至今在职')
            )
          ));
          const rt=buildRichText('实习内容/收获描述',rec.content||'');
          card.appendChild(rt.wrap);
          bindInputs(card,rec,['company','position','start','end']);
          rt.editor.addEventListener('input',()=>{rec.content=rt.editor.innerHTML;});

        }else if(kind==='project' || kind==='campus'){
          const labels = kind==='campus' ? ['经历名称','担任角色','起止时间','经历描述/成果'] : ['项目名称','担任角色','起止时间','项目描述/个人贡献'];
          card.appendChild(el('div',{class:'ed-field-row'},makeInput(labels[0],'name',rec.name),makeInput(labels[1],'role',rec.role)));
          card.appendChild(el('div',{class:'ed-field-row'},makeInput(labels[2],'period',rec.period,'如：2022-03 ~ 2022-09')));
          const rt=buildRichText(labels[3],rec.content||'');
          card.appendChild(rt.wrap);
          bindInputs(card,rec,['name','role','period']);
          rt.editor.addEventListener('input',()=>{rec.content=rt.editor.innerHTML;});
        }else if(kind==='skill'){
          card.appendChild(el('div',{class:'ed-field-row'},makeInput('技能名称','name',rec.name),makeSelect('掌握程度','level',['了解','熟悉','熟练','精通'],rec.level||'熟练')));
          card.appendChild(makeInput('技能说明','content',rec.content,'如：可独立完成 Spring Boot 服务开发'));
          bindInputs(card,rec,['name','level','content']);
        }else if(kind==='honor'){
          card.appendChild(el('div',{class:'ed-field-row'},makeInput('获奖/取证时间','time',rec.time,'如：2024-06'),makeInput('奖项或证书名称','name',rec.name)));
          card.appendChild(makeInput('颁发机构','issuer',rec.issuer));
          bindInputs(card,rec,['time','name','issuer']);
        }
        cardsContainer.appendChild(card);
      });
    }

    const body=el('div');
    body.appendChild(cardsContainer);
    body.appendChild(el('button',{
      class:'ed-add-btn',onclick:()=>{list.push(newRecord());renderCards();}
    },'+ 添加一条'));

    const titles={education:'教育背景',work:'工作经验',internship:'实习经验',project:'项目经验',campus:'校园经历',skill:'技能特长',honor:'荣誉证书'};
    const footer=el('div',null,
      el('button',{class:'ed-btn ed-btn-soft',onclick:closeModal},'取消'),
      el('button',{
        class:'ed-btn ed-btn-primary',
        onclick:()=>{closeModal();renderPreview();renderRightPanel();persistLocal();setDirtyTip('已修改','dirty');scheduleLivePreview();toast('已暂存');}
      },'确定')
    );
    showModal(modalShell(titles[kind]||'',body,footer,true));
    renderCards();
  }

  function makeInput(label,name,value,ph){
    return el('label',{class:'ed-field'},
      el('span',null,label),
      el('input',{type:'text',name,value:value||'',placeholder:ph||''})
    );
  }
  function makeSelect(label,name,options,value){
    const wrap=el('label',{class:'ed-field'},el('span',null,label));
    const sel=el('select',{name});
    options.forEach(o=>{
      const opt=el('option',{value:o},o);
      if((value||'')===o) opt.setAttribute('selected','');
      sel.appendChild(opt);
    });
    wrap.appendChild(sel);return wrap;
  }
  function bindInputs(card,target,keys){
    keys.forEach(k=>{
      const input=card.querySelector('[name="'+k+'"]');
      if(!input)return;
      input.addEventListener('input',e=>{target[k]=e.target.value;});
    });
  }

  /* ----- 简单文本弹窗 ----- */
  function openSimpleModal(m){
    const val=State.modules[m.dataKey]||'';
    const ta=el('textarea',{rows:8,placeholder:'请填写'+m.label+'…'});
    ta.value=val;
    const body=el('div',{class:'ed-field'},el('span',null,m.label+'内容'),ta);
    const footer=el('div',null,
      el('button',{class:'ed-btn ed-btn-soft',onclick:closeModal},'取消'),
      el('button',{
        class:'ed-btn ed-btn-primary',
        onclick: ()=>{
          State.modules[m.dataKey]=ta.value;
          closeModal();renderPreview();renderRightPanel();persistLocal();
          setDirtyTip('已修改','dirty');scheduleLivePreview();toast('已暂存');
        }
      },'确定')
    );
    showModal(modalShell(m.label,body,footer));
  }

  /* ----- 兴趣爱好（标签） ----- */
  function openHobbyModal(){
    const tags = Array.isArray(State.modules.hobby)
      ? State.modules.hobby
      : (State.modules.hobby = []);
    const body=el('div',{class:'ed-field'},
      el('span',null,'兴趣爱好（输入后回车添加）'),
      (()=>{
        const box=el('div',{class:'ed-tag-input'});
        function render(){
          box.innerHTML='';
          tags.forEach((t,i)=>{
            box.appendChild(el('span',{class:'ed-tag'},t,
              el('button',{onclick:()=>{tags.splice(i,1);render();}},'×')
            ));
          });
          const input=el('input',{type:'text',placeholder:'输入后按回车…'});
          input.addEventListener('keydown',e=>{
            if(e.key==='Enter'){e.preventDefault();const v=input.value.trim();if(v&&!tags.includes(v)){tags.push(v);render();}else input.value='';}
          });
          box.appendChild(input);
        }
        render();return box;
      })()
    );
    const footer=el('div',null,
      el('button',{class:'ed-btn ed-btn-soft',onclick:closeModal},'取消'),
      el('button',{
        class:'ed-btn ed-btn-primary',
        onclick: ()=>{closeModal();renderPreview();renderRightPanel();persistLocal();setDirtyTip('已修改','dirty');scheduleLivePreview();toast('已暂存');}
      },'确定')
    );
    showModal(modalShell('兴趣爱好',body,footer));
  }

  /* ----- 自定义（富文本） ----- */
  function openCustomModal(){
    const rt=buildRichText('自由编辑任意内容…',State.modules.custom||'');
    const body=el('div',null,
      el('p',{class:'ed-panel-hint',style:'margin-bottom:10px'},
        '提示：可放技能图谱、获奖经历、自我介绍、推荐语等任意内容'),
      rt.wrap
    );
    const footer=el('div',null,
      el('button',{class:'ed-btn ed-btn-soft',onclick:closeModal},'取消'),
      el('button',{
        class:'ed-btn ed-btn-primary',
        onclick: ()=>{
          State.modules.custom=rt.editor.innerHTML;
          closeModal();renderPreview();renderRightPanel();persistLocal();
          setDirtyTip('已修改','dirty');scheduleLivePreview();toast('已暂存');
        }
      },'确定')
    );
    showModal(modalShell('自定义模块',body,footer,true));
  }

  /* ============ 富文本编辑器 ============ */
  function buildRichText(placeholder,html){
    const wrap=el('div',{class:'ed-richtext'});
    const toolbar=el('div',{class:'ed-richtext-toolbar'});
    const editor=el('div',{class:'ed-richtext-body',contenteditable:'true','data-placeholder':placeholder,oninput:()=>{}});
    editor.innerHTML=html||'';

    function cmd(name,val){editor.focus();try{document.execCommand(name,false,val);}catch(e){}}
    function btn(label,name,val){
      return el('button',{title:name,onclick:e=>{e.preventDefault();cmd(name,val);}},label);
    }
    toolbar.appendChild(btn('撤销','undo'));
    toolbar.appendChild(btn('重做','redo'));
    toolbar.appendChild(el('span',{class:'sep'}));
    toolbar.appendChild(btn('B','bold'));
    toolbar.appendChild(btn('I','italic'));
    toolbar.appendChild(btn('U','underline'));
    toolbar.appendChild(el('span',{class:'sep'}));
    toolbar.appendChild(btn('• 列表','insertUnorderedList'));
    toolbar.appendChild(btn('1. 列表','insertOrderedList'));
    toolbar.appendChild(el('span',{class:'sep'}));
    toolbar.appendChild(btn('左对齐','justifyLeft'));
    toolbar.appendChild(btn('居中','justifyCenter'));
    toolbar.appendChild(el('span',{class:'sep'}));
    toolbar.appendChild(btn('清除格式','removeFormat'));

    wrap.appendChild(toolbar);wrap.appendChild(editor);
    return{wrap,editor};
  }

  /* ============ 设置弹窗 ============ */
  let currentSetting=null;
  /* 配色：id 必须与 resume-render.js 的 THEMES 一一对应（旧草稿 skin 字段可直接复用） */
  const SKIN_PRESETS=[
    {id:'default',name:'星系紫',primary:'#6B4CF5',accent:'#A78BFA',bg:'#F5F3FF'},
    {id:'blue',name:'商务蓝',primary:'#1E5AE8',accent:'#3D8BFF',bg:'#F2F6FC'},
    {id:'green',name:'清新绿',primary:'#1FA67A',accent:'#5DC79E',bg:'#F1FAF5'},
    {id:'orange',name:'活力橙',primary:'#E2691A',accent:'#FF8A3D',bg:'#FCF6F0'},
    {id:'gray',name:'沉稳灰',primary:'#4B5563',accent:'#6B7280',bg:'#F5F6F8'},
    {id:'wine',name:'酒红',primary:'#A03A52',accent:'#C9667D',bg:'#FBEAF0'},
    {id:'teal',name:'青碧',primary:'#0F766E',accent:'#3AA79C',bg:'#E4F5F2'}
  ];
  const FONT_PRESETS=[
    {id:'yahei',name:'微软雅黑',family:'"Microsoft YaHei","PingFang SC",sans-serif',size:14},
    {id:'songti',name:'宋体',family:'"SimSun","宋体",serif',size:14},
    {id:'heiti',name:'黑体',family:'"SimHei","黑体",sans-serif',size:14},
    {id:'kai',name:'楷体',family:'"KaiTi","楷体",serif',size:14},
    {id:'pingfang',name:'苹方',family:'"PingFang SC","Helvetica Neue",sans-serif',size:14}
  ];
  /* 版式族：决定简历的结构骨架（id 与 resume-render.js 的 FAMILIES 对应） */
  const FAMILY_PRESETS=[
    {id:'single',   name:'单栏经典', hint:'自上而下单列，最通用稳妥'},
    {id:'sidebar',  name:'左侧栏',   hint:'左栏放联系与技能，右侧主内容'},
    {id:'headerBar',name:'顶部横幅', hint:'顶部色带突出姓名与求职意向'},
    {id:'twoCol',   name:'双栏紧凑', hint:'正文分两栏，适合经历较多'}
  ];
  /* 小节标题样式（id 与引擎 sectionStyle 对应：underline=默认无类名） */
  const SECSTYLE_PRESETS=[
    {id:'underline',name:'下划线'},
    {id:'bar',      name:'色块'},
    {id:'leftbar',  name:'左竖线'},
    {id:'plain',    name:'纯文字'}
  ];
  /* 版式族缩略示意图（纯 div/CSS 拼，避免额外图片请求） */
  const FAMILY_MINI={
    single:{cls:'fm-single',
      html:'<span class="hd w60"></span><span class="ln w100"></span><span class="ln w90"></span><span class="ln w100"></span><span class="ln w76"></span>'},
    sidebar:{cls:'fm-sidebar',
      html:'<span class="side"></span><div class="body"><span class="hd w90"></span><span class="ln w100"></span><span class="ln w90"></span><span class="ln w100"></span><span class="ln w76"></span></div>'},
    headerBar:{cls:'fm-headerBar',
      html:'<span class="hd w100"></span><span class="ln w90"></span><span class="ln w100"></span><span class="ln w76"></span><span class="ln w100"></span>'},
    twoCol:{cls:'fm-twoCol',
      html:'<div class="col"><span class="hd w90"></span><span class="ln w100"></span><span class="ln w76"></span><span class="ln w100"></span></div><div class="col"><span class="hd w90"></span><span class="ln w100"></span><span class="ln w76"></span><span class="ln w100"></span></div>'}
  };

  async function openSettingModal(type){
    currentSetting=type;
    /* 模板弹窗：快照当前模板状态，点「取消」时完整还原，
       避免「点缩略图立即切换」后取消却回不去 */
    if(type==='template'){
      _tplSnapshot={ templateId:State.templateId,
        structure:realStructure, structureTid:realTemplateId,
        boxTexts:realBoxTexts,
        pages:realPreviewPages, previewTid:realPreviewTemplateId };
    }
    const titles={spacing:'间距设置',skin:'皮肤设置',font:'正文字体',cover:'标题封面',template:'更换模板'};
    $('settingTitle').textContent=titles[type]||'设置';
    $('settingBody').innerHTML='';
    /* 模板面板每次打开前重新拉取列表：
       管理端「编辑器可用性」改动即时生效，不再吃初始化时的旧数据 */
    if(type==='template'){
      $('settingModal').hidden=false;
      $('settingBody').innerHTML='<div style="padding:36px;color:#999;text-align:center">正在加载模板列表…</div>';
      await loadTemplates();
      buildTemplateSetting();
      return;
    }
    if(type==='spacing')buildSpacingSetting();
    else if(type==='skin')buildSkinSetting();
    else if(type==='font')buildFontSetting();
    else if(type==='cover')buildCoverSetting();
    $('settingModal').hidden=false;
  }
  /* _tplSnapshot：更换模板弹窗打开时的模板状态快照（取消时还原） */
  let _tplSnapshot=null;
  function closeSettingModal(cancelled){
    if(cancelled && currentSetting==='template' && _tplSnapshot){
      const s=_tplSnapshot;
      State.templateId=s.templateId;
      realStructure=s.structure;
      realTemplateId=s.structureTid;
      realBoxTexts=s.boxTexts||{};
      realPreviewPages=s.pages||null;
      realPreviewSrc=realPreviewPages?realPreviewPages[0]:null;
      realPreviewTemplateId=s.previewTid;
      _loadStructReqId++;           // 作废所有在途的结构加载，防止慢响应再覆盖
      persistLocal();
      renderPreview();
      renderRightPanel();
    }
    _tplSnapshot=null;
    $('settingModal').hidden=true;currentSetting=null;
    renderAppearancePanel();
  }

  /* ════════════════════════════════════════════════════════════════
   * 外观面板 —— 渲染参数的唯一入口（版式/配色/字体/字号行距/版心/标题照片）
   * 版式族变更 → 重排 DOM；其余参数 → 只写 CSS 变量，毫秒级生效且不闪烁
   * ════════════════════════════════════════════════════════════════ */

  /** 改版式族：结构骨架变了，必须重渲染 DOM */
  function setFamily(id){
    if((State.style.family||'single')===id) return;
    State.style.family=id;
    renderPreview();          // 内部会刷新外观面板与顶栏预览按钮
    persistLocal();
    setDirtyTip('已修改','dirty');
  }

  /** 拖拽中的实时预览：只写 CSS 变量，不落盘、不重建面板（拖动不掉帧） */
  function liveStyle(){
    const page=document.querySelector('#previewPaper .rr-page');
    if(!page || !window.ResumeRender) return;
    window.ResumeRender.applyVars(page,buildRenderStyle());
    updatePageHint();
  }

  /** 一次调整结束：落盘 + 刷新面板选中态 */
  function commitStyle(patch){
    Object.assign(State.style,patch||{});
    applyStyle();             // 内含 syncRenderStyle + persistLocal
    renderAppearancePanel();
    setDirtyTip('已修改','dirty');
  }

  /** 滑杆行：拖动中 liveStyle 即时反馈，松手才落盘 */
  function rangeRow(label,key,min,max,step,cur,fmt){
    const show=fmt||(v=>String(v));
    const valEl=el('b',null,show(cur));
    const input=el('input',{class:'ed-range',type:'range',
      min:String(min),max:String(max),step:String(step),value:String(cur)});
    input.addEventListener('input',function(){
      const v=parseFloat(input.value);
      if(isNaN(v))return;
      valEl.textContent=show(v);
      State.style[key]=v;
      liveStyle();
    });
    input.addEventListener('change',function(){ commitStyle({}); });
    return el('div',{class:'ed-range-row'},
      el('div',{class:'ed-range-head'},el('span',null,label),valEl),
      input
    );
  }

  /** 分段选择行 */
  function segRow(label,presets,cur,key){
    return el('div',{class:'ed-range-row'},
      el('div',{class:'ed-range-head'},el('span',null,label)),
      el('div',{class:'ed-seg'},
        presets.map(p=>el('button',{
          type:'button',
          class:(cur===p.id?'active':''),
          onclick:()=>commitStyle({[key]:p.id})
        },p.name))
      )
    );
  }

  /** 恢复默认外观（只重置外观，不动简历内容） */
  function resetAppearance(){
    const D=(window.ResumeRender&&window.ResumeRender.DEFAULT_STYLE)||{};
    Object.assign(State.style,{
      family:D.family||'single', skin:D.theme||'default', font:D.font||'yahei',
      fontSize:D.fontSize||13, lineHeight:D.lineHeight||1.72,
      spacing:'normal', gap:null, padding:null,
      nameSize:D.nameSize||30, photoSize:D.photoSize||92,
      photoShape:D.photoShape||'rect', sectionStyle:D.sectionStyle||'underline'
    });
    applyStyle();
    renderPreview();
    toast('已恢复默认外观','success');
  }

  function renderAppearancePanel(){
    const pane=$('appearancePane');
    if(!pane) return;
    const sv=State.style||{};
    pane.innerHTML='';

    /* 精确预览模式下外观参数不生效，明确告知（不隐藏，方便用户理解两种模式） */
    if(State.previewMode==='exact' && isRealTemplateActive()){
      pane.appendChild(el('div',{class:'ed-ap-lock'},
        el('span',{class:'ico'},'🔒'),
        el('span',null,'当前是「精确预览」：版面完全由 Word 模板原件决定，下列外观参数暂不生效。点顶栏「精确预览」切回 HTML 预览，即可自由调整版式、字体与间距。')
      ));
    } else if(isRealTemplateActive()){
      /* 两条轨并存时讲清楚分工，避免用户以为调了没用 */
      pane.appendChild(el('div',{
        class:'ed-ap-lock',
        style:'background:#EEF4FF;border-color:#CADCFF;color:#2A4B8D'
      },
        el('span',{class:'ico'},'🧩'),
        el('span',null,'已选模板：导出 Word/PDF 时会套用该模板的原生版式；下面调整的是 HTML 预览的版式与外观，用来快速编排内容。'),
        el('button',{type:'button',class:'ed-ap-reset',style:'flex:0 0 auto',
          onclick:()=>toggleExactPreview()},'看模板原版式')
      ));
    }

    /* ── 1. 版式结构 ── */
    const famCur=sv.family||'single';
    pane.appendChild(el('div',{class:'ed-ap-sec'},
      el('h5',null,'版式结构',el('small',null,'改结构')),
      el('div',{class:'ed-fam-grid'},
        FAMILY_PRESETS.map(f=>{
          const mini=FAMILY_MINI[f.id]||FAMILY_MINI.single;
          return el('div',{
            class:'ed-fam-tile'+(famCur===f.id?' active':''),
            title:f.hint,
            onclick:()=>setFamily(f.id)
          },
            el('div',{class:'fm '+mini.cls,html:mini.html}),
            el('div',{class:'fname'},f.name),
            el('div',{class:'fhint'},f.hint)
          );
        })
      )
    ));

    /* ── 2. 配色 ── */
    const skinCur=sv.skin||'default';
    pane.appendChild(el('div',{class:'ed-ap-sec'},
      el('h5',null,'配色方案',el('small',null,'主色 / 强调色')),
      el('div',{class:'ed-sw-grid'},
        SKIN_PRESETS.map(s=>el('div',{
          class:'ed-sw'+(skinCur===s.id?' active':''),
          title:s.name,
          onclick:()=>commitStyle({skin:s.id})
        },
          el('i',{style:'background:linear-gradient(135deg,'+s.primary+','+s.accent+')'}),
          el('span',null,s.name)
        ))
      )
    ));

    /* ── 3. 字体 ── */
    const fontCur=sv.font||'yahei';
    pane.appendChild(el('div',{class:'ed-ap-sec'},
      el('h5',null,'正文字体',el('small',null,'中文简历推荐雅黑')),
      el('div',{class:'ed-font-grid'},
        FONT_PRESETS.map(f=>el('div',{
          class:'ed-font-tile'+(fontCur===f.id?' active':''),
          onclick:()=>commitStyle({font:f.id})
        },
          el('div',{class:'fa',style:'font-family:'+f.family},'Aa 简历'),
          el('div',{class:'fname'},f.name)
        ))
      )
    ));

    /* ── 4. 字号与行距 ── */
    pane.appendChild(el('div',{class:'ed-ap-sec'},
      el('h5',null,'字号与行距',el('small',null,'内容超一页先缩字号')),
      rangeRow('正文字号','fontSize',11,17,0.5,sv.fontSize||13,v=>v+' px'),
      rangeRow('行距','lineHeight',1.3,2.2,0.02,sv.lineHeight||1.72,v=>v.toFixed(2)+' 倍'),
      rangeRow('姓名字号','nameSize',20,44,1,sv.nameSize||30,v=>v+' px')
    ));

    /* ── 5. 版心与留白 ── */
    pane.appendChild(el('div',{class:'ed-ap-sec'},
      el('h5',null,'版心与留白',el('small',null,'值越大内容越靠内')),
      rangeRow('模块间距','gap',6,40,1,effGap(),v=>v+' px'),
      rangeRow('版心留白','padding',20,72,1,effPad(),v=>v+' px')
    ));

    /* ── 6. 小节标题 ── */
    pane.appendChild(el('div',{class:'ed-ap-sec'},
      el('h5',null,'小节标题',el('small',null,'章节标题样式')),
      segRow('标题样式',SECSTYLE_PRESETS,sv.sectionStyle||'underline','sectionStyle')
    ));

    /* ── 7. 照片 ── */
    pane.appendChild(el('div',{class:'ed-ap-sec'},
      el('h5',null,'照片',el('small',null,'需先在基本信息里上传')),
      segRow('照片形状',[{id:'rect',name:'方形'},{id:'circle',name:'圆形'}],sv.photoShape||'rect','photoShape'),
      rangeRow('照片尺寸','photoSize',64,140,2,sv.photoSize||92,v=>v+' px')
    ));

    pane.appendChild(el('div',{class:'ed-ap-foot'},
      el('div',{class:'ed-ap-note'},'改动即时生效并自动保存'),
      el('button',{class:'ed-ap-reset',type:'button',onclick:resetAppearance},'恢复默认')
    ));
  }

  /* 顶栏「精确预览」开关：HTML 预览（快，可调样式） ⇄ Word 成品图（慢，与导出一致） */
  function syncExactBtn(){
    const b=$('tbExact');
    if(!b) return;
    const on=State.previewMode==='exact';
    b.classList.toggle('on',on);
    const t=b.lastElementChild;
    if(t && t.tagName==='SPAN') t.textContent=on?'精确预览 开':'精确预览';
  }
  function toggleExactPreview(){
    if(!isRealTemplateActive()){
      toast('「精确预览」需要先在「更换模板」里选择一个模板','');
      return;
    }
    State.previewMode=(State.previewMode==='exact')?'doc':'exact';
    syncExactBtn();
    renderPreview();
    // 切到精确预览时用当前内容重排一次，保证看到的是最新编辑结果
    if(State.previewMode==='exact') scheduleRealPreview(80);
    toast(State.previewMode==='exact'
      ? '已切到 Word 精确预览（版面 = 导出效果，编辑响应较慢）'
      : '已切回 HTML 预览（可自由调整版式、字体与间距）','success');
  }

  /* ============ AI 一键生成整份简历 ============ */
  async function openAiGenModal() {
    if (!(await requireVip())) return;
    const m = $('aiGenModal');
    if (m) m.hidden = false;
    const ta = $('aiDesc');
    if (ta) setTimeout(() => ta.focus(), 50);
  }
  function closeAiGenModal() {
    const m = $('aiGenModal');
    if (m) m.hidden = true;
  }
  async function runAiGenerate() {
    if (!(await requireVip())) return;
    const runBtn = $('aiGenRunBtn');
    const target = ($('aiTargetJob').value || '').trim();
    const desc = ($('aiDesc').value || '').trim();
    const jd = ($('aiJd').value || '').trim();
    if (!desc && !jd && !target) {
      toast('请至少填写「个人情况描述」或「求职意向」', '');
      return;
    }
    if (runBtn) { runBtn.disabled = true; runBtn.textContent = '⏳ 生成中…'; }
    showLoading('AI 正在生成整份简历…');
    try {
      const data = await apiPost('/api/ai-generate-resume', {
        description: desc, jd: jd, target_job: target
      });
      applyAiResume(data);
      closeAiGenModal();
      toast('已生成整份简历，可继续微调', 'success');
      setDirtyTip('AI 已生成，待保存', 'dirty');
    } catch (e) {
      toast('生成失败：' + (e.message || '请稍后重试'), '');
    } finally {
      hideLoading();
      if (runBtn) { runBtn.disabled = false; runBtn.textContent = '⚡ 生成简历'; }
    }
  }
  function applyAiResume(data) {
    if (!data || typeof data !== 'object') return;
    /* 退出真实模板模式，确保 AI 生成的结构化整份简历立即在标准预览中可见、可编辑 */
    realStructure = null;
    realTemplateId = null;
    if (data.basic && typeof data.basic === 'object') Object.assign(State.basic, data.basic);
    const m = data.modules || {};
    const arrKeys = ['education_info', 'work_history', 'internship_info', 'projects',
                     'campus_exp', 'skill_info', 'honor_cert', 'hobby'];
    arrKeys.forEach(k => { if (Array.isArray(m[k])) State.modules[k] = m[k]; });
    if (typeof m.self_evaluate === 'string') State.modules.self_evaluate = m.self_evaluate;
    if (typeof m.custom === 'string') State.modules.custom = m.custom;
    // 自动开启有内容的模块
    State.visible.education = State.modules.education_info.length > 0;
    State.visible.work = State.modules.work_history.length > 0;
    State.visible.self = (State.modules.self_evaluate || '').trim().length > 0;
    State.visible.project = State.modules.projects.length > 0;
    State.visible.internship = State.modules.internship_info.length > 0;
    State.visible.campus = State.modules.campus_exp.length > 0;
    State.visible.skill = State.modules.skill_info.length > 0;
    State.visible.honor = State.modules.honor_cert.length > 0;
    State.visible.hobby = State.modules.hobby.length > 0;
    renderPreview();
    renderRightPanel();
    persistLocal();
  }

  /* ============ 质量引擎：匹配度评分（免费） ============ */
  function escapeHtml(s){
    return String(s==null?'':s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }
  function getQualityProfile(){
    /* 以编辑器结构化档案为唯一真相源，AI 输出不得超出 */
    return { basic: State.basic, modules: State.modules };
  }
  function openMatchScoreModal(){
    const m=$('matchScoreModal');
    if(m) m.hidden=false;
    const t=$('msTargetJob');
    if(t && !t.value) t.value=State.quality.target_job||'';
    const j=$('msJd');
    if(j && !j.value) j.value=State.quality.jd||'';
  }
  function closeMatchScoreModal(){ const m=$('matchScoreModal'); if(m) m.hidden=true; }
  async function runMatchScore(){
    const target=($('msTargetJob').value||'').trim();
    const jd=($('msJd').value||'').trim();
    State.quality.target_job=target; State.quality.jd=jd;
    const runBtn=$('msRunBtn');
    if(runBtn){ runBtn.disabled=true; runBtn.textContent='⏳ 评分中…'; }
    showLoading('AI 正在评估匹配度…');
    try{
      const data=await apiPost('/api/quality/match-score',{
        profile:getQualityProfile(), target_job:target, jd:jd
      });
      renderMatchScoreResult(data);
      toast('匹配度评分完成','success');
    }catch(e){
      toast('评分失败：'+(e.message||'请稍后重试'),'');
    }finally{
      hideLoading();
      if(runBtn){ runBtn.disabled=false; runBtn.textContent='⚡ 开始评分'; }
    }
  }
  function renderMatchScoreResult(d){
    const box=$('msResult'); if(!box) return;
    box.hidden=false;
    const dims=d.dimensions||{};
    const dimLabels={technical:'技术能力',experience:'相关经验',behavioral:'软技能/行为',career:'职业匹配'};
    const dimHtml=Object.keys(dimLabels).map(k=>{
      const v=Math.max(0,Math.min(100,Number(dims[k]||0)));
      return `<div class="ms-dim"><div class="ms-dim-row"><span>${dimLabels[k]}</span><span>${v}</span></div>`
        +`<div class="ms-dim-bar"><div class="ms-dim-fill" style="width:${v}%"></div></div></div>`;
    }).join('');
    const kwList=(arr)=> (arr&&arr.length)? arr.map(x=>`<li>${escapeHtml(String(x))}</li>`).join(''):'<li>无</li>';
    const locTxt={pass:'✅ 地点符合',fail:'❌ 地点不符（硬门槛）',flag:'⚠️ 地点需确认',unknown:'— 未提供地点'}[d.location_gate||'unknown']||'—';
    box.innerHTML=`<div class="ms-score-wrap">`
      +`<div class="ms-score-num">${d.total_score}</div>`
      +`<div class="ms-score-meta"><span class="ms-verdict ${d.recommendation||''}">${escapeHtml(d.verdict_text||'')}</span>`
      +`<div class="ms-note">综合匹配分（满分 100）· 地点闸门：${locTxt}</div></div></div>`
      +`<div>${dimHtml}</div>`
      +`<div class="ms-cols"><div class="ms-col"><h4>✅ 命中关键词</h4><ul>${kwList(d.matched_keywords)}</ul></div>`
      +`<div class="ms-col"><h4>➕ 建议补充</h4><ul>${kwList(d.missing_keywords)}</ul></div></div>`
      +`<div class="ms-cols"><div class="ms-col"><h4>核心优势</h4><ul>${kwList(d.strengths)}</ul></div>`
      +`<div class="ms-col"><h4>待补缺口</h4><ul>${kwList(d.gaps)}</ul></div></div>`
      +`<div class="ms-note">${escapeHtml(d.note||'')}</div>`;
  }

  /* ============ 质量引擎：ATS 文本层校验（免费，导出后自动触发） ============ */
  async function runAtsCheck(blob, format){
    if(format!=='pdf' && format!=='docx') return; // PNG 等图片格式无法做文本层校验
    const fd=new FormData();
    fd.append('file', blob, 'resume.'+format);
    fd.append('jd', State.quality.jd||'');
    fd.append('target_job', State.quality.target_job||'');
    fd.append('profile', JSON.stringify(getQualityProfile()));
    try{
      const data=await apiPost('/api/quality/ats-check', fd);
      renderAtsReport(data);
    }catch(e){
      console.warn('[editor] ATS 校验失败:', e.message);
      // 不影响导出主流程，仅静默
    }
  }
  function renderAtsReport(d){
    const body=$('atsReportBody'); if(!body) return;
    const lvl=d.pass_level||'warn';
    const ico={pass:'✅',warn:'⚠️',fail:'❌'}[lvl]||'⚠️';
    const checksHtml=(d.checks||[]).map(c=>{
      const ci={pass:'pass',warn:'warn',fail:'fail'}[c.status]||'warn';
      return `<li><span class="ats-ico ${ci}">${ico}</span>`
        +`<div class="ats-check-body"><div class="ats-check-name">${escapeHtml(c.name)}</div>`
        +`<div class="ats-check-detail">${escapeHtml(c.detail||'')}</div></div></li>`;
    }).join('');
    let covHtml='';
    if(d.jd_coverage){
      const cov=d.jd_coverage.coverage||0;
      const matched=(d.jd_coverage.matched||[]).map(x=>`<b>${escapeHtml(x)}</b>`).join('、');
      const miss=(d.jd_coverage.missing||[]).slice(0,30).map(x=>`<span class="miss">${escapeHtml(x)}</span>`).join('、');
      covHtml=`<div class="ats-cov"><div class="ms-dim-row"><span>JD 关键词覆盖率</span><span>${cov}%</span></div>`
        +`<div class="ats-cov-bar"><div class="ats-cov-fill" style="width:${cov}%"></div></div>`
        +`<div class="ats-kw">命中：${matched||'无'} ${miss?(' · 缺失：'+miss):''}</div></div>`;
    }
    const fmtTxt={pdf:'PDF',docx:'Word'}[d.format]||d.format;
    body.innerHTML=`<div class="ats-head"><div class="ats-gauge ${lvl}">${d.ats_score}</div>`
      +`<div class="ats-head-meta"><span class="ats-badge ${lvl}">${lvl==='pass'?'ATS 兼容良好':(lvl==='warn'?'存在兼容隐患':'兼容性较差')}</span>`
      +`<div class="ms-note">${fmtTxt} 文本层校验 · ${escapeHtml(d.verdict_text||'')}</div></div></div>`
      +`<ul class="ats-checks">${checksHtml}</ul>${covHtml}`;
    const m=$('atsReportModal'); if(m) m.hidden=false;
  }
  function closeAtsReport(){ const m=$('atsReportModal'); if(m) m.hidden=true; }

  function buildSpacingSetting(){
    const body=$('settingBody');
    const opts=[
      {id:'compact',name:'紧凑',gap:6},
      {id:'normal',name:'标准',gap:12},
      {id:'loose',name:'宽松',gap:18}
    ];
    const cur=State.style.spacing||'normal';
    body.appendChild(el('div',{class:'ed-setting-section'},
      el('h4',null,'模块间距'),
      el('div',{class:'ed-setting-grid'},
        ...opts.map(o=>el('div',{
          class:'ed-setting-tile'+(cur===o.id?' active':''),'data-id':o.id,
          onclick:e=>{body.querySelectorAll('.ed-setting-tile').forEach(x=>x.classList.remove('active'));e.currentTarget.classList.add('active');
            /* 切档位 = 恢复「跟随档位」状态：清掉手动滑杆值，间距交给档位派生 */
            State.style.spacing=o.id;State.style.gap=null;State.style.padding=null;applyStyle();}
        },
          el('div',{class:'preview',style:'background:'+(o.id==='compact'?'#FCEBF5':o.id==='loose'?'#EDE9FF':'#EFEBFF')+';display:flex;flex-direction:column;gap:'+o.gap+'px;padding:10px'},
            el('div',{style:'height:8px;background:#6B4CF5;border-radius:2px'}),
            el('div',{style:'height:8px;background:#6B4CF5;border-radius:2px;width:70%'})
          ),
          el('div',{class:'name'},o.name)
        ))
      )
    ));
  }
  function buildSkinSetting(){
    const body=$('settingBody');
    const cur=State.style.skin||'default';
    body.appendChild(el('div',{class:'ed-setting-section'},
      el('h4',null,'选择配色方案'),
      el('div',{class:'ed-setting-grid'},
        ...SKIN_PRESETS.map(s=>el('div',{
          class:'ed-setting-tile'+(cur===s.id?' active':''),'data-id':s.id,
          onclick:e=>{body.querySelectorAll('.ed-setting-tile').forEach(x=>x.classList.remove('active'));e.currentTarget.classList.add('active');State.style.skin=s.id;applyStyle();}
        },
          el('div',{class:'preview',style:'background:linear-gradient(135deg,'+s.primary+','+s.accent+')'}),
          el('div',{class:'name'},s.name)
        ))
      )
    ));
  }
  function buildFontSetting(){
    const body=$('settingBody');
    const cur=State.style.font||'yahei';
    body.appendChild(el('div',{class:'ed-setting-section'},
      el('h4',null,'选择正文字体'),
      el('div',{class:'ed-setting-grid'},
        ...FONT_PRESETS.map(f=>el('div',{
          class:'ed-setting-tile'+(cur===f.id?' active':''),'data-id':f.id,
          onclick:e=>{body.querySelectorAll('.ed-setting-tile').forEach(x=>x.classList.remove('active'));e.currentTarget.classList.add('active');State.style.font=f.id;applyStyle();}
        },
          el('div',{class:'preview',style:'display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:700;font-family:'+f.family+';color:#6B4CF5'},'Aa'),
          el('div',{class:'name'},f.name)
        ))
      )
    ));
  }
  function buildCoverSetting(){
    const body=$('settingBody');
    const cur=State.style.cover||false;
    body.appendChild(el('div',{class:'ed-setting-section'},
      el('h4',null,'封面页'),
      el('label',{class:'ed-setting-row'},
        el('input',{type:'checkbox',checked:cur?true:false,onchange:e=>{State.style.cover=e.target.checked;applyStyle();}}),
        el('span',null,' 启用封面页')
      )
    ));
  }
  function buildTemplateSetting(){
    const body=$('settingBody');
    const vips=State.vipTemplates||[];
    const frees=State.freeTemplates||[];
    if(!vips.length && !frees.length){
      body.appendChild(el('div',{class:'ed-setting-section'},
        el('h4',null,el('span',{class:'ed-vip-title'},'模板中心')),
        el('div',{class:'ed-tpl-empty'},el('div',{class:'ed-tpl-empty-ico'},'📄'),
          el('p',null,'暂无可用的模板'),
          el('small',null,'请联系管理员在「模板管理」中启用模板'))
      ));
      return;
    }
    const tplTile = t => {
      const isVip = (State.vipTemplates||[]).some(v=>v.id===t.id);
      return el('div',{
          class:'ed-tpl-mini'+(t.id===State.templateId?' active':''),'data-id':t.id,
          onclick:e=>{
            State.templateId=t.id;
            body.querySelectorAll('.ed-tpl-mini').forEach(x=>x.classList.remove('active'));
            e.currentTarget.classList.add('active');
            persistLocal();
            renderPreview();          // 结构就绪前显示引导页，loadRealStructure 完成后自动重渲染
            loadRealStructure(t.id);
            toast('已选择「'+t.name+'」 — 正在加载模板原件…','success');
          }
        },
          t.preview_url?el('img',{src:t.preview_url+(t.preview_url.includes('?')?'&':'?')+'t='+Date.now(),alt:t.name,loading:'lazy'}):el('div',{class:'no-preview'},'暂无预览'),
          el('div', { class: 'name' },
            isVip?el('span',{class:'ed-tpl-vip-badge'},'👑 VIP'):null,
            t.name
          )
        );
    };
    if(frees.length){
      body.appendChild(el('div',{class:'ed-setting-section'},
        el('h4',null,el('span',{class:'ed-tpl-title'},'🆓 免费模板库（点缩略图立即切换）')),
        el('div',{class:'ed-tpl-tip'},'全部支持真实结构就地编辑，套用后直接在模板上修改'),
        el('div',{class:'ed-tpl-grid'},
          ...frees.map(tplTile)
        )
      ));
    }
    if(vips.length){
      body.appendChild(el('div',{class:'ed-setting-section'},
        el('h4',null,el('span',{class:'ed-vip-title'},'👑 VIP模板中心（点缩略图立即切换）')),
        el('div',{class:'ed-vip-tip'},'VIP 模板由管理员在管理端「VIP模板中心」上传'),
        el('div',{class:'ed-tpl-grid'},
          ...vips.map(tplTile)
        )
      ));
    }
  }
  function applySetting(){
    persistLocal();
    if (currentSetting === 'template') renderPreview();
    closeSettingModal();
    toast('设置已应用','success');
  }

  function applyStyle(){
    const skin=SKIN_PRESETS.find(s=>s.id===(State.style.skin||'default'))||SKIN_PRESETS[0];
    document.documentElement.style.setProperty('--primary',skin.primary);
    document.documentElement.style.setProperty('--primary-soft',skin.primary+'22');
    document.documentElement.style.setProperty('--bg',skin.bg);
    const font=FONT_PRESETS.find(f=>f.id===(State.style.font||'yahei'));
    if(font){
      document.documentElement.style.setProperty('--ed-font-family',font.family);
      document.documentElement.style.setProperty('--ed-font-size',font.size+'px');
    }
    const gaps={compact:'8px',normal:'14px',loose:'22px'};
    document.documentElement.style.setProperty('--ed-module-gap',gaps[State.style.spacing]||gaps.normal);
    document.body.classList.toggle('ed-cover-enabled',State.style.cover===true);
    syncRenderStyle();
    persistLocal();
  }

  /** 把样式变更同步到简历预览：
   *  结构项（版式族/标题样式/照片形状）变了 → 重渲染结构；
   *  只改配色/字体/字号/行距/间距 → 仅更新 CSS 变量（毫秒级，无闪烁） */
  function syncRenderStyle(){
    if(!window.ResumeRender) return;
    const page=document.querySelector('#previewPaper .rr-page');
    if(!page) return;
    if(structKey()!==_renderedStruct){
      renderDocPreview();
    } else {
      window.ResumeRender.applyVars(page, buildRenderStyle());
      updatePageHint();
    }
  }

  /* ============ 导出 ============ */
  async function renderAndExport(format){
    if(!State.templateId){toast('请先在「更换模板」中选择一个模板','error');return;}
    // 仅支持真实模板导出（写回模板文本框，保留原格式）
    if (isRealTemplateActive()) {
      await exportRealTemplate(format);
      return;
    }
    toast('模板尚未加载完成，请稍候重试或在「更换模板」中重新选择','error');
  }

  async function exportRealTemplate(format){
    if(!State.templateId){toast('请先选择一个模板','error');return;}
    if(format==='png') return exportPngLongImage();
    showLoading(format==='pdf'?'正在生成 PDF…':'正在生成 Word…');
    try{
      const fd=new FormData();
      fd.append('edits',JSON.stringify(realBoxTexts||{}));
      fd.append('format',format==='pdf'?'pdf':'docx');
      const r=await fetch('/api/template-save/'+State.templateId,{
        method:'POST',headers:authHeader(),body:fd
      });
      if(!r.ok){
        const t=await r.text();
        let d={};try{d=JSON.parse(t);}catch(e){}
        throw new Error(d.detail||d.error||('HTTP '+r.status));
      }
      const blob=await r.blob();
      const url=URL.createObjectURL(blob);
      const a=document.createElement('a');
      a.href=url;
      a.download=(format==='pdf'?'简历.pdf':'简历.docx');
      document.body.appendChild(a);a.click();
      setTimeout(function(){a.remove();URL.revokeObjectURL(url);},120);
      toast((format==='pdf'?'PDF':'Word')+' 已开始下载','success');
      /* 真实模板导出同样自动做 ATS 校验（仅 PDF/Word） */
      if(format==='pdf'||format==='docx') runAtsCheck(blob, format);
    }catch(e){toast('导出失败：'+e.message,'error');}
    finally{hideLoading();}
  }

  /* 长图导出：用最新编辑内容渲染全部页面，纵向拼成一张 PNG */
  async function exportPngLongImage(){
    showLoading('正在生成长图…');
    try{
      const fd=new FormData();
      fd.append('edits',JSON.stringify(realBoxTexts||{}));
      const r=await apiPost('/api/template-preview/'+State.templateId,fd);
      const pages=(r&&r.pages&&r.pages.length)?r.pages:(r&&r.png_b64?[r.png_b64]:[]);
      if(!pages.length) throw new Error('渲染失败，请稍后重试');
      const imgs=await Promise.all(pages.map(src=>new Promise((res,rej)=>{
        const im=new Image();
        im.onload=()=>res(im);
        im.onerror=()=>rej(new Error('页面图片加载失败'));
        im.src=src;
      })));
      const w=Math.max.apply(null,imgs.map(i=>i.naturalWidth));
      const gap=Math.round(w*0.03);
      const h=imgs.reduce((s,i)=>s+i.naturalHeight,0)+gap*(imgs.length-1);
      const cv=document.createElement('canvas');
      cv.width=w;cv.height=h;
      const ctx=cv.getContext('2d');
      ctx.fillStyle='#F3F1FF';
      ctx.fillRect(0,0,w,h);
      let y=0;
      imgs.forEach(im=>{ctx.drawImage(im,0,y);y+=im.naturalHeight+gap;});
      const blob=await new Promise(res=>cv.toBlob(res,'image/png'));
      if(!blob) throw new Error('图片合成失败');
      const url=URL.createObjectURL(blob);
      const a=document.createElement('a');
      a.href=url;a.download='简历.png';
      document.body.appendChild(a);a.click();
      setTimeout(function(){a.remove();URL.revokeObjectURL(url);},120);
      toast('长图已开始下载','success');
    }catch(e){toast('长图导出失败：'+e.message,'error');}
    finally{hideLoading();}
  }

  function stripHtml(html){
    const div=document.createElement('div');div.innerHTML=String(html==null?'':html);
    return div.textContent||div.innerText||'';
  }

  /* ============ VIP 门禁 UI（免费用户隐藏 AI 编辑入口，改显升级提示） ============ */
  async function applyVipUi() {
    const vip = await isVipUser();
    const aiBtn = $('aiGenBtn');
    const vipBtn = $('vipBtn');
    if (vip) {
      if (aiBtn) aiBtn.style.display = '';
      if (vipBtn) vipBtn.style.display = 'none';
    } else {
      if (aiBtn) aiBtn.style.display = 'none';
      if (vipBtn) { vipBtn.style.display = 'inline-flex'; vipBtn.textContent = '升级VIP 解锁AI'; }
    }
  }

  /* ============ 事件绑定 ============ */
  function bindEvents(){
    $('saveBtn').addEventListener('click',saveDraft);
    $('vipBtn').addEventListener('click',()=>toast('AI 智能编辑为 VIP 会员专属，敬请期待',''));

    $('tbTemplate').addEventListener('click',()=>openSettingModal('template'));
    const tbExact=$('tbExact');
    if(tbExact) tbExact.addEventListener('click',toggleExactPreview);

    const dlBtn=$('downloadBtn'),dlMenu=$('downloadMenu');
    dlBtn.addEventListener('click',e=>{e.stopPropagation();dlMenu.hidden=!dlMenu.hidden;});
    document.addEventListener('click',()=>{dlMenu.hidden=true;});
    dlMenu.querySelectorAll('button[data-fmt]').forEach(b=>{
      b.addEventListener('click',()=>{dlMenu.hidden=true;renderAndExport(b.dataset.fmt);});
    });

    document.querySelectorAll('[data-close]').forEach(b=>{b.addEventListener('click',()=>closeSettingModal(true));});
    /* AI 一键生成整份简历 */
    $('aiGenBtn').addEventListener('click', openAiGenModal);
    $('aiGenRunBtn').addEventListener('click', runAiGenerate);
    const aiModal = $('aiGenModal');
    if (aiModal) {
      aiModal.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click', closeAiGenModal));
      aiModal.addEventListener('click', e => { if (e.target === aiModal) closeAiGenModal(); });
    }
    $('settingApplyBtn').addEventListener('click',applySetting);

    /* 质量引擎：匹配度评分（免费，无需 VIP） */
    $('matchScoreBtn').addEventListener('click', openMatchScoreModal);
    $('msRunBtn').addEventListener('click', runMatchScore);
    const msModal=$('matchScoreModal');
    if(msModal){
      msModal.querySelectorAll('[data-close-ms]').forEach(b=>b.addEventListener('click', closeMatchScoreModal));
      msModal.addEventListener('click', e=>{ if(e.target===msModal) closeMatchScoreModal(); });
    }
    const atsModal=$('atsReportModal');
    if(atsModal){
      atsModal.querySelectorAll('[data-close-ats]').forEach(b=>b.addEventListener('click', closeAtsReport));
      atsModal.addEventListener('click', e=>{ if(e.target===atsModal) closeAtsReport(); });
    }

    document.querySelectorAll('.ed-tab').forEach(t=>{
      t.addEventListener('click',()=>{
        document.querySelectorAll('.ed-tab').forEach(x=>x.classList.remove('active'));
        document.querySelectorAll('.ed-tab-pane').forEach(x=>x.classList.remove('active'));
        t.classList.add('active');
        const pane=$('tab-'+t.dataset.tab);if(pane)pane.classList.add('active');
      });
    });
  }

  /* ============ 启动 ============ */
  /* ── 从「我的简历」页加载指定草稿 ── */
  async function loadDraftById(draftId) {
    try {
      const data = await apiGet('/api/draft/' + draftId);
      // 填充 State
      State.draftId = data.id;
      State.templateId = data.template_id || State.templateId;
      if (data.data) {
        const d = data.data;
        if (d.basic) Object.assign(State.basic, d.basic);
        if (d.modules) Object.assign(State.modules, d.modules);
        if (d.order) State.order = d.order;
        if (d.visible) Object.assign(State.visible, d.visible);
        if (d.field_visible) Object.assign(State.fieldVisible, d.field_visible);
        if (d.style) Object.assign(State.style, d.style);
        if (d.photo) State.photoDataUrl = d.photo;
        /* 恢复真实模板模式（新版本草稿才有；旧草稿按 templateId 兜底） */
        realTemplateId = Number(d.real_template_id) || data.template_id || null;
        realBoxTexts = {};
        if (d.real_box_texts && typeof d.real_box_texts === 'object') {
          Object.keys(d.real_box_texts).forEach(function(k) {
            realBoxTexts[k] = cleanBoxText(d.real_box_texts[k]);
          });
        }
      } else {
        realTemplateId = data.template_id || null;
      }
      // 同样的旧版兼容处理
      _migrateLegacyModules();
      persistLocal();
      return true;
    } catch(e) {
      console.warn('[editor] loadDraftById failed:', e.message);
      return false;
    }
  }

  function _migrateLegacyModules() {
    const legacyTextToRecord = {
      education_info: text => ({ school:'', major:'', degree:'', start:'', end:'', current:false, content:text }),
      work_history: text => ({ company:'', position:'', start:'', end:'', current:false, content:text }),
      internship_info: text => ({ company:'', position:'', start:'', end:'', current:false, content:text }),
      projects: text => ({ name:'', role:'', period:'', content:text }),
      campus_exp: text => ({ name:'', role:'', period:'', content:text }),
      skill_info: text => ({ name:'', level:'熟练', content:text }),
      honor_cert: text => ({ time:'', name:text, issuer:'' })
    };
    Object.keys(legacyTextToRecord).forEach(key => {
      const value = State.modules[key];
      if (Array.isArray(value)) return;
      const text = typeof value === 'string' ? value.trim() : '';
      State.modules[key] = text ? [legacyTextToRecord[key](text)] : [];
    });
    if (!Array.isArray(State.modules.hobby)) {
      State.modules.hobby = typeof State.modules.hobby === 'string'
        ? State.modules.hobby.split(/[、,，\n]/).map(x => x.trim()).filter(Boolean)
        : [];
    }
  }

  async function init(){
    window.__editor = { openModuleModal };
    // 登录门禁：需登录才能使用编辑器（AI 编辑等付费能力另行按 VIP 校验）
    if (!(await ensureVipAccess())) return;
    bindEvents();
    bindRealBoxModal();      // 真实模板：热区弹窗编辑器（一次绑定）
    applyVipUi();

    // URL 支持两种明确入口：
    // ① ?draft_id=：从“我的简历”继续编辑指定云端草稿；
    // ② ?template_id=：指定模板建立一份空白新简历（不恢复旧草稿）。
    //    注意：首页模板中心已改为「只下载」，不再带 template_id 跳进来；
    //    这个入口留给「我的简历」等需要指定模板的场景。
    const urlParams = new URLSearchParams(location.search);
    const urlDraftId = urlParams.get('draft_id');
    const urlTemplateId = parseInt(urlParams.get('template_id'), 10);
    let loadedFromServer = false;
    const createWithTemplate = !urlDraftId && Number.isInteger(urlTemplateId) && urlTemplateId > 0;

    if (urlDraftId) {
      loadedFromServer = await loadDraftById(parseInt(urlDraftId, 10));
      if (loadedFromServer) {
        toast('已加载云端草稿', 'success');
        setDirtyTip('已加载云端草稿', '');
      }
    }

    if (createWithTemplate) {
      State.draftId = null;
      State.templateId = urlTemplateId;
      realStructure = null;
      realTemplateId = null;
      realBoxTexts = {};
      applyStyle();
      setDirtyTip('新建简历，等待填写', '');
      toast('已选择模板，请开始填写', 'success');
    } else if (!loadedFromServer) {
      const restored=restoreLocal();
      applyStyle();
      if(restored){toast('已恢复上次草稿（本地）','success');setDirtyTip('已恢复本地草稿','');}
      else{setDirtyTip('未保存','');}
    } else {
      applyStyle();
    }

    // 先渲染预览与模块面板（预览不依赖模板列表），
    // 模板列表改为异步加载，仅「更换模板」弹窗需要，避免每次进入都要先等接口
    renderRightPanel();
    wireSortDrag();
    renderPreview();
    if (State.photoDataUrl) {
      const avImg=$('avatarImg');
      if(avImg)avImg.src=State.photoDataUrl;
    }
    await loadTemplates();
    // 统一激活真实模板模式：只要草稿/URL 指定了模板（不论新建还是云端恢复），
    // 都尝试解析其可编辑盒子结构。解析失败会自动回退内置渲染器。
    if (State.templateId && !(realStructure && realTemplateId === State.templateId)) {
      loadRealStructure(State.templateId);
    }
    console.log('[editor jxq v2] init complete — ', Object.keys(TEMPLATE_LAYOUTS).length, ' template layouts loaded');
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',init);
  }else{
    init();
  }
})();
