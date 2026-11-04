/* SPA 路由与菜单 */
const MENUS = [
  { group: '智能客服', items: [
    { key: 'service', title: '客服工作台', icon: '💬' },
    { key: 'human', title: '人工工作台', icon: '🎧' },
    { key: 'tickets', title: '服务工单', icon: '🎫' },
    { key: 'kb', title: '知识库管理', icon: '📚' },
  ]},
  { group: '移动作业', items: [
    { key: 'scan', title: '扫码作业', icon: '⌗' },
  ]},
  { group: '智能决策', items: [
    { key: 'dashboard', title: '数据看板', icon: '📊' },
    { key: 'alerts', title: '预警中心', icon: '🔔' },
    { key: 'replenishment', title: '智能补货', icon: '🤖' },
    { key: 'pathopt', title: '路径优化', icon: '🧭' },
    { key: 'reports', title: '报表中心', icon: '📈' },
  ]},
  { group: '入库管理', items: [
    { key: 'asn', title: '收货通知', icon: '📥' },
    { key: 'inbound', title: '入库单管理', icon: '📋' },
    { key: 'inspections', title: '质检管理', icon: '🔍' },
  ]},
  { group: '出库管理', items: [
    { key: 'outbound', title: '出库单管理', icon: '📤' },
    { key: 'waves', title: '波次拣货', icon: '🌊' },
  ]},
  { group: '库存管理', items: [
    { key: 'inventory', title: '实时库存', icon: '🏷️' },
    { key: 'moves', title: '库存流水', icon: '🔄' },
    { key: 'adjustments', title: '调整记录', icon: '⚖️' },
    { key: 'checks', title: '盘点管理', icon: '🧮' },
    { key: 'batches', title: '批次效期', icon: '⏰' },
  ]},
  { group: '基础管理', items: [
    { key: 'products', title: '商品档案', icon: '📦' },
    { key: 'warehouses', title: '仓库管理', icon: '🏭' },
    { key: 'areas', title: '库区管理', icon: '🗺️' },
    { key: 'locations', title: '库位管理', icon: '📍' },
    { key: 'suppliers', title: '供应商管理', icon: '🚚' },
    { key: 'customers', title: '客户管理', icon: '👥' },
    { key: 'users', title: '用户管理', icon: '👤' },
    { key: 'roles', title: '角色权限', icon: '🔐' },
  ]},
  { group: '系统管理', items: [
    { key: 'configs', title: '系统参数', icon: '⚙️' },
    { key: 'logs', title: '操作日志', icon: '📝' },
  ]},
];

let CURRENT_PAGE = null;

/* 各菜单所需权限（未列出的菜单所有登录用户可见） */
const MENU_PERMS = {
  users: 'user:view', roles: 'role:view', logs: 'log:view', configs: 'system:config',
  replenishment: 'decision:view', reports: 'report:view', inspections: 'inbound:view',
  service: 'cs:view', human: 'cs:ticket', tickets: 'cs:ticket', kb: 'cs:kb', scan: 'scan:view',
};

function buildMenu() {
  const nav = document.getElementById('menuNav');
  nav.innerHTML = MENUS.map(g => {
    const items = g.items.filter(it => !MENU_PERMS[it.key] || hasPerm(MENU_PERMS[it.key]));
    if (!items.length) return '';
    return `
      <div class="group-title">${g.group}</div>
      ${items.map(it => `<a class="nav-link" id="menu_${it.key}" href="javascript:loadPage('${it.key}')">${it.icon} ${it.title}</a>`).join('')}`;
  }).join('');
}

async function loadPage(key) {
  const page = PAGES[key];
  if (!page) return;
  if (MENU_PERMS[key] && !hasPerm(MENU_PERMS[key])) return UI.toast('您没有访问该模块的权限', 'error');
  document.querySelectorAll('.app-sidebar .nav-link').forEach(a => a.classList.remove('active'));
  const menuEl = document.getElementById('menu_' + key);
  if (menuEl) menuEl.classList.add('active');
  document.getElementById('pageTitle').textContent = page.title;
  try { history.replaceState(null, '', '#' + key); } catch (e) {}
  if (window.innerWidth < 992) document.getElementById('sidebar').classList.remove('show');
  const fab = document.querySelector('.cs-fab');
  if (fab) fab.style.display = key === 'service' ? 'none' : 'flex';

  // 销毁上一页图表实例
  if (CURRENT_PAGE && CURRENT_PAGE.destroy) { try { CURRENT_PAGE.destroy(); } catch (e) {} }
  echarts?.dispose ? Object.keys(echarts._chartsMaps || {}).forEach(() => {}) : null;
  document.querySelectorAll('.chart-box, .chart-box-sm').forEach(el => { const inst = echarts.getInstanceByDom(el); if (inst) inst.dispose(); });

  CURRENT_PAGE = page;
  const content = document.getElementById('content');
  content.innerHTML = '<div class="text-center py-5"><div class="spinner-border text-primary"></div></div>';
  try {
    await page.render(content);
    // 页面切换入场动画（重置后重加触发重新播放）
    content.classList.remove('page-enter');
    void content.offsetWidth;
    content.classList.add('page-enter');
  } catch (e) {
    content.innerHTML = `<div class="alert alert-danger">页面加载失败: ${e.message}</div>`;
  }
}

function doLogout() {
  API.post('/auth/logout').finally(() => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    location.href = '/';
  });
}

/* ==================== 个人中心：查看态 / 编辑态 ==================== */
let _profileUser = null;   // 服务端返回的当前资料（编辑态对比基线）

function profileSet(html) {
  const body = document.getElementById('profile_body');
  if (!body) return;
  body.innerHTML = html;
  body.classList.remove('profile-enter');
  void body.offsetWidth;
  body.classList.add('profile-enter');
}

function profilePermsHtml(perms) {
  if (perms.includes('*')) return '<span class="badge perm-chip perm-star">★ 全部权限</span>';
  if (!perms.length) return '<span class="text-muted small">暂无</span>';
  const shown = perms.slice(0, 6).map(p => `<span class="badge perm-chip">${p}</span>`).join('');
  const more = perms.length > 6 ? `<span class="badge perm-chip perm-more">+${perms.length - 6} 项</span>` : '';
  return shown + more;
}

async function showProfile() {
  const res = await API.get('/auth/me');
  if (res.code !== 0) return UI.toast(res.msg, 'error');
  _profileUser = res.data;
  const m = UI.modal({ title: '👤 个人中心', body: '<div id="profile_body"></div>' });
  m.el.querySelector('.modal-footer')?.remove();   // 底部按钮由内容区自行渲染
  renderProfileView();
}

/* —— 查看态：纯阅读 —— */
function renderProfileView() {
  const u = _profileUser;
  const local = JSON.parse(localStorage.getItem('user') || '{}');
  const perms = local.perms || [];
  const roleBadges = (u.roles || []).map(r => `<span class="badge profile-role">${r}</span>`).join('');
  profileSet(`
    <div class="profile-banner">
      <div class="profile-avatar">${(u.real_name || u.username || '?').slice(0, 1)}</div>
      <div class="profile-name">${u.real_name || '-'}</div>
      <div class="profile-uname">@${u.username}</div>
      ${roleBadges ? `<div class="profile-roles">${roleBadges}</div>` : ''}
    </div>
    <div class="profile-info">
      <div class="info-item">
        <div class="info-icon tint-blue">📱</div>
        <div><div class="info-label">手机号</div>
        <div class="info-value">${u.phone || '<span class="text-muted fst-italic">未绑定</span>'}</div></div>
      </div>
      <div class="info-item">
        <div class="info-icon tint-cyan">✉️</div>
        <div><div class="info-label">邮箱</div>
        <div class="info-value">${u.email || '<span class="text-muted fst-italic">未绑定</span>'}</div></div>
      </div>
      <div class="info-item">
        <div class="info-icon tint-violet">💼</div>
        <div><div class="info-label">职位</div>
        <div class="info-value">${(u.roles || []).join(' / ') || '-'}</div></div>
      </div>
      <div class="info-item">
        <div class="info-icon tint-amber">🔑</div>
        <div><div class="info-label">权限</div>
        <div class="info-value"><div class="perm-chips">${profilePermsHtml(perms)}</div>
          <div class="info-lock" style="margin-top:4px">共 ${perms.includes('*') ? '全部' : perms.length} 项</div></div></div>
      </div>
    </div>
    <div class="profile-actions">
      <button class="btn btn-sm btn-outline-danger" onclick="doLogout()">🚪 退出登录</button>
      <div class="flex-fill"></div>
      <button class="btn btn-sm btn-outline-primary" onclick="profileGotoPwd()">🔑 修改密码</button>
      <button class="btn btn-sm btn-primary" onclick="renderProfileEdit()">✏️ 修改资料</button>
    </div>`);
}

/* —— 编辑态：换绑手机/邮箱（需验证码），职位权限只读 —— */
function renderProfileEdit() {
  const u = _profileUser;
  profileSet(`
    <div class="profile-edit-head">
      <div class="profile-avatar profile-avatar-sm">${(u.real_name || u.username || '?').slice(0, 1)}</div>
      <div class="flex-fill">
        <div class="fw-bold">${u.real_name || '-'} <span class="text-muted small fw-normal">@${u.username}</span></div>
        <div class="small text-muted">职位：${(u.roles || []).join(' / ') || '-'}</div>
      </div>
      <span class="badge text-bg-light border">✏️ 编辑中</span>
    </div>
    <div class="alert alert-info py-2 small mb-3">仅手机号、邮箱可自助修改；换绑需验证码验证，未修改的字段无需验证。</div>
    <div class="edit-item">
      <label>📱 手机号</label>
      <input class="form-control form-control-sm" name="phone" value="${u.phone || ''}" placeholder="请输入新手机号"
             oninput="profileToggleCode('phone')" onkeydown="if(event.key==='Enter')profileSave()">
      <div class="code-row d-none" data-for="phone">
        <input class="form-control form-control-sm" name="sms_code" placeholder="短信验证码" maxlength="6"
               onkeydown="if(event.key==='Enter')profileSave()">
        <button class="btn btn-sm btn-outline-secondary text-nowrap" onclick="profileSendCode(this,'sms')">获取验证码</button>
      </div>
    </div>
    <div class="edit-item">
      <label>✉️ 邮箱</label>
      <input class="form-control form-control-sm" name="email" value="${u.email || ''}" placeholder="请输入新邮箱"
             oninput="profileToggleCode('email')" onkeydown="if(event.key==='Enter')profileSave()">
      <div class="code-row d-none" data-for="email">
        <input class="form-control form-control-sm" name="email_code" placeholder="邮箱验证码" maxlength="6"
               onkeydown="if(event.key==='Enter')profileSave()">
        <button class="btn btn-sm btn-outline-secondary text-nowrap" onclick="profileSendCode(this,'email')">获取验证码</button>
      </div>
    </div>
    <div class="profile-actions">
      <button class="btn btn-sm btn-outline-secondary flex-fill" onclick="renderProfileView()">取消</button>
      <button class="btn btn-sm btn-primary flex-fill" onclick="profileSave()">💾 保存资料</button>
    </div>`);
}

/* 输入值与原值对比：变更时才显示验证码行 */
function profileToggleCode(field) {
  const body = document.getElementById('profile_body');
  const val = body.querySelector(`[name=${field}]`).value.trim();
  const row = body.querySelector(`.code-row[data-for=${field}]`);
  const changed = val !== (_profileUser[field] || '');
  row.classList.toggle('d-none', !changed);
  if (!changed) {
    const code = row.querySelector('input');
    if (code) code.value = '';
  }
}

/* 发送换绑验证码（60s 倒计时） */
async function profileSendCode(btn, kind) {
  const body = document.getElementById('profile_body');
  const target = body.querySelector(`[name=${kind === 'sms' ? 'phone' : 'email'}]`).value.trim();
  if (!target) return UI.toast(kind === 'sms' ? '请先输入新手机号' : '请先输入新邮箱', 'error');
  const res = await API.post(kind === 'sms' ? '/auth/rebind/sms-code' : '/auth/rebind/email-code',
                             kind === 'sms' ? { new_phone: target } : { new_email: target });
  if (res.code !== 0) return UI.toast(res.msg, 'error');
  UI.toast(`验证码已发送：${res.data.code}（演示环境直接显示）`, 'info');
  btn.disabled = true;
  let left = 60;
  const t = setInterval(() => {
    btn.textContent = left > 0 ? `${left--}s 后重发` : '获取验证码';
    if (left <= 0) { clearInterval(t); btn.disabled = false; }
  }, 1000);
}

/* 保存：校验变更字段的验证码后提交 */
async function profileSave() {
  const u = _profileUser;
  const body = document.getElementById('profile_body');
  const phone = body.querySelector('[name=phone]').value.trim();
  const email = body.querySelector('[name=email]').value.trim();
  const sms_code = body.querySelector('[name=sms_code]')?.value.trim() || '';
  const email_code = body.querySelector('[name=email_code]')?.value.trim() || '';
  const phoneChanged = phone !== (u.phone || '');
  const emailChanged = email !== (u.email || '');
  if (!phoneChanged && !emailChanged) return UI.toast('资料未做修改', 'warning');
  if (phoneChanged && !sms_code) return UI.toast('手机号已变更，请获取并填写短信验证码', 'error');
  if (emailChanged && !email_code) return UI.toast('邮箱已变更，请获取并填写邮箱验证码', 'error');
  const res = await API.put('/auth/me', { phone, sms_code, email, email_code });
  if (res.code !== 0) return UI.toast(res.msg, 'error');
  UI.toast('资料修改成功');
  const me = await API.get('/auth/me');
  if (me.code === 0) _profileUser = me.data;
  else { _profileUser.phone = phone; _profileUser.email = email; }
  renderProfileView();   // 回到查看态展示最新资料
}

/* 从个人中心跳转修改密码 */
function profileGotoPwd() {
  const mdl = document.querySelector('.modal.show');
  if (mdl) bootstrap.Modal.getInstance(mdl)?.hide();
  setTimeout(showChangePwd, 350);
}

function showChangePwd() {
  const m = UI.modal({
    title: '修改密码',
    body: `<div id="pwd_normal">
        ${UI.field('原密码', UI.input('old_password', '', 'password'))}
        ${UI.field('新密码（至少6位）', UI.input('new_password', '', 'password'))}
        <div class="text-center small">
          <a href="javascript:void(0)" onclick="switchPwdMode('sms')">忘记原密码？用手机验证码修改</a>
        </div>
      </div>
      <div id="pwd_sms" style="display:none">
        <div class="alert alert-info py-2 small">验证码将发送至您账号绑定的手机号，验证通过后可直接设置新密码。</div>
        ${UI.field('验证码', `<div class="d-flex gap-2"><input class="form-control form-control-sm" name="sms_code" style="flex:1"><button class="btn btn-sm btn-outline-secondary" id="send_code_btn" onclick="sendSmsCode(this)">获取验证码</button></div>`)}
        ${UI.field('新密码（至少6位）', UI.input('sms_new_password', '', 'password'))}
        <div class="text-center small">
          <a href="javascript:void(0)" onclick="switchPwdMode('normal')">返回原密码修改</a>
        </div>
      </div>
      <div class="text-center small mt-2">
        无法自助修改？<a href="javascript:void(0)" onclick="applyResetPwd()">向管理员申请重置</a>
      </div>`,
    okText: '确认修改',
    onOk: async () => {
      const smsMode = document.getElementById('pwd_sms').style.display !== 'none';
      if (smsMode) {
        const code = document.querySelector(`#${m.id} [name=sms_code]`).value.trim();
        const pwd = document.querySelector(`#${m.id} [name=sms_new_password]`).value;
        if (!code || (pwd || '').length < 6) { UI.toast('请填写完整，新密码至少6位', 'error'); return false; }
        const res = await API.post('/auth/password/reset-by-sms', { code, new_password: pwd });
        if (res.code === 0) UI.toast('密码重置成功，下次登录请使用新密码');
        else { UI.toast(res.msg, 'error'); return false; }
        return true;
      }
      const d = UI.formData(m.id);
      if (!d.old_password || (d.new_password || '').length < 6) { UI.toast('请填写完整，新密码至少6位', 'error'); return false; }
      const res = await API.post('/auth/change-password', d);
      if (res.code === 0) UI.toast('密码修改成功');
      else { UI.toast(res.msg, 'error'); return false; }
      return true;
    },
  });
}

function switchPwdMode(mode) {
  document.getElementById('pwd_normal').style.display = mode === 'normal' ? '' : 'none';
  document.getElementById('pwd_sms').style.display = mode === 'sms' ? '' : 'none';
}

async function sendSmsCode(btn) {
  btn.disabled = true;
  const res = await API.post('/auth/password/sms-code');
  if (res.code !== 0) { UI.toast(res.msg, 'error'); btn.disabled = false; return; }
  UI.toast(`验证码已发送至 ${res.data.phone.slice(0,3)}****${res.data.phone.slice(-4)}：${res.data.code}（演示环境直接显示）`, 'info');
  let left = 60;
  const t = setInterval(() => {
    btn.textContent = left > 0 ? `${left--}s 后重发` : '获取验证码';
    if (left <= 0) { clearInterval(t); btn.disabled = false; }
  }, 1000);
}

function applyResetPwd() {
  UI.confirm('确定向管理员申请重置密码吗？<br><span class="text-muted small">管理员审核通过后，您的密码将重置为 123456</span>', async () => {
    const res = await API.post('/auth/reset-requests', { reason: '忘记原密码，申请重置' });
    if (res.code === 0) UI.toast('申请已提交，请等待管理员审核');
    else UI.toast(res.msg, 'error');
  }, false);
}

/* 权限判断 */
function hasPerm(code) {
  const user = JSON.parse(localStorage.getItem('user') || '{}');
  const perms = user.perms || [];
  return perms.includes('*') || perms.includes(code);
}

window.addEventListener('hashchange', () => {
  const key = location.hash.replace('#', '');
  if (PAGES[key]) loadPage(key);
});

(function init() {
  if (!localStorage.getItem('token')) { location.href = '/'; return; }
  const user = JSON.parse(localStorage.getItem('user') || '{}');
  document.getElementById('userName').textContent = user.real_name || user.username || '';
  buildMenu();
  const hash = location.hash.replace('#', '') || 'dashboard';
  loadPage(PAGES[hash] ? hash : 'dashboard');
  // 同步最新角色权限，角色调整后无需重新登录即可显示新菜单
  API.get('/auth/me').then(res => {
    if (res.code !== 0 || !res.data) return;
    const merged = { ...user, ...res.data };
    localStorage.setItem('user', JSON.stringify(merged));
    buildMenu();
    const key = location.hash.replace('#', '') || 'dashboard';
    document.querySelectorAll('.app-sidebar .nav-link').forEach(a => a.classList.remove('active'));
    document.getElementById('menu_' + key)?.classList.add('active');
  }).catch(() => {});
})();
