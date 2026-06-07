/* 用户画像页：查看 + 手动编辑偏好 */

function getAuthState() {
  try { return JSON.parse(localStorage.getItem('auth') || 'null'); } catch { return null; }
}

const auth = getAuthState();
if (!auth || !auth.token) {
  window.location.href = '/?login=1';
}

function escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* ─── 导航栏（与 history.js 一致） ─────────────── */
function renderNav() {
  const nav = document.getElementById('nav-placeholder');
  nav.innerHTML = `
    <header class="site-nav">
      <div class="nav-inner">
        <a class="nav-logo" href="/">✈ AI 旅游规划</a>
        <nav class="nav-links">
          <a href="/" class="nav-link">新建规划</a>
          <a href="/history" class="nav-link">历史行程</a>
          <a href="/profile" class="nav-link active">我的画像</a>
        </nav>
        <div class="nav-user">
          <span class="nav-username">${escHtml(auth.username)}</span>
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

/* ─── 画像字段定义 ──────────────────────────────── */
const FIELDS = [
  { key: 'attraction_prefs',     icon: '🏛', label: '景点偏好',   ph: '如 历史古迹、自然风光' },
  { key: 'food_prefs',           icon: '🍴', label: '餐饮偏好',   ph: '如 本地小吃、清淡' },
  { key: 'habit_prefs',          icon: '🧘', label: '游玩节奏',   ph: '如 慢节奏、睡到自然醒' },
  { key: 'visited_destinations', icon: '📍', label: '去过的城市', ph: '如 南京、杭州' },
];

let profileData = {};

/* ─── 渲染编辑器 ────────────────────────────────── */
function renderEditors() {
  const body = document.getElementById('profile-body');
  body.innerHTML = '';

  FIELDS.forEach(f => {
    const wrap = document.createElement('div');
    wrap.className = 'profile-field';
    wrap.innerHTML = `
      <div class="field-label">${f.icon} ${f.label}</div>
      <div class="tag-editor" data-key="${f.key}">
        <input class="tag-input" placeholder="${f.ph}" />
      </div>`;
    body.appendChild(wrap);

    const editor = wrap.querySelector('.tag-editor');
    const input  = wrap.querySelector('.tag-input');
    (profileData[f.key] || []).forEach(v => addTag(editor, input, v));

    // 回车 / 逗号 添加；退格删除最后一个
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ',' || e.key === '，') {
        e.preventDefault();
        const val = input.value.trim().replace(/[,，]$/, '');
        if (val) { addTag(editor, input, val); input.value = ''; }
      } else if (e.key === 'Backspace' && !input.value) {
        const tags = editor.querySelectorAll('.tag');
        if (tags.length) tags[tags.length - 1].remove();
      }
    });
    // 失焦时把残留文本也收进去
    input.addEventListener('blur', () => {
      const val = input.value.trim().replace(/[,，]$/, '');
      if (val) { addTag(editor, input, val); input.value = ''; }
    });
  });

  // 操作区
  const actions = document.createElement('div');
  actions.className = 'profile-actions';
  actions.innerHTML = `
    <button class="save-btn" id="save-btn">保存画像</button>
    <span class="save-hint" id="save-hint">✓ 已保存</span>`;
  body.appendChild(actions);
  document.getElementById('save-btn').addEventListener('click', saveProfile);
}

function addTag(editor, input, value) {
  // 去重
  const existing = [...editor.querySelectorAll('.tag-text')].map(t => t.textContent);
  if (existing.includes(value)) return;
  const tag = document.createElement('span');
  tag.className = 'tag';
  tag.innerHTML = `<span class="tag-text">${escHtml(value)}</span><button class="tag-remove" title="删除">✕</button>`;
  tag.querySelector('.tag-remove').addEventListener('click', () => tag.remove());
  editor.insertBefore(tag, input);
}

function collectField(key) {
  const editor = document.querySelector(`.tag-editor[data-key="${key}"]`);
  if (!editor) return [];
  return [...editor.querySelectorAll('.tag-text')].map(t => t.textContent);
}

/* ─── 加载 / 保存 ───────────────────────────────── */
async function loadProfile() {
  try {
    const res = await fetch('/api/profile', { headers: { 'Authorization': `Bearer ${auth.token}` } });
    if (res.status === 401) { localStorage.removeItem('auth'); window.location.href = '/?login=1'; return; }
    profileData = await res.json();
    renderEditors();
  } catch {
    document.getElementById('profile-body').innerHTML =
      '<div class="loading-hint">加载失败，请刷新重试。</div>';
  }
}

async function saveProfile() {
  const btn  = document.getElementById('save-btn');
  const hint = document.getElementById('save-hint');
  const payload = {};
  FIELDS.forEach(f => { payload[f.key] = collectField(f.key); });

  btn.disabled = true;
  try {
    const res = await fetch('/api/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${auth.token}` },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error();
    profileData = await res.json();
    hint.classList.add('show');
    setTimeout(() => hint.classList.remove('show'), 1800);
  } catch {
    alert('保存失败，请重试');
  } finally {
    btn.disabled = false;
  }
}

loadProfile();
