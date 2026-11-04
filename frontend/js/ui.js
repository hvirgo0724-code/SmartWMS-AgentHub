/* 搜索栏实时搜索：输入或删除后自动刷新列表（防抖300ms，无需点击搜索按钮） */
(function liveSearch() {
  let timer = null;
  document.addEventListener('input', e => {
    const el = e.target;
    // 仅拦截页面级搜索框（id 以 _kw 结尾的输入框），不影响弹窗表单
    if (!el.id || !el.id.endsWith('_kw') || el.tagName !== 'INPUT') return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      try {
        if (typeof CURRENT_PAGE !== 'undefined' && CURRENT_PAGE && typeof CURRENT_PAGE.load === 'function') {
          CURRENT_PAGE.load(1);
        }
      } catch (_) {}
    }, 300);
  });
})();

/* UI 组件：表格 / 弹窗 / 提示 / 分页 / 表单构建 */
const UI = {

  toast(msg, type = 'success') {
    let area = document.querySelector('.toast-area');
    if (!area) { area = document.createElement('div'); area.className = 'toast-area'; document.body.appendChild(area); }
    const bg = { success: 'text-bg-success', error: 'text-bg-danger', warning: 'text-bg-warning', info: 'text-bg-primary' }[type] || 'text-bg-dark';
    const el = document.createElement('div');
    el.className = `toast align-items-center show ${bg} border-0 mb-2`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body">${msg}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" onclick="this.parentElement.parentElement.remove()"></button></div>`;
    area.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  },

  statusBadge(status) {
    const map = {
      pending: '待审核', approved: '已审核', completed: '已完成', cancelled: '已取消',
      allocated: '已分配', shipped: '已发货', picked: '已拣货', checking: '盘点中',
      empty: '空闲', occupied: '占用', locked: '锁定', normal: '正常', frozen: '冻结',
      received: '已收货',
    };
    return `<span class="badge badge-status st-${status}">${map[status] || status}</span>`;
  },

  /* 通用表格渲染
     cols: [{key, title, render(row), width, class}] */
  table(cols, rows, opts = {}) {
    if (!rows || !rows.length) return `<div class="empty-state"><div class="empty-icon">📭</div><div class="empty-text">暂无数据</div></div>`;
    const thead = cols.map(c => `<th ${c.width ? `style="width:${c.width}"` : ''}>${c.title}</th>`).join('');
    const tbody = rows.map((r, i) => {
      const delay = Math.min(i * 30, 360);
      const tds = cols.map(c => {
        const v = c.render ? c.render(r) : (r[c.key] ?? '-');
        return `<td class="${c.class || ''}">${v ?? '-'}</td>`;
      }).join('');
      return `<tr class="tr-in" style="animation-delay:${delay}ms">${tds}</tr>`;
    }).join('');
    return `<div class="table-responsive"><table class="table table-hover align-middle mb-0">
      <thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table></div>`;
  },

  /* 数字滚动动画 */
  animateNumber(el, target, { duration = 800, prefix = '', suffix = '', decimals = 0 } = {}) {
    if (!el || !Number.isFinite(Number(target))) return;
    const to = Number(target);
    const start = performance.now();
    const fmt = v => v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    const step = now => {
      const p = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
      el.textContent = prefix + fmt(Math.round(to * eased * 100) / 100) + suffix;
      if (p < 1) requestAnimationFrame(step);
      else el.textContent = prefix + fmt(to) + suffix;
    };
    requestAnimationFrame(step);
  },

  pagination(total, page, size, onPage) {
    const pages = Math.max(1, Math.ceil(total / size));
    if (pages <= 1) return total ? `<div class="text-muted small p-2">共 ${total} 条</div>` : '';
    let btns = '';
    if (page > 1) btns += `<li class="page-item"><a class="page-link" href="javascript:${onPage}(${page - 1})">上一页</a></li>`;
    const start = Math.max(1, page - 2), end = Math.min(pages, page + 2);
    for (let i = start; i <= end; i++)
      btns += `<li class="page-item ${i === page ? 'active' : ''}"><a class="page-link" href="javascript:${onPage}(${i})">${i}</a></li>`;
    if (page < pages) btns += `<li class="page-item"><a class="page-link" href="javascript:${onPage}(${page + 1})">下一页</a></li>`;
    return `<div class="d-flex align-items-center justify-content-between flex-wrap gap-2">
      <div class="text-muted small">共 ${total} 条 / ${pages} 页</div>
      <ul class="pagination pagination-sm mb-0">${btns}</ul></div>`;
  },

  /* 弹窗: title, bodyHTML, onOk(关闭由调用方控制), okText, size, okClass */
  modal({ title, body, okText = '保存', onOk, size = '', okClass = 'btn-primary' }) {
    const id = 'mdl_' + Date.now();
    const html = `
    <div class="modal fade" id="${id}" tabindex="-1">
      <div class="modal-dialog ${size} modal-dialog-scrollable modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header py-2">
            <h6 class="modal-title fw-bold">${title}</h6>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body" id="${id}_body">${body}</div>
          <div class="modal-footer py-2">
            <button class="btn btn-secondary btn-sm" data-bs-dismiss="modal">取消</button>
            ${onOk ? `<button class="btn ${okClass} btn-sm" id="${id}_ok">${okText}</button>` : ''}
          </div>
        </div>
      </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    const el = document.getElementById(id);
    const inst = new bootstrap.Modal(el);
    if (onOk) document.getElementById(id + '_ok').onclick = async (e) => {
      const btn = e.currentTarget;
      if (btn.disabled) return;                       // 防重复提交
      const orig = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>处理中...';
      let ok;
      try { ok = await onOk(); } catch (err) { ok = false; console.error(err); }
      btn.disabled = false;
      btn.innerHTML = orig;
      if (ok !== false) { inst.hide(); el.remove(); }
    };
    el.addEventListener('hidden.bs.modal', () => el.remove());
    inst.show();
    return { id, inst, el };
  },

  confirm(msg, onOk, danger = true) {
    return this.modal({
      title: danger ? '危险操作确认' : '确认操作',
      body: `<div class="py-3 text-center">
        <div class="confirm-icon ${danger ? 'danger' : ''}">${danger ? '⚠️' : '❓'}</div>
        <div class="mt-3">${msg}</div></div>`,
      okText: danger ? '确认执行' : '确认',
      okClass: danger ? 'btn-danger' : 'btn-primary',
      onOk: async () => { await onOk(); return true; },
    });
  },

  /* 表单字段构建 */
  field(label, input) {
    return `<div class="mb-3"><label class="form-label">${label}</label>${input}</div>`;
  },
  input(name, value = '', type = 'text', attrs = '') {
    return `<input class="form-control form-control-sm" name="${name}" value="${value ?? ''}" type="${type}" ${attrs}>`;
  },
  select(name, options, value = '') {
    const opts = options.map(o => {
      const [v, t] = Array.isArray(o) ? o : [o, o];
      return `<option value="${v ?? ''}" ${String(v ?? '') === String(value ?? '') ? 'selected' : ''}>${t}</option>`;
    }).join('');
    return `<select class="form-select form-select-sm" name="${name}">${opts}</select>`;
  },
  textarea(name, value = '', rows = 2) {
    return `<textarea class="form-control form-control-sm" name="${name}" rows="${rows}">${value ?? ''}</textarea>`;
  },

  /* 读取弹窗内表单数据 */
  formData(modalId) {
    const data = {};
    document.querySelectorAll(`#${modalId} [name]`).forEach(el => {
      if (el.tagName === 'SELECT') {
        // 空值/占位值 → null；数字串 → 数字，避免后端 int 校验失败
        const v = el.value;
        data[el.name] = (v === '' || v === 'null') ? null : (/^\d+$/.test(v) ? Number(v) : v);
      } else {
        data[el.name] = el.type === 'number' ? (el.value === '' ? null : Number(el.value)) : el.value;
      }
    });
    return data;
  },
};
