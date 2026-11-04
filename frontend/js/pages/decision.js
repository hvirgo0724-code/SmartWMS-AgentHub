/* 智能决策页面：数据看板 / 预警中心 / 智能补货 / 路径优化 / 报表中心 */
PAGES.dashboard = {
  title: '数据分析看板',
  _charts: [],
  destroy() { this._charts.forEach(c => { try { c.dispose(); } catch (e) {} }); this._charts = []; },
  async render(el) {
    const res = await API.get('/analytics/dashboard');
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const d = res.data, k = d.kpi;
    // [图标, 左边框色, 图标底色, 数值, 前缀, 后缀, 标签, 点击跳转模块]
    const kpis = [
      ['📦', 'kpi-accent-primary', 'bg-primary bg-opacity-10', k.total_qty, '', '', '在库总量（件）', 'inventory'],
      ['💰', 'kpi-accent-success', 'bg-success bg-opacity-10', Math.round(Number(k.total_value)), '¥', '', '库存总货值', 'inventory'],
      ['🏭', 'kpi-accent-info', 'bg-info bg-opacity-10', k.warehouse_count, '', '', '在用仓库', 'warehouses'],
      ['📍', 'kpi-accent-warning', 'bg-warning bg-opacity-10', k.location_rate, '', '%', `库位利用率（${k.location_used}/${k.location_total}）`, 'locations'],
      ['📥', 'kpi-accent-secondary', 'bg-secondary bg-opacity-10', k.pending_inbound, '', '', '待处理入库单', 'inbound'],
      ['📤', 'kpi-accent-danger', 'bg-danger bg-opacity-10', k.pending_outbound, '', '', '待处理出库单', 'outbound'],
      ['🚚', 'kpi-accent-primary', 'bg-primary bg-opacity-10', k.shipped_month, '', '', '本月发货单量', 'outbound'],
      ['🎯', 'kpi-accent-success', 'bg-success bg-opacity-10', k.fulfill_rate, '', '%', '订单满足率', 'reports'],
    ];
    el.innerHTML = `
      <div class="row g-3 mb-3">
        ${kpis.map(([icon, accent, bg, num, prefix, suffix, label, link]) => `
          <div class="col-6 col-md-3"><div class="card kpi-card kpi-click ${accent}" role="button" title="点击查看明细" onclick="loadPage('${link}')">
            <div class="card-body py-3 d-flex align-items-center gap-3">
              <div class="kpi-icon ${bg}">${icon}</div>
              <div class="text-truncate"><div class="kpi-value" data-num="${num}" data-prefix="${prefix}" data-suffix="${suffix}">${prefix}0${suffix}</div>
                <div class="kpi-label">${label}</div></div>
            </div>
            <div class="kpi-goto">查看明细 →</div>
          </div></div>`).join('')}
      </div>
      <div class="row g-3 mb-3">
        <div class="col-lg-8"><div class="card"><div class="card-header d-flex justify-content-between align-items-center">出入库趋势（近14天）
          <a href="javascript:loadPage('inbound')" class="small text-decoration-none">查看入库单 →</a></div>
          <div class="card-body"><div class="chart-box" id="ch_trend"></div></div></div></div>
        <div class="col-lg-4"><div class="card"><div class="card-header d-flex justify-content-between align-items-center">ABC 分类（库存价值）
          <a href="javascript:loadPage('products')" class="small text-decoration-none">商品档案 →</a></div>
          <div class="card-body"><div class="chart-box" id="ch_abc"></div></div></div></div>
      </div>
      <div class="row g-3">
        <div class="col-lg-4"><div class="card"><div class="card-header d-flex justify-content-between align-items-center">各仓库库存分布
          <a href="javascript:loadPage('inventory')" class="small text-decoration-none">实时库存 →</a></div>
          <div class="card-body"><div class="chart-box-sm" id="ch_wh"></div></div></div></div>
        <div class="col-lg-4"><div class="card"><div class="card-header d-flex justify-content-between align-items-center">商品分类库存分布
          <a href="javascript:loadPage('products')" class="small text-decoration-none">商品档案 →</a></div>
          <div class="card-body"><div class="chart-box-sm" id="ch_cat"></div></div></div></div>
        <div class="col-lg-4"><div class="card"><div class="card-header d-flex justify-content-between align-items-center">库存价值 TOP 商品
          <a href="javascript:loadPage('products')" class="small text-decoration-none">商品档案 →</a></div>
          <div class="card-body"><div class="chart-box-sm" id="ch_top"></div></div></div></div>
      </div>`;

    // KPI 数字滚动动画
    el.querySelectorAll('.kpi-value[data-num]').forEach(v => {
      UI.animateNumber(v, v.dataset.num, { prefix: v.dataset.prefix, suffix: v.dataset.suffix });
    });

    const mk = (id) => { const c = echarts.init(document.getElementById(id)); this._charts.push(c); return c; };
    mk('ch_trend').setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['入库单据', '出库单据'] },
      grid: { left: 40, right: 20, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: d.trend.map(t => t.date) },
      yAxis: { type: 'value', minInterval: 1 },
      series: [
        { name: '入库单据', type: 'line', smooth: true, data: d.trend.map(t => t.inbound), areaStyle: { opacity: .15 } },
        { name: '出库单据', type: 'line', smooth: true, data: d.trend.map(t => t.outbound), areaStyle: { opacity: .15 } },
      ],
    });
    mk('ch_abc').setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} 类商品 ({d}%)' },
      legend: { bottom: 0 },
      series: [{
        type: 'pie', radius: ['40%', '65%'], center: ['50%', '45%'],
        label: { formatter: '{b}\n{c}类' },
        data: ['A', 'B', 'C'].map(cls => ({ name: cls + '类', value: d.abc.stat[cls].count,
          itemStyle: { color: { A: '#2563eb', B: '#f59e0b', C: '#94a3b8' }[cls] } })),
      }],
    });
    mk('ch_wh').setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 80, right: 20, top: 20, bottom: 30 },
      xAxis: { type: 'value' },
      yAxis: { type: 'category', data: d.wh_stock.map(w => w.name) },
      series: [{ type: 'bar', data: d.wh_stock.map(w => w.qty), itemStyle: { color: '#2563eb' } }],
    });
    mk('ch_cat').setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} 件 ({d}%)' },
      series: [{ type: 'pie', radius: '60%', data: d.category.map(c => ({ name: c.name, value: Number(c.qty) })) }],
    });
    mk('ch_top').setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 100, right: 30, top: 20, bottom: 30 },
      xAxis: { type: 'value' },
      yAxis: { type: 'category', data: d.top_products.map(p => p.name).reverse() },
      series: [{ type: 'bar', data: d.top_products.map(p => Number(p.value)).reverse(), itemStyle: { color: '#10b981' } }],
    });
  },
};

PAGES.alerts = {
  title: '预警中心',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span>库存预警（缺货 / 超储 / 临期 / 滞销）</span>
          <div class="d-flex gap-2">
            <select class="form-select form-select-sm" id="al_type" style="width:140px" onchange="PAGES.alerts.load()">
              <option value="">全部类型</option>
              <option value="low_stock">缺货预警</option>
              <option value="over_stock">超储预警</option>
              <option value="expiry">临期预警</option>
              <option value="dead_stock">滞销预警</option>
            </select>
            <button class="btn btn-sm btn-primary" onclick="PAGES.alerts.load(true)">🔄 重新扫描</button>
          </div>
        </div>
        <div class="card-body p-0" id="al_list"></div>
      </div>`;
    this.load();
  },
  async load(manual = false) {
    const type = document.getElementById('al_type')?.value || '';
    const res = await API.get(`/alerts${type ? `?alert_type=${type}` : ''}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    if (manual) UI.toast(`扫描完成，本次发现 ${res.data.today_new} 条预警`);
    const typeMap = { low_stock: ['缺货预警', 'text-bg-danger'], over_stock: ['超储预警', 'text-bg-warning'],
      expiry: ['临期预警', 'text-bg-danger'], dead_stock: ['滞销预警', 'text-bg-secondary'] };
    const typeNames = { low_stock: '缺货', over_stock: '超储', expiry: '临期', dead_stock: '滞销' };
    const filterName = type ? typeNames[type] : '全部';
    document.getElementById('al_list').innerHTML = `
      <div class="p-2 bg-light border-bottom small">当前筛选：<b>${filterName}</b>　共 <b>${res.data.alerts.length}</b> 条　本次扫描新增 <b>${res.data.today_new}</b> 条</div>` +
      UI.table([
        { key: 'alert_type', title: '类型', render: r => { const m = typeMap[r.alert_type] || [r.alert_type, 'text-bg-light']; return `<span class="badge ${m[1]}">${m[0]}</span>`; } },
        { key: 'level', title: '级别', render: r => ({ high: '🔴 高', medium: '🟡 中', low: '🟢 低' }[r.level] || r.level) },
        { key: 'sku', title: 'SKU', class: 'mono' },
        { key: 'product_name', title: '商品' },
        { key: 'content', title: '预警内容' },
        { key: 'is_read', title: '状态', render: r => r.is_read ? '<span class="text-muted">已读</span>' : '<span class="badge st-pending badge-status">未读</span>' },
        { key: 'create_time', title: '时间', render: r => fmtTime(r.create_time) },
        { title: '操作', render: r => r.is_read ? '' : `<button class="btn btn-sm btn-outline-secondary" onclick="PAGES.alerts.read(${r.id})">标记已读</button>` },
      ], res.data.alerts);
  },
  async read(id) {
    await API.post(`/alerts/${id}/read`);
    this.load();
  },
};

PAGES.replenishment = {
  title: '智能补货',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span>补货建议（基于出库速度 / 安全库存 / 采购周期预测）</span>
          <button class="btn btn-sm btn-primary" onclick="PAGES.replenishment.suggest()">🤖 重新计算补货建议</button>
        </div>
        <div class="card-body p-0" id="rp_list"></div>
      </div>`;
    this.load();
  },
  async load() {
    const res = await API.get('/replenishment');
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._cache = res.data;
    const stMap = { pending: '<span class="badge st-pending badge-status">待处理</span>',
      ordered: '<span class="badge st-completed badge-status">已下单</span>',
      ignored: '<span class="badge st-cancelled badge-status">已忽略</span>' };
    document.getElementById('rp_list').innerHTML = UI.table([
      { key: 'sku', title: 'SKU', class: 'mono' },
      { key: 'product_name', title: '商品' },
      { key: 'current_stock', title: '当前库存' },
      { key: 'avg_daily', title: '日均出库' },
      { key: 'suggested_qty', title: '建议补货量', render: r => `<span class="text-primary fw-bold">${r.suggested_qty}</span> ${r.unit}` },
      { key: 'estimated_cost', title: '预计成本(元)', render: r => Number(r.estimated_cost).toLocaleString() },
      { key: 'reason', title: '分析依据', render: r => `<span class="small text-muted">${r.reason}</span>` },
      { key: 'status', title: '状态', render: r => stMap[r.status] || r.status },
      { title: '操作', render: r => r.status === 'pending' ? `
        <button class="btn btn-sm btn-success" onclick="PAGES.replenishment.handle(${r.id},'ordered')">下单</button>
        <button class="btn btn-sm btn-outline-secondary" onclick="PAGES.replenishment.handle(${r.id},'ignored')">忽略</button>` : '-' },
    ], res.data);
  },
  async suggest() {
    const res = await API.post('/replenishment/suggest');
    if (res.code === 0) { UI.toast(res.msg); this.load(); } else UI.toast(res.msg, 'error');
  },
  async handle(id, status) {
    await API.post(`/replenishment/${id}/handle`, { status });
    UI.toast('已处理'); this.load();
  },
};

/* ---------- 拣货路径优化 ---------- */
PAGES.pathopt = {
  title: '拣货路径优化',
  _chart: null,
  _heat: [],
  _path: null,
  destroy() { if (this._chart) { try { this._chart.dispose(); } catch (e) {} this._chart = null; } },
  async render(el) {
    const whRes = await API.get('/warehouses');
    this._wh = whRes.data || [];
    el.innerHTML = `
      <div class="card mb-3"><div class="card-body py-2 d-flex gap-2 align-items-center flex-wrap">
        <select class="form-select form-select-sm" id="po_wh" style="width:180px" onchange="PAGES.pathopt.changeWh()">
          <option value="">全部仓库</option>
          ${this._wh.map(w => `<option value="${w.id}">${w.warehouse_name}</option>`).join('')}
        </select>
        <button class="btn btn-sm btn-primary" onclick="PAGES.pathopt.optimize()">🧭 生成优化路径</button>
        <span class="text-muted small">自动选取近90天高频出库商品 · 最近邻 + 2-opt 算法 · 巷道曼哈顿距离（每格 2 米）</span>
      </div></div>
      <div class="row g-3 mb-3" id="po_stats">
        <div class="col-12"><div class="card"><div class="card-body text-center text-muted py-4">
          点击「生成优化路径」查看库位热力图与拣货路径对比</div></div></div>
      </div>
      <div class="row g-3">
        <div class="col-lg-8"><div class="card"><div class="card-header">库位热力图与拣货路径</div>
          <div class="card-body"><div class="chart-box" id="po_chart"></div></div></div></div>
        <div class="col-lg-4"><div class="card"><div class="card-header">优化后拣货顺序</div>
          <div class="card-body p-0" id="po_seq"><div class="text-center text-muted py-4">尚未生成</div></div></div></div>
      </div>`;
    this.loadHeatmap();
  },
  async changeWh() { this._path = null; await this.loadHeatmap(); },
  async loadHeatmap() {
    const wh = document.getElementById('po_wh')?.value || '';
    const res = await API.get(`/analytics/heatmap${wh ? `?warehouse_id=${wh}` : ''}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._heat = res.data.points;
    this.drawChart();
  },
  async optimize() {
    const wh = document.getElementById('po_wh')?.value || '';
    const btn = event?.target;
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>计算中...'; }
    try {
      const res = await API.get(`/analytics/pick-path${wh ? `?warehouse_id=${wh}` : ''}`);
      if (res.code !== 0) { UI.toast(res.msg, 'error'); return; }
      this._path = res.data;
      this.drawStats();
      this.drawSeq();
      this.drawChart();
      UI.toast(`优化完成：节省行走距离 ${res.data.saving_pct}%`);
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = '🧭 生成优化路径'; }
    }
  },
  drawStats() {
    const d = this._path;
    const cards = [
      ['🎯', 'kpi-accent-primary', 'bg-primary bg-opacity-10', d.picks.length, '', '拣货点数'],
      ['🚶', 'kpi-accent-secondary', 'bg-secondary bg-opacity-10', d.distance_before, '', '优化前行走距离(米)'],
      ['🏁', 'kpi-accent-success', 'bg-success bg-opacity-10', d.distance_after, '', '优化后行走距离(米)'],
      ['⚡', 'kpi-accent-danger', 'bg-danger bg-opacity-10', d.saving_pct, '', '距离节省比例(%)'],
    ];
    document.getElementById('po_stats').innerHTML = cards.map(([icon, accent, bg, num, prefix, label]) => `
      <div class="col-6 col-md-3"><div class="card kpi-card ${accent}">
        <div class="card-body py-3 d-flex align-items-center gap-3">
          <div class="kpi-icon ${bg}">${icon}</div>
          <div><div class="kpi-value" data-num="${num}" data-prefix="${prefix}">${prefix}0</div>
            <div class="kpi-label">${label}</div></div>
        </div></div></div>`).join('');
    document.querySelectorAll('#po_stats .kpi-value[data-num]').forEach(v => {
      UI.animateNumber(v, v.dataset.num, { prefix: v.dataset.prefix });
    });
  },
  drawSeq() {
    const d = this._path;
    document.getElementById('po_seq').innerHTML = UI.table([
      { title: '#', width: '50px', render: r => `<b class="text-primary">${r.seq}</b>` },
      { key: 'sku', title: 'SKU', class: 'mono' },
      { key: 'product_name', title: '商品' },
      { key: 'code', title: '库位', class: 'mono' },
    ], d.optimized.map((p, i) => ({ ...p, seq: i + 1 })));
  },
  drawChart() {
    const el = document.getElementById('po_chart');
    if (!el) return;
    if (this._chart) this._chart.dispose();
    this._chart = echarts.init(el);
    const pts = this._heat;
    const maxAct = Math.max(1, ...pts.map(p => p.activity));

    // 库区带背景（A/B/C 存储区、P 拣货区、R 退货区）
    const areaInfo = {};
    pts.forEach(p => {
      if (!areaInfo[p.area]) areaInfo[p.area] = { min: p.x, max: p.x };
      areaInfo[p.area].min = Math.min(areaInfo[p.area].min, p.x);
      areaInfo[p.area].max = Math.max(areaInfo[p.area].max, p.x);
    });
    const areaNames = { A: 'A 存储区', B: 'B 存储区', C: 'C 存储区', P: 'P 拣货区', R: 'R 退货区' };
    const markAreas = Object.entries(areaInfo).map(([a, r]) => [{
      xAxis: r.min - 0.5, name: areaNames[a] || a + ' 区',
      itemStyle: { color: a === 'P' ? 'rgba(16,185,129,0.07)' : 'rgba(37,99,235,0.05)' },
      label: { position: 'insideTop', fontSize: 10, color: '#64748b' },
    }, { xAxis: r.max + 0.5 }]);

    const series = [{
      name: '库位活跃度', type: 'scatter', z: 2,
      data: pts.map(p => ({ value: [p.x, p.y, p.activity], code: p.code, act: p.activity })),
      symbolSize: v => 6 + (v[2] / maxAct) * 9,
      itemStyle: { opacity: .9 },
      tooltip: { formatter: p => `${p.data.code}<br/>近90天作业 ${p.data.act} 次` },
      markArea: { silent: true, data: markAreas },
    }];

    // 拣货路径叠加
    if (this._path) {
      const d = this._path;
      const originCoords = [[0, 0], ...d.picks.map(p => [p.x, p.y]), [0, 0]];
      const optCoords = [[0, 0], ...d.optimized.map(p => [p.x, p.y]), [0, 0]];
      series.push({
        name: '优化前路径', type: 'lines', coordinateSystem: 'cartesian2d', polyline: true, silent: true, z: 4,
        lineStyle: { color: '#f97316', width: 2, type: 'dashed', opacity: .85 },
        data: [{ coords: originCoords }],
      });
      series.push({
        name: '优化后路径', type: 'lines', coordinateSystem: 'cartesian2d', polyline: true, z: 5,
        effect: { show: true, period: 5, trailLength: 0.4, symbol: 'arrow', symbolSize: 7, color: '#2563eb' },
        lineStyle: { color: '#2563eb', width: 3, opacity: .9 },
        data: [{ coords: optCoords }],
      });
      series.push({
        name: '拣货点', type: 'effectScatter', rippleEffect: { scale: 2.4, brushType: 'stroke' }, z: 6,
        data: d.picks.map(p => ({ value: [p.x, p.y], name: p.sku, pname: p.product_name, code: p.code })),
        symbolSize: 11, itemStyle: { color: '#f59e0b' },
        label: { show: true, formatter: p => p.name, position: 'top', fontSize: 9, color: '#b45309' },
        tooltip: { formatter: p => `${p.data.pname}<br/>${p.data.code} · SKU ${p.data.name}` },
      });
      series.push({
        name: '出库口', type: 'effectScatter', rippleEffect: { scale: 3, brushType: 'stroke' }, z: 7,
        data: [{ value: [0, 0], name: '出库口/打包台' }],
        symbolSize: 14, itemStyle: { color: '#10b981' },
        label: { show: true, formatter: '出库口', position: 'right', fontSize: 10, color: '#047857' },
      });
    }

    this._chart.setOption({
      tooltip: { trigger: 'item' },
      legend: this._path ? { top: 4, data: ['库位活跃度', '优化前路径', '优化后路径', '拣货点'] } : { show: false },
      visualMap: {
        min: 0, max: maxAct, right: 8, bottom: 30, orient: 'vertical', dimension: 2,
        text: ['高频', '低频'], itemHeight: 90,
        inRange: { color: ['#e2e8f0', '#93c5fd', '#fbbf24', '#ef4444'] },
      },
      grid: { left: 40, right: 60, top: 34, bottom: 30 },
      xAxis: { type: 'value', min: -2, name: '库位列 →', nameLocation: 'middle', nameGap: 22, axisLabel: { show: false }, splitLine: { show: false } },
      yAxis: { type: 'value', min: 0, max: 4, name: '排', axisLabel: { show: false }, splitLine: { show: false } },
      series,
    });
  },
};

PAGES.reports = {
  title: '报表中心',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <div class="btn-group">
            ${[['inbound_summary', '入库汇总'], ['outbound_summary', '出库汇总'], ['inventory_detail', '库存明细'],
               ['expiry_analysis', '效期分析'], ['performance', '作业绩效']].map(([t, n], i) =>
              `<button class="btn btn-sm ${i === 0 ? 'btn-primary' : 'btn-outline-primary'}" id="rp_tab_${t}" onclick="PAGES.reports.load('${t}')">${n}</button>`).join('')}
          </div>
          <button class="btn btn-sm btn-success" onclick="PAGES.reports.export()">📥 导出 Excel</button>
        </div>
        <div class="card-body p-0" id="rp_body"><div class="text-center py-5 text-muted">请选择报表类型</div></div>
      </div>`;
  },
  async load(type) {
    this._type = type;
    document.querySelectorAll('[id^=rp_tab_]').forEach(b => {
      b.className = 'btn btn-sm ' + (b.id === 'rp_tab_' + type ? 'btn-primary' : 'btn-outline-primary');
    });
    document.getElementById('rp_body').innerHTML = '<div class="text-center py-5"><div class="spinner-border text-primary"></div></div>';
    const res = await API.get(`/reports/${type}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const { title, rows } = res.data;
    this._rows = rows;
    if (!rows.length) {
      document.getElementById('rp_body').innerHTML = `<div class="text-center py-5 text-muted">${title}：暂无数据</div>`;
      return;
    }
    const cols = Object.keys(rows[0]);
    document.getElementById('rp_body').innerHTML = `
      <div class="p-2 bg-light border-bottom small">${title} · 共 ${rows.length} 行</div>
      <div class="table-responsive" style="max-height:600px">
        <table class="table table-hover table-sm mb-0">
          <thead class="sticky-top bg-light"><tr>${cols.map(c => `<th>${c}</th>`).join('')}</tr></thead>
          <tbody>${rows.map(r => `<tr>${cols.map(c => {
            let v = r[c];
            if (v && String(c).includes('time')) v = fmtTime(v);
            else if (v && String(c).includes('date') && String(v).length > 10) v = fmtDate(v);
            return `<td>${v ?? '-'}</td>`;
          }).join('')}</tr>`).join('')}</tbody>
        </table>
      </div>`;
  },
  async export() {
    if (!this._type) return UI.toast('请先选择报表类型', 'warning');
    const res = await API.download(`/reports/${this._type}/export`);
    if (res.code !== 0) UI.toast(res.msg, 'error'); else UI.toast('Excel 导出成功');
  },
};
