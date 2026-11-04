/* 扫码作业：硬件扫码枪 / 键盘输入 / 摄像头识码（BarcodeDetector） */
PAGES.scan = {
  title: '扫码作业',
  _mode: 'auto',
  _result: null,
  _move: { from: '', product: '', to: '', qty: 1 },
  _moveStep: 0,
  _audio: null,
  _camStream: null,
  _camTimer: null,

  destroy() {
    this.stopCamera();
  },

  async render(el) {
    el.innerHTML = `
      <div class="sc-page">
        <div class="sc-hero">
          <div class="sc-hero-brand">
            <div class="sc-hero-icon">⌗</div>
            <div>
              <div class="sc-hero-title">扫码作业台</div>
              <div class="sc-hero-sub">扫码枪即插即用 · 条码 / SKU / 库位 / 单据一号通扫</div>
            </div>
          </div>
          <div class="sc-task-chips" id="sc_tasks"><span class="sc-task-chip">加载中…</span></div>
        </div>

        <div class="sc-layout">
          <section class="cs-card sc-work">
            <div class="sc-mode-tabs">
              <button class="sc-mode active" data-mode="auto" onclick="PAGES.scan.setMode('auto')">智能识别</button>
              <button class="sc-mode" data-mode="move" onclick="PAGES.scan.setMode('move')">快速移库</button>
              <button class="sc-mode" data-mode="outbound" onclick="PAGES.scan.setMode('outbound')">出库发货</button>
              <button class="sc-mode" data-mode="inbound" onclick="PAGES.scan.setMode('inbound')">入库收货</button>
            </div>

            <div class="sc-scan-area">
              <div class="sc-scan-box">
                <span class="sc-scan-symbol">⌗</span>
                <input id="sc_input" autocomplete="off" spellcheck="false"
                  placeholder="请扫描商品条码、SKU、库位码或单据号…"
                  onkeydown="if(event.key==='Enter'){event.preventDefault();PAGES.scan.submit()}">
                <button class="sc-scan-btn" onclick="PAGES.scan.submit()">识别</button>
                <button class="sc-cam-btn" id="sc_cam_btn" title="摄像头扫描" onclick="PAGES.scan.cameraScan()">📷</button>
              </div>
              <div class="sc-hint" id="sc_hint">扫码枪回车即识别；支持商品条码、SKU、库位编码、入库单、出库单、ASN、波次号</div>
            </div>

            <div class="sc-result" id="sc_result">
              <div class="sc-empty">
                <div class="sc-empty-icon">⌗</div>
                <div class="sc-empty-title">等待扫描</div>
                <div class="sc-empty-sub">将光标保持在输入框，使用扫码枪扫描或手动输入编码后回车。</div>
              </div>
            </div>
          </section>

          <aside class="sc-side">
            <div class="cs-card sc-steps" id="sc_steps" style="display:none">
              <div class="sc-side-head">移库步骤 <button class="sc-reset" onclick="PAGES.scan.resetMove()">重置</button></div>
              <div class="sc-steps-body" id="sc_steps_body"></div>
            </div>
            <div class="cs-card sc-log">
              <div class="sc-side-head">最近扫描
                <button class="sc-reset" onclick="PAGES.scan.loadLogs()">刷新</button>
              </div>
              <div class="sc-log-list" id="sc_log"><div class="sc-empty-sub">暂无扫描记录</div></div>
            </div>
          </aside>
        </div>
      </div>`;

    if (!('BarcodeDetector' in window)) {
      const btn = document.getElementById('sc_cam_btn');
      if (btn) btn.style.display = 'none';
    }
    const input = document.getElementById('sc_input');
    input.focus();
    this.loadTasks();
    this.loadLogs();
    this.renderMoveSteps();
  },

  setMode(mode) {
    this._mode = mode;
    document.querySelectorAll('.sc-mode').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
    const hints = {
      auto: '扫码枪回车即识别；支持商品条码、SKU、库位编码、入库单、出库单、ASN、波次号',
      move: '按顺序扫描：源库位 → 商品条码 → 目标库位，最后填写数量并确认',
      outbound: '扫描出库单号，识别后可一键分配并发货',
      inbound: '扫描入库单号可一键确认入库；扫描 ASN 号可转入库单',
    };
    const ph = {
      auto: '请扫描商品条码、SKU、库位码或单据号…',
      move: this._moveStep === 0 ? '第 1 步：扫描源库位码…' : this._moveStep === 1 ? '第 2 步：扫描商品条码 / SKU…' : this._moveStep === 2 ? '第 3 步：扫描目标库位码…' : '第 4 步：填写移库数量并确认',
      outbound: '请扫描出库单号（OUT…）…',
      inbound: '请扫描入库单号（IN…）或 ASN 号…',
    };
    document.getElementById('sc_hint').textContent = hints[mode] || hints.auto;
    document.getElementById('sc_input').placeholder = ph[mode] || ph.auto;
    document.getElementById('sc_steps').style.display = mode === 'move' ? 'flex' : 'none';
    this.renderMoveSteps();
    if (mode !== 'move') {
      this._result = null;
      this.showEmpty('切换模式后，请扫描对应的条码或单号');
    }
    document.getElementById('sc_input').focus();
  },

  async submit(value) {
    const input = document.getElementById('sc_input');
    const code = (value ?? input.value).trim();
    if (!code) return UI.toast('请扫描或输入编码', 'warning');
    if (this._mode === 'move') return this.handleMoveScan(code);
    await this.resolve(code);
    input.value = '';
    input.focus();
  },

  async resolve(code) {
    const res = await API.get(`/scan/resolve?code=${encodeURIComponent(code)}`);
    if (res.code !== 0) {
      this.beep(false);
      this._result = null;
      this.showError(res.msg || '未识别编码', code);
      this.loadLogs();
      return;
    }
    this._result = res.data;
    this.beep(true);
    this.renderResult(res.data);
    this.loadTasks();
    this.loadLogs();
  },

  showEmpty(msg = '将光标保持在输入框，使用扫码枪扫描或手动输入编码后回车。') {
    document.getElementById('sc_result').innerHTML = `
      <div class="sc-empty">
        <div class="sc-empty-icon">⌗</div>
        <div class="sc-empty-title">等待扫描</div>
        <div class="sc-empty-sub">${csEscape(msg)}</div>
      </div>`;
  },

  showError(msg, code) {
    document.getElementById('sc_result').innerHTML = `
      <div class="sc-error">
        <div class="sc-error-icon">!</div>
        <div class="sc-error-title">未匹配到编码</div>
        <div class="sc-error-code mono">${csEscape(code)}</div>
        <div class="sc-error-sub">${csEscape(msg)}</div>
      </div>`;
  },

  renderResult(r) {
    const data = r.data || {};
    let body = '';
    if (r.type === 'product') {
      const p = data.product, s = data.stock || {};
      body = `
        <div class="sc-stat-grid">
          <div><label>总库存</label><b>${s.qty ?? 0}<small>${csEscape(p.unit || '')}</small></b></div>
          <div><label>可用库存</label><b class="ok">${s.avail ?? 0}</b></div>
          <div><label>分布库位</label><b>${s.locs ?? 0}</b></div>
          <div><label>安全库存</label><b>${p.min_stock ?? 0}</b></div>
        </div>
        ${data.locations?.length ? `<div class="sc-table">${data.locations.map(x => `
          <div class="sc-row">
            <span class="sc-row-main">${csEscape(x.location_code)} <em>${csEscape(x.warehouse_name)}</em></span>
            <span class="mono">${csEscape(x.batch_no || '无批次')}</span>
            <span class="sc-row-num">${x.quantity} / 可用 ${x.available_qty}</span>
          </div>`).join('')}</div>` : '<div class="sc-empty-sub">当前无库存分布</div>'}
        <div class="sc-result-actions">
          <button class="sc-btn ghost" onclick="loadPage('inventory')">查看实时库存</button>
        </div>`;
    } else if (r.type === 'location') {
      const l = data.location;
      body = `
        <div class="sc-stat-grid">
          <div><label>仓库</label><b class="sm">${csEscape(l.warehouse_name)}</b></div>
          <div><label>库区</label><b class="sm">${csEscape(l.area_name)}</b></div>
          <div><label>状态</label><b class="sm">${csEscape(l.status)}</b></div>
          <div><label>库存行</label><b>${(data.items || []).length}</b></div>
        </div>
        ${data.items?.length ? `<div class="sc-table">${data.items.map(x => `
          <div class="sc-row">
            <span class="sc-row-main">${csEscape(x.product_name)} <em>${csEscape(x.sku)}</em></span>
            <span class="mono">${csEscape(x.batch_no || '无批次')}</span>
            <span class="sc-row-num">${x.quantity} / 可用 ${x.available_qty}</span>
          </div>`).join('')}</div>` : '<div class="sc-empty-sub">该库位暂无库存</div>'}
        <div class="sc-result-actions">${this.actionsHtml(r.actions)}</div>`;
    } else {
      const order = data.order || data.asn || data.wave || {};
      const details = data.details || data.items || [];
      const stats = r.type === 'inbound' || r.type === 'outbound'
        ? `<div class="sc-stat-grid">
            <div><label>状态</label><b class="sm">${csEscape(order.status || '')}</b></div>
            <div><label>明细行</label><b>${details.length}</b></div>
            <div><label>${r.type === 'inbound' ? '供应商' : '客户'}</label><b class="sm">${csEscape(order.supplier_name || order.customer_name || '-')}</b></div>
            <div><label>仓库</label><b class="sm">${csEscape(order.warehouse_name || '-')}</b></div>
          </div>` : `<div class="sc-stat-grid">
            <div><label>状态</label><b class="sm">${csEscape(order.status || '')}</b></div>
            <div><label>明细</label><b>${details.length}</b></div>
          </div>`;
      body = stats + (details.length ? `<div class="sc-table">${details.map(x => `
        <div class="sc-row">
          <span class="sc-row-main">${csEscape(x.product_name || x.sku)} <em>${csEscape(x.sku || '')}</em></span>
          <span class="mono">${csEscape(x.batch_no || '')}</span>
          <span class="sc-row-num">${x.quantity ?? x.total_qty ?? x.qty}${x.received_qty != null ? ` / 已收 ${x.received_qty}` : ''}${x.picked_qty != null ? ` / 已拣 ${x.picked_qty}` : ''}</span>
        </div>`).join('')}</div>` : '') + `
        <div class="sc-result-actions">${this.actionsHtml(r.actions)}</div>`;
    }
    document.getElementById('sc_result').innerHTML = `
      <div class="sc-result-card">
        <div class="sc-result-head">
          <span class="sc-type-badge sc-type-${r.type}">${csEscape(r.badge)}</span>
          <div class="min-w-0">
            <div class="sc-result-title">${csEscape(r.title)}</div>
            <div class="sc-result-sub">${csEscape(r.subtitle || '')}</div>
          </div>
        </div>
        ${body}
      </div>`;
    document.getElementById('sc_input').focus();
  },

  actionsHtml(actions) {
    if (!actions?.length) return '';
    return actions.map(a => `
      <button class="sc-btn ${a.enabled ? 'primary' : 'disabled'}"
        onclick="PAGES.scan.runAction('${a.key}', ${a.enabled}, '${csEscape(a.reason || '')}')">
        ${csEscape(a.label)}
      </button>`).join('');
  },

  async runAction(key, enabled, reason) {
    if (!enabled) return UI.toast(reason || '当前操作不可用', 'warning');
    const r = this._result;
    if (!r) return;
    const d = r.data || {};
    if (key === 'move') {
      const code = d.location?.location_code || r.title;
      this.setMode('move');
      this._move = { from: code, product: '', to: '', qty: 1 };
      this._moveStep = 1;
      this.renderMoveSteps();
      UI.toast(`源库位已设为 ${code}，请扫描商品条码`, 'info');
      return;
    }
    const id = d.order?.id || d.asn?.id || d.wave?.id;
    if (!id) return;
    const no = d.order?.order_no || d.asn?.asn_no || d.wave?.wave_no || r.title;
    const label = r.actions?.find(a => a.key === key)?.label || '执行操作';
    UI.confirm(`确定对 ${no} 执行「${label}」吗？`, async () => {
      let res;
      if (key === 'confirm_inbound') res = await API.post(`/scan/inbound/${id}/confirm`, {});
      else if (key === 'ship_outbound') res = await API.post(`/scan/outbound/${id}/ship`, {});
      else if (key === 'asn_to_inbound') res = await API.post(`/scan/asn/${id}/to-inbound`, {});
      else if (key === 'wave_pick') res = await API.post(`/scan/wave/${id}/pick`, {});
      else return;
      if (res.code !== 0) { this.beep(false); UI.toast(res.msg, 'error'); return; }
      this.beep(true);
      UI.toast(res.msg, 'success');
      await this.resolve(no);
      this.loadTasks();
      this.loadLogs();
    }, false);
  },

  /* ---------- 快速移库 ---------- */
  async handleMoveScan(code) {
    if (this._moveStep >= 3) return UI.toast('请先填写数量并确认移库', 'warning');
    const res = await this.resolveSilent(code);
    if (res.code !== 0) { this.beep(false); return UI.toast(res.msg, 'error'); }
    const expect = this._moveStep === 1 ? 'product' : 'location';
    if (res.data.type !== expect) {
      this.beep(false);
      return UI.toast(this._moveStep === 1 ? '请扫描商品条码或 SKU' : '请扫描库位码', 'error');
    }
    if (this._moveStep === 0) {
      this._move.from = res.data.data.location.location_code;
      this._moveStep = 1;
      UI.toast(`源库位 ${this._move.from} 已确认，请扫描商品`, 'info');
    } else if (this._moveStep === 1) {
      this._move.product = res.data.data.product.barcode || res.data.data.product.sku;
      this._moveStep = 2;
      UI.toast(`商品 ${res.data.title} 已确认，请扫描目标库位`, 'info');
    } else if (this._moveStep === 2) {
      this._move.to = res.data.data.location.location_code;
      this._moveStep = 3;
      UI.toast(`目标库位 ${this._move.to} 已确认，请填写数量`, 'info');
    }
    this.beep(true);
    this.renderMoveSteps();
    this.loadLogs();
    const input = document.getElementById('sc_input');
    input.value = '';
    input.focus();
    if (this._moveStep === 3) {
      const qty = document.getElementById('sc_move_qty');
      if (qty) qty.focus();
    }
  },

  async resolveSilent(code) {
    return API.get(`/scan/resolve?code=${encodeURIComponent(code)}`);
  },

  renderMoveSteps() {
    const box = document.getElementById('sc_steps_body');
    if (!box) return;
    const m = this._move;
    const steps = [
      ['源库位', m.from],
      ['商品条码', m.product],
      ['目标库位', m.to],
      ['移库数量', this._moveStep >= 3 ? '待确认' : ''],
    ];
    box.innerHTML = steps.map(([label, val], i) => `
      <div class="sc-step ${i === this._moveStep ? 'active' : ''} ${val ? 'done' : ''}">
        <i>${i + 1}</i>
        <div><b>${label}</b><span>${csEscape(val || '等待扫描')}</span></div>
      </div>`).join('') + `
      <div class="sc-qty-row">
        <label>数量</label>
        <input type="number" min="1" id="sc_move_qty" value="${m.qty || 1}"
          onchange="PAGES.scan._move.qty=Number(this.value)||1">
        <button class="sc-btn primary" onclick="PAGES.scan.executeMove()">确认移库</button>
      </div>`;
    const input = document.getElementById('sc_input');
    if (input) {
      input.placeholder = [
        '第 1 步：扫描源库位码…',
        '第 2 步：扫描商品条码 / SKU…',
        '第 3 步：扫描目标库位码…',
        '第 4 步：填写移库数量并确认',
      ][Math.min(this._moveStep, 3)];
    }
  },

  resetMove() {
    this._move = { from: '', product: '', to: '', qty: 1 };
    this._moveStep = 0;
    this.renderMoveSteps();
    document.getElementById('sc_input').placeholder = '第 1 步：扫描源库位码…';
    UI.toast('移库流程已重置', 'info');
  },

  async executeMove() {
    const m = this._move;
    if (!m.from || !m.product || !m.to) return UI.toast('请先完成前 3 步扫描', 'warning');
    const qtyEl = document.getElementById('sc_move_qty');
    const qty = Number(qtyEl?.value || m.qty || 1);
    if (qty <= 0) return UI.toast('数量必须大于 0', 'error');
    const res = await API.post('/scan/move', {
      from_code: m.from, product_code: m.product, to_code: m.to, quantity: qty,
    });
    if (res.code !== 0) { this.beep(false); return UI.toast(res.msg, 'error'); }
    this.beep(true);
    UI.toast(res.msg, 'success');
    document.getElementById('sc_result').innerHTML = `
      <div class="sc-success">
        <div class="sc-success-icon">✓</div>
        <div class="sc-success-title">移库完成</div>
        <div class="sc-success-sub">${csEscape(m.product)} × ${qty} 件：${csEscape(m.from)} → ${csEscape(m.to)}</div>
      </div>`;
    this.resetMove();
    this._moveStep = 0;
    this.renderMoveSteps();
    this.loadLogs();
    this.loadTasks();
  },

  /* ---------- 任务与日志 ---------- */
  async loadTasks() {
    const res = await API.get('/scan/tasks');
    if (res.code !== 0) return;
    const c = res.data.counts || {};
    document.getElementById('sc_tasks').innerHTML = `
      <span class="sc-task-chip">入库待处理 <b>${c.inbound || 0}</b></span>
      <span class="sc-task-chip">出库待发货 <b>${c.outbound || 0}</b></span>
      <span class="sc-task-chip">待收货 ASN <b>${c.asn || 0}</b></span>
      <span class="sc-task-chip">待拣波次 <b>${c.wave || 0}</b></span>`;
  },

  async loadLogs() {
    const res = await API.get('/scan/logs?limit=12');
    if (res.code !== 0) return;
    const box = document.getElementById('sc_log');
    if (!res.data.length) { box.innerHTML = '<div class="sc-empty-sub">暂无扫描记录</div>'; return; }
    const icons = { product: '🏷️', location: '📍', inbound: '📥', outbound: '📤',
      asn: '🚚', wave: '🌊', move: '🔄', unknown: '❔' };
    box.innerHTML = res.data.map(x => `
      <div class="sc-log-item">
        <span class="sc-log-icon">${icons[x.scan_type] || '⌗'}</span>
        <div class="min-w-0">
          <div class="sc-log-code">${csEscape(x.ref_no || x.code)}</div>
          <div class="sc-log-meta">${csEscape(x.scan_type)} · ${csEscape(x.action)} · ${fmtTime(x.create_time).slice(11, 16)}</div>
        </div>
        <span class="sc-log-result ${x.result === 'success' ? 'ok' : 'bad'}">${x.result === 'success' ? '成功' : '未识别'}</span>
      </div>`).join('');
  },

  /* ---------- 声音反馈 ---------- */
  beep(ok = true) {
    try {
      if (!this._audio) this._audio = new (window.AudioContext || window.webkitAudioContext)();
      const ctx = this._audio;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = ok ? 880 : 260;
      gain.gain.setValueAtTime(0.08, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.12);
      osc.start();
      osc.stop(ctx.currentTime + 0.13);
    } catch (e) {}
    try { navigator.vibrate?.(ok ? 30 : [60, 40, 60]); } catch (e) {}
  },

  /* ---------- 摄像头扫码 ---------- */
  cameraScan() {
    if (!('BarcodeDetector' in window)) return UI.toast('当前浏览器不支持摄像头识码，请使用扫码枪', 'warning');
    const m = UI.modal({
      title: '摄像头扫码', size: 'modal-lg', okText: '关闭', onOk: async () => true,
      body: `<div class="sc-camera"><video id="sc_video" playsinline muted></video>
        <div class="sc-camera-tip">将条码对准取景框，识别后自动填入</div></div>`,
    });
    m.el.addEventListener('hidden.bs.modal', () => this.stopCamera());
    this.startCamera();
  },

  async startCamera() {
    try {
      this._camStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      const video = document.getElementById('sc_video');
      if (!video) return;
      video.srcObject = this._camStream;
      await video.play();
      const detector = new BarcodeDetector({ formats: ['ean_13', 'ean_8', 'code_128', 'code_39', 'qr_code'] });
      this._camTimer = setInterval(async () => {
        try {
          const codes = await detector.detect(video);
          if (codes?.length) {
            const value = codes[0].rawValue;
            this.stopCamera();
            document.querySelectorAll('.modal.show').forEach(el => bootstrap.Modal.getInstance(el)?.hide());
            const input = document.getElementById('sc_input');
            if (input) { input.value = value; this.submit(value); }
          }
        } catch (e) {}
      }, 500);
    } catch (e) {
      UI.toast('无法启动摄像头：' + e.message, 'error');
      this.stopCamera();
    }
  },

  stopCamera() {
    if (this._camTimer) clearInterval(this._camTimer);
    this._camTimer = null;
    try { this._camStream?.getTracks().forEach(t => t.stop()); } catch (e) {}
    this._camStream = null;
  },
};
