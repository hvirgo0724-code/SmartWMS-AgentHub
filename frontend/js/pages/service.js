/* 智能客服工作台 / 服务工单 / 知识库管理 */

/* ---------- 轻量 Markdown 渲染（防 XSS） ---------- */
function csEscape(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function csMarkdown(text, citations = []) {
  const map = {};
  let n = 0;
  (citations || []).forEach(c => { if (!map[c.doc_id]) map[c.doc_id] = ++n; });
  const lines = csEscape(text).split('\n');
  return lines.map(line => {
    let l = line;
    l = l.replace(/\[(\d+)\]/g, (m, num) =>
      `<span class="cs-cite-ref" title="查看引用" onclick="PAGES.service.showCitation(${num})">[${num}]</span>`);
    l = l.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
    l = l.replace(/`([^`]+)`/g, '<code>$1</code>');
    if (/^###\s+/.test(l)) return `<div class="cs-md-h">${l.replace(/^###\s+/, '')}</div>`;
    if (/^\s*[-•]\s+/.test(l)) return `<div class="cs-md-li">${l.replace(/^\s*[-•]\s+/, '')}</div>`;
    if (/^&gt;\s+/.test(l)) return `<div class="cs-md-quote">${l.replace(/^&gt;\s+/, '')}</div>`;
    if (!l.trim()) return '<div class="cs-md-gap"></div>';
    return `<div class="cs-md-line">${l}</div>`;
  }).join('');
}

function csCitationList(citations = []) {
  const seen = {}, list = [];
  citations.forEach(c => {
    if (seen[c.doc_id]) {
      const item = list[seen[c.doc_id] - 1];
      if (item) item.chunks++;
      return;
    }
    seen[c.doc_id] = list.length + 1;
    list.push({ ...c, num: list.length + 1, chunks: 1 });
  });
  return list;
}

/* ==================== 智能客服工作台 ==================== */
PAGES.service = {
  title: '智能客服工作台',
  _sessionId: null,
  _sending: false,
  _citations: [],
  _lastQuestion: '',
  _ctrl: null,
  _eventCtrl: null,
  _agents: [],
  _lastAgents: [],
  _humanStatus: 'active',
  _humanAgent: '',
  _lastEventId: 0,
  _seenMessageIds: new Set(),

  destroy() {
    try { this._ctrl?.abort(); } catch (e) {}
    try { this._eventCtrl?.abort(); } catch (e) {}
    this._ctrl = null;
    this._eventCtrl = null;
  },

  async render(el) {
    el.innerHTML = `
      <div class="cs-layout">
        <aside class="cs-card cs-side">
          <div class="cs-side-head">
            <div>
              <div class="cs-side-title">会话</div>
              <div class="cs-side-sub" id="cs_stats_line">加载中…</div>
            </div>
            <button class="btn btn-sm btn-primary" onclick="PAGES.service.newSession()">＋</button>
          </div>
          <div class="cs-side-list" id="cs_session_list"></div>
          <div class="cs-side-foot">
            <div class="cs-mode" id="cs_mode"></div>
            <a class="cs-side-link" href="javascript:loadPage('kb')" id="cs_kb_link">📚 知识库管理</a>
          </div>
        </aside>

        <section class="cs-card cs-main">
          <div class="cs-main-head">
            <div class="d-flex align-items-center gap-2 min-w-0">
              <div class="cs-brand"><span>🤖</span></div>
              <div class="min-w-0">
                <div class="cs-main-title">WMS 智能客服 <span class="cs-live-dot"></span></div>
                <div class="cs-main-sub" id="cs_main_sub">多 Agent 协作 · RAG 知识增强 · 实时业务数据</div>
              </div>
            </div>
            <div class="d-flex gap-2">
              <button class="btn btn-sm btn-outline-secondary cs-sessions-toggle" onclick="PAGES.service.showSessions()">🗂 会话</button>
              <button class="btn btn-sm btn-outline-secondary cs-trace-toggle" onclick="PAGES.service.showTrace()">🧩 轨迹</button>
              <button class="btn btn-sm btn-outline-secondary" onclick="PAGES.service.showAgents()">🧩 Agent</button>
              <button class="btn btn-sm btn-outline-danger" onclick="PAGES.service.ticketModal()">🎫 转人工</button>
            </div>
          </div>
          <div class="cs-human-banner" id="cs_human_banner" style="display:none"></div>
          <div class="cs-messages" id="cs_messages"></div>
          <div class="cs-suggest" id="cs_suggest"></div>
          <div class="cs-input-wrap">
            <textarea class="cs-input" id="cs_input" rows="1" placeholder="问我库存、单据、预警、补货、供应商协同或系统操作…（Enter 发送，Shift+Enter 换行）"></textarea>
            <button class="cs-send" id="cs_send" onclick="PAGES.service.send()" title="发送">➤</button>
          </div>
          <div class="cs-input-tip">回答由 RAG 知识库与实时业务数据生成，重要数据请以单据页面为准。</div>
        </section>

        <aside class="cs-card cs-trace">
          <div class="cs-trace-head">
            <div>
              <div class="cs-side-title">Agent 协作轨迹</div>
              <div class="cs-side-sub" id="cs_trace_sub">每次提问实时展示</div>
            </div>
            <span class="cs-conf" id="cs_conf">—</span>
          </div>
          <div class="cs-trace-body" id="cs_trace_body">
            <div class="cs-empty-trace">
              <div class="cs-empty-icon">🧭</div>
              <div>发送问题后，这里会展示<br>路由 → 检索 → 业务查询 → 生成</div>
            </div>
          </div>
          <div class="cs-cite-head">知识引用 <span id="cs_cite_count">0</span></div>
          <div class="cs-cite-body" id="cs_cite_body">
            <div class="cs-cite-empty">暂无引用</div>
          </div>
        </aside>
      </div>`;

    const input = document.getElementById('cs_input');
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.send(); }
    });

    if (!hasPerm('cs:kb')) {
      const link = document.getElementById('cs_kb_link');
      if (link) link.style.display = 'none';
    }

    this._humanStatus = 'active';
    this._humanAgent = '';
    this._lastEventId = 0;
    this._seenMessageIds = new Set();
    this.applyHumanStatus('active', '');
    this.showWelcome();
    const [catalog, stats, sessions] = await Promise.all([
      API.get('/cs/agents'), API.get('/cs/stats'), API.get('/cs/sessions?page=1&size=20')
    ]);
    if (catalog.code === 0) {
      this._agents = catalog.data.agents || [];
      const mode = catalog.data.llm?.enabled ? '大模型生成模式' : '本地检索式模式';
      const kb = catalog.data.kb || {};
      document.getElementById('cs_mode').innerHTML =
        `<span class="cs-dot ${catalog.data.llm?.enabled ? 'on' : 'off'}"></span>${mode} · 知识 ${kb.published || 0} 篇 / ${kb.chunks || 0} 切片`;
      document.getElementById('cs_main_sub').textContent =
        `${mode} · ${kb.published || 0} 篇知识 · ${(this._agents || []).length} 个专职 Agent`;
    }
    if (stats.code === 0) {
      const d = stats.data;
      document.getElementById('cs_stats_line').textContent =
        `今日 ${d.today_sessions} 次会话 · ${d.resolved_tickets} 个工单已解决`;
    }
    if (sessions.code === 0) this.renderSessions(sessions.data.list);
  },

  showWelcome() {
    const examples = [
      ['📦', '库存查询', '蒙牛纯牛奶还有多少库存？'],
      ['📥', '单据进度', '入库单 IN20260825001 到哪一步了？'],
      ['🚚', '供应商协同', '供应商 SUP001 的准时率和合格率怎么样？'],
      ['⏰', '效期管理', '最近有哪些临期批次？'],
    ];
    document.getElementById('cs_messages').innerHTML = `
      <div class="cs-welcome">
        <div class="cs-welcome-icon">🤖</div>
        <div class="cs-welcome-title">你好，我是 WMS 智能客服</div>
        <div class="cs-welcome-sub">由 6 个专职 Agent 协作：意图路由、RAG 知识检索、实时业务查询、供应商协同、通用问答、工单升级。<br>我会给出可溯源的知识引用与实时数据，不确定时会主动建议转人工。</div>
        <div class="cs-example-grid">
          ${examples.map(([icon, tag, q]) => `
            <button class="cs-example" onclick="PAGES.service.quick(this)" data-q="${csEscape(q)}">
              <span class="cs-example-icon">${icon}</span>
              <span><i>${tag}</i><b>${q}</b></span>
            </button>`).join('')}
        </div>
      </div>`;
    this.renderSuggestions(['入库单怎么创建和确认？', '按供应商汇总补货清单', '如何给商品指定默认供应商？', '库存不足出库失败怎么办？']);
  },

  renderSuggestions(items) {
    document.getElementById('cs_suggest').innerHTML = (items || []).map(t =>
      `<button class="cs-chip" onclick="PAGES.service.quick(this)" data-q="${csEscape(t)}">${csEscape(t)}</button>`).join('');
  },

  renderSessions(list) {
    this._sessions = list || [];
    const box = document.getElementById('cs_session_list');
    if (!list || !list.length) {
      box.innerHTML = `<div class="cs-empty-session">暂无会话，点击右上角 ＋ 开始</div>`;
      return;
    }
    box.innerHTML = list.map(s => `
      <button class="cs-session ${s.id === this._sessionId ? 'active' : ''}" onclick="PAGES.service.openSession(${s.id})">
        <div class="cs-session-title">${csEscape(s.title || '新会话')}</div>
        <div class="cs-session-meta">
          <span>${s.message_count || 0} 条</span>
          <span>${(s.update_time || '').slice(5, 16).replace('T', ' ')}</span>
        </div>
      </button>`).join('');
  },

  async refreshSessions() {
    const res = await API.get('/cs/sessions?page=1&size=20');
    if (res.code === 0) this.renderSessions(res.data.list);
  },

  showSessions() {
    const list = this._sessions || [];
    const m = UI.modal({
      title: '🗂 我的会话', size: 'modal-lg', okText: '关闭', onOk: async () => true,
      body: `<div class="d-flex justify-content-end mb-2">
          <button class="btn btn-sm btn-primary" onclick="PAGES.service.newSession();PAGES.service._sessionModal?.hide()">＋ 新会话</button>
        </div>` +
        (list.length ? list.map(s => `
          <button class="cs-session w-100 ${s.id === this._sessionId ? 'active' : ''}"
                  onclick="PAGES.service.pickSession(${s.id})">
            <div class="cs-session-title">${csEscape(s.title || '新会话')}</div>
            <div class="cs-session-meta"><span>${s.message_count || 0} 条</span>
              <span>${(s.update_time || '').slice(5, 16).replace('T', ' ')}</span></div>
          </button>`).join('') : '<div class="text-muted small text-center py-3">暂无会话</div>'),
    });
    this._sessionModal = m.inst;
  },

  pickSession(id) {
    try { this._sessionModal?.hide(); } catch (e) {}
    this.openSession(id);
  },

  async newSession() {
    const res = await API.post('/cs/sessions', { title: '新会话' });
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this.stopEvents();
    this._sessionId = res.data.id;
    this._lastQuestion = '';
    this._citations = [];
    this._humanStatus = 'active';
    this._humanAgent = '';
    this._lastEventId = 0;
    this._seenMessageIds = new Set();
    this.applyHumanStatus('active', '');
    this.showWelcome();
    this.clearTrace();
    document.getElementById('cs_input').value = '';
    this.refreshSessions();
    this.startEvents();
    UI.toast('已创建新会话');
  },

  async openSession(id) {
    if (this._sending) return;
    this.stopEvents();
    const res = await API.get(`/cs/sessions/${id}/messages`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._sessionId = id;
    const box = document.getElementById('cs_messages');
    box.innerHTML = '';
    const msgs = res.data.messages || [];
    this._seenMessageIds = new Set(msgs.map(m => m.id));
    this._lastEventId = msgs.length ? msgs[msgs.length - 1].id : 0;
    const session = res.data.session || {};
    this.applyHumanStatus(session.status || 'active', session.human_agent || '');
    if (!msgs.length) this.showWelcome();
    msgs.forEach(m => box.insertAdjacentHTML('beforeend', this.messageHtml(m)));
    this.scrollBottom();
    this.renderSessions((await API.get('/cs/sessions?page=1&size=20')).data?.list || []);
    this.startEvents();
    const lastAi = [...msgs].reverse().find(m => m.role === 'assistant');
    if (lastAi) {
      this._citations = lastAi.citations || [];
      this._lastQuestion = [...msgs].reverse().find(m => m.role === 'user')?.content || '';
      this.renderCitations(this._citations);
      this.setConfidence(lastAi.confidence);
      this.renderTraceFromTools(lastAi);
      this.renderSuggestions(lastAi.suggestions?.length ? lastAi.suggestions : ['继续追问', '转人工客服']);
    } else {
      this.clearTrace();
    }
  },

  messageHtml(m) {
    if (m.role === 'system') {
      return `<div class="cs-system-note"><span>🔔</span>${csEscape(m.content)}</div>`;
    }
    if (m.role === 'user') {
      return `<div class="cs-msg cs-msg-user">
        <div class="cs-bubble cs-bubble-user">${csEscape(m.content).replace(/\n/g, '<br>')}</div>
        <div class="cs-avatar cs-avatar-user">${csEscape((JSON.parse(localStorage.getItem('user') || '{}').real_name || '我').slice(0, 1))}</div>
      </div>`;
    }
    if (m.role === 'agent') {
      return `<div class="cs-msg cs-msg-ai cs-msg-agent">
        <div class="cs-avatar cs-avatar-agent">🎧</div>
        <div class="cs-bubble cs-bubble-agent">
          <div class="cs-human-name">人工客服 · ${csEscape(m.sender_name || m.agent || '坐席')}</div>
          <div class="cs-answer">${csEscape(m.content).replace(/\n/g, '<br>')}</div>
        </div>
      </div>`;
    }
    const tools = (m.tools || m.tool_results || []);
    return `<div class="cs-msg cs-msg-ai" data-mid="${m.id}">
      <div class="cs-avatar">🤖</div>
      <div class="cs-bubble">
        ${m.agent && m.agent !== 'SupervisorAgent' ? `<div class="cs-agent-tag">${csEscape(m.agent)}</div>` : ''}
        <div class="cs-answer">${csMarkdown(m.content, m.citations || [])}</div>
        ${tools.length ? this.toolCardsHtml(tools) : ''}
        ${this.feedbackHtml(m)}
      </div>
    </div>`;
  },

  toolCardsHtml(tools) {
    return `<div class="cs-tool-wrap">${tools.map(t => `
      <div class="cs-tool ${t.ok ? 'ok' : 'warn'}">
        <div class="cs-tool-head">
          <span>${t.agent === 'supplier' ? '🚚' : '🗄️'} ${csEscape(t.title || t.label || '查询')}</span>
          <span class="cs-tool-status">${t.ok ? '实时数据' : '未获取'}</span>
        </div>
        <div class="cs-tool-body">${csEscape(t.summary || '').split('\n').map(x => `<div>${x || '&nbsp;'}</div>`).join('')}</div>
        ${t.link ? `<a class="cs-tool-link" href="javascript:loadPage('${t.link}')">打开对应模块 →</a>` : ''}
      </div>`).join('')}</div>`;
  },

  feedbackHtml(m) {
    if (!m.id) return '';
    const f = Number(m.feedback || 0);
    return `<div class="cs-feedback" data-mid="${m.id}">
      <button class="cs-fb ${f === 1 ? 'active' : ''}" title="有帮助" onclick="PAGES.service.feedback(${m.id}, 1, this)">👍</button>
      <button class="cs-fb ${f === -1 ? 'active' : ''}" title="没帮助" onclick="PAGES.service.feedback(${m.id}, -1, this)">👎</button>
      <span class="cs-fb-tip">这个回答有帮助吗？</span>
    </div>`;
  },

  async feedback(mid, rating, btn) {
    const res = await API.post(`/cs/messages/${mid}/feedback`, { rating });
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const box = btn.parentElement;
    box.querySelectorAll('.cs-fb').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    box.querySelector('.cs-fb-tip').textContent = rating > 0 ? '已记录：有帮助' : '已记录，我们会继续优化';
  },

  quick(btn) {
    const q = btn.dataset.q || btn.textContent.trim();
    document.getElementById('cs_input').value = q;
    this.send(q);
  },

  async send(explicit) {
    if (this._sending) return;
    const input = document.getElementById('cs_input');
    const text = (explicit ?? input.value).trim();
    if (!text) return;
    this._sending = true;
    this._lastQuestion = text;
    document.getElementById('cs_send').disabled = true;
    input.value = '';
    input.style.height = 'auto';

    if (!this._sessionId) {
      const res = await API.post('/cs/sessions', { title: text.slice(0, 30) });
      if (res.code !== 0) {
        this._sending = false;
        document.getElementById('cs_send').disabled = false;
        return UI.toast(res.msg, 'error');
      }
      this._sessionId = res.data.id;
      this._seenMessageIds = new Set();
      this._lastEventId = 0;
      this.startEvents();
    }

    const box = document.getElementById('cs_messages');
    if (box.querySelector('.cs-welcome')) box.innerHTML = '';
    box.insertAdjacentHTML('beforeend', `<div class="cs-msg cs-msg-user">
      <div class="cs-bubble cs-bubble-user">${csEscape(text).replace(/\n/g, '<br>')}</div>
      <div class="cs-avatar cs-avatar-user">${csEscape((JSON.parse(localStorage.getItem('user') || '{}').real_name || '我').slice(0, 1))}</div>
    </div>`);
    this.scrollBottom();

    // 人工接管中：消息直接进入人工队列，不再触发 AI
    if (this._humanStatus === 'waiting' || this._humanStatus === 'human') {
      const r = await API.post('/cs/chat', { session_id: this._sessionId, message: text });
      this._sending = false;
      document.getElementById('cs_send').disabled = false;
      if (r.code !== 0) return UI.toast(r.msg, 'error');
      this.markSeen(r.data.user_message_id);
      if (this._humanStatus === 'waiting') UI.toast('消息已进入人工队列，等待客服接入', 'info');
      else UI.toast('已发送给人工客服', 'info');
      this.refreshSessions();
      return;
    }

    const pendingId = 'cs_pending_' + Date.now();
    box.insertAdjacentHTML('beforeend', `<div class="cs-msg cs-msg-ai" id="${pendingId}">
      <div class="cs-avatar">🤖</div>
      <div class="cs-bubble cs-bubble-pending">
        <div class="cs-thinking"><span class="cs-typing"><i></i><i></i><i></i></span> 多 Agent 协同处理中…</div>
        <div class="cs-live-steps" id="${pendingId}_steps"></div>
      </div></div>`);
    this.scrollBottom();

    this.clearTrace();
    LoadingBar.start();
    const onStage = (agent) => {
      const steps = document.getElementById(`${pendingId}_steps`);
      if (steps) steps.insertAdjacentHTML('beforeend', `
        <div class="cs-live-step">
          <span>${agent.icon || '•'}</span><b>${csEscape(agent.label)}</b>
          <em>${csEscape(agent.detail)}</em><i>${agent.ms}ms</i>
        </div>`);
      this.appendTrace(agent);
      this.scrollBottom();
    };

    let finalRes = null;
    try {
      await this.stream(text, {
        stage: onStage,
        error: msg => { throw new Error(msg); },
        answer: data => { finalRes = data; },
      });
    } catch (e) {
      const pend = document.getElementById(pendingId);
      if (pend) pend.querySelector('.cs-bubble').innerHTML =
        `<div class="cs-error">⚠️ ${csEscape(e.message || '智能客服暂时不可用')}<button class="btn btn-sm btn-outline-primary ms-2" onclick="PAGES.service.retry()">重试</button></div>`;
      this._sending = false;
      document.getElementById('cs_send').disabled = false;
      LoadingBar.done();
      return;
    }

    LoadingBar.done();
    this._sending = false;
    document.getElementById('cs_send').disabled = false;
    if (!finalRes) return;

    this._sessionId = finalRes.session_id;
    this._citations = finalRes.citations || [];
    this.markSeen(finalRes.user_message_id);
    this.markSeen(finalRes.message_id);
    const pend = document.getElementById(pendingId);
    if (pend) {
      pend.dataset.mid = finalRes.message_id;
      pend.querySelector('.cs-bubble').outerHTML = `<div class="cs-bubble">
        <div class="cs-answer">${csMarkdown(finalRes.answer, finalRes.citations || [])}</div>
        ${(finalRes.tools || []).length ? this.toolCardsHtml(finalRes.tools) : ''}
        ${this.feedbackHtml({ id: finalRes.message_id, feedback: 0 })}
        <div class="cs-answer-foot">
          <span>置信度 ${(finalRes.confidence * 100).toFixed(0)}%</span>
          <span>${finalRes.llm_used ? '大模型生成' : '本地检索生成'}</span>
          <span>${finalRes.latency_ms}ms</span>
          <span class="cs-intent-badge">${csEscape(finalRes.intent?.label || '')}</span>
        </div>
      </div>`;
    }
    this.renderSuggestions(finalRes.suggestions || []);
    this.renderCitations(this._citations);
    this.renderTrace(finalRes.agents || []);
    this.setConfidence(finalRes.confidence);
    if (finalRes.ticket) {
      this.applyHumanStatus('waiting', '');
      UI.toast(`已创建工单 ${finalRes.ticket.ticket_no}，正在等待人工接入`, 'info');
    }
    this.scrollBottom();
    this.refreshSessions();
  },

  retry() {
    if (this._lastQuestion) this.send(this._lastQuestion);
  },

  async stream(text, handlers) {
    const ctrl = new AbortController();
    this._ctrl = ctrl;
    const res = await fetch(API.base + '/cs/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'token': API.token() },
      body: JSON.stringify({ session_id: this._sessionId, message: text }),
      signal: ctrl.signal,
    });
    if (res.status === 401) { localStorage.removeItem('token'); location.href = '/'; return; }
    if (!res.ok || !res.body) throw new Error('无法连接智能客服服务');
    await this.readSSE(res, (event, payload) => {
      if (event === 'stage') handlers.stage(payload);
      else if (event === 'answer') handlers.answer(payload);
      else if (event === 'error') handlers.error(payload.msg || '处理失败');
    });
  },

  async readSSE(res, onEvent) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let event = 'message', data = '';
        block.split('\n').forEach(line => {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) data += line.slice(5).trim();
        });
        if (!data) continue;
        let payload;
        try { payload = JSON.parse(data); } catch (e) { continue; }
        onEvent(event, payload);
      }
    }
  },

  markSeen(id) {
    if (id) this._seenMessageIds.add(Number(id));
  },

  applyHumanStatus(status, agent) {
    this._humanStatus = status || 'active';
    this._humanAgent = agent || '';
    const banner = document.getElementById('cs_human_banner');
    const input = document.getElementById('cs_input');
    if (!banner) return;
    if (this._humanStatus === 'waiting') {
      banner.style.display = 'flex';
      banner.className = 'cs-human-banner waiting';
      banner.innerHTML = `<span>⏳</span><div><b>正在等待人工客服接入</b>
        <em>消息会进入人工队列，接入后客服可实时回复</em></div>`;
      if (input) input.placeholder = '输入补充信息，等待人工客服接入…';
    } else if (this._humanStatus === 'human') {
      banner.style.display = 'flex';
      banner.className = 'cs-human-banner human';
      banner.innerHTML = `<span>🎧</span><div><b>人工客服 ${csEscape(this._humanAgent || '')} 正在为你服务</b>
        <em>当前为人工会话，消息将实时发送给坐席</em></div>`;
      if (input) input.placeholder = '输入消息发送给人工客服…（Enter 发送）';
    } else {
      banner.style.display = 'none';
      if (input) input.placeholder = '问我库存、单据、预警、补货、供应商协同或系统操作…（Enter 发送，Shift+Enter 换行）';
    }
    const main = document.querySelector('.cs-main');
    if (main) main.classList.toggle('cs-human-mode', this._humanStatus === 'human' || this._humanStatus === 'waiting');
  },

  onLiveMessage(m) {
    const id = Number(m.id);
    if (!id || this._seenMessageIds.has(id)) return;
    if (m.role === 'user' || m.role === 'assistant') return;  // 本端已渲染
    this.markSeen(id);
    const box = document.getElementById('cs_messages');
    if (!box) return;
    if (box.querySelector('.cs-welcome')) box.innerHTML = '';
    box.insertAdjacentHTML('beforeend', this.messageHtml(m));
    this.scrollBottom();
    this._lastEventId = Math.max(this._lastEventId, id);
    if (m.role === 'agent') this.refreshSessions();
  },

  stopEvents() {
    try { this._eventCtrl?.abort(); } catch (e) {}
    this._eventCtrl = null;
  },

  startEvents() {
    this.stopEvents();
    const sid = this._sessionId;
    if (!sid) return;
    const ctrl = new AbortController();
    this._eventCtrl = ctrl;
    const loop = async () => {
      while (!ctrl.signal.aborted && this._sessionId === sid) {
        try {
          const res = await fetch(`${API.base}/cs/sessions/${sid}/events?after_id=${this._lastEventId}`,
            { headers: { token: API.token() }, signal: ctrl.signal });
          if (res.status === 401) { localStorage.removeItem('token'); location.href = '/'; return; }
          if (res.ok && res.body) {
            await this.readSSE(res, (event, payload) => {
              if (event === 'message') {
                if (payload.id) this._lastEventId = Math.max(this._lastEventId, Number(payload.id));
                this.onLiveMessage(payload);
              } else if (event === 'status') {
                this.applyHumanStatus(payload.status, payload.human_agent);
              }
            });
          }
        } catch (e) {
          if (ctrl.signal.aborted) return;
        }
        if (ctrl.signal.aborted) return;
        await new Promise(r => setTimeout(r, 800));
      }
    };
    loop();
  },

  scrollBottom() {
    const box = document.getElementById('cs_messages');
    if (box) box.scrollTop = box.scrollHeight;
  },

  clearTrace() {
    document.getElementById('cs_trace_body').innerHTML = `
      <div class="cs-empty-trace"><div class="cs-empty-icon">🧭</div>
      <div>发送问题后，这里会展示<br>路由 → 检索 → 业务查询 → 生成</div></div>`;
    document.getElementById('cs_cite_body').innerHTML = '<div class="cs-cite-empty">暂无引用</div>';
    document.getElementById('cs_cite_count').textContent = '0';
    document.getElementById('cs_conf').textContent = '—';
    document.getElementById('cs_conf').className = 'cs-conf';
    document.getElementById('cs_trace_sub').textContent = '每次提问实时展示';
    this._lastAgents = [];
  },

  appendTrace(agent) {
    const body = document.getElementById('cs_trace_body');
    if (body.querySelector('.cs-empty-trace')) body.innerHTML = '';
    body.insertAdjacentHTML('beforeend', `
      <div class="cs-trace-item ${agent.status || 'done'}">
        <div class="cs-trace-dot">${agent.icon || '•'}</div>
        <div class="cs-trace-main">
          <div class="cs-trace-top"><b>${csEscape(agent.label)}</b><i>${agent.ms}ms</i></div>
          <div class="cs-trace-detail">${csEscape(agent.detail)}</div>
        </div>
      </div>`);
    body.scrollTop = body.scrollHeight;
  },

  renderTrace(agents) {
    this._lastAgents = agents || [];
    document.getElementById('cs_trace_body').innerHTML = '';
    (agents || []).forEach(a => this.appendTrace(a));
    const names = new Set((agents || []).map(a => a.name)).size;
    document.getElementById('cs_trace_sub').textContent =
      `${names} 个 Agent 协作 · ${(agents || []).reduce((s, a) => s + (a.ms || 0), 0)}ms`;
  },

  renderTraceFromTools(msg) {
    const tools = msg.tools || msg.tool_results || [];
    const body = document.getElementById('cs_trace_body');
    body.innerHTML = '';
    this._lastAgents = tools.map(t => ({
      icon: t.agent === 'supplier' ? '🚚' : '🗄️',
      label: t.agent === 'supplier' ? '供应商协同 Agent' : '业务数据 Agent',
      detail: (t.title || '') + (t.ok ? '（历史会话）' : '（未获取数据）'),
      ms: 0, status: t.ok ? 'done' : 'warn',
    }));
    document.getElementById('cs_conf').textContent = '—';
    document.getElementById('cs_conf').className = 'cs-conf';
    if (!tools.length) {
      body.innerHTML = `<div class="cs-empty-trace"><div class="cs-empty-icon">🗂️</div>
        <div>这是一条知识问答，未调用业务工具</div></div>`;
      document.getElementById('cs_trace_sub').textContent = '历史会话的 Agent 记录';
      return;
    }
    tools.forEach(t => this.appendTrace({
      icon: t.agent === 'supplier' ? '🚚' : '🗄️',
      label: t.agent === 'supplier' ? '供应商协同 Agent' : '业务数据 Agent',
      detail: t.title + (t.ok ? '（历史会话）' : '（未获取数据）'),
      ms: 0, status: t.ok ? 'done' : 'warn',
    }));
    document.getElementById('cs_trace_sub').textContent = '历史会话的 Agent 记录';
  },

  setConfidence(v) {
    if (typeof v !== 'number') return;
    const el = document.getElementById('cs_conf');
    const pct = Math.round(v * 100);
    el.textContent = pct + '%';
    el.className = 'cs-conf ' + (pct >= 75 ? 'high' : pct >= 50 ? 'mid' : 'low');
    el.title = '回答置信度：综合知识命中与业务数据完整性';
  },

  renderCitations(citations) {
    const list = csCitationList(citations || []);
    this._citations = list;
    document.getElementById('cs_cite_count').textContent = list.length;
    const body = document.getElementById('cs_cite_body');
    if (!list.length) { body.innerHTML = '<div class="cs-cite-empty">本次回答未引用知识库</div>'; return; }
    body.innerHTML = list.map(c => `
      <button class="cs-cite" onclick="PAGES.service.showCitation(${c.num})">
        <div class="cs-cite-top">
          <span class="cs-cite-num">[${c.num}]</span>
          <span class="cs-cite-title">${csEscape(c.title)}</span>
        </div>
        <div class="cs-cite-meta">${csEscape(c.category)} · ${(c.score * 100).toFixed(0)}% 匹配${c.chunks > 1 ? ` · ${c.chunks} 片段` : ''}</div>
      </button>`).join('');
  },

  showCitation(num) {
    const c = (this._citations || []).find(x => x.num === num);
    if (!c) return;
    UI.modal({
      title: `知识引用 [${num}] · ${csEscape(c.title)}`, size: 'modal-lg', okText: '关闭',
      onOk: async () => true,
      body: `<div class="cs-cite-modal">
        <div class="d-flex gap-2 mb-3 flex-wrap">
          <span class="badge text-bg-light border">${csEscape(c.doc_no)}</span>
          <span class="badge text-bg-light border">${csEscape(c.category)}</span>
          <span class="badge text-bg-primary">匹配度 ${(c.score * 100).toFixed(1)}%</span>
        </div>
        <div class="cs-cite-full">${csEscape(c.content).replace(/\n/g, '<br>')}</div>
      </div>`,
    });
  },

  showTrace() {
    const agents = this._lastAgents || [];
    const cites = csCitationList(this._citations || []);
    UI.modal({
      title: '🧩 Agent 协作轨迹与知识引用', size: 'modal-lg', okText: '关闭',
      onOk: async () => true,
      body: `<div class="fw-bold mb-2">协作轨迹</div>
        ${agents.length ? `<div class="cs-trace-list-modal">${agents.map(a => `
          <div class="cs-trace-item ${a.status || 'done'}">
            <div class="cs-trace-dot">${a.icon || '•'}</div>
            <div class="cs-trace-main">
              <div class="cs-trace-top"><b>${csEscape(a.label)}</b><i>${a.ms}ms</i></div>
              <div class="cs-trace-detail">${csEscape(a.detail)}</div>
            </div>
          </div>`).join('')}</div>` : '<div class="text-muted small mb-3">当前还没有 Agent 记录，请先发送问题。</div>'}
        <div class="fw-bold mt-3 mb-2">知识引用</div>
        ${cites.length ? cites.map(c => `
          <div class="kb-test-hit">
            <div class="d-flex justify-content-between">
              <b>[${c.num}] ${csEscape(c.title)}</b>
              <span class="badge text-bg-primary">${(c.score * 100).toFixed(1)}%</span>
            </div>
            <div class="text-muted small mb-1">${csEscape(c.category)} · ${csEscape(c.doc_no)}</div>
            <div class="small">${csEscape(c.excerpt || c.content || '')}</div>
          </div>`).join('') : '<div class="text-muted small">本次回答未引用知识库。</div>'}`,
    });
  },

  showAgents() {
    const list = this._agents || [];
    UI.modal({
      title: '多 Agent 协作架构', size: 'modal-lg', okText: '关闭', onOk: async () => true,
      body: `<div class="cs-agent-grid">
        ${list.map(a => `<div class="cs-agent-card">
          <div class="cs-agent-icon">${a.icon}</div>
          <div><div class="fw-bold">${csEscape(a.label)}</div>
          <div class="text-muted small mono">${csEscape(a.name)}</div>
          <div class="small mt-1">${csEscape(a.desc)}</div></div>
        </div>`).join('') || '<div class="text-muted">暂无 Agent 信息</div>'}
      </div>
      <div class="alert alert-light border small mt-3 mb-0">
        编排流程：RouterAgent 识别意图与实体 → KnowledgeAgent 检索知识（BM25 + 语义向量混合）→
        BusinessAgent / SupplierAgent 查询实时数据 → ComposeAgent 生成答案（可接入大模型）→ 低置信度时 TicketAgent 升级人工。
      </div>`,
    });
  },

  ticketModal() {
    const q = this._lastQuestion || document.getElementById('cs_input')?.value?.trim() || '需要人工协助';
    const m = UI.modal({
      title: '🎫 转人工 / 提交工单', size: 'modal-lg',
      body: UI.field('标题', UI.input('title', q.slice(0, 60))) +
        `<div class="row g-2">
          <div class="col-md-6">${UI.field('问题类型', UI.select('category', ['咨询', '投诉', '建议', '报障'], '咨询'))}</div>
          <div class="col-md-6">${UI.field('优先级', UI.select('priority', [['normal', '普通（1 个工作日）'], ['high', '高（2 小时）'], ['low', '低']], 'normal'))}</div>
        </div>` +
        UI.field('问题详情', UI.textarea('content', `原始问题：${q}\n\n补充说明：`, 4)) +
        `<div class="alert alert-info py-2 small mb-0">提交后将生成工单号，可在「服务工单」中跟踪处理进度。</div>`,
      onOk: async () => {
        const d = UI.formData(m.id);
        if (!this._sessionId) {
          const s = await API.post('/cs/sessions', { title: q.slice(0, 30) });
          if (s.code !== 0) { UI.toast(s.msg, 'error'); return false; }
          this._sessionId = s.data.id;
          this.startEvents();
        }
        d.session_id = this._sessionId;
        const res = await API.post('/cs/tickets', d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        this.applyHumanStatus('waiting', '');
        UI.toast(`工单 ${res.data.ticket_no} 已创建，等待人工接入`, 'info');
        const box = document.getElementById('cs_messages');
        if (box) {
          this.startEvents();
          if (box.querySelector('.cs-welcome')) box.innerHTML = '';
          box.insertAdjacentHTML('beforeend', `<div class="cs-msg cs-msg-ai">
            <div class="cs-avatar">🎫</div>
            <div class="cs-bubble"><div class="cs-answer">
              已为你创建工单 <b>${res.data.ticket_no}</b>，正在等待人工客服接入。接入后可在本会话实时沟通，也可在「服务工单」查看进度。
            </div></div></div>`);
          this.scrollBottom();
        }
        return true;
      },
    });
  },
};

/* ==================== 人工工作台 ==================== */
PAGES.human = {
  title: '人工工作台',
  _queue: [],
  _ticket: null,
  _sessionId: null,
  _eventCtrl: null,
  _lastId: 0,
  _seen: new Set(),
  _timer: null,
  _filter: 'all',
  _search: '',
  _stats: {},

  destroy() {
    this.stopEvents();
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  },

  async render(el) {
    const me = JSON.parse(localStorage.getItem('user') || '{}');
    el.innerHTML = `
      <div class="hw-page">
        <div class="hw-command">
          <div class="hw-command-brand">
            <div class="hw-command-icon">🎧</div>
            <div>
              <div class="hw-command-title">人工服务工作台</div>
              <div class="hw-command-sub">实时接管 · 坐席回复即时送达客户</div>
            </div>
          </div>
          <div class="hw-kpis">
            <div class="hw-kpi amber"><span class="hw-kpi-label">待接入</span><b id="hw_kpi_open">0</b></div>
            <div class="hw-kpi green"><span class="hw-kpi-label">处理中</span><b id="hw_kpi_processing">0</b></div>
            <div class="hw-kpi blue"><span class="hw-kpi-label">今日已解决</span><b id="hw_kpi_resolved">0</b></div>
            <div class="hw-kpi slate"><span class="hw-kpi-label">平均等待</span><b id="hw_kpi_wait">0<small>分</small></b></div>
          </div>
          <div class="hw-online"><i class="hw-live-dot"></i><span id="hw_agent_name">${csEscape(me.real_name || me.username || '坐席')}</span><em>在线</em></div>
        </div>

        <div class="hw-layout">
          <aside class="hw-queue cs-card">
            <div class="hw-queue-head">
              <div class="hw-queue-title-row">
                <span>排队队列</span><span class="hw-queue-badge" id="hw_queue_badge">0</span>
              </div>
              <div class="hw-search">
                <span>⌕</span>
                <input id="hw_search" placeholder="搜索客户 / 工单号" oninput="PAGES.human.onSearch(this.value)">
              </div>
              <div class="hw-tabs">
                <button class="hw-tab active" data-filter="all" onclick="PAGES.human.setFilter('all')">全部 <b id="hw_tab_all">0</b></button>
                <button class="hw-tab" data-filter="open" onclick="PAGES.human.setFilter('open')">待接入 <b id="hw_tab_open">0</b></button>
                <button class="hw-tab" data-filter="processing" onclick="PAGES.human.setFilter('processing')">处理中 <b id="hw_tab_processing">0</b></button>
              </div>
            </div>
            <div class="hw-queue-list" id="hu_queue_list"></div>
            <div class="hw-queue-foot" id="hw_queue_foot">正在加载排队数据…</div>
          </aside>

          <section class="hw-main cs-card">
            <div class="hw-head" id="hu_head">
              <div class="hw-head-empty">从左侧排队队列选择工单，接入后即可与客户实时沟通</div>
            </div>
            <div class="hw-messages" id="hu_messages">
              <div class="hw-empty">
                <div class="hw-empty-visual"><span>🎧</span><i></i></div>
                <div class="hw-empty-title">准备好接待客户</div>
                <div class="hw-empty-sub">接入左侧待处理工单后，客户消息会实时出现在这里，你的回复也会即时送达。</div>
                <div class="hw-empty-steps">
                  <div><b>01</b><span>选择待接入工单</span></div>
                  <div><b>02</b><span>查看 AI 会话历史</span></div>
                  <div><b>03</b><span>实时回复并结束服务</span></div>
                </div>
              </div>
            </div>
            <div class="hw-composer" id="hu_composer" style="display:none">
              <div class="hw-quick-row" id="hu_quick">
                ${['您好，我是人工客服，请描述一下遇到的问题。', '请提供一下单号，我帮您查询。', '已为您登记，请稍候。']
                  .map(t => `<button class="hw-quick-chip" data-q="${csEscape(t)}" onclick="PAGES.human.quick(this)">${csEscape(t)}</button>`).join('')}
              </div>
              <div class="hw-compose-box">
                <textarea class="hw-textarea" id="hu_input" rows="1" maxlength="500"
                  placeholder="回复客户…（Enter 发送，Shift+Enter 换行）"
                  oninput="PAGES.human.onInput()"></textarea>
                <div class="hw-compose-foot">
                  <span class="hw-compose-hint">Enter 发送 · Shift+Enter 换行 · 最长 500 字</span>
                  <span class="hw-count" id="hu_count">0 / 500</span>
                  <button class="hw-send" id="hu_send" onclick="PAGES.human.send()" disabled>发送 <span>➤</span></button>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>`;

    const input = document.getElementById('hu_input');
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.send(); }
    });
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 110) + 'px';
    });
    this.loadQueue();
    this._timer = setInterval(() => this.loadQueue(true), 5000);
  },

  setFilter(filter) {
    this._filter = filter;
    document.querySelectorAll('.hw-tab').forEach(b => b.classList.toggle('active', b.dataset.filter === filter));
    this.renderQueue();
  },

  onSearch(value) {
    this._search = (value || '').trim().toLowerCase();
    this.renderQueue();
  },

  onInput() {
    const input = document.getElementById('hu_input');
    if (!input) return;
    const len = input.value.length;
    const count = document.getElementById('hu_count');
    const send = document.getElementById('hu_send');
    if (count) count.textContent = `${len} / 500`;
    if (send) send.disabled = !input.value.trim();
  },

  async loadQueue(silent = false) {
    const res = await API.get('/cs/human/queue');
    if (res.code !== 0) { if (!silent) UI.toast(res.msg, 'error'); return; }
    this._queue = res.data.list || [];
    this._stats = res.data.stats || {};
    const c = res.data.counts || {};
    const stats = this._stats;
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.innerHTML = val; };
    set('hw_kpi_open', c.open || 0);
    set('hw_kpi_processing', c.processing || 0);
    set('hw_kpi_resolved', stats.today_resolved || 0);
    set('hw_kpi_wait', `${stats.avg_waiting || 0}<small>分</small>`);
    set('hw_queue_badge', this._queue.length);
    set('hw_tab_all', this._queue.length);
    set('hw_tab_open', c.open || 0);
    set('hw_tab_processing', c.processing || 0);
    const foot = document.getElementById('hw_queue_foot');
    if (foot) {
      const now = new Date();
      foot.textContent = `最后更新 ${now.toTimeString().slice(0, 8)} · 每 5 秒自动刷新`;
    }
    this.renderQueue();
    if (this._ticket) {
      const cur = this._queue.find(t => t.id === this._ticket.id);
      if (cur) { this._ticket = cur; this.renderHead(); }
    }
  },

  renderQueue() {
    const box = document.getElementById('hu_queue_list');
    if (!box) return;
    let list = this._queue.filter(t => this._filter === 'all' || t.status === this._filter);
    if (this._search) {
      list = list.filter(t => `${t.username || ''} ${t.ticket_no || ''} ${t.title || ''}`.toLowerCase().includes(this._search));
    }
    if (!list.length) {
      box.innerHTML = `<div class="hw-queue-empty">
        <div class="hw-queue-empty-icon">🗂️</div>
        <div>${this._search ? '没有匹配的工单' : this._filter === 'open' ? '暂无待接入工单' : '当前队列为空'}</div>
        <em>${this._search ? '换个关键词试试' : '新工单会自动出现在这里'}</em>
      </div>`;
      return;
    }
    const pr = { high: ['高', 'pri-high'], normal: ['普通', 'pri-normal'], low: ['低', 'pri-low'] };
    box.innerHTML = list.map(t => {
      const p = pr[t.priority] || [t.priority, 'pri-normal'];
      const isOpen = t.status === 'open';
      const dur = isOpen ? (t.waiting_minutes || 0) : (t.service_minutes || 0);
      const durText = dur < 60 ? `${dur} 分钟` : `${Math.floor(dur / 60)}h ${dur % 60}m`;
      const lastRole = { user: '客户', agent: '坐席', assistant: 'AI', system: '系统' }[t.last_role] || '系统';
      return `
      <div class="hw-qcard ${p[1]} ${t.id === this._ticket?.id ? 'active' : ''}" onclick="PAGES.human.openTicket(${t.id})">
        <div class="hw-qcard-top">
          <div class="hw-avatar-sm">${csEscape((t.username || '客').slice(0, 1))}</div>
          <div class="hw-qcard-id">
            <div class="hw-qcard-name">${csEscape(t.username || '')}
              <i class="hw-qcard-dot ${isOpen ? 'waiting' : 'serving'}"></i>
            </div>
            <div class="hw-qcard-no">${csEscape(t.ticket_no)}</div>
          </div>
          <span class="hw-priority">${p[0]}</span>
        </div>
        <div class="hw-qcard-title">${csEscape(t.title || '')}</div>
        <div class="hw-qcard-last"><b>${lastRole}</b>${csEscape((t.last_message || '暂无消息').slice(0, 54))}</div>
        <div class="hw-qcard-foot">
          <span class="hw-qcard-time">⏱ ${isOpen ? '等待 ' : '服务 '}${durText}</span>
          <span class="hw-qcard-state ${isOpen ? 'waiting' : 'serving'}">${isOpen ? '待接入' : '处理中'}</span>
          ${isOpen
            ? `<button class="hw-qcard-btn" onclick="event.stopPropagation();PAGES.human.acceptTicket(${t.id})">接入 →</button>`
            : `<button class="hw-qcard-btn ghost" onclick="event.stopPropagation();PAGES.human.openTicket(${t.id})">进入 →</button>`}
        </div>
      </div>`;
    }).join('');
  },

  async acceptTicket(id) {
    const t = this._queue.find(x => x.id === id);
    const res = await API.post(`/cs/tickets/${id}/accept`, {});
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    UI.toast(res.msg);
    if (t) this.openSession(res.data.session_id, { ...t, status: 'processing', session_status: 'human' });
    this.loadQueue(true);
  },

  async openTicket(id) {
    const t = this._queue.find(x => x.id === id);
    if (!t) return;
    if (!t.session_id) return UI.toast('该工单未关联在线会话，无法聊天', 'error');
    if (t.status === 'open') return this.acceptTicket(id);
    this.openSession(t.session_id, t);
  },

  async openSession(sid, ticket) {
    this.stopEvents();
    const res = await API.get(`/cs/sessions/${sid}/messages`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._ticket = ticket;
    this._sessionId = sid;
    const msgs = res.data.messages || [];
    this._seen = new Set(msgs.map(m => m.id));
    this._lastId = msgs.length ? msgs[msgs.length - 1].id : 0;
    const box = document.getElementById('hu_messages');
    box.innerHTML = msgs.length ? '' : '<div class="hw-queue-empty">暂无消息</div>';
    msgs.forEach(m => box.insertAdjacentHTML('beforeend', this.messageHtml(m)));
    document.getElementById('hu_composer').style.display = 'flex';
    this.onInput();
    this.renderHead();
    this.scrollBottom();
    this.startEvents();
  },

  renderHead() {
    const t = this._ticket;
    if (!t) return;
    const el = document.getElementById('hu_head');
    if (!el) return;
    const pr = { high: ['高优先级', 'pri-high'], normal: ['普通', 'pri-normal'], low: ['低优先级', 'pri-low'] };
    const p = pr[t.priority] || [t.priority, 'pri-normal'];
    const isOpen = t.status === 'open';
    const wait = isOpen ? (t.waiting_minutes || 0) : (t.service_minutes || 0);
    const waitText = wait < 60 ? `${wait} 分钟` : `${Math.floor(wait / 60)} 小时 ${wait % 60} 分`;
    const sla = t.priority === 'high' ? 120 : t.priority === 'normal' ? 480 : 1440;
    const left = sla - wait;
    const slaText = isOpen
      ? (left >= 0 ? `剩余 ${left < 60 ? left + ' 分钟' : Math.floor(left / 60) + 'h' + (left % 60) + 'm'}`
                   : `已超时 ${Math.abs(left) < 60 ? Math.abs(left) + ' 分钟' : Math.floor(Math.abs(left) / 60) + ' 小时'}`)
      : '服务进行中';
    el.innerHTML = `
      <div class="hw-head-top">
        <div class="hw-head-left">
          <div class="hw-avatar-lg">${csEscape((t.username || '客').slice(0, 1))}</div>
          <div class="min-w-0">
            <div class="hw-head-name">客户 ${csEscape(t.username || '')}
              <span class="hw-status ${isOpen ? 'waiting' : 'on'}">${isOpen ? '待接入' : '人工服务中'}</span>
            </div>
            <div class="hw-head-ticket">${csEscape(t.ticket_no)} · ${csEscape(t.title || '')}</div>
          </div>
        </div>
        <div class="hw-head-actions">
          <button class="hw-btn ghost" onclick="PAGES.human.checkMessages()">刷新消息</button>
          <button class="hw-btn danger" onclick="PAGES.human.resolveModal()">结束服务</button>
        </div>
      </div>
      <div class="hw-ticket-strip">
        <div><label>工单类型</label><b>${csEscape(t.category || '咨询')}</b></div>
        <div><label>优先级</label><b class="strip-pri ${p[1]}">${p[0]}</b></div>
        <div><label>${isOpen ? '已等待' : '已服务'}</label><b>${waitText}</b></div>
        <div><label>SLA</label><b class="${isOpen && left < 0 ? 'overdue' : ''}">${slaText}</b></div>
        <div><label>当前坐席</label><b>${csEscape(t.human_agent || '未接入')}</b></div>
      </div>`;
  },

  messageHtml(m) {
    const time = (m.create_time || '').slice(11, 16);
    if (m.role === 'system') {
      return `<div class="cs-system-note"><span>🔔</span>${csEscape(m.content)}</div>`;
    }
    if (m.role === 'user') {
      return `<div class="cs-msg">
        <div class="cs-avatar cs-avatar-user">${csEscape((this._ticket?.username || '客').slice(0, 1))}</div>
        <div class="cs-bubble cs-bubble-customer">
          <div class="cs-human-name">客户 · ${csEscape(this._ticket?.username || '')}</div>
          <div class="cs-answer">${csEscape(m.content).replace(/\n/g, '<br>')}</div>
          ${time ? `<div class="hw-msg-time">${time}</div>` : ''}
        </div>
      </div>`;
    }
    if (m.role === 'agent') {
      return `<div class="cs-msg cs-msg-user">
        <div class="cs-bubble cs-bubble-agent">
          <div class="cs-human-name">我 · ${csEscape(m.sender_name || '坐席')}</div>
          <div class="cs-answer">${csEscape(m.content).replace(/\n/g, '<br>')}</div>
          ${time ? `<div class="hw-msg-time right">${time}</div>` : ''}
        </div>
        <div class="cs-avatar cs-avatar-agent">🎧</div>
      </div>`;
    }
    return PAGES.service.messageHtml(m);
  },

  scrollBottom() {
    const box = document.getElementById('hu_messages');
    if (box) box.scrollTop = box.scrollHeight;
  },

  async checkMessages() {
    if (!this._sessionId) return;
    const res = await API.get(`/cs/sessions/${this._sessionId}/messages`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const box = document.getElementById('hu_messages');
    box.innerHTML = '';
    (res.data.messages || []).forEach(m => box.insertAdjacentHTML('beforeend', this.messageHtml(m)));
    this.scrollBottom();
  },

  quick(btn) {
    const input = document.getElementById('hu_input');
    input.value = btn.dataset.q || btn.textContent.trim();
    this.onInput();
    input.focus();
  },

  async send() {
    if (!this._sessionId) return;
    const input = document.getElementById('hu_input');
    const text = input.value.trim();
    if (!text) return;
    const btn = document.getElementById('hu_send');
    input.disabled = true;
    if (btn) btn.disabled = true;
    const res = await API.post(`/cs/sessions/${this._sessionId}/agent-message`, { content: text });
    input.disabled = false;
    if (res.code !== 0) { this.onInput(); return UI.toast(res.msg, 'error'); }
    input.value = '';
    input.style.height = 'auto';
    this.onInput();
    this._seen.add(Number(res.data.id));
    const box = document.getElementById('hu_messages');
    box.insertAdjacentHTML('beforeend', this.messageHtml({ ...res.data, role: 'agent' }));
    this.scrollBottom();
    this.loadQueue(true);
  },

  resolveModal() {
    const t = this._ticket;
    if (!t) return;
    const m = UI.modal({
      title: `结束人工服务 · ${t.ticket_no}`,
      body: `<div class="alert alert-info py-2 small">结束后会话将恢复智能客服，客户可继续提问；工单状态变为已解决。</div>` +
        UI.field('处理结论（必填）', UI.textarea('resolution', '已通过人工沟通解决客户问题。', 4)),
      okText: '结束服务', okClass: 'btn-danger',
      onOk: async () => {
        const d = UI.formData(m.id);
        if (!d.resolution?.trim()) { UI.toast('请填写处理结论', 'error'); return false; }
        const res = await API.post(`/cs/tickets/${t.id}/resolve`, d);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
        UI.toast('人工服务已结束，会话已恢复智能客服');
        this.stopEvents();
        this._ticket = null;
        this._sessionId = null;
        this._seen = new Set();
        this._lastId = 0;
        document.getElementById('hu_head').innerHTML =
          '<div class="hw-head-empty">从左侧排队队列选择工单，接入后即可与客户实时沟通</div>';
        document.getElementById('hu_messages').innerHTML = `<div class="hw-empty">
          <div class="hw-empty-visual"><span>🎧</span><i></i></div>
          <div class="hw-empty-title">准备好接待客户</div>
          <div class="hw-empty-sub">接入左侧待处理工单后，客户消息会实时出现在这里。</div></div>`;
        document.getElementById('hu_composer').style.display = 'none';
        this.loadQueue(true);
        return true;
      },
    });
  },

  stopEvents() {
    try { this._eventCtrl?.abort(); } catch (e) {}
    this._eventCtrl = null;
  },

  startEvents() {
    this.stopEvents();
    const sid = this._sessionId;
    if (!sid) return;
    const ctrl = new AbortController();
    this._eventCtrl = ctrl;
    const loop = async () => {
      while (!ctrl.signal.aborted && this._sessionId === sid) {
        try {
          const res = await fetch(`${API.base}/cs/sessions/${sid}/events?after_id=${this._lastId}`,
            { headers: { token: API.token() }, signal: ctrl.signal });
          if (res.status === 401) { localStorage.removeItem('token'); location.href = '/'; return; }
          if (res.ok && res.body) {
            await PAGES.service.readSSE(res, (event, payload) => {
              if (event === 'message') {
                if (payload.id) this._lastId = Math.max(this._lastId, Number(payload.id));
                if (this._seen.has(Number(payload.id))) return;
                this._seen.add(Number(payload.id));
                const box = document.getElementById('hu_messages');
                if (box) {
                  if (box.querySelector('.hu-empty, .hu-queue-empty')) box.innerHTML = '';
                  box.insertAdjacentHTML('beforeend', this.messageHtml(payload));
                  this.scrollBottom();
                }
                if (payload.role === 'user') this.loadQueue(true);
              } else if (event === 'status') {
                if (this._ticket) {
                  this._ticket.session_status = payload.status;
                  this._ticket.human_agent = payload.human_agent;
                  this.renderHead();
                }
              }
            });
          }
        } catch (e) {
          if (ctrl.signal.aborted) return;
        }
        if (ctrl.signal.aborted) return;
        await new Promise(r => setTimeout(r, 800));
      }
    };
    loop();
  },
};

/* ==================== 服务工单 ==================== */
PAGES.tickets = {
  title: '服务工单',
  _status: '',
  async render(el) {
    el.innerHTML = `
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <span>工单中心 <span class="text-muted small">按优先级排序，高优先级 2 小时内响应</span></span>
          <div class="d-flex gap-2">
            <div class="btn-group btn-group-sm" id="tk_tabs">
              <button class="btn btn-outline-secondary active" onclick="PAGES.tickets.filter('', this)">全部</button>
              <button class="btn btn-outline-secondary" onclick="PAGES.tickets.filter('open', this)">待处理</button>
              <button class="btn btn-outline-secondary" onclick="PAGES.tickets.filter('processing', this)">处理中</button>
              <button class="btn btn-outline-secondary" onclick="PAGES.tickets.filter('resolved', this)">已解决</button>
            </div>
            <button class="btn btn-sm btn-outline-primary" onclick="loadPage('human')">🎧 人工工作台</button>
            <button class="btn btn-sm btn-primary" onclick="PAGES.service.ticketModal()">＋ 新建工单</button>
          </div>
        </div>
        <div class="card-body p-0" id="tk_list"></div>
        <div class="card-footer bg-white" id="tk_page"></div>
      </div>`;
    this.load(1);
  },
  filter(status, btn) {
    this._status = status;
    document.querySelectorAll('#tk_tabs .btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    this.load(1);
  },
  async load(page = 1) {
    const res = await API.get(`/cs/tickets?page=${page}&size=10${this._status ? '&status=' + this._status : ''}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const st = { open: ['待处理', 'st-pending'], processing: ['处理中', 'st-checking'],
      resolved: ['已解决', 'st-completed'], closed: ['已关闭', 'st-cancelled'] };
    const pr = { high: ['高', 'text-bg-danger'], normal: ['普通', 'text-bg-primary'], low: ['低', 'text-bg-secondary'] };
    document.getElementById('tk_list').innerHTML = UI.table([
      { key: 'ticket_no', title: '工单号', class: 'mono' },
      { key: 'title', title: '标题', render: r => `<div class="text-truncate" style="max-width:320px" title="${csEscape(r.title)}">${csEscape(r.title)}</div>` },
      { key: 'category', title: '类型' },
      { key: 'priority', title: '优先级', render: r => `<span class="badge ${pr[r.priority]?.[1] || 'text-bg-secondary'}">${pr[r.priority]?.[0] || r.priority}</span>` },
      { key: 'status', title: '状态', render: r => `<span class="badge badge-status ${st[r.status]?.[1] || ''}">${st[r.status]?.[0] || r.status}</span>` },
      { key: 'username', title: '提交人' },
      { key: 'assignee', title: '处理人', render: r => r.assignee || '<span class="text-muted">未分配</span>' },
      { key: 'create_time', title: '创建时间', render: r => fmtTime(r.create_time) },
      { title: '操作', render: r => `<button class="btn btn-sm btn-outline-primary" onclick="PAGES.tickets.handle(${r.id})">处理</button>` },
    ], res.data.list);
    document.getElementById('tk_page').innerHTML = UI.pagination(res.data.total, page, 10, 'PAGES.tickets.load');
  },
  async handle(id) {
    const res = await API.get(`/cs/tickets?page=1&size=100`);
    const t = (res.data?.list || []).find(x => x.id === id);
    if (!t) return UI.toast('工单不存在', 'error');
    const m = UI.modal({
      title: `处理工单 · ${t.ticket_no}`, size: 'modal-lg',
      body: `<div class="mb-3 p-3 bg-light rounded small">
          <div><b>${csEscape(t.title)}</b></div>
          <div class="text-muted mt-1">${csEscape(t.content || '').replace(/\n/g, '<br>')}</div>
        </div>
        <div class="row g-2">
          <div class="col-md-4">${UI.field('状态', UI.select('status', [['open', '待处理'], ['processing', '处理中'], ['resolved', '已解决'], ['closed', '已关闭']], t.status))}</div>
          <div class="col-md-4">${UI.field('优先级', UI.select('priority', [['high', '高'], ['normal', '普通'], ['low', '低']], t.priority))}</div>
          <div class="col-md-4">${UI.field('处理人', UI.input('assignee', t.assignee || ''))}</div>
        </div>` +
        UI.field('处理结论', UI.textarea('resolution', t.resolution || '', 4)),
      okText: '保存处理',
      onOk: async () => {
        const d = UI.formData(m.id);
        const r = await API.put(`/cs/tickets/${id}`, d);
        if (r.code !== 0) { UI.toast(r.msg, 'error'); return false; }
        UI.toast('工单已更新'); this.load(1); return true;
      },
    });
  },
};

/* ==================== 知识库管理 ==================== */
PAGES.kb = {
  title: '知识库管理',
  _data: [],
  async render(el) {
    el.innerHTML = `
      <div class="row g-3 mb-3" id="kb_stats"></div>
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <span>知识文档 <span class="text-muted small">发布后自动切片并重建向量索引</span></span>
          <div class="d-flex gap-2 flex-wrap">
            <input class="form-control form-control-sm" id="kb_kw" placeholder="标题/编号/标签" style="width:170px">
            <button class="btn btn-sm btn-outline-primary" onclick="PAGES.kb.load(1)">搜索</button>
            <button class="btn btn-sm btn-outline-secondary" onclick="PAGES.kb.testSearch()">🔍 检索测试</button>
            <button class="btn btn-sm btn-outline-warning" onclick="PAGES.kb.reindexAll()">♻️ 重建索引</button>
            <button class="btn btn-sm btn-primary" onclick="PAGES.kb.edit()">＋ 新增文档</button>
          </div>
        </div>
        <div class="card-body p-0" id="kb_list"></div>
        <div class="card-footer bg-white" id="kb_page"></div>
      </div>`;
    this.load(1);
  },
  async load(page = 1) {
    const kw = document.getElementById('kb_kw')?.value || '';
    const res = await API.get(`/cs/kb?page=${page}&size=10&keyword=${encodeURIComponent(kw)}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    this._data = res.data.list;
    this._categories = res.data.categories;
    const s = res.data.stats;
    document.getElementById('kb_stats').innerHTML = [
      ['📚', '知识文档', s.documents, '篇'],
      ['✅', '已发布', s.published, '篇'],
      ['🧩', '知识切片', s.chunks, '个'],
      ['🏷️', '内置文档', res.data.builtin, '篇'],
    ].map(([icon, label, val, unit]) => `
      <div class="col-6 col-md-3"><div class="card kb-stat">
        <div class="card-body py-3 d-flex align-items-center gap-3">
          <div class="kb-stat-icon">${icon}</div>
          <div><div class="kb-stat-val">${val}<small>${unit}</small></div><div class="kb-stat-label">${label}</div></div>
        </div></div></div>`).join('');

    const stMap = { published: '已发布', draft: '草稿', archived: '归档' };
    document.getElementById('kb_list').innerHTML = UI.table([
      { key: 'doc_no', title: '编号', class: 'mono' },
      { key: 'title', title: '标题', render: r => `<span class="kb-title-link" onclick="PAGES.kb.preview(${r.id})">${csEscape(r.title)}</span>` },
      { key: 'category', title: '分类', render: r => `<span class="badge text-bg-light border">${csEscape(r.category)}</span>` },
      { key: 'tags', title: '标签', render: r => csEscape(r.tags || '-') },
      { key: 'chunk_count', title: '切片' },
      { key: 'status', title: '状态', render: r => `<span class="badge ${r.status === 'published' ? 'text-bg-success' : 'text-bg-secondary'}">${stMap[r.status] || r.status}</span>` },
      { key: 'update_time', title: '更新时间', render: r => fmtTime(r.update_time) },
      { title: '操作', render: r => `
        <button class="btn btn-sm btn-outline-primary" onclick="PAGES.kb.preview(${r.id})">查看</button>
        <button class="btn btn-sm btn-outline-secondary" onclick="PAGES.kb.edit(${r.id})">编辑</button>
        <button class="btn btn-sm btn-outline-warning" onclick="PAGES.kb.reindex(${r.id})">重建</button>
        <button class="btn btn-sm btn-outline-danger" onclick="PAGES.kb.del(${r.id})">删除</button>` },
    ], res.data.list);
    document.getElementById('kb_page').innerHTML = UI.pagination(res.data.total, page, 10, 'PAGES.kb.load');
  },
  async preview(id) {
    const res = await API.get(`/cs/kb/${id}`);
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const d = res.data;
    UI.modal({
      title: `${d.doc_no} · ${csEscape(d.title)}`, size: 'modal-lg', okText: '关闭',
      onOk: async () => true,
      body: `<div class="d-flex gap-2 mb-3 flex-wrap">
          <span class="badge text-bg-light border">${csEscape(d.category)}</span>
          <span class="badge text-bg-light border">${csEscape(d.tags || '无标签')}</span>
          <span class="badge text-bg-primary">${d.chunk_count} 个切片</span>
          <span class="badge text-bg-secondary">v${d.version}</span>
        </div>
        <div class="cs-cite-full mb-3">${csEscape(d.content).replace(/\n/g, '<br>')}</div>
        <div class="fw-bold mb-2">切片预览</div>
        <div class="kb-chunks">${(d.chunks || []).map(c => `
          <div class="kb-chunk"><span>#${c.chunk_index + 1}</span>${csEscape(c.content).replace(/\n/g, '<br>')}</div>`).join('')}
        </div>`,
    });
  },
  edit(id) {
    const load = async () => {
      let d = null;
      if (id) {
        const res = await API.get(`/cs/kb/${id}`);
        if (res.code !== 0) { UI.toast(res.msg, 'error'); return; }
        d = res.data;
      }
      const m = UI.modal({
        title: id ? `编辑知识 · ${d.doc_no}` : '新增知识文档', size: 'modal-lg',
        body: `<div class="row g-2">
            <div class="col-md-8">${UI.field('标题', UI.input('title', d?.title || ''))}</div>
            <div class="col-md-4">${UI.field('分类', UI.input('category', d?.category || '系统使用'))}</div>
            <div class="col-md-8">${UI.field('标签（逗号分隔）', UI.input('tags', d?.tags || ''))}</div>
            <div class="col-md-4">${UI.field('状态', UI.select('status', [['published', '发布（参与检索）'], ['draft', '草稿'], ['archived', '归档']], d?.status || 'published'))}</div>
          </div>` +
          UI.field('来源', UI.input('source', d?.source || '人工录入')) +
          UI.field('内容', UI.textarea('content', d?.content || '', 12)) +
          `<div class="alert alert-light border small mb-0">建议单篇聚焦一个主题。发布状态保存后会自动切片并重建索引；草稿不参与检索。</div>`,
        onOk: async () => {
          const data = UI.formData(m.id);
          if (!data.title || !data.content) { UI.toast('标题与内容不能为空', 'error'); return false; }
          const res = id ? await API.put(`/cs/kb/${id}`, data) : await API.post('/cs/kb', data);
          if (res.code !== 0) { UI.toast(res.msg, 'error'); return false; }
          UI.toast('保存成功'); this.load(1); return true;
        },
      });
    };
    load();
  },
  async reindex(id) {
    const res = await API.post(`/cs/kb/${id}/reindex`, {});
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    UI.toast(res.msg); this.load(1);
  },
  reindexAll() {
    UI.confirm('将重建全部已发布文档的切片与向量索引，确定继续？', async () => {
      const res = await API.post('/cs/kb/reindex-all', {});
      if (res.code === 0) { UI.toast(res.msg); this.load(1); } else UI.toast(res.msg, 'error');
    }, false);
  },
  del(id) {
    UI.confirm('确定删除该知识文档？内置文档不可删除。', async () => {
      const res = await API.delete(`/cs/kb/${id}`);
      if (res.code === 0) { UI.toast('已删除'); this.load(1); } else UI.toast(res.msg, 'error');
    });
  },
  testSearch() {
    const m = UI.modal({
      title: '🔍 知识检索测试', size: 'modal-lg',
      body: UI.field('模拟提问', UI.input('query', '入库单怎么确认入库？')) +
        `<div class="d-flex justify-content-between align-items-center mb-2">
          <div class="text-muted small">混合检索：BM25 + 哈希语义向量，按融合分数排序</div>
          <button class="btn btn-sm btn-primary" onclick="PAGES.kb.doTest()">检索</button>
        </div>
        <div id="kb_test_result" class="kb-test-result"><div class="text-muted small">输入问题后点击检索</div></div>`,
      okText: '关闭', onOk: async () => true,
    });
    this._testId = m.id;
  },
  async doTest() {
    const root = document.getElementById(this._testId);
    const q = root?.querySelector('[name=query]')?.value?.trim();
    if (!q) return UI.toast('请输入问题', 'error');
    const res = await API.post('/cs/kb/search', { query: q, top_k: 5 });
    if (res.code !== 0) return UI.toast(res.msg, 'error');
    const box = document.getElementById('kb_test_result');
    if (!res.data.hits.length) { box.innerHTML = '<div class="text-muted small">未命中任何知识片段，可尝试补充文档或调整表述。</div>'; return; }
    box.innerHTML = res.data.hits.map((h, i) => `
      <div class="kb-test-hit">
        <div class="d-flex justify-content-between">
          <b>${i + 1}. ${csEscape(h.title)}</b>
          <span class="badge text-bg-primary">${(h.score * 100).toFixed(1)}%</span>
        </div>
        <div class="text-muted small mb-1">${csEscape(h.doc_no)} · ${csEscape(h.category)} · 切片 #${h.chunk_index + 1}</div>
        <div class="small">${csEscape(h.excerpt)}</div>
      </div>`).join('');
  },
};
