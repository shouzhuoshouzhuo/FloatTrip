/* 历史行程页逻辑 */

// ─── Auth 状态（与 app.js 共享 localStorage key） ────────────

function getAuthState() {
  try {
    return JSON.parse(localStorage.getItem('auth') || 'null');
  } catch { return null; }
}

const auth = getAuthState();
if (!auth || !auth.token) {
  window.location.href = '/?login=1';
}

// ─── 注入导航栏 ───────────────────────────────────────────────

function renderNav() {
  const nav = document.getElementById('nav-placeholder');
  nav.innerHTML = `
    <header class="site-nav">
      <div class="nav-inner">
        <a class="nav-logo" href="/">✈ AI 旅游规划</a>
        <nav class="nav-links">
          <a href="/" class="nav-link">新建规划</a>
          <a href="/history" class="nav-link active">历史行程</a>
          <a href="/profile" class="nav-link">我的画像</a>
        </nav>
        <div class="nav-user">
          <span class="nav-username">${auth.username}</span>
          <button class="nav-logout-btn" id="nav-logout">退出</button>
        </div>
      </div>
    </header>`;
  document.getElementById('nav-logout').addEventListener('click', () => {
    localStorage.removeItem('auth');
    window.location.href = '/';
  });
}

renderNav();

// ─── 加载并渲染历史列表 ───────────────────────────────────────

async function loadHistory() {
  const container = document.getElementById('trip-list');
  try {
    const res = await fetch('/api/history', {
      headers: { 'Authorization': `Bearer ${auth.token}` }
    });
    if (res.status === 401) {
      localStorage.removeItem('auth');
      window.location.href = '/?login=1';
      return;
    }
    const items = await res.json();
    if (!items || items.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="icon">🗺️</div>
          <p>还没有规划记录。<a href="/">去规划第一个行程</a></p>
        </div>`;
      return;
    }
    renderList(items);
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><p>加载失败，请刷新重试。</p></div>`;
  }
}

function renderList(items) {
  const container = document.getElementById('trip-list');
  const grid = document.createElement('div');
  grid.className = 'trip-grid';

  items.forEach(item => {
    const card = document.createElement('div');
    card.className = 'trip-card';
    const dateText = item.start_date && item.end_date
      ? `${item.start_date} → ${item.end_date}`
      : '日期未知';
    const isModified = !!item.parent_id;
    card.innerHTML = `
      <div class="destination">${item.destination || '未知目的地'}</div>
      <div class="dates">${dateText}</div>
      <span class="badge ${isModified ? 'modified' : ''}">${isModified ? '修改版' : '原版'}</span>
      <div style="font-size:.75rem;color:#9ca3af;margin-top:8px">${formatDate(item.created_at)}</div>`;
    card.addEventListener('click', () => {
      window.location.href = `/?view_plan_id=${item.id}`;
    });
    grid.appendChild(card);
  });

  container.innerHTML = '';
  container.appendChild(grid);
}

function formatDate(isoStr) {
  if (!isoStr) return '';
  try {
    return new Date(isoStr).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return isoStr; }
}

loadHistory();
