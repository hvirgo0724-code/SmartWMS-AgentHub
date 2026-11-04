/* 库存管理页面：实时库存 / 库存流水 / 调整记录 / 盘点 / 批次效期 */
PAGES.inventory = {
  title: '实时库存',
  async render(el) {
    const whRes = await API.get('/warehouses');
    this._wh = whRes.data || [];
    el.innerHTML = `
      <div class="card mb-3">
        <div class="card-body py-2">
          <div class="d-flex gap-2 flex-wrap align-items-center">
            <select class="form-select form-select-sm" id="iv_wh" style="width:160px" onchange="PAGES.inventory.load(1)">
              <option value="">全部仓库</option>
              ${this._wh.map(w => `<option value="${w.id}">${w.warehouse_name}</option>`).join('')}
            </select>
            <select class="form-select form-select-sm" id="iv_st" style="width:110px" onchange="PAGES.inventory.load(1)">
              <option value="">全部状态</option><option value="normal">正常</option><option value="frozen">冻结</option>
            </select>
            <input class="form-control form-control-sm" id="iv_kw" placeholder="商品/SKU/库位" style="width:170px">
            <button class="btn btn-sm btn-outline-primary" onclick="PAGES.inventory.load(1)">搜索</button>
          </div>
        </div>
      </div>
      <div class="row mb-3" id="iv_summary"></div>
      <div class="card">
        <div class="card-body p-0" id="iv_list"></div>
        <div class="card-footer bg-white" id="iv_page"></div>
      </div>`;
    this.load(1);
  },
  async load(page = 1) {
    const wh = document.getElementById('iv_wh')?.value || '';
    const st = document.getElementById('iv_st')?.value || '';
    const kw = document.getElementById('iv_kw')?.value || '';
    const res = await API.get(`/inventory?page=${page}&size=15${wh ? `&warehouse_id=${wh}` : ''}${st ? `&status=${st}` : ''}&keyword=${encodeURIComponent(kw)}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._cache = res.data.list;
    const s = res.data.summary || {};
    document.getElementById('iv_summary').innerHTML = `
      <div class="col-md-4"><div class="card kpi-card"><div class="card-body py-2 d-flex align-items-center gap-3">
        <div class="kpi-icon bg-primary bg-opacity-10">📦</div>
        <div><div class="kpi-value">${Number(s.qty || 0).toLocaleString()}</div><div class="kpi-label">在库总量</div></div>
      </div></div></div>
      <div class="col-md-4"><div class="card kpi-card"><div class="card-body py-2 d-flex align-items-center gap-3">
        <div class="kpi-icon bg-success bg-opacity-10">✅</div>
        <div><div class="kpi-value">${Number(s.avail || 0).toLocaleString()}</div><div class="kpi-label">可用库存</div></div>
      </div></div></div>
      <div class="col-md-4"><div class="card kpi-card"><div class="card-body py-2 d-flex align-items-center gap-3">
        <div class="kpi-icon bg-warning bg-opacity-10">🔒</div>
        <div><div class="kpi-value">${Number(s.locked || 0).toLocaleString()}</div><div class="kpi-label">锁定库存</div></div>
      </div></div></div>`;
    document.getElementById('iv_list').innerHTML = UI.table([
      { key: 'sku', title: 'SKU', class: 'mono' },
      { key: 'product_name', title: '商品' },
      { key: 'warehouse_name', title: '仓库' },
      { key: 'location_code', title: '库位', class: 'mono' },
      { key: 'batch_no', title: '批次号', render: r => r.batch_no ? `<span class="mono">${r.batch_no}</span>` : '-' },
      { key: 'quantity', title: '在库量', render: r => `<b>${r.quantity}</b>` },
      { key: 'locked_qty', title: '锁定', render: r => r.locked_qty ? `<span class="text-warning">${r.locked_qty}</span>` : '0' },
      { key: 'available_qty', title: '可用', render: r => `<span class="text-primary fw-bold">${r.available_qty}</span>` },
      { key: 'status', title: '状态', render: r => UI.statusBadge(r.status) },
      { key: 'stock_value', title: '货值(元)', render: r => Number(r.stock_value).toLocaleString() },
      { title: '操作', render: r => `
        <button class="btn btn-sm btn-outline-primary" onclick="PAGES.inventory.move(${r.id})">移动</button>
        <button class="btn btn-sm btn-outline-warning" onclick="PAGES.inventory.adjust(${r.id})">调整</button>
        ${r.status === 'normal'
          ? `<button class="btn btn-sm btn-outline-secondary" onclick="PAGES.inventory.freeze(${r.id},'freeze')">冻结</button>`
          : `<button class="btn btn-sm btn-outline-success" onclick="PAGES.inventory.freeze(${r.id},'unfreeze')">解冻</button>`}` },
    ], res.data.list);
    document.getElementById('iv_page').innerHTML = UI.pagination(res.data.total, page, 15, 'PAGES.inventory.load');
  },
  async move(id) {
    const inv = this._cache.find(i => i.id === id);
    const locRes = await API.get(`/locations?warehouse_id=${inv.warehouse_id}&size=500`);
    const locOpts = locRes.data.list.map(l => [l.id, `${l.location_code}（${l.status === 'empty' ? '空闲' : l.status === 'occupied' ? '占用' : '锁定'}）`]);
    const m = UI.modal({
      title: `库存移动 · ${inv.product_name} @ ${inv.location_code}`,
      body: `
        <div class="alert alert-info py-2 small">当前在库 <b>${inv.quantity}</b>，移动将生成移库流水并更新两个库位的库存与状态。</div>` +
        UI.field('目标库位', UI.select('to_location_id', locOpts)) +
        UI.field(`移动数量（1~${inv.quantity}）`, UI.input('quantity', 1, 'number', `min=1 max=${inv.quantity}`)),
      okText: '确认移动',
      onOk: async () => {
        const d = UI.formData(m.id);
        const res = await API.post('/inventory/move', { inventory_id: id, ...d });
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('移动成功'); this.load(1); return true;
      },
    });
  },
  adjust(id) {
    const inv = this._cache.find(i => i.id === id);
    const m = UI.modal({
      title: `库存调整 · ${inv.product_name} @ ${inv.location_code}`,
      body: `
        <div class="alert alert-info py-2 small">当前在库 <b>${inv.quantity}</b>（锁定 ${inv.locked_qty}）。正数为盘盈、负数为盘亏，调整将生成调整单与流水记录。</div>` +
        UI.field('调整数量（±）', UI.input('adjust_qty', 0, 'number')) +
        UI.field('调整原因', UI.select('reason', [['manual', '手动调整'], ['surplus', '盘盈'], ['loss', '盘亏'], ['damage', '破损'], ['expiry', '过期']])),
      okText: '确认调整',
      onOk: async () => {
        const d = UI.formData(m.id);
        if (!d.adjust_qty) { UI.toast('调整数量不能为0', 'error'); return false; }
        const res = await API.post('/inventory/adjust', { inventory_id: id, ...d });
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('调整成功'); this.load(1); return true;
      },
    });
  },
  freeze(id, action) {
    UI.confirm(`确定${action === 'freeze' ? '冻结' : '解冻'}该库存记录吗？冻结库存不可出库。`, async () => {
      const res = await API.post('/inventory/freeze', { inventory_ids: [id], action });
      if (res.code === 0) { UI.toast(res.msg); this.load(1); } else UI.toast(res.msg, 'error');
    }, false);
  },
};

PAGES.moves = {
  title: '库存流水',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span>库存移动流水（入库/出库/移动/调整/盘点）</span>
          <select class="form-select form-select-sm" id="mv_type" style="width:140px" onchange="PAGES.moves.load(1)">
            <option value="">全部类型</option><option value="inbound">入库</option>
            <option value="outbound">出库</option><option value="move">移动</option>
            <option value="adjust">调整</option><option value="check">盘点</option>
          </select>
        </div>
        <div class="card-body p-0" id="mv_list"></div>
        <div class="card-footer bg-white" id="mv_page"></div>
      </div>`;
    this.load(1);
  },
  async load(page = 1) {
    const t = document.getElementById('mv_type')?.value || '';
    const res = await API.get(`/inventory/moves?page=${page}&size=15&move_type=${t}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const typeMap = { inbound: '<span class="badge st-completed badge-status">入库</span>',
      outbound: '<span class="badge st-shipped badge-status">出库</span>',
      move: '<span class="badge st-approved badge-status">移动</span>',
      adjust: '<span class="badge st-pending badge-status">调整</span>',
      check: '<span class="badge st-locked badge-status">盘点</span>' };
    document.getElementById('mv_list').innerHTML = UI.table([
      { key: 'move_type', title: '类型', render: r => typeMap[r.move_type] || r.move_type },
      { key: 'sku', title: 'SKU', class: 'mono' },
      { key: 'product_name', title: '商品' },
      { key: 'batch_no', title: '批次', render: r => r.batch_no ? `<span class="mono">${r.batch_no}</span>` : '-' },
      { key: 'from_loc', title: '源库位', render: r => r.from_loc ? `<span class="mono">${r.from_loc}</span>` : '-' },
      { key: 'to_loc', title: '目标库位', render: r => r.to_loc ? `<span class="mono">${r.to_loc}</span>` : '-' },
      { key: 'quantity', title: '数量', render: r => `<b>${r.quantity}</b>` },
      { key: 'ref_no', title: '关联单号', render: r => r.ref_no ? `<span class="mono">${r.ref_no}</span>` : '-' },
      { key: 'operator', title: '操作人' },
      { key: 'create_time', title: '时间', render: r => fmtTime(r.create_time) },
    ], res.data.list);
    document.getElementById('mv_page').innerHTML = UI.pagination(res.data.total, page, 15, 'PAGES.moves.load');
  },
};

PAGES.adjustments = {
  title: '库存调整记录',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header">库存调整记录（盘盈/盘亏/手动/破损/过期）</div>
        <div class="card-body p-0" id="adj_list"></div>
      </div>`;
    const res = await API.get('/adjustments');
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const reasonMap = { check: '盘点', surplus: '盘盈', loss: '盘亏', damage: '破损', expiry: '过期', manual: '手动' };
    document.getElementById('adj_list').innerHTML = UI.table([
      { key: 'adjust_no', title: '调整单号', class: 'mono' },
      { key: 'warehouse_name', title: '仓库' },
      { key: 'sku', title: 'SKU', class: 'mono' },
      { key: 'product_name', title: '商品' },
      { key: 'location_code', title: '库位', class: 'mono' },
      { key: 'batch_no', title: '批次', render: r => r.batch_no ? `<span class="mono">${r.batch_no}</span>` : '-' },
      { key: 'before_qty', title: '调整前' },
      { key: 'after_qty', title: '调整后' },
      { key: 'diff_qty', title: '差异', render: r => `<span class="${r.diff_qty > 0 ? 'text-success' : 'text-danger'} fw-bold">${r.diff_qty > 0 ? '+' : ''}${r.diff_qty}</span>` },
      { key: 'reason', title: '原因', render: r => reasonMap[r.reason] || r.reason },
      { key: 'operator', title: '操作人' },
      { key: 'create_time', title: '时间', render: r => fmtTime(r.create_time) },
    ], res.data);
  },
};

PAGES.checks = {
  title: '盘点管理',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span>盘点单（循环盘点 / 全盘，支持盲盘）</span>
          <button class="btn btn-sm btn-primary" onclick="PAGES.checks.create()">+ 创建盘点单</button>
        </div>
        <div class="card-body p-0" id="ck_list"></div>
      </div>`;
    this.load();
  },
  async load() {
    const res = await API.get('/check-orders');
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._cache = res.data;
    const typeMap = { cycle: '循环盘点', dynamic: '动态盘点', full: '全盘' };
    document.getElementById('ck_list').innerHTML = UI.table([
      { key: 'check_no', title: '盘点单号', class: 'mono' },
      { key: 'warehouse_name', title: '仓库' },
      { key: 'area_name', title: '库区', render: r => r.area_name || '全仓' },
      { key: 'type', title: '类型', render: r => typeMap[r.type] || r.type },
      { key: 'blind', title: '盲盘', render: r => r.blind ? '是' : '否' },
      { key: 'detail_count', title: '盘点项' },
      { key: 'diff_count', title: '差异数', render: r => r.diff_count ? `<span class="text-danger fw-bold">${r.diff_count}</span>` : '0' },
      { key: 'status', title: '状态', render: r => UI.statusBadge(r.status) },
      { key: 'operator', title: '盘点人' },
      { key: 'end_time', title: '完成时间', render: r => fmtTime(r.end_time) },
      { title: '操作', render: r => `
        ${r.status === 'checking' ? `<button class="btn btn-sm btn-success" onclick="PAGES.checks.submit(${r.id})">录入结果</button>` : ''}
        <button class="btn btn-sm btn-outline-secondary" onclick="PAGES.checks.detail(${r.id})">查看</button>` },
    ], res.data);
  },
  async create() {
    const whRes = await API.get('/warehouses');
    const whOpts = whRes.data.map(w => [w.id, w.warehouse_name]);
    const m = UI.modal({
      title: '创建盘点单',
      body: `
        <div class="alert alert-info py-2 small">创建盘点单将按当前库存快照生成盘点明细；提交结果后差异自动生成调整单并同步库存。</div>` +
        UI.field('仓库', UI.select('warehouse_id', whOpts)) +
        UI.field('盘点类型', UI.select('type', [['cycle', '循环盘点'], ['dynamic', '动态盘点'], ['full', '全盘']])) +
        UI.field('盲盘（隐藏账面数量）', UI.select('blind', [[0, '明盘'], [1, '盲盘']])),
      okText: '创建',
      onOk: async () => {
        const d = UI.formData(m.id);
        const res = await API.post('/check-orders', d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast(res.msg); this.load(); return true;
      },
    });
  },
  async detail(id) {
    const res = await API.get(`/check-orders/${id}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const o = res.data;
    UI.modal({
      title: `盘点单 · ${o.check_no}`,
      body: `
        <table class="table table-sm detail-table">
          <thead><tr><th>库位</th><th>SKU</th><th>商品</th><th>批次</th><th>账面数量</th><th>实盘数量</th><th>差异</th></tr></thead>
          <tbody>${o.details.map(d => `<tr>
            <td class="mono">${d.location_code || '-'}</td><td class="mono">${d.sku}</td><td>${d.product_name}</td>
            <td class="mono">${d.batch_no || '-'}</td><td>${d.book_qty}</td>
            <td>${d.actual_qty ?? '-'}</td>
            <td>${d.diff_qty == null ? '-' : (d.diff_qty === 0 ? '0' : `<span class="${d.diff_qty > 0 ? 'text-success' : 'text-danger'} fw-bold">${d.diff_qty > 0 ? '+' : ''}${d.diff_qty}</span>`)}</td>
          </tr>`).join('')}</tbody>
        </table>`,
    });
  },
  async submit(id) {
    const res = await API.get(`/check-orders/${id}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const o = res.data;
    const rows = o.details.map(d => `
      <tr>
        <td class="mono">${d.location_code || '-'}</td><td>${d.sku}</td><td>${d.product_name}</td>
        <td>${o.blind ? '***' : d.book_qty}</td>
        <td><input class="form-control form-control-sm" name="ac_${d.id}" type="number" min="0" value="${d.book_qty}" style="width:90px"></td>
      </tr>`).join('');
    const m = UI.modal({
      title: `盘点结果录入 · ${o.check_no}（${o.blind ? '盲盘' : '明盘'}）`, size: 'modal-lg',
      body: `
        <div class="alert alert-info py-2 small">录入实盘数量后提交，差异项将自动生成库存调整单并同步更新库存。</div>
        <div style="max-height:400px;overflow:auto">
        <table class="table table-sm detail-table">
          <thead><tr><th>库位</th><th>SKU</th><th>商品</th><th>账面数量</th><th>实盘数量</th></tr></thead>
          <tbody>${rows}</tbody>
        </table></div>`,
      okText: '提交盘点结果',
      onOk: async () => {
        const actuals = {};
        o.details.forEach(d => {
          actuals[d.id] = Number(document.querySelector(`#${m.id} [name=ac_${d.id}]`).value);
        });
        const res = await API.post(`/check-orders/${id}/submit`, { actuals });
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast(res.msg); this.load(); return true;
      },
    });
  },
};

PAGES.batches = {
  title: '批次效期管理',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span>批次效期跟踪（先进先出推荐）</span>
          <select class="form-select form-select-sm" id="bt_days" style="width:180px" onchange="PAGES.batches.load()">
            <option value="0">全部批次</option>
            <option value="30">30天内到期</option>
            <option value="15">15天内到期</option>
            <option value="7">7天内到期</option>
          </select>
        </div>
        <div class="card-body p-0" id="bt_list"></div>
      </div>`;
    this.load();
  },
  async load() {
    const days = document.getElementById('bt_days')?.value || 0;
    const res = await API.get(`/batches?expiring_days=${days}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    document.getElementById('bt_list').innerHTML = UI.table([
      { key: 'sku', title: 'SKU', class: 'mono' },
      { key: 'product_name', title: '商品' },
      { key: 'batch_no', title: '批次号', class: 'mono' },
      { key: 'production_date', title: '生产日期', render: r => fmtDate(r.production_date) },
      { key: 'expiry_date', title: '到期日', render: r => fmtDate(r.expiry_date) },
      { key: 'shelf_life', title: '保质期(天)' },
      { key: 'stock_qty', title: '在库量', render: r => `<b>${r.stock_qty}</b>` },
      { key: 'days_left', title: '剩余天数', render: r => {
          if (r.days_left == null) return '<span class="text-muted">不限</span>';
          if (r.days_left < 0) return '<span class="badge text-bg-danger">已过期</span>';
          if (r.days_left <= 30) return `<span class="badge text-bg-warning">${r.days_left} 天 ⚠️</span>`;
          return `<span class="text-success">${r.days_left} 天</span>`;
        } },
    ], res.data);
  },
};
