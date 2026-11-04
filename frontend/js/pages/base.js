/* 基础管理页面：用户/角色/仓库/库区/库位/商品/供应商/客户 */
const PAGES = window.PAGES || {};

/* ============ 用户管理 ============ */
PAGES.users = {
  title: '用户管理',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span>用户列表</span>
          <div class="d-flex gap-2">
            <input class="form-control form-control-sm" id="u_kw" placeholder="搜索用户名/姓名" style="width:200px">
            <button class="btn btn-sm btn-outline-primary" onclick="PAGES.users.load(1)">搜索</button>
            <button class="btn btn-sm btn-outline-warning position-relative" onclick="PAGES.users.resetRequests()">📋 重置申请<span class="position-absolute top-0 start-100 translate-middle badge rounded-pill text-bg-danger" id="reset_badge" style="display:none"></span></button>
            <button class="btn btn-sm btn-primary" onclick="PAGES.users.edit()">+ 新增用户</button>
          </div>
        </div>
        <div class="card-body p-0" id="u_list"></div>
        <div class="card-footer bg-white" id="u_page"></div>
      </div>`;
    this.load(1);
    this.refreshResetBadge();
  },
  async refreshResetBadge() {
    if (!hasPerm('user:edit')) return;
    const res = await API.get('/auth/reset-requests');
    if (res.code !== 0 || !res.data || !res.data.pending) return;
    const badge = document.getElementById('reset_badge');
    if (badge) { badge.textContent = res.data.pending; badge.style.display = ''; }
  },
  async resetRequests() {
    const res = await API.get('/auth/reset-requests');
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const stMap = { pending: '<span class="badge st-pending badge-status">待处理</span>',
      approved: '<span class="badge st-normal badge-status">已通过</span>',
      rejected: '<span class="badge st-cancelled badge-status">已拒绝</span>' };
    const m = UI.modal({
      title: '密码重置申请', size: 'modal-lg', okText: '关闭', onOk: async () => { this.refreshResetBadge(); return true; },
      body: UI.table([
        { key: 'id', title: 'ID', width: '60px' },
        { key: 'username', title: '申请人', render: r => `${r.real_name || '-'} <span class="text-muted small">@${r.username}</span>` },
        { key: 'reason', title: '申请原因', render: r => r.reason || '-' },
        { key: 'status', title: '状态', render: r => stMap[r.status] || r.status },
        { key: 'handler_name', title: '处理人', render: r => r.handler_name || '-' },
        { key: 'create_time', title: '申请时间', render: r => fmtTime(r.create_time) },
        { title: '操作', render: r => r.status !== 'pending' ? '-' :
          `<button class="btn btn-sm btn-success" onclick="PAGES.users.handleReset(${r.id}, 'approve')">✓ 通过（重置为123456）</button>
           <button class="btn btn-sm btn-outline-danger" onclick="PAGES.users.handleReset(${r.id}, 'reject')">✕ 拒绝</button>` },
      ], res.data.list),
    });
    this._resetModal = m;
  },
  async handleReset(id, action) {
    const res = await API.post(`/auth/reset-requests/${id}/${action}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    UI.toast(res.msg);
    if (this._resetModal) { this._resetModal.inst.hide(); }
    this.resetRequests();
    this.refreshResetBadge();
  },
  async load(page = 1) {
    const kw = document.getElementById('u_kw')?.value || '';
    const res = await API.get(`/users?page=${page}&size=10&keyword=${encodeURIComponent(kw)}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    document.getElementById('u_list').innerHTML = UI.table([
      { key: 'id', title: 'ID', width: '60px' },
      { key: 'username', title: '用户名' },
      { key: 'real_name', title: '姓名' },
      { key: 'phone', title: '手机号' },
      { key: 'email', title: '邮箱' },
      { key: 'role_names', title: '角色', render: r => (r.role_names || '-').split(',').filter(Boolean).join('、') },
      { key: 'status', title: '状态', render: r => r.status === 1 ? '<span class="badge st-normal badge-status">启用</span>' : '<span class="badge st-cancelled badge-status">禁用</span>' },
      { title: '操作', render: r => `
        <button class="btn btn-sm btn-outline-primary" onclick="PAGES.users.edit(${r.id})">编辑</button>
        <button class="btn btn-sm btn-outline-warning" onclick="PAGES.users.resetPwd(${r.id})">重置密码</button>
        <button class="btn btn-sm btn-outline-danger" onclick="PAGES.users.del(${r.id})">删除</button>` },
    ], res.data.list);
    document.getElementById('u_page').innerHTML = UI.pagination(res.data.total, page, 10, 'PAGES.users.load');
  },
  async edit(id) {
    const [rolesRes, userRes] = await Promise.all([API.get('/roles'), id ? API.get(`/users`) : null]);
    const roles = rolesRes.data || [];
    let user = null;
    if (id) {
      const res = await API.get(`/users?page=1&size=100`);
      user = res.data.list.find(u => u.id === id);
    }
    const roleChecks = roles.map(r => `
      <div class="form-check">
        <input class="form-check-input" type="checkbox" name="role_ids" value="${r.id}" id="rl_${r.id}"
          ${user?.role_ids?.split(',').map(Number).includes(r.id) ? 'checked' : ''}>
        <label class="form-check-label" for="rl_${r.id}">${r.role_name} <span class="text-muted small">${r.description || ''}</span></label>
      </div>`).join('');
    const m = UI.modal({
      title: id ? '编辑用户' : '新增用户',
      body: UI.field('用户名', UI.input('username', user?.username || '')) +
        UI.field('姓名', UI.input('real_name', user?.real_name || '')) +
        UI.field('手机号', UI.input('phone', user?.phone || '')) +
        UI.field('邮箱', UI.input('email', user?.email || '')) +
        (id ? '' : UI.field('初始密码', UI.input('password', '123456'))) +
        UI.field('状态', UI.select('status', [[1, '启用'], [0, '禁用']], user?.status ?? 1)) +
        UI.field('分配角色', `<div style="max-height:160px;overflow:auto">${roleChecks || '<span class="text-muted">暂无角色</span>'}</div>`),
      okText: '保存',
      onOk: async () => {
        const d = UI.formData(m.id);
        d.role_ids = [...document.querySelectorAll(`#${m.id} [name=role_ids]:checked`)].map(c => Number(c.value));
        const res = id ? await API.put(`/users/${id}`, d) : await API.post('/users', d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('保存成功'); this.load(1); return true;
      },
    });
  },
  resetPwd(id) {
    UI.confirm('确定将该用户密码重置为 123456 吗？', async () => {
      const res = await API.post(`/users/${id}/reset-password`);
      if (res.code === 0) UI.toast('密码已重置为 123456'); else UI.toast(res.msg, 'error');
    });
  },
  del(id) {
    UI.confirm('确定删除该用户吗？删除后不可恢复。', async () => {
      const res = await API.delete(`/users/${id}`);
      if (res.code === 0) { UI.toast('删除成功'); this.load(1); } else UI.toast(res.msg, 'error');
    });
  },
};

/* ============ 角色权限 ============ */
PAGES.roles = {
  title: '角色权限管理',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span>角色列表（RBAC 权限模型）</span>
          <button class="btn btn-sm btn-primary" onclick="PAGES.roles.edit()">+ 新增角色</button>
        </div>
        <div class="card-body p-0" id="r_list"></div>
      </div>`;
    this.load();
  },
  async load() {
    const res = await API.get('/roles');
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    document.getElementById('r_list').innerHTML = UI.table([
      { key: 'id', title: 'ID', width: '60px' },
      { key: 'role_name', title: '角色名称' },
      { key: 'role_code', title: '角色编码' },
      { key: 'description', title: '描述' },
      { key: 'user_count', title: '用户数', render: r => `<span class="badge text-bg-light">${r.user_count} 人</span>` },
      { key: 'perm_ids', title: '权限数', render: r => `${(r.perm_ids || []).length} 项` },
      { title: '操作', render: r => `
        <button class="btn btn-sm btn-outline-primary" onclick="PAGES.roles.edit(${r.id})">编辑</button>
        <button class="btn btn-sm btn-outline-danger" onclick="PAGES.roles.del(${r.id})">删除</button>` },
    ], res.data);
  },
  async edit(id) {
    const [rolesRes, permsRes] = await Promise.all([API.get('/roles'), API.get('/permissions')]);
    const role = id ? rolesRes.data.find(r => r.id === id) : null;
    const permChecks = permsRes.data.map(p => `
      <div class="col-md-4 col-6"><div class="form-check">
        <input class="form-check-input" type="checkbox" name="perm_ids" value="${p.id}" id="pm_${p.id}"
          ${role?.perm_ids?.includes(p.id) ? 'checked' : ''}>
        <label class="form-check-label small" for="pm_${p.id}">${p.perm_name}<span class="text-muted mono"> ${p.perm_code}</span></label>
      </div></div>`).join('');
    const m = UI.modal({
      title: id ? '编辑角色' : '新增角色', size: 'modal-lg',
      body: UI.field('角色名称', UI.input('role_name', role?.role_name || '')) +
        UI.field('角色编码', UI.input('role_code', role?.role_code || '')) +
        UI.field('描述', UI.input('description', role?.description || '')) +
        UI.field('权限分配（可多选）', `<div class="row g-1 border rounded p-2" style="max-height:320px;overflow:auto">${permChecks}</div>`),
      okText: '保存',
      onOk: async () => {
        const d = UI.formData(m.id);
        d.perm_ids = [...document.querySelectorAll(`#${m.id} [name=perm_ids]:checked`)].map(c => Number(c.value));
        const res = id ? await API.put(`/roles/${id}`, d) : await API.post('/roles', d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('保存成功'); this.load(); return true;
      },
    });
  },
  del(id) {
    UI.confirm('确定删除该角色吗？', async () => {
      const res = await API.delete(`/roles/${id}`);
      if (res.code === 0) { UI.toast('删除成功'); this.load(); } else UI.toast(res.msg, 'error');
    });
  },
};

/* ============ 仓库管理 ============ */
PAGES.warehouses = {
  title: '仓库管理',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span>仓库列表（多仓库体系）</span>
          <button class="btn btn-sm btn-primary" onclick="PAGES.warehouses.edit()">+ 新增仓库</button>
        </div>
        <div class="card-body p-0" id="w_list"></div>
      </div>`;
    this.load();
  },
  async load() {
    const res = await API.get('/warehouses');
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const typeMap = { normal: '常温仓', cold: '冷藏仓', hazard: '危品仓' };
    document.getElementById('w_list').innerHTML = UI.table([
      { key: 'warehouse_code', title: '仓库编码', class: 'mono' },
      { key: 'warehouse_name', title: '仓库名称' },
      { key: 'type', title: '类型', render: r => typeMap[r.type] || r.type },
      { key: 'address', title: '地址' },
      { key: 'area', title: '面积(㎡)', render: r => Number(r.area).toLocaleString() },
      { key: 'area_count', title: '库区数' },
      { key: 'location_count', title: '库位数' },
      { key: 'status', title: '状态', render: r => r.status === 1 ? '<span class="badge st-normal badge-status">启用</span>' : '<span class="badge st-cancelled badge-status">停用</span>' },
      { title: '操作', render: r => `
        <button class="btn btn-sm btn-outline-primary" onclick="PAGES.warehouses.edit(${r.id})">编辑</button>
        <button class="btn btn-sm btn-outline-danger" onclick="PAGES.warehouses.del(${r.id})">删除</button>` },
    ], res.data);
  },
  edit(id) {
    const data = this._cache?.find(w => w.id === id);
    const m = UI.modal({
      title: id ? '编辑仓库' : '新增仓库',
      body: UI.field('仓库编码', UI.input('warehouse_code', data?.warehouse_code || '')) +
        UI.field('仓库名称', UI.input('warehouse_name', data?.warehouse_name || '')) +
        UI.field('地址', UI.input('address', data?.address || '')) +
        UI.field('类型', UI.select('type', [['normal', '常温仓'], ['cold', '冷藏仓'], ['hazard', '危品仓']], data?.type || 'normal')) +
        UI.field('面积(㎡)', UI.input('area', data?.area || 0, 'number')) +
        UI.field('状态', UI.select('status', [[1, '启用'], [0, '停用']], data?.status ?? 1)),
      onOk: async () => {
        const d = UI.formData(m.id);
        const res = id ? await API.put(`/warehouses/${id}`, d) : await API.post('/warehouses', d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('保存成功'); this.load(); return true;
      },
    });
  },
  async del(id) {
    UI.confirm('确定删除该仓库吗？', async () => {
      const res = await API.delete(`/warehouses/${id}`);
      if (res.code === 0) { UI.toast('删除成功'); this.load(); } else UI.toast(res.msg, 'error');
    });
  },
};
// 缓存仓库数据供编辑用
const _origWarehouseLoad = PAGES.warehouses.load.bind(PAGES.warehouses);
PAGES.warehouses.load = async function () {
  const res = await API.get('/warehouses');
  if (res.code !== 0) return UI.toast(res.msg, 'error');
  this._cache = res.data;
  return _origWarehouseLoad();
};

/* ============ 库区管理 ============ */
PAGES.areas = {
  title: '库区管理',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span>库区列表（存储/拣货/退货/收货区）</span>
          <button class="btn btn-sm btn-primary" onclick="PAGES.areas.edit()">+ 新增库区</button>
        </div>
        <div class="card-body p-0" id="a_list"></div>
      </div>`;
    const [areasRes, whRes] = await Promise.all([API.get('/areas'), API.get('/warehouses')]);
    this._wh = whRes.data || [];
    this._cache = areasRes.data || [];
    const typeMap = { storage: '存储区', picking: '拣货区', return: '退货区', receiving: '收货区' };
    document.getElementById('a_list').innerHTML = UI.table([
      { key: 'area_code', title: '库区编码', class: 'mono' },
      { key: 'area_name', title: '库区名称' },
      { key: 'warehouse_name', title: '所属仓库' },
      { key: 'type', title: '类型', render: r => typeMap[r.type] || r.type },
      { key: 'capacity', title: '容量' },
      { key: 'location_count', title: '库位数' },
      { title: '操作', render: r => `
        <button class="btn btn-sm btn-outline-primary" onclick="PAGES.areas.edit(${r.id})">编辑</button>
        <button class="btn btn-sm btn-outline-danger" onclick="PAGES.areas.del(${r.id})">删除</button>` },
    ], this._cache);
  },
  edit(id) {
    const data = id ? this._cache.find(a => a.id === id) : null;
    const whOpts = this._wh.map(w => [w.id, w.warehouse_name]);
    const m = UI.modal({
      title: id ? '编辑库区' : '新增库区',
      body: UI.field('所属仓库', UI.select('warehouse_id', whOpts, data?.warehouse_id)) +
        UI.field('库区编码', UI.input('area_code', data?.area_code || '')) +
        UI.field('库区名称', UI.input('area_name', data?.area_name || '')) +
        UI.field('类型', UI.select('type', [['storage', '存储区'], ['picking', '拣货区'], ['return', '退货区'], ['receiving', '收货区']], data?.type || 'storage')) +
        UI.field('容量', UI.input('capacity', data?.capacity || 0, 'number')),
      onOk: async () => {
        const d = UI.formData(m.id);
        const res = id ? await API.put(`/areas/${id}`, d) : await API.post('/areas', d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('保存成功'); loadPage('areas'); return true;
      },
    });
  },
  del(id) {
    UI.confirm('确定删除该库区吗？', async () => {
      const res = await API.delete(`/areas/${id}`);
      if (res.code === 0) { UI.toast('删除成功'); loadPage('areas'); } else UI.toast(res.msg, 'error');
    });
  },
};

/* ============ 库位管理 ============ */
PAGES.locations = {
  title: '库位管理',
  async render(el) {
    const whRes = await API.get('/warehouses');
    this._wh = whRes.data || [];
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <span>库位列表</span>
          <div class="d-flex gap-2 flex-wrap">
            <select class="form-select form-select-sm" id="l_wh" style="width:160px" onchange="PAGES.locations.load(1)">
              <option value="">全部仓库</option>
              ${this._wh.map(w => `<option value="${w.id}">${w.warehouse_name}</option>`).join('')}
            </select>
            <select class="form-select form-select-sm" id="l_st" style="width:120px" onchange="PAGES.locations.load(1)">
              <option value="">全部状态</option><option value="empty">空闲</option>
              <option value="occupied">占用</option><option value="locked">锁定</option>
            </select>
            <input class="form-control form-control-sm" id="l_kw" placeholder="库位编码" style="width:140px">
            <button class="btn btn-sm btn-outline-primary" onclick="PAGES.locations.load(1)">搜索</button>
            <button class="btn btn-sm btn-primary" onclick="PAGES.locations.edit()">+ 新增库位</button>
            <button class="btn btn-sm btn-success" onclick="PAGES.locations.batch()">⚡ 批量生成</button>
          </div>
        </div>
        <div class="card-body p-0" id="l_list"></div>
        <div class="card-footer bg-white" id="l_page"></div>
      </div>`;
    this.load(1);
  },
  async load(page = 1) {
    const wh = document.getElementById('l_wh')?.value || '';
    const st = document.getElementById('l_st')?.value || '';
    const kw = document.getElementById('l_kw')?.value || '';
    const res = await API.get(`/locations?page=${page}&size=15${wh ? `&warehouse_id=${wh}` : ''}${st ? `&status=${st}` : ''}&keyword=${encodeURIComponent(kw)}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._cache = res.data.list;
    const typeMap = { normal: '普通', heavy: '重型', temp: '温控' };
    document.getElementById('l_list').innerHTML = UI.table([
      { key: 'location_code', title: '库位编码', class: 'mono' },
      { key: 'warehouse_name', title: '仓库' },
      { key: 'area_name', title: '库区' },
      { key: 'type', title: '类型', render: r => typeMap[r.type] || r.type },
      { key: 'max_weight', title: '承重(kg)' },
      { key: 'max_volume', title: '容积(m³)' },
      { key: 'status', title: '状态', render: r => UI.statusBadge(r.status) },
      { title: '操作', render: r => `
        <button class="btn btn-sm btn-outline-primary" onclick="PAGES.locations.edit(${r.id})">编辑</button>
        <button class="btn btn-sm btn-outline-danger" onclick="PAGES.locations.del(${r.id})">删除</button>` },
    ], res.data.list);
    document.getElementById('l_page').innerHTML = UI.pagination(res.data.total, page, 15, 'PAGES.locations.load');
  },
  async edit(id) {
    const areasRes = await API.get('/areas');
    const data = id ? this._cache.find(l => l.id === id) : null;
    const areaOpts = areasRes.data.map(a => [a.id, `${a.warehouse_name} / ${a.area_name}`]);
    const m = UI.modal({
      title: id ? '编辑库位' : '新增库位',
      body: UI.field('所属库区', UI.select('area_id', areaOpts, data?.area_id)) +
        UI.field('库位编码', UI.input('location_code', data?.location_code || '')) +
        UI.field('类型', UI.select('type', [['normal', '普通'], ['heavy', '重型'], ['temp', '温控']], data?.type || 'normal')) +
        UI.field('最大承重(kg)', UI.input('max_weight', data?.max_weight ?? 500, 'number')) +
        UI.field('最大容积(m³)', UI.input('max_volume', data?.max_volume ?? 10, 'number')) +
        UI.field('状态', UI.select('status', [['empty', '空闲'], ['occupied', '占用'], ['locked', '锁定']], data?.status || 'empty')),
      onOk: async () => {
        const d = UI.formData(m.id);
        const res = id ? await API.put(`/locations/${id}`, d) : await API.post('/locations', d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('保存成功'); this.load(1); return true;
      },
    });
  },
  async batch() {
    const areasRes = await API.get('/areas');
    const areaOpts = areasRes.data.map(a => [a.id, `${a.warehouse_name} / ${a.area_name}`]);
    const m = UI.modal({
      title: '批量生成库位',
      body: UI.field('所属库区', UI.select('area_id', areaOpts)) +
        UI.field('库位编码前缀', UI.input('prefix', 'AUTO')) +
        `<div class="row g-2">
          <div class="col-6">${UI.field('排数', UI.input('rows', 3, 'number', 'min=1 max=9'))}</div>
          <div class="col-6">${UI.field('每排列数', UI.input('cols', 10, 'number', 'min=1 max=20'))}</div>
        </div>` +
        UI.field('库位类型', UI.select('type', [['normal', '普通'], ['heavy', '重型'], ['temp', '温控']])),
      okText: '生成',
      onOk: async () => {
        const d = UI.formData(m.id);
        const res = await API.post('/locations/batch', d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast(res.msg); this.load(1); return true;
      },
    });
  },
  del(id) {
    UI.confirm('确定删除该库位吗？', async () => {
      const res = await API.delete(`/locations/${id}`);
      if (res.code === 0) { UI.toast('删除成功'); this.load(1); } else UI.toast(res.msg, 'error');
    });
  },
};

/* ============ 商品档案 ============ */
PAGES.products = {
  title: '商品档案',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <span>商品列表（SKU / 批次管理）</span>
          <div class="d-flex gap-2 flex-wrap">
            <input class="form-control form-control-sm" id="p_kw" placeholder="名称/SKU/条码" style="width:180px">
            <button class="btn btn-sm btn-outline-primary" onclick="PAGES.products.load(1)">搜索</button>
            <button class="btn btn-sm btn-primary" onclick="PAGES.products.edit()">+ 新增商品</button>
          </div>
        </div>
        <div class="card-body p-0" id="p_list"></div>
        <div class="card-footer bg-white" id="p_page"></div>
      </div>`;
    this.load(1);
  },
  async load(page = 1) {
    const kw = document.getElementById('p_kw')?.value || '';
    const res = await API.get(`/products?page=${page}&size=10&keyword=${encodeURIComponent(kw)}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._cache = res.data.list;
    document.getElementById('p_list').innerHTML = UI.table([
      { key: 'sku', title: 'SKU', class: 'mono' },
      { key: 'barcode', title: '条码', class: 'mono' },
      { key: 'product_name', title: '商品名称' },
      { key: 'category', title: '分类' },
      { key: 'unit', title: '单位' },
      { key: 'price', title: '单价(元)' },
      { key: 'shelf_life', title: '保质期', render: r => r.shelf_life ? `${r.shelf_life}天` : '不限' },
      { key: 'is_batch_managed', title: '批次管理', render: r => r.is_batch_managed ? '✅' : '—' },
      { key: 'min_stock', title: '安全库存' },
      { key: 'supplier_name', title: '默认供应商', render: r => r.supplier_name ? csEscape(r.supplier_name) : '<span class="text-muted">未指定</span>' },
      { key: 'stock_qty', title: '在库量', render: r => `<b>${r.stock_qty}</b> / 可用 <span class="text-primary">${r.available_qty}</span>` },
      { title: '操作', render: r => `
        <button class="btn btn-sm btn-outline-primary" onclick="PAGES.products.edit(${r.id})">编辑</button>
        <button class="btn btn-sm btn-outline-danger" onclick="PAGES.products.del(${r.id})">删除</button>` },
    ], res.data.list);
    document.getElementById('p_page').innerHTML = UI.pagination(res.data.total, page, 10, 'PAGES.products.load');
  },
  async edit(id) {
    const data = id ? this._cache.find(p => p.id === id) : null;
    const supRes = await API.get('/suppliers');
    const suppliers = supRes.code === 0 ? supRes.data : [];
    const m = UI.modal({
      title: id ? '编辑商品' : '新增商品', size: 'modal-lg',
      body: `<div class="row g-2">
        <div class="col-md-6">${UI.field('SKU编码', UI.input('sku', data?.sku || ''))}</div>
        <div class="col-md-6">${UI.field('条码', UI.input('barcode', data?.barcode || ''))}</div>
        <div class="col-md-6">${UI.field('商品名称', UI.input('product_name', data?.product_name || ''))}</div>
        <div class="col-md-3">${UI.field('分类', UI.input('category', data?.category || ''))}</div>
        <div class="col-md-3">${UI.field('单位', UI.input('unit', data?.unit || '件'))}</div>
        <div class="col-md-3">${UI.field('重量(kg)', UI.input('weight', data?.weight ?? 0, 'number', 'step=0.001'))}</div>
        <div class="col-md-3">${UI.field('体积(m³)', UI.input('volume', data?.volume ?? 0, 'number', 'step=0.0001'))}</div>
        <div class="col-md-3">${UI.field('单价(元)', UI.input('price', data?.price ?? 0, 'number', 'step=0.01'))}</div>
        <div class="col-md-3">${UI.field('保质期(天)', UI.input('shelf_life', data?.shelf_life ?? 0, 'number'))}</div>
        <div class="col-md-3">${UI.field('安全库存', UI.input('min_stock', data?.min_stock ?? 0, 'number'))}</div>
        <div class="col-md-3">${UI.field('库存上限', UI.input('max_stock', data?.max_stock ?? 0, 'number'))}</div>
        <div class="col-md-6">${UI.field('默认供应商', UI.select('supplier_id',
          [[null, '未指定（补货清单归入未指定组）'], ...suppliers.map(s => [s.id, `${s.supplier_name}（${s.supplier_code}）`])],
          data?.supplier_id ?? null))}</div>
        <div class="col-md-3">${UI.field('是否批次管理', UI.select('is_batch_managed', [[1, '是'], [0, '否']], data?.is_batch_managed ?? 1))}</div>
        <div class="col-md-3">${UI.field('状态', UI.select('status', [[1, '启用'], [0, '停用']], data?.status ?? 1))}</div>
      </div>`,
      onOk: async () => {
        const d = UI.formData(m.id);
        const res = id ? await API.put(`/products/${id}`, d) : await API.post('/products', d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('保存成功'); this.load(1); return true;
      },
    });
  },
  del(id) {
    UI.confirm('确定删除该商品吗？', async () => {
      const res = await API.delete(`/products/${id}`);
      if (res.code === 0) { UI.toast('删除成功'); this.load(1); } else UI.toast(res.msg, 'error');
    });
  },
};

/* ============ 供应商 / 客户 ============ */
function partnerPage(kind) {
  const apiPath = kind === 'supplier' ? 'suppliers' : 'customers';
  const codeField = kind === 'supplier' ? 'supplier_code' : 'customer_code';
  const nameField = kind === 'supplier' ? 'supplier_name' : 'customer_name';
  return {
    async render(el) {
      el.innerHTML = `
        <div class="card">
          <div class="card-header d-flex justify-content-between align-items-center">
            <span>${kind === 'supplier' ? '供应商' : '客户'}列表</span>
            <div class="d-flex gap-2">
              <input class="form-control form-control-sm" id="pt_kw" placeholder="搜索编码/名称" style="width:180px">
              <button class="btn btn-sm btn-outline-primary" onclick="PAGES.${apiPath}.load()">搜索</button>
              <button class="btn btn-sm btn-primary" onclick="PAGES.${apiPath}.edit()">+ 新增</button>
            </div>
          </div>
          <div class="card-body p-0" id="pt_list"></div>
        </div>`;
      this.load();
    },
    async load() {
      const kw = document.getElementById('pt_kw')?.value || '';
      const res = await API.get(`/${apiPath}?keyword=${encodeURIComponent(kw)}`);
      if (res.code !== 0) return UI.toast(res.msg, 'error');
      this._cache = res.data;
      const cntField = kind === 'supplier' ? 'inbound_count' : 'outbound_count';
      document.getElementById('pt_list').innerHTML = UI.table([
        { key: codeField, title: '编码', class: 'mono' },
        { key: nameField, title: '名称' },
        { key: 'contact', title: '联系人' },
        { key: 'phone', title: '电话' },
        { key: 'address', title: '地址' },
        { key: cntField, title: kind === 'supplier' ? '入库单数' : '出库单数' },
        { key: 'status', title: '状态', render: r => r.status === 1 ? '<span class="badge st-normal badge-status">启用</span>' : '<span class="badge st-cancelled badge-status">停用</span>' },
        { title: '操作', render: r => `
          <button class="btn btn-sm btn-outline-primary" onclick="PAGES.${apiPath}.edit(${r.id})">编辑</button>
          <button class="btn btn-sm btn-outline-danger" onclick="PAGES.${apiPath}.del(${r.id})">删除</button>` },
      ], res.data);
    },
    edit(id) {
      const data = id ? this._cache.find(p => p.id === id) : null;
      const m = UI.modal({
        title: id ? '编辑' : '新增',
        body: UI.field('编码', UI.input('code', data?.[codeField] || '')) +
          UI.field('名称', UI.input('name', data?.[nameField] || '')) +
          UI.field('联系人', UI.input('contact', data?.contact || '')) +
          UI.field('电话', UI.input('phone', data?.phone || '')) +
          UI.field('地址', UI.input('address', data?.address || '')) +
          UI.field('状态', UI.select('status', [[1, '启用'], [0, '停用']], data?.status ?? 1)),
        onOk: async () => {
          const d = UI.formData(m.id);
          const res = id ? await API.put(`/${apiPath}/${id}`, d) : await API.post(`/${apiPath}`, d);
          if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
          UI.toast('保存成功'); this.load(); return true;
        },
      });
    },
    del(id) {
      UI.confirm('确定删除吗？', async () => {
        const res = await API.delete(`/${apiPath}/${id}`);
        if (res.code === 0) { UI.toast('删除成功'); this.load(); } else UI.toast(res.msg, 'error');
      });
    },
  };
}
PAGES.suppliers = { title: '供应商管理', ...partnerPage('supplier') };
PAGES.customers = { title: '客户管理', ...partnerPage('customer') };
