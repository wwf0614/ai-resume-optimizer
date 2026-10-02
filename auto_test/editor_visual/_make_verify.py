"""生成编辑器验证页（仅用于本地视觉验证，不属于产品代码）。

背景：本机 Git Bash 极度精简（缺 dirname/sed/head/chmod/sh），
agent-browser 的官方 shim 跑不起来；而 Edge headless 又无法预先写 localStorage。
方案：把「登录拿 token + 写样例草稿」的内联脚本插到 editor.html 最前面
（同源，允许写 localStorage），再用 URL 参数控制外观与交互。

⚠️ 生成的 _verify_editor.html 里含明文 token，用完必须删除——
    它在 static/ 下会被 HTTP 直接对外提供。用完执行：
        python _make_verify.py --clean

用法：
    python _make_verify.py            # 生成 static/_verify_editor.html
    python _make_verify.py --clean     # 删除该文件（务必执行）
"""
import json
import pathlib
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:8000"
BASE = pathlib.Path(r"D:\DeepseekV4-智简历\resume_optimizer\static")
TEST_ACCOUNT = "editor_test@local.dev"
TEST_PASSWORD = "test123456"

SAMPLE_BASIC = {
    "name": "测试用户", "gender": "男", "birth_date": "1998-03", "age": "3年经验",
    "phone": "138-0000-1234", "email": "wenfeng@example.com", "wechat": "wf_dev",
    "city": "贵阳", "hometown": "贵州遵义", "political_status": "中共党员",
    "nation": "汉族", "marriage": "未婚", "height": "175cm",
    "education_degree": "本科", "school": "贵州大学", "major": "计算机科学与技术",
}

SAMPLE = {
    "basic": SAMPLE_BASIC,
    "intention": {"position": "Python 后端开发工程师", "city": "贵阳 / 成都",
                  "salary": "15-22K", "entry": "一个月内到岗"},
    "modules": {
        "education_info": [
            {"school": "贵州大学", "major": "计算机科学与技术", "degree": "本科",
             "start": "2016-09", "end": "2020-06",
             "content": "主修课程：数据结构、操作系统、数据库原理、计算机网络；GPA 3.6/4.0，专业前 15%。"},
        ],
        "work_history": [
            {"company": "某科技（深圳）有限公司", "position": "Python 后端开发工程师",
             "start": "2022-07", "end": "至今", "current": True,
             "content": "主导订单中心重构，QPS 从 800 提升至 4200，接口 P99 由 620ms 降到 110ms；\n"
                        "搭建基于 Redis + 延迟队列的库存扣减方案，超卖率降至 0；\n"
                        "沉淀 12 个内部公共组件，团队重复开发工时下降约 35%。"},
            {"company": "某网络科技有限公司", "position": "后端开发工程师",
             "start": "2020-07", "end": "2022-06",
             "content": "负责用户中心与权限体系开发，支撑 60 万日活；\n"
                        "引入 Celery 异步化对账任务，日终对账耗时从 40 分钟降到 6 分钟。"},
        ],
        "internship_info": [
            {"company": "某信息技术有限公司", "position": "后端开发实习生",
             "start": "2019-09", "end": "2020-03",
             "content": "参与内部工单系统开发，独立完成报表导出模块，支撑日均 3000+ 次导出。"},
        ],
        "projects": [
            {"name": "智能简历优化平台", "role": "项目负责人", "period": "2023-05 ~ 2023-11",
             "content": "基于 FastAPI + MySQL 搭建简历结构化解析与模板渲染服务；\n"
                        "实现 Word 模板占位符解析与回填，支持 50+ 套模板一键导出 PDF/Word；\n"
                        "上线后注册用户 1.2 万，简历导出成功率达 99.2%。"},
            {"name": "实时风控规则引擎", "role": "核心开发", "period": "2022-09 ~ 2023-02",
             "content": "设计可热更新的规则 DSL，规则变更无需发版，生效时间由 2 天缩短至 30 秒。"},
        ],
        "campus_exp": [
            {"name": "校计算机协会", "role": "技术部部长", "period": "2017-09 ~ 2019-06",
             "content": "组织 8 场技术分享会，累计参与 900+ 人次；带队完成协会官网改版。"},
        ],
        "skill_info": [
            {"name": "Python / FastAPI / Django", "level": "精通",
             "content": "熟悉异步编程、性能调优与工程化拆分"},
            {"name": "MySQL / Redis", "level": "熟练",
             "content": "慢查询优化、索引设计、缓存与分布式锁"},
            {"name": "Docker / Linux", "level": "熟练",
             "content": "容器化部署、日志排查、CI 流水线维护"},
        ],
        "honor_cert": [
            {"time": "2019-11", "name": "国家励志奖学金", "issuer": "教育部"},
            {"time": "2021-06", "name": "软件设计师（中级）", "issuer": "工信部"},
        ],
        "self_evaluate": "3 年 Python 后端经验，擅长高并发场景下的性能优化与系统重构，"
                         "主导过订单中心与风控引擎从 0 到 1 的建设。习惯用数据说话，"
                         "能独立完成需求拆解、方案设计到上线监控的完整闭环，"
                         "对代码质量与线上稳定性有较高要求。",
        "hobby": ["长跑（半马 1h52m）", "开源贡献", "摄影", "围棋"],
        "custom": "",
    },
    "order": ["basic", "intention", "education", "work", "internship", "project",
              "campus", "skill", "honor", "self", "hobby", "custom"],
    "visible": {"basic": True, "intention": True, "education": True, "work": True,
                "internship": True, "project": True, "campus": True, "skill": True,
                "honor": True, "self": True, "hobby": True, "custom": False},
    "style": {"family": "single", "skin": "default", "font": "yahei",
              "fontSize": 12.5, "lineHeight": 1.62, "spacing": "normal",
              "gap": 16, "padding": 40, "nameSize": 30, "photoSize": 92,
              "photoShape": "rect", "sectionStyle": "underline", "cover": False},
    "photoDataUrl": None,
    "showPhoto": False,
    "templateId": None,
    "draftId": None,
}

INJECT = """
<script>
/* 验证页专用：预置登录令牌与样例草稿（同源，允许写 localStorage） */
window.__ERR__ = [];
window.addEventListener('error', function (e) {
  window.__ERR__.push('ERROR: ' + (e.message || '') + ' @' +
    (e.filename || '').split('/').pop() + ':' + (e.lineno || 0));
});
window.addEventListener('unhandledrejection', function (e) {
  window.__ERR__.push('REJECT: ' + String((e.reason && e.reason.message) || e.reason));
});
(function () {
  var q = new URLSearchParams(location.search);
  var d = __DRAFT__;
  if (q.get('fam'))   d.style.family = q.get('fam');
  if (q.get('theme')) d.style.skin = q.get('theme');
  if (q.get('font'))  d.style.font = q.get('font');
  if (q.get('sec'))   d.style.sectionStyle = q.get('sec');
  if (q.get('zoom'))  d.style.fontSize = parseFloat(q.get('zoom'));
  if (q.get('tpl'))   d.templateId = parseInt(q.get('tpl'), 10);
  if (q.get('mode'))  d.previewMode = q.get('mode');
  if (q.get('empty')) {
    d.basic = {}; d.modules = {}; d.visible = { basic: true, intention: true };
    d.order = ['basic', 'intention'];
  }
  localStorage.setItem('resume_planet_token', '__TOKEN__');
  localStorage.setItem('rz_token', '__TOKEN__');
  localStorage.setItem('rz_editor_draft', JSON.stringify(d));
})();
</script>
"""

# 自动切到「外观」标签，便于截图看到面板；并在 ?geom=1 时把关键元素几何写进 DOM
AUTOSHOW = """
<script>
var __DELAY__ = parseInt((new URLSearchParams(location.search).get('delay') || '2600'), 10);
setTimeout(function () {
  var t = document.querySelector('.ed-tab[data-tab="appearance"]');
  if (t) t.click();
  var toast = document.getElementById('toast');
  if (toast) toast.hidden = true;

  /* ?panel=tpl → 打开顶栏「更换模板」弹窗（截图模板面板用） */
  var panel = new URLSearchParams(location.search).get('panel');
  if (panel === 'tpl') {
    var btn = document.getElementById('tbTemplate');
    if (btn) btn.click();
    setTimeout(function () {
      var m = document.getElementById('settingModal');
      if (m) { m.hidden = false; m.style.display = 'flex'; }
    }, 400);
  }

  if (new URLSearchParams(location.search).get('geom')) {
    var q = new URLSearchParams(location.search);

    /* 交互测试：?click=fam:1,sw:3,font:2 —— 依次点击面板控件，再读渲染结果 */
    (q.get('click') || '').split(',').filter(Boolean).forEach(function (spec) {
      var kv = spec.split(':');
      var sel = kv[0] === 'fam' ? '.ed-fam-tile'
              : kv[0] === 'sw' ? '.ed-sw'
              : kv[0] === 'sec' ? '.ed-seg button'
              : '.ed-font-tile';
      var list = document.querySelectorAll(sel);
      var idx = parseInt(kv[1], 10) || 0;
      if (list[idx]) list[idx].click();
    });

    var sels = ['#previewWrap', '#previewPaper', '#previewPaper .rr-page',
                '.rr-head', '.rr-sec', '.rr-item', '.rr-item-head', '.rr-item-meta',
                '.rr-side', '#rrPageHint', '#appearancePane', '.ed-fam-tile'];
    var info = {};
    sels.forEach(function (s) {
      var e = document.querySelector(s);
      if (!e) { info[s] = 'MISSING'; return; }
      var r = e.getBoundingClientRect();
      info[s] = { x: Math.round(r.x), y: Math.round(r.y),
                  w: Math.round(r.width), h: Math.round(r.height),
                  sw: e.scrollWidth, sh: e.scrollHeight };
    });
    var paper = document.querySelector('#previewPaper');
    if (paper) info['__paper__'] = { sw: paper.scrollWidth, cw: paper.clientWidth,
                             cls: paper.className };

    /* 渲染结果快照：class 与 CSS 变量（验证「点击 → 生效」真的通了） */
    var page = document.querySelector('#previewPaper .rr-page');
    if (page) {
      var cs = getComputedStyle(page);
      info['__style__'] = {
        cls: page.className,
        accent: cs.getPropertyValue('--rr-accent').trim(),
        fs: cs.getPropertyValue('--rr-fs').trim(),
        lh: cs.getPropertyValue('--rr-lh').trim(),
        gap: cs.getPropertyValue('--rr-gap').trim(),
        pad: cs.getPropertyValue('--rr-pad').trim(),
        nameSize: cs.getPropertyValue('--rr-name-size').trim(),
        font: cs.getPropertyValue('--rr-font').trim(),
        secTitleCls: (document.querySelector('.rr-sec-title') || {}).className || 'MISSING'
      };
    }
    var activeTabs = Array.prototype.map.call(
      document.querySelectorAll('.ed-fam-tile.active .fname, .ed-sw.active span, ' +
                               '.ed-font-tile.active .fname'),
      function (e) { return e.textContent; });
    info['__active__'] = activeTabs;
    info['__errors__'] = (window.__ERR__ || []).slice(0, 12);
    var wrapEl = document.querySelector('.ed-preview-wrap');
    info['__previewCls__'] = wrapEl ? wrapEl.className : 'MISSING';
    var pre = document.createElement('pre');
    pre.id = '__geom__';
    pre.textContent = 'GEOMSTART' + JSON.stringify(info) + 'GEOMEND';
    document.documentElement.appendChild(pre);
  }
}, __DELAY__);
</script>
"""


def _post(path, payload):
    req = urllib.request.Request(
        API + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def get_token():
    """自备测试账号：优先登录，没注册过就注册。避免 token 落盘。"""
    try:
        return _post("/api/login",
                     {"account": TEST_ACCOUNT, "password": TEST_PASSWORD})["token"]
    except urllib.error.HTTPError:
        return _post("/api/register",
                     {"account": TEST_ACCOUNT, "password": TEST_PASSWORD,
                      "nickname": "编辑器测试"})["token"]


def make_index(token):
    """首页验证页：注入 token 让 checkAuth() 通过，便于截图模板弹窗。

    URL 参数：?modal=<模板id> 直接打开该模板的预览弹窗。
    """
    html = (BASE / "index.html").read_text(encoding="utf-8")
    inject = ("<script>try{localStorage.setItem('resume_planet_token','%s');}catch(e){}</script>\n"
              % token)
    html = html.replace("<head>", "<head>\n" + inject, 1)
    # 首页脚本依赖外部 API，多给一点时间再截图；顺手把 toast 藏掉。
    # ?clickcard=N 延时点击第 N 张模板卡片 —— 比 ?modal= 可靠：
    # index.html 里 loadTemplates() 没有 await 就紧接着读 templateList，
    # 冷启动（无 localStorage 缓存）时列表还是空的，?modal= 深链因此打不开弹窗。
    html = html.replace("</body>", """
<script>
setTimeout(function(){
  var t = document.getElementById('toast'); if (t) t.hidden = true;
  var n = parseInt((new URLSearchParams(location.search).get('clickcard') || '-1'), 10);
  if (n >= 0) {
    var cards = document.querySelectorAll('#tplGrid .tpl-card');
    if (cards[n]) cards[n].click();
  }
  if (new URLSearchParams(location.search).get('geom')) {
    setTimeout(function () {
      var info = { buttons: [], modal: null };
      var m = document.getElementById('tplModal');
      if (m) {
        var r = m.getBoundingClientRect();
        info.modal = { cls: m.className, x: Math.round(r.x), y: Math.round(r.y),
                       w: Math.round(r.width), h: Math.round(r.height) };
        var box = m.querySelector('.tpl-modal-box');
        if (box) { var rb = box.getBoundingClientRect();
          info.modal.box = { x: Math.round(rb.x), y: Math.round(rb.y),
                             w: Math.round(rb.width), h: Math.round(rb.height) }; }
      }
      ['tplModalUse', 'tplModalDl', 'tplModalVip'].forEach(function (id) {
        var e = document.getElementById(id);
        if (!e) { info.buttons.push({ id: id, state: 'MISSING' }); return; }
        var cs = getComputedStyle(e);
        info.buttons.push({ id: id, tag: e.tagName, text: (e.textContent || '').trim(),
                            display: cs.display, visibility: cs.visibility,
                            visible: cs.display !== 'none' && cs.visibility !== 'hidden',
                            href: e.getAttribute('href') || '' });
      });
      var pre = document.createElement('pre');
      pre.id = '__geom__';
      pre.textContent = 'GEOMSTART' + JSON.stringify(info) + 'GEOMEND';
      document.documentElement.appendChild(pre);
    }, 1500);
  }
}, 8000);
</script>
</body>""", 1)
    out = BASE / "_verify_index.html"
    out.write_text(html, encoding="utf-8")
    print("written:", out, len(html), "chars")
    print("提醒：验证完请执行  python _make_verify.py --index --clean  删除含 token 的验证页")


def clean():
    for out in (BASE / "_verify_editor.html", BASE / "_verify_index.html"):
        if out.exists():
            out.unlink()
            print("removed:", out)
    if not (BASE / "_verify_editor.html").exists() and not (BASE / "_verify_index.html").exists():
        print("nothing to clean")


def main():
    if "--clean" in sys.argv:
        return clean()
    token = get_token()
    if "--index" in sys.argv:
        return make_index(token)
    html = (BASE / "editor.html").read_text(encoding="utf-8")
    inject = (INJECT.replace("__TOKEN__", token)
                    .replace("__DRAFT__", json.dumps(SAMPLE, ensure_ascii=False)))
    html = html.replace("<head>", "<head>\n" + inject, 1)
    html = html.replace("</body>", AUTOSHOW + "\n</body>", 1)
    out = BASE / "_verify_editor.html"
    out.write_text(html, encoding="utf-8")
    print("written:", out, len(html), "chars")
    print("提醒：验证完请执行  python _make_verify.py --clean  删除含 token 的验证页")


if __name__ == "__main__":
    sys.exit(main())
