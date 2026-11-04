/* 入库管理页面：收货通知ASN / 入库单 / 质检 */
PAGES.asn = {
  title: '收货通知（ASN）',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span>预到货通知列表（可一键转入库单）</span>
          <button class="btn btn-sm btn-primary" onclick="PAGES.asn.edit()">+ 新建收货通知</button>
        </div>
        <div class="card-body p-0" id="asn_list"></div>
      </div>`;
    this.load();
  },
  async load() {
    const res = await API.get('/asn');
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._cache = res.data;
    document.getElementById('asn_list').innerHTML = UI.table([
      { key: 'asn_no', title: 'ASN单号', class: 'mono' },
      { key: 'warehouse_name', title: '目标仓库' },
      { key: 'supplier_name', title: '供应商' },
      { key: 'items', title: '商品数', render: r => (r.items || []).length },
      { key: 'items', title: '总数量', render: r => (r.items || []).reduce((s, i) => s + i.quantity, 0) },
      { key: 'expected_time', title: '预计到货', render: r => fmtTime(r.expected_time) },
      { key: 'status', title: '状态', render: r => UI.statusBadge(r.status) },
      { title: '操作', render: r => r.status === 'pending' ? `
        <button class="btn btn-sm btn-success" onclick="PAGES.asn.toInbound(${r.id})">转入库单</button>
        <button class="btn btn-sm btn-outline-danger" onclick="PAGES.asn.cancel(${r.id})">取消</button>` : '-' },
    ], res.data);
  },
  async edit() {
    const [whRes, supRes, prodRes] = await Promise.all([
      API.get('/warehouses'), API.get('/suppliers'), API.get('/products?page=1&size=100')]);
    const whOpts = whRes.data.map(w => [w.id, w.warehouse_name]);
    const supOpts = [[null, '不指定']].concat(supRes.data.map(s => [s.id, s.supplier_name]));
    const prodOpts = prodRes.data.list.map(p => [p.id, `${p.sku} ${p.product_name}`]);
    const m = UI.modal({
      title: '新建收货通知', size: 'modal-lg',
      body: `<div class="row g-2">
        <div class="col-md-4">${UI.field('目标仓库', UI.select('warehouse_id', whOpts))}</div>
        <div class="col-md-4">${UI.field('供应商', UI.select('supplier_id', supOpts))}</div>
        <div class="col-md-4">${UI.field('预计到货时间', UI.input('expected_time', '', 'datetime-local'))}</div>
      </div>
      <div class="mb-2 fw-semibold">商品明细</div>
      <div id="asn_items"></div>
      <button class="btn btn-sm btn-outline-secondary" onclick="PAGES.asn.addItem(prodOptsGlobal)">+ 添加明细</button>`,
      okText: '创建',
      onOk: async () => {
        const d = UI.formData(m.id);
        d.items = [...document.querySelectorAll(`#${m.id} .asn-row`)].map(row => ({
          product_id: Number(row.querySelector('[name=product_id]').value),
          quantity: Number(row.querySelector('[name=quantity]').value),
        })).filter(i => i.product_id && i.quantity > 0);
        if (!d.items.length) { UI.toast('请添加至少一条明细', 'error'); return false; }
        const res = await API.post('/asn', d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('收货通知创建成功'); this.load(); return true;
      },
    });
    window.prodOptsGlobal = prodOpts;
    this.addItem(prodOpts);
  },
  addItem(prodOpts) {
    const row = document.createElement('div');
    row.className = 'asn-row d-flex gap-2 mb-2';
    row.innerHTML = `
      <select class="form-select form-select-sm" name="product_id" style="flex:2">${prodOpts.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</select>
      <input class="form-control form-control-sm" name="quantity" type="number" min="1" value="50" style="flex:1" placeholder="数量">
      <button class="btn btn-sm btn-outline-danger" onclick="this.parentElement.remove()">✕</button>`;
    document.getElementById('asn_items').appendChild(row);
  },
  toInbound(id) {
    UI.confirm('将此收货通知转为入库单？系统将自动生成批次号。', async () => {
      const res = await API.post(`/asn/${id}/to-inbound`);
      if (res.code === 0) { UI.toast(res.msg); loadPage('inbound'); }
      else UI.toast(res.msg, 'error');
    }, false);
  },
  cancel(id) {
    UI.confirm('确定取消该收货通知吗？', async () => {
      const res = await API.post(`/asn/${id}/cancel`);
      if (res.code === 0) { UI.toast('已取消'); this.load(); } else UI.toast(res.msg, 'error');
    });
  },
};

PAGES.inbound = {
  title: '入库单管理',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <span>入库单列表</span>
          <div class="d-flex gap-2 flex-wrap">
            <select class="form-select form-select-sm" id="ib_st" style="width:120px" onchange="PAGES.inbound.load(1)">
              <option value="">全部状态</option><option value="pending">待审核</option>
              <option value="approved">已审核</option><option value="completed">已入库</option>
              <option value="cancelled">已取消</option>
            </select>
            <input class="form-control form-control-sm" id="ib_kw" placeholder="单号/供应商" style="width:160px">
            <button class="btn btn-sm btn-outline-primary" onclick="PAGES.inbound.load(1)">搜索</button>
            <button class="btn btn-sm btn-primary" onclick="PAGES.inbound.create()">+ 新建入库单</button>
          </div>
        </div>
        <div class="card-body p-0" id="ib_list"></div>
        <div class="card-footer bg-white" id="ib_page"></div>
      </div>
      <div id="ib_detail"></div>`;
    this.load(1);
  },
  async load(page = 1) {
    const st = document.getElementById('ib_st')?.value || '';
    const kw = document.getElementById('ib_kw')?.value || '';
    const res = await API.get(`/inbound-orders?page=${page}&size=10&status=${st}&keyword=${encodeURIComponent(kw)}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._cache = res.data.list;
    document.getElementById('ib_list').innerHTML = UI.table([
      { key: 'order_no', title: '入库单号', class: 'mono' },
      { key: 'warehouse_name', title: '仓库' },
      { key: 'supplier_name', title: '供应商' },
      { key: 'expected_time', title: '预计到货', render: r => fmtTime(r.expected_time) },
      { key: 'actual_time', title: '实际入库', render: r => fmtTime(r.actual_time) },
      { key: 'operator', title: '操作员' },
      { key: 'status', title: '状态', render: r => UI.statusBadge(r.status) },
      { title: '操作', render: r => `
        <button class="btn btn-sm btn-outline-secondary" onclick="PAGES.inbound.detail(${r.id})">明细</button>
        ${r.status === 'pending' ? `<button class="btn btn-sm btn-outline-primary" onclick="PAGES.inbound.approve(${r.id})">审核</button>` : ''}
        ${['pending', 'approved'].includes(r.status) ? `<button class="btn btn-sm btn-success" onclick="PAGES.inbound.confirm(${r.id})">确认入库</button>
          <button class="btn btn-sm btn-outline-danger" onclick="PAGES.inbound.cancel(${r.id})">取消</button>` : ''}` },
    ], res.data.list);
    document.getElementById('ib_page').innerHTML = UI.pagination(res.data.total, page, 10, 'PAGES.inbound.load');
  },
  async detail(id) {
    const res = await API.get(`/inbound-orders/${id}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const o = res.data;
    UI.modal({
      title: `入库单明细 · ${o.order_no}`,
      body: `
        <div class="row small mb-3 g-2">
          <div class="col-md-3"><b>仓库：</b>${o.warehouse_name}</div>
          <div class="col-md-3"><b>供应商：</b>${o.supplier_name || '-'}</div>
          <div class="col-md-3"><b>状态：</b>${UI.statusBadge(o.status)}</div>
          <div class="col-md-3"><b>操作员：</b>${o.operator || '-'}</div>
        </div>
        <div class="table-responsive">
          <table class="table table-sm detail-table">
            <thead><tr><th>SKU</th><th>商品</th><th>批次号</th><th>应收</th><th>实收</th><th>生产日期</th><th>到期日</th><th>上架库位</th></tr></thead>
            <tbody>${o.details.map(d => `<tr>
              <td class="mono">${d.sku}</td><td>${d.product_name}</td><td class="mono">${d.batch_no || '-'}</td>
              <td>${d.quantity}</td><td>${d.received_qty}</td>
              <td>${fmtDate(d.production_date)}</td><td>${fmtDate(d.expiry_date)}</td>
              <td class="mono">${d.location_code || '-'}</td></tr>`).join('')}</tbody>
          </table>
        </div>`,
    });
  },
  async create() {
    const [whRes, supRes, prodRes] = await Promise.all([
      API.get('/warehouses'), API.get('/suppliers'), API.get('/products?page=1&size=100')]);
    const whOpts = whRes.data.map(w => [w.id, w.warehouse_name]);
    const supOpts = [[null, '不指定']].concat(supRes.data.map(s => [s.id, s.supplier_name]));
    const prodCache = prodRes.data.list;
    const prodOpts = prodCache.map(p => [p.id, `${p.sku} ${p.product_name}${p.is_batch_managed ? '（批次）' : ''}`]);
    const m = UI.modal({
      title: '新建入库单', size: 'modal-lg',
      body: `<div class="row g-2">
        <div class="col-md-3">${UI.field('仓库', UI.select('warehouse_id', whOpts))}</div>
        <div class="col-md-3">${UI.field('供应商', UI.select('supplier_id', supOpts))}</div>
        <div class="col-md-3">${UI.field('预计到货', UI.input('expected_time', '', 'datetime-local'))}</div>
        <div class="col-md-3">${UI.field('备注', UI.input('remark', ''))}</div>
      </div>
      <div class="fw-semibold mb-2">商品明细（批次商品请填写批次信息）</div>
      <div id="ib_items"></div>
      <button class="btn btn-sm btn-outline-secondary" onclick="PAGES.inbound.addItem()">+ 添加明细</button>`,
      okText: '创建',
      onOk: async () => {
        const d = UI.formData(m.id);
        d.items = [...document.querySelectorAll(`#${m.id} .ib-row`)].map(row => {
          const pid = Number(row.querySelector('[name=product_id]').value);
          const p = prodCache.find(x => x.id === pid);
          return {
            product_id: pid,
            quantity: Number(row.querySelector('[name=quantity]').value),
            batch_no: row.querySelector('[name=batch_no]').value,
            production_date: row.querySelector('[name=production_date]').value || null,
            expiry_date: row.querySelector('[name=expiry_date]').value || null,
          };
        }).filter(i => i.product_id && i.quantity > 0);
        if (!d.items.length) { UI.toast('请添加至少一条明细', 'error'); return false; }
        const res = await API.post('/inbound-orders', d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('入库单创建成功，可进行审核后确认入库'); this.load(1); return true;
      },
    });
    window._inboundProdOpts = prodOpts;
    this.addItem();
  },
  addItem() {
    const prodOpts = window._inboundProdOpts || [];
    const row = document.createElement('div');
    row.className = 'ib-row border rounded p-2 mb-2';
    row.innerHTML = `
      <div class="d-flex gap-2 mb-1">
        <select class="form-select form-select-sm" name="product_id" style="flex:3">${prodOpts.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</select>
        <input class="form-control form-control-sm" name="quantity" type="number" min="1" value="50" style="flex:1" placeholder="数量">
        <button class="btn btn-sm btn-outline-danger" onclick="this.closest('.ib-row').remove()">✕</button>
      </div>
      <div class="d-flex gap-2">
        <input class="form-control form-control-sm" name="batch_no" placeholder="批次号（可空自动留空）" style="flex:2">
        <input class="form-control form-control-sm" name="production_date" type="date" style="flex:1.5" title="生产日期">
        <input class="form-control form-control-sm" name="expiry_date" type="date" style="flex:1.5" title="到期日">
      </div>`;
    document.getElementById('ib_items').appendChild(row);
  },
  approve(id) {
    UI.confirm('审核通过该入库单？审核后可执行入库。', async () => {
      const res = await API.post(`/inbound-orders/${id}/approve`);
      if (res.code === 0) { UI.toast('审核通过'); this.load(1); } else UI.toast(res.msg, 'error');
    }, false);
  },
  async confirm(id) {
    // 先获取明细，支持录入质检结果
    const res = await API.get(`/inbound-orders/${id}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const o = res.data;
    const inspRows = o.details.map(d => `
      <tr>
        <td class="mono">${d.sku}</td><td>${d.product_name}</td>
        <td>${d.quantity}</td>
        <td><input class="form-control form-control-sm" name="q_${d.id}" type="number" value="${d.quantity}" min="0" max="${d.quantity}"></td>
        <td><input class="form-control form-control-sm" name="u_${d.id}" type="number" value="0" min="0" max="${d.quantity}"></td>
      </tr>`).join('');
    const m = UI.modal({
      title: `确认入库 · ${o.order_no}`, size: 'modal-lg',
      body: `
        <div class="alert alert-info py-2 small">确认入库将执行：<b>智能推荐库位上架 → 库存增加 → 批次登记 → 库位状态更新 → 生成移库流水与质检记录</b>。不合格品数量将退回供应商不入库。</div>
        <table class="table table-sm detail-table">
          <thead><tr><th>SKU</th><th>商品</th><th>应收数量</th><th>合格数量</th><th>不合格数量</th></tr></thead>
          <tbody>${inspRows}</tbody>
        </table>`,
      okText: '确认入库',
      onOk: async () => {
        const inspections = {};
        o.details.forEach(d => {
          const q = Number(document.querySelector(`#${m.id} [name=q_${d.id}]`).value);
          const u = Number(document.querySelector(`#${m.id} [name=u_${d.id}]`).value);
          inspections[d.id] = { qualified_qty: q, unqualified_qty: u };
        });
        const res = await API.post(`/inbound-orders/${id}/confirm`, { inspections });
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast(res.msg); this.load(1); return true;
      },
    });
  },
  cancel(id) {
    UI.confirm('确定取消该入库单吗？', async () => {
      const res = await API.post(`/inbound-orders/${id}/cancel`);
      if (res.code === 0) { UI.toast('已取消'); this.load(1); } else UI.toast(res.msg, 'error');
    });
  },
};

PAGES.inspections = {
  title: '质检管理',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header">质检记录（入库自动生成）</div>
        <div class="card-body p-0" id="qc_list"></div>
      </div>`;
    const res = await API.get('/inspections');
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const resultMap = { pass: '<span class="badge st-normal badge-status">合格</span>',
      unqualified: '<span class="badge st-cancelled badge-status">不合格</span>',
      partial: '<span class="badge st-pending badge-status">部分合格</span>' };
    document.getElementById('qc_list').innerHTML = UI.table([
      { key: 'inspection_no', title: '质检单号', class: 'mono' },
      { key: 'order_no', title: '关联入库单', class: 'mono' },
      { key: 'sku', title: 'SKU', class: 'mono' },
      { key: 'product_name', title: '商品' },
      { key: 'quantity', title: '质检数' },
      { key: 'qualified_qty', title: '合格数', render: r => `<span class="text-success fw-bold">${r.qualified_qty}</span>` },
      { key: 'unqualified_qty', title: '不合格数', render: r => r.unqualified_qty ? `<span class="text-danger fw-bold">${r.unqualified_qty}</span>` : '0' },
      { key: 'result', title: '结果', render: r => resultMap[r.result] || r.result },
      { key: 'inspector', title: '质检员' },
      { key: 'create_time', title: '质检时间', render: r => fmtTime(r.create_time) },
    ], res.data);
  },
};
