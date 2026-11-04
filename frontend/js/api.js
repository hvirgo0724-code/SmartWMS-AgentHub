/* API 请求封装 + 全局加载进度条 */
const LoadingBar = {
  _count: 0, _el: null,
  _ensure() {
    if (!this._el) {
      this._el = document.createElement('div');
      this._el.id = '__loadingbar';
      document.body.appendChild(this._el);
    }
    return this._el;
  },
  start() {
    this._count++;
    const el = this._ensure();
    el.style.opacity = '1';
    el.style.width = Math.min(30 + this._count * 10, 80) + '%';
  },
  done() {
    this._count = Math.max(0, this._count - 1);
    if (this._count === 0 && this._el) {
      const el = this._el;
      el.style.width = '100%';
      setTimeout(() => {
        el.style.opacity = '0';
        setTimeout(() => { el.style.width = '0'; }, 400);
      }, 150);
    }
  },
};

const API = {
  base: '/api/v1',
  token() { return localStorage.getItem('token') || ''; },

  async request(method, path, body) {
    LoadingBar.start();
    try {
      const opts = {
        method,
        headers: { 'Content-Type': 'application/json', 'token': this.token() },
      };
      if (body !== undefined) opts.body = JSON.stringify(body);
      let res;
      try {
        res = await fetch(this.base + path, opts);
      } catch (e) {
        throw new Error('无法连接服务器');
      }
      if (res.status === 401) {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        location.href = '/';
        return { code: 401, msg: '登录已过期', data: null };
      }
      // 文件下载（Excel 导出）
      if (res.headers.get('content-type')?.includes('spreadsheet')) {
        const blob = await res.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = path.split('/').pop() + '.xlsx';
        a.click();
        return { code: 0, msg: '导出成功', data: null };
      }
      return res.json();
    } finally {
      LoadingBar.done();
    }
  },

  get(path) { return this.request('GET', path); },
  post(path, body) { return this.request('POST', path, body || {}); },
  put(path, body) { return this.request('PUT', path, body || {}); },
  delete(path) { return this.request('DELETE', path); },
  download(path) {
    LoadingBar.start();
    return fetch(this.base + path, { headers: { token: this.token() } }).then(async res => {
      if (!res.headers.get('content-type')?.includes('spreadsheet')) {
        return res.json();
      }
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      const m = path.match(/reports\/(\w+)/);
      a.download = `${m ? m[1] : 'report'}_${new Date().toISOString().slice(0,10).replace(/-/g,'')}.xlsx`;
      a.click();
      return { code: 0, msg: '导出成功', data: null };
    }).finally(() => LoadingBar.done());
  },
};

/* 日期格式化 */
function fmtTime(v) {
  if (!v) return '-';
  return String(v).replace('T', ' ').slice(0, 19);
}
function fmtDate(v) {
  if (!v) return '-';
  return String(v).slice(0, 10);
}
