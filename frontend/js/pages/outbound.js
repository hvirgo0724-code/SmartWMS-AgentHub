/* 出库管理页面：出库单 / 波次拣货 */
PAGES.outbound = {
  title: '出库单管理',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <span>出库单列表</span>
          <div class="d-flex gap-2 flex-wrap">
            <select class="form-select form-select-sm" id="ob_st" style="width:120px" onchange="PAGES.outbound.load(1)">
              <option value="">全部状态</option><option value="pending">待审核</option>
              <option value="approved">已审核</option><option value="allocated">已分配</option>
              <option value="shipped">已发货</option><option value="cancelled">已取消</option>
            </select>
            <input class="form-control form-control-sm" id="ob_kw" placeholder="单号/客户" style="width:160px">
            <button class="btn btn-sm btn-outline-primary" onclick="PAGES.outbound.load(1)">搜索</button>
            <button class="btn btn-sm btn-primary" onclick="PAGES.outbound.create()">+ 新建出库单</button>
          </div>
        </div>
        <div class="card-body p-0" id="ob_list"></div>
        <div class="card-footer bg-white" id="ob_page"></div>
      </div>`;
    this.load(1);
  },
  async load(page = 1) {
    const st = document.getElementById('ob_st')?.value || '';
    const kw = document.getElementById('ob_kw')?.value || '';
    const res = await API.get(`/outbound-orders?page=${page}&size=10&status=${st}&keyword=${encodeURIComponent(kw)}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._cache = res.data.list;
    const priMap = { 1: '<span class="badge text-bg-danger">紧急</span>', 2: '<span class="badge text-bg-light">普通</span>', 3: '<span class="badge text-bg-secondary">低</span>' };
    document.getElementById('ob_list').innerHTML = UI.table([
      { key: 'order_no', title: '出库单号', class: 'mono' },
      { key: 'warehouse_name', title: '仓库' },
      { key: 'customer_name', title: '客户' },
      { key: 'priority', title: '优先级', render: r => priMap[r.priority] || r.priority },
      { key: 'wave_no', title: '波次', render: r => r.wave_no ? `<span class="mono">${r.wave_no}</span>` : '-' },
      { key: 'expected_time', title: '期望发货', render: r => fmtTime(r.expected_time) },
      { key: 'actual_time', title: '实际发货', render: r => fmtTime(r.actual_time) },
      { key: 'status', title: '状态', render: r => UI.statusBadge(r.status) },
      { title: '操作', render: r => `
        <button class="btn btn-sm btn-outline-secondary" onclick="PAGES.outbound.detail(${r.id})">明细</button>
        ${r.status === 'pending' ? `<button class="btn btn-sm btn-outline-primary" onclick="PAGES.outbound.approve(${r.id})">审核</button>` : ''}
        ${r.status === 'approved' ? `<button class="btn btn-sm btn-warning" onclick="PAGES.outbound.allocate(${r.id})">分配库存</button>` : ''}
        ${r.status === 'allocated' ? `<button class="btn btn-sm btn-success" onclick="PAGES.outbound.ship(${r.id})">发货确认</button>` : ''}
        ${r.status !== 'shipped' && r.status !== 'cancelled' ? `<button class="btn btn-sm btn-outline-danger" onclick="PAGES.outbound.cancel(${r.id})">取消</button>` : ''}` },
    ], res.data.list);
    document.getElementById('ob_page').innerHTML = UI.pagination(res.data.total, page, 10, 'PAGES.outbound.load');
  },
  async detail(id) {
    const res = await API.get(`/outbound-orders/${id}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const o = res.data;
    const allocTable = o.allocations?.length ? `
      <div class="fw-semibold mt-3 mb-1">库存分配（FIFO 先进先出）</div>
      <table class="table table-sm detail-table">
        <thead><tr><th>SKU</th><th>商品</th><th>批次号</th><th>拣货库位</th><th>分配数量</th></tr></thead>
        <tbody>${o.allocations.map(a => `<tr>
          <td class="mono">${a.sku}</td><td>${a.product_name}</td><td class="mono">${a.batch_no || '-'}</td>
          <td class="mono">${a.location_code}</td><td><b>${a.quantity}</b></td></tr>`).join('')}</tbody>
      </table>` : '';
    UI.modal({
      title: `出库单明细 · ${o.order_no}`,
      body: `
        <div class="row small mb-2 g-2">
          <div class="col-md-3"><b>仓库：</b>${o.warehouse_name}</div>
          <div class="col-md-3"><b>客户：</b>${o.customer_name || '-'}</div>
          <div class="col-md-3"><b>状态：</b>${UI.statusBadge(o.status)}</div>
          <div class="col-md-3"><b>波次：</b>${o.wave_no || '-'}</div>
        </div>
        <table class="table table-sm detail-table">
          <thead><tr><th>SKU</th><th>商品</th><th>需求数量</th><th>已拣数量</th><th>批次</th><th>拣货库位</th></tr></thead>
          <tbody>${o.details.map(d => `<tr>
            <td class="mono">${d.sku}</td><td>${d.product_name}</td><td>${d.quantity}</td>
            <td>${d.picked_qty}</td><td class="mono">${d.batch_no || '-'}</td><td class="mono">${d.location_code || '-'}</td></tr>`).join('')}</tbody>
        </table>${allocTable}`,
    });
  },
  async create() {
    const [whRes, cusRes, prodRes] = await Promise.all([
      API.get('/warehouses'), API.get('/customers'), API.get('/products?page=1&size=100')]);
    const whOpts = whRes.data.map(w => [w.id, w.warehouse_name]);
    const cusOpts = [[null, '不指定']].concat(cusRes.data.map(c => [c.id, c.customer_name]));
    const prodCache = prodRes.data.list;
    const prodOpts = prodCache.map(p => [p.id, `${p.sku} ${p.product_name}`]);
    const m = UI.modal({
      title: '新建出库单', size: 'modal-lg',
      body: `<div class="alert alert-warning py-2 small">创建时校验可用库存；分配库存按 <b>FIFO 先进先出</b> 锁定批次库存，发货后自动扣减并释放库位。</div>
      <div class="row g-2">
        <div class="col-md-3">${UI.field('仓库', UI.select('warehouse_id', whOpts))}</div>
        <div class="col-md-3">${UI.field('客户', UI.select('customer_id', cusOpts))}</div>
        <div class="col-md-3">${UI.field('优先级', UI.select('priority', [[1, '紧急'], [2, '普通'], [3, '低']]))}</div>
        <div class="col-md-3">${UI.field('期望发货', UI.input('expected_time', '', 'datetime-local'))}</div>
      </div>
      <div class="fw-semibold mb-2">商品明细</div>
      <div id="ob_items"></div>
      <button class="btn btn-sm btn-outline-secondary" onclick="PAGES.outbound.addItem()">+ 添加明细</button>`,
      okText: '创建',
      onOk: async () => {
        const d = UI.formData(m.id);
        d.items = [...document.querySelectorAll(`#${m.id} .ob-row`)].map(row => ({
          product_id: Number(row.querySelector('[name=product_id]').value),
          quantity: Number(row.querySelector('[name=quantity]').value),
        })).filter(i => i.product_id && i.quantity > 0);
        if (!d.items.length) { UI.toast('请添加至少一条明细', 'error'); return false; }
        const res = await API.post('/outbound-orders', d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('出库单创建成功'); this.load(1); return true;
      },
    });
    window._outboundProdOpts = prodOpts;
    this.addItem();
  },
  addItem() {
    const prodOpts = window._outboundProdOpts || [];
    const row = document.createElement('div');
    row.className = 'ob-row d-flex gap-2 mb-2';
    row.innerHTML = `
      <select class="form-select form-select-sm" name="product_id" style="flex:3">${prodOpts.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</select>
      <input class="form-control form-control-sm" name="quantity" type="number" min="1" value="10" style="flex:1" placeholder="数量">
      <button class="btn btn-sm btn-outline-danger" onclick="this.parentElement.remove()">✕</button>`;
    document.getElementById('ob_items').appendChild(row);
  },
  approve(id) {
    UI.confirm('审核通过该出库单？审核后可分配库存。', async () => {
      const res = await API.post(`/outbound-orders/${id}/approve`);
      if (res.code === 0) { UI.toast('审核通过'); this.load(1); } else UI.toast(res.msg, 'error');
    }, false);
  },
  allocate(id) {
    UI.confirm('按 FIFO 先进先出策略分配并锁定库存？', async () => {
      const res = await API.post(`/outbound-orders/${id}/allocate`);
      if (res.code === 0) { UI.toast(res.msg); this.load(1); } else UI.toast(res.msg, 'error');
    }, false);
  },
  ship(id) {
    UI.confirm('发货确认将扣减库存、释放库位并生成发货记录，确认执行？', async () => {
      const res = await API.post(`/outbound-orders/${id}/ship`);
      if (res.code === 0) { UI.toast(res.msg); this.load(1); } else UI.toast(res.msg, 'error');
    }, false);
  },
  cancel(id) {
    UI.confirm('取消该出库单？已锁定的库存将自动释放。', async () => {
      const res = await API.post(`/outbound-orders/${id}/cancel`);
      if (res.code === 0) { UI.toast(res.msg); this.load(1); } else UI.toast(res.msg, 'error');
    });
  },
};

PAGES.waves = {
  title: '波次拣货',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span>波次管理（合并订单优化拣货路径）</span>
          <button class="btn btn-sm btn-primary" onclick="PAGES.waves.create()">+ 创建波次</button>
        </div>
        <div class="card-body p-0" id="wv_list"></div>
      </div>`;
    this.load();
  },
  async load() {
    const res = await API.get('/waves');
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._cache = res.data;
    document.getElementById('wv_list').innerHTML = UI.table([
      { key: 'wave_no', title: '波次号', class: 'mono' },
      { key: 'warehouse_name', title: '仓库' },
      { key: 'strategy', title: '策略', render: r => r.strategy === 'product' ? '播种式(按商品)' : '摘果式(按订单)' },
      { key: 'order_count', title: '订单数' },
      { key: 'operator', title: '创建人' },
      { key: 'status', title: '状态', render: r => UI.statusBadge(r.status) },
      { key: 'create_time', title: '创建时间', render: r => fmtTime(r.create_time) },
      { title: '操作', render: r => `
        <button class="btn btn-sm btn-outline-secondary" onclick="PAGES.waves.pickList(${r.id})">拣货单</button>
        ${r.status === 'pending' ? `<button class="btn btn-sm btn-success" onclick="PAGES.waves.pick(${r.id})">执行拣货</button>` : ''}` },
    ], res.data);
  },
  async create() {
    const res = await API.get('/outbound-orders?status=approved&size=100');
    const orders = res.data?.list || [];
    if (!orders.length) return UI.toast('暂无已审核待分配的出库单，请先在出库管理中审核订单', 'warning');
    const m = UI.modal({
      title: '创建波次',
      body: `
        <div class="alert alert-info py-2 small">从已审核的出库单中选择订单组成波次。波次拣货按商品汇总需求（播种式），一次拣完多个订单。</div>
        <div style="max-height:320px;overflow:auto">
        ${orders.map(o => `<div class="form-check border-bottom py-1">
          <input class="form-check-input" type="checkbox" name="order_ids" value="${o.id}" id="wo_${o.id}">
          <label class="form-check-label" for="wo_${o.id}">
            <span class="mono">${o.order_no}</span> · ${o.customer_name || '-'} · ${o.warehouse_name}
          </label></div>`).join('')}
        </div>`,
      okText: '创建波次',
      onOk: async () => {
        const ids = [...document.querySelectorAll(`#${m.id} [name=order_ids]:checked`)].map(c => Number(c.value));
        if (ids.length < 2) { UI.toast('请至少选择2个订单组成波次', 'error'); return false; }
        const wid = orders.find(o => o.id === ids[0]).warehouse_id;
        const res = await API.post('/waves', { warehouse_id: wid, strategy: 'product', order_ids: ids });
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast(res.msg); this.load(); return true;
      },
    });
  },
  async pickList(id) {
    const res = await API.get(`/waves/${id}/pick-list`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const { wave, items } = res.data;
    UI.modal({
      title: `拣货单 · ${wave.wave_no}（${wave.strategy === 'product' ? '播种式' : '摘果式'}）`, size: 'modal-lg',
      body: `
        <div class="alert alert-light py-2 small border">按商品汇总的拣货任务清单，拣货员按库位路径一次拣货后分播到各订单。</div>
        <table class="table table-sm detail-table">
          <thead><tr><th>SKU</th><th>商品</th><th>拣货库位</th><th>批次号</th><th>汇总数量</th><th>涉及订单数</th></tr></thead>
          <tbody>${items.map(i => `<tr>
            <td class="mono">${i.sku}</td><td>${i.product_name}</td><td class="mono">${i.location_code || '-'}</td>
            <td class="mono">${i.batch_no || '-'}</td><td><b>${i.total_qty}</b></td><td>${i.order_count || '-'}</td></tr>`).join('')}</tbody>
        </table>`,
    });
  },
  pick(id) {
    UI.confirm('执行波次拣货？系统将对波次内所有订单自动完成分配与拣货发货。', async () => {
      const res = await API.post(`/waves/${id}/pick`);
      if (res.code === 0) { UI.toast(res.msg); this.load(); } else UI.toast(res.msg, 'error');
    }, false);
  },
};
