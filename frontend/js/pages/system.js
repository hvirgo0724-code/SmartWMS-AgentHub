/* 系统管理页面：系统参数 / 操作日志 */
PAGES.configs = {
  title: '系统参数配置',
  async render(el) {
    const [res, llmCfg] = await Promise.all([API.get('/configs'), API.get('/configs/llm')]);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._cache = res.data;
    this._llm = llmCfg.code === 0 ? llmCfg.data : {};
    const c = this._llm;
    el.innerHTML = `
      <div class="card mb-3 llm-config-card">
        <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <span>AI 大模型配置 <span class="text-muted small">OpenAI 兼容接口 · 用于天气理解、翻译与开放域问答</span></span>
          <span class="badge ${c.enabled ? 'text-bg-success' : 'text-bg-secondary'}" id="llm_badge">
            ${c.enabled ? '已启用' : '未配置'}
          </span>
        </div>
        <div class="card-body">
          <div class="row g-2">
            <div class="col-lg-5">${UI.field('Base URL', UI.input('llm_base', c.base || '', 'text', 'placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"'))}</div>
            <div class="col-lg-3">${UI.field('模型名称', UI.input('llm_model', c.model || 'qwen-plus', 'text', 'placeholder="qwen-plus"'))}</div>
            <div class="col-lg-2">${UI.field('超时（秒）', UI.input('llm_timeout', c.timeout || 30, 'number', 'min=5 max=120'))}</div>
            <div class="col-lg-2 d-flex align-items-end mb-3">
              <button class="btn btn-sm btn-primary w-100" onclick="PAGES.configs.saveLlm(this)">保存</button>
            </div>
            <div class="col-12">${UI.field('API Key', UI.input('llm_key', '', 'password', `placeholder="${c.key_masked ? '已配置：' + c.key_masked + '，留空保持不变' : '请输入 API Key'}"`))}</div>
          </div>
          <div class="d-flex align-items-center gap-2 flex-wrap">
            <button class="btn btn-sm btn-outline-primary" onclick="PAGES.configs.testLlm(this)">测试连接</button>
            <span class="text-muted small" id="llm_test_status">支持通义千问 DashScope、DeepSeek、OpenAI 等兼容接口；未配置时自动使用本地检索式回答。</span>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-header">全局系统参数</div>
        <div class="card-body p-0" id="cf_list"></div>
      </div>`;
    document.getElementById('cf_list').innerHTML = UI.table([
      { key: 'config_key', title: '参数键', class: 'mono' },
      { key: 'config_value', title: '参数值' },
      { key: 'description', title: '说明' },
      { key: 'update_time', title: '更新时间', render: r => fmtTime(r.update_time) },
      { title: '操作', render: r => `<button class="btn btn-sm btn-outline-primary" onclick="PAGES.configs.edit(${r.id})">修改</button>` },
    ], res.data);
  },
  async saveLlm(btn) {
    const body = {
      base: document.querySelector('[name=llm_base]').value.trim(),
      model: document.querySelector('[name=llm_model]').value.trim(),
      timeout: Number(document.querySelector('[name=llm_timeout]').value || 30),
      key: document.querySelector('[name=llm_key]').value.trim(),
    };
    btn.disabled = true;
    const res = await API.put('/configs/llm', body);
    btn.disabled = false;
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const c = res.data;
    this._llm = c;
    const badge = document.getElementById('llm_badge');
    badge.textContent = c.enabled ? '已启用' : '未配置';
    badge.className = 'badge ' + (c.enabled ? 'text-bg-success' : 'text-bg-secondary');
    const keyInput = document.querySelector('[name=llm_key]');
    keyInput.value = '';
    keyInput.placeholder = c.key_masked ? `已配置：${c.key_masked}，留空保持不变` : '请输入 API Key';
    UI.toast('大模型配置已保存');
  },
  async testLlm(btn) {
    btn.disabled = true;
    const status = document.getElementById('llm_test_status');
    status.textContent = '正在测试连接…';
    const res = await API.post('/configs/llm/test', {});
    btn.disabled = false;
    if (res.code !== 0) {
      status.textContent = res.msg;
      return UI.toast(res.msg, 'error');
    }
    status.textContent = `连接成功：${res.data.answer}（${res.data.latency_ms}ms）`;
    UI.toast('大模型连接成功');
  },
  edit(id) {
    const data = this._cache.find(c => c.id === id);
    const m = UI.modal({
      title: `修改参数 · ${data.config_key}`,
      body: UI.field('参数值', UI.input('config_value', data.config_value)) +
        `<div class="text-muted small">${data.description || ''}</div>`,
      onOk: async () => {
        const d = UI.formData(m.id);
        const res = await API.put(`/configs/${id}`, d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('更新成功'); loadPage('configs'); return true;
      },
    });
  },
};

PAGES.logs = {
  title: '操作日志',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <span>操作日志（审计追踪）</span>
          <div class="d-flex gap-2">
            <input class="form-control form-control-sm" id="lg_kw" placeholder="用户/操作内容" style="width:180px">
            <button class="btn btn-sm btn-outline-primary" onclick="PAGES.logs.load(1)">搜索</button>
          </div>
        </div>
        <div class="card-body p-0" id="lg_list"></div>
        <div class="card-footer bg-white" id="lg_page"></div>
      </div>`;
    this.load(1);
  },
  async load(page = 1) {
    const kw = document.getElementById('lg_kw')?.value || '';
    const res = await API.get(`/logs?page=${page}&size=20&keyword=${encodeURIComponent(kw)}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    document.getElementById('lg_list').innerHTML = UI.table([
      { key: 'id', title: 'ID', width: '70px' },
      { key: 'username', title: '操作用户' },
      { key: 'module', title: '模块' },
      { key: 'action', title: '动作' },
      { key: 'detail', title: '详情' },
      { key: 'ip', title: 'IP', class: 'mono' },
      { key: 'create_time', title: '时间', render: r => fmtTime(r.create_time) },
    ], res.data.list);
    document.getElementById('lg_page').innerHTML = UI.pagination(res.data.total, page, 20, 'PAGES.logs.load');
  },
};
