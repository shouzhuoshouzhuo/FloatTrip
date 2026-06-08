/* ─── 全局状态 ─────────────────────────────────── */
let currentPlanData = null;
let currentPlanId   = null;   // 最近一次成功规划的 plan_id（用于修改）
let pendingThreadId = null;   // missing_fields 后多轮续接用
const optimizedDays = new Map(); // dayIdx → agent 原始 timeline（供回退用）

/* ─── Auth 状态 ─────────────────────────────────── */
function getAuth() {
  try { return JSON.parse(localStorage.getItem('auth') || 'null'); } catch { return null; }
}
function setAuth(data) {
  localStorage.setItem('auth', JSON.stringify(data));
}
function clearAuth() {
  localStorage.removeItem('auth');
}
function authHeaders() {
  const a = getAuth();
  return a && a.token ? { 'Authorization': `Bearer ${a.token}` } : {};
}

/* ─── 导航栏用户区 ──────────────────────────────── */
function updateNavUser() {
  const nav = document.getElementById('nav-user');
  if (!nav) return;
  const a = getAuth();
  if (a && a.username) {
    nav.innerHTML =
      `<span class="nav-username">${escHtml(a.username)}</span>` +
      `<button class="nav-logout-btn" id="nav-logout">退出</button>`;
    document.getElementById('nav-logout').addEventListener('click', () => {
      clearAuth(); updateNavUser();
    });
  } else {
    nav.innerHTML = `<button class="nav-login-btn" id="nav-login-btn">登录 / 注册</button>`;
    document.getElementById('nav-login-btn').addEventListener('click', () => openModal('login'));
  }
}

/* ─── 顶部框模式切换（新建 vs 修改）─────────────── */
const NEW_LABEL  = '描述你的旅行需求（含目的地、日期、偏好）';
const NEW_PH     = '例如：南京 2026-06-10 到 2026-06-12 三天，喜欢历史古迹，想吃本地小吃，慢节奏';
const MOD_LABEL  = '对行程有意见？再次输入即可修改当前行程';
const MOD_PH     = '例如：第2天把夫子庙换成中山陵，景点别太多';

function updateSubmitMode() {
  const label = document.querySelector('#query-section label');
  const isModify = !!currentPlanId;
  submitBtn.textContent = isModify ? '🔧 修改规划' : '✨ 开始规划';
  if (label) label.textContent = isModify ? MOD_LABEL : NEW_LABEL;
  queryInput.placeholder = isModify ? MOD_PH : NEW_PH;
}

/* ─── 登录/注册模态框 ───────────────────────────── */
let _modalMode = 'login';

function openModal(mode) {
  _modalMode = mode || 'login';
  document.getElementById('auth-modal').style.display = 'flex';
  document.getElementById('auth-username').value = '';
  document.getElementById('auth-password').value = '';
  document.getElementById('auth-error').style.display = 'none';
  _updateModalUI();
}
function closeModal() {
  document.getElementById('auth-modal').style.display = 'none';
}
function _updateModalUI() {
  const isLogin = _modalMode === 'login';
  document.getElementById('tab-login').classList.toggle('active', isLogin);
  document.getElementById('tab-register').classList.toggle('active', !isLogin);
  document.getElementById('auth-submit').textContent = isLogin ? '登录' : '注册';
}

document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('auth-modal').addEventListener('click', e => {
  if (e.target === document.getElementById('auth-modal')) closeModal();
});
document.getElementById('tab-login').addEventListener('click', () => { _modalMode = 'login'; _updateModalUI(); });
document.getElementById('tab-register').addEventListener('click', () => { _modalMode = 'register'; _updateModalUI(); });

document.getElementById('auth-submit').addEventListener('click', async () => {
  const username = document.getElementById('auth-username').value.trim();
  const password = document.getElementById('auth-password').value;
  const errEl    = document.getElementById('auth-error');
  if (!username || !password) {
    errEl.textContent = '用户名和密码不能为空'; errEl.style.display = 'block'; return;
  }
  const btn = document.getElementById('auth-submit');
  btn.disabled = true;
  try {
    const url = _modalMode === 'login' ? '/api/auth/login' : '/api/auth/register';
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.detail || '操作失败'; errEl.style.display = 'block'; return;
    }
    setAuth(data);
    closeModal();
    updateNavUser();
  } catch (e) {
    errEl.textContent = '网络错误，请重试'; errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
  }
});

// 回车提交
['auth-username', 'auth-password'].forEach(id => {
  document.getElementById(id).addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('auth-submit').click();
  });
});

// 初始化导航栏（不依赖下方 DOM 引用）
updateNavUser();

/* ─── DOM 引用 ─────────────────────────────────── */
const queryInput   = document.getElementById('query-input');
const submitBtn    = document.getElementById('submit-btn');
const querySection = document.getElementById('query-section');
const loadingSection = document.getElementById('loading-section');
const errorSection = document.getElementById('error-section');
const errorList    = document.getElementById('error-list');
const resultSection = document.getElementById('result-section');

// 初始化顶部框模式（依赖上方 submitBtn / queryInput）
updateSubmitMode();

/* ─── 工具函数 ─────────────────────────────────── */

function showSection(name) {
  loadingSection.style.display = 'none';
  errorSection.style.display   = 'none';
  resultSection.style.display  = 'none';

  if (name === 'loading') {
    loadingSection.style.display = 'block';
  } else if (name === 'error') {
    errorSection.style.display = 'block';
  } else if (name === 'result') {
    resultSection.style.display = 'block';
  }
}

function periodInfo(period) {
  const MAP = {
    morning:   { icon: '🌅', label: '上午', cls: 'morning' },
    afternoon: { icon: '☀️',  label: '下午', cls: 'afternoon' },
    evening:   { icon: '🌙', label: '夜间', cls: 'evening' },
  };
  return MAP[period] || { icon: '📍', label: period, cls: 'morning' };
}

function starRating(r) {
  if (r == null) return '';
  return `⭐ ${r.toFixed(1)}`;
}

function makeImg(url, alt) {
  if (!url) {
    return `<div class="thumb thumb-placeholder" aria-label="${escHtml(alt)}">🖼</div>`;
  }
  return `<div class="thumb" style="background-image:url('${escHtml(url)}')" aria-label="${escHtml(alt)}"></div>`;
}

function escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function el(html) {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div.firstElementChild;
}

/* ─── 构建距离徽章 ─────────────────────────────── */
function distBadge(km) {
  const wrap = document.createElement('div');
  wrap.className = 'dist-badge';
  wrap.innerHTML = `<span>↕ ${km} km</span>`;
  return wrap;
}

/* ─── 景点卡 ────────────────────────────────────── */
function attractionCard(item) {
  const p = periodInfo(item.period);
  const timeRange = (item.start_time && item.end_time)
    ? `${item.start_time} – ${item.end_time}`
    : '';
  const openTime = item.open_time
    ? item.open_time.substring(0, 40) + (item.open_time.length > 40 ? '…' : '')
    : '';

  const node = document.createElement('div');
  node.className = 'timeline-node';

  const card = document.createElement('div');
  card.className = 'card attraction-card';
  card.innerHTML = `
    ${makeImg(item.photo, item.name)}
    <div class="card-body">
      <div class="card-title">${escHtml(item.name)}</div>
      <div class="card-meta">
        <span class="period-badge ${p.cls}">${p.icon} ${p.label}</span>
        ${timeRange ? `<span class="time-range">🕐 ${escHtml(timeRange)}</span>` : ''}
        ${item.rating != null ? `<span class="meta-item">${starRating(item.rating)}</span>` : ''}
      </div>
      ${openTime ? `<div class="open-time" title="${escHtml(item.open_time || '')}">🕒 ${escHtml(openTime)}</div>` : ''}
    </div>`;

  node.appendChild(card);
  return node;
}

/* ─── 餐厅卡（内容部分，可复用于并排和顺序两种布局）─── */
function mealCardInner(item) {
  const isLunch   = item.type === 'lunch';
  const typeLabel = isLunch ? '🍜 午餐' : '🍽 晚餐';

  const card = document.createElement('div');
  card.className = `card meal-card ${item.type}`;

  const extras = item.reason
    ? `<div class="reason-box">${escHtml(item.reason)}</div>`
    : '';

  card.innerHTML = `
    ${makeImg(item.photo, item.name)}
    <div class="card-body">
      <div class="meal-type-label">${typeLabel}</div>
      <div class="card-title">${escHtml(item.name || '—')}</div>
      <div class="card-meta">
        ${item.rating != null ? `<span class="meta-item">${starRating(item.rating)}</span>` : ''}
        ${item.cost ? `<span class="meta-item">💰 ¥${escHtml(item.cost)}/人</span>` : ''}
      </div>
      ${item.address ? `<div class="open-time">📍 ${escHtml(item.address)}</div>` : ''}
      ${extras}
    </div>`;
  return card;
}

/* 无餐厅提醒卡内容 */
function noRestaurantCardInner(item) {
  const typeLabel = item.type === 'lunch' ? '🍜 午餐' : '🍽 晚餐';
  const mealCn   = item.type === 'lunch' ? '午餐' : '晚餐';
  const card = document.createElement('div');
  card.className = `card no-restaurant-card ${item.type}`;
  card.innerHTML = `
    <div class="card-body">
      <div class="meal-type-label">${typeLabel}</div>
      <div class="no-restaurant-notice">
        ⚠️ 该时段附近暂无餐厅数据，建议出发前自行规划${mealCn}
      </div>
    </div>`;
  return card;
}

/* 顺序布局的单餐条目 */
function mealTimelineNode(item) {
  const node = document.createElement('div');
  node.className = 'timeline-node';
  node.appendChild(item.no_restaurant ? noRestaurantCardInner(item) : mealCardInner(item));
  return node;
}

/* ─── 普通时间轴（多景点日）─────────────────────── */
function buildNormalTimeline(container, items) {
  items.forEach((item) => {
    if (item.dist_from_prev_km != null) {
      container.appendChild(distBadge(item.dist_from_prev_km));
    }
    if (item.type === 'attraction') {
      container.appendChild(attractionCard(item));
    } else if (item.type === 'lunch' || item.type === 'dinner') {
      container.appendChild(mealTimelineNode(item));
    }
  });
}

/* ─── 全天游时间轴（单景点日）──────────────────── */
function buildFullDayTimeline(container, items) {
  const attraction = items.find(i => i.type === 'attraction');
  const meals      = items.filter(i => i.type === 'lunch' || i.type === 'dinner');

  // 景点卡（全天 badge 替换 period pill）
  if (attraction) {
    const node = document.createElement('div');
    node.className = 'timeline-node';

    const timeRange = (attraction.start_time && attraction.end_time)
      ? `${attraction.start_time} – ${attraction.end_time}`
      : '';
    const openTime = attraction.open_time
      ? attraction.open_time.substring(0, 40) + (attraction.open_time.length > 40 ? '…' : '')
      : '';

    const card = document.createElement('div');
    card.className = 'card attraction-card';
    card.innerHTML = `
      ${makeImg(attraction.photo, attraction.name)}
      <div class="card-body">
        <div class="card-title">${escHtml(attraction.name)}</div>
        <div class="card-meta">
          <span class="period-badge full-day">🗓 全天游</span>
          ${timeRange ? `<span class="time-range">🕐 ${escHtml(timeRange)}</span>` : ''}
          ${attraction.rating != null ? `<span class="meta-item">${starRating(attraction.rating)}</span>` : ''}
        </div>
        ${openTime ? `<div class="open-time" title="${escHtml(attraction.open_time || '')}">🕒 ${escHtml(openTime)}</div>` : ''}
      </div>`;
    node.appendChild(card);
    container.appendChild(node);
  }

  // 餐饮并排区
  if (meals.length > 0) {
    const label = document.createElement('div');
    label.className = 'meals-section-label';
    label.textContent = '今日餐饮安排';
    container.appendChild(label);

    const row = document.createElement('div');
    row.className = 'meals-row';

    meals.forEach(meal => {
      const half = document.createElement('div');
      half.className = 'meal-half';
      half.appendChild(meal.no_restaurant ? noRestaurantCardInner(meal) : mealCardInner(meal));
      row.appendChild(half);
    });
    container.appendChild(row);
  }
}

/* ─── 渲染时间轴（入口）─────────────────────────── */
function buildTimeline(items) {
  const container = document.getElementById('timeline');
  container.innerHTML = '';

  const attractionCount = items.filter(i => i.type === 'attraction').length;

  if (attractionCount === 1) {
    buildFullDayTimeline(container, items);
  } else {
    buildNormalTimeline(container, items);
  }
}

/* ─── 天气工具 ──────────────────────────────────── */
function getWeatherForDate(weatherForecast, dateStr) {
  if (!weatherForecast || !dateStr) return null;
  return weatherForecast.find(w => w.date === dateStr) || null;
}

function weatherIcon(weather) {
  if (!weather) return '☀️';
  if (weather.includes('雨'))                        return '🌧️';
  if (weather.includes('雪'))                        return '❄️';
  if (weather.includes('雾') || weather.includes('霾')) return '🌫️';
  if (weather.includes('阴'))                        return '☁️';
  if (weather.includes('多云'))                      return '⛅';
  return '☀️';
}

/* ─── 渲染天标签 ───────────────────────────────── */
function buildDayTabs(days, weatherForecast) {
  const tabsEl = document.getElementById('day-tabs');
  tabsEl.innerHTML = '';

  days.forEach((day, i) => {
    const w   = getWeatherForDate(weatherForecast, day.date);
    const btn = document.createElement('button');
    btn.className = 'tab' + (i === 0 ? ' active' : '');
    if (w && w.is_bad) btn.classList.add('rainy');
    if (day.date) btn.title = day.date;

    const dayLabel = document.createElement('span');
    dayLabel.textContent = `Day ${day.day}`;
    btn.appendChild(dayLabel);

    if (w) {
      const wSpan = document.createElement('span');
      wSpan.className = 'tab-weather';
      wSpan.textContent = `${weatherIcon(w.day_weather)} ${w.day_temp}°C`;
      btn.appendChild(wSpan);
    }

    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      switchDay(i);
    });
    tabsEl.appendChild(btn);
  });
}

function switchDay(i) {
  const days = currentPlanData.plan.days;
  const day  = days[i];

  // 天主题文字 + 优化按钮（同行 flex 布局）
  const themeEl = document.getElementById('day-theme');
  themeEl.innerHTML = '';

  const themeText = document.createElement('span');
  themeText.textContent = day.theme ? `📅 ${day.date || ''}  ${day.theme}` : (day.date || '');
  themeEl.appendChild(themeText);

  // 当天景点 ≥ 2 个且已登录（有 plan_id）时显示优化/回退按钮
  const attractionCount = (day.timeline || []).filter(t => t.type === 'attraction').length;
  if (attractionCount >= 2 && currentPlanId) {
    const btn = document.createElement('button');
    btn.className = 'btn-optimize';
    // 无论是否已优化，都预先绑定 onclick，确保 revertDay 恢复按钮后仍可点击
    btn.onclick = () => optimizeDay(currentPlanId, day.day, btn, i);

    if (optimizedDays.has(i)) {
      // 已优化状态：禁用优化按钮 + 显示回退
      btn.textContent = '✅ 已优化';
      btn.disabled = true;
      themeEl.appendChild(btn);

      const revertBtn = document.createElement('button');
      revertBtn.className = 'btn-revert';
      revertBtn.textContent = '↩️ 回退';
      revertBtn.onclick = () => revertDay(currentPlanId, day.day, optimizedDays.get(i), revertBtn, btn, i);
      themeEl.appendChild(revertBtn);
    } else {
      btn.textContent = '🔀 优化路线';
      themeEl.appendChild(btn);
    }
  }

  buildTimeline(day.timeline);
  renderDayMap(day);
}

/* ─── 路线优化（暴力枚举最短路径）────────────────── */
async function optimizeDay(planId, dayNum, btn, dayIdx) {
  // 首次优化才保存 agent 原始 timeline，防止二次优化时覆盖
  if (!optimizedDays.has(dayIdx)) {
    optimizedDays.set(dayIdx,
      JSON.parse(JSON.stringify(currentPlanData?.plan?.days?.[dayIdx]?.timeline || []))
    );
  }

  btn.disabled = true;
  btn.textContent = '⏳ 优化中…';

  try {
    const res = await fetch('/api/plan/optimize_day', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ plan_id: planId, day: dayNum }),
    });

    if (!res.ok) {
      btn.textContent = '❌ 失败，重试';
      btn.disabled = false;
      optimizedDays.delete(dayIdx); // 失败时清除，允许重试
      return;
    }

    const data = await res.json();

    // 更新内存中的 plan（保证切换回来时数据也是最新的）
    if (currentPlanData?.plan?.days?.[dayIdx]) {
      currentPlanData.plan.days[dayIdx].timeline = data.optimized_day.timeline;
    }

    // 重新渲染当天 timeline 和地图
    buildTimeline(data.optimized_day.timeline);
    renderDayMap(data.optimized_day);

    // 显示优化结果
    if (data.improved) {
      btn.textContent = `✅ ${data.original_km.toFixed(1)}→${data.optimized_km.toFixed(1)}km`;
    } else {
      btn.textContent = '✅ 已是最优';
    }

    // 注入回退按钮（从 Map 取 agent 原始 timeline）
    const revertBtn = document.createElement('button');
    revertBtn.className = 'btn-revert';
    revertBtn.textContent = '↩️ 回退';
    revertBtn.onclick = () => revertDay(planId, dayNum, optimizedDays.get(dayIdx), revertBtn, btn, dayIdx);
    document.getElementById('day-theme').appendChild(revertBtn);

  } catch {
    btn.textContent = '❌ 失败，重试';
    btn.disabled = false;
    optimizedDays.delete(dayIdx);
  }
}

/* ─── 回退路线优化 ──────────────────────────────── */
async function revertDay(planId, dayNum, originalTimeline, revertBtn, optimizeBtn, dayIdx) {
  revertBtn.disabled = true;
  revertBtn.textContent = '⏳ 回退中…';

  try {
    const res = await fetch('/api/plan/revert_day', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ plan_id: planId, day: dayNum, original_timeline: originalTimeline }),
    });

    if (!res.ok) {
      revertBtn.textContent = '❌ 失败';
      revertBtn.disabled = false;
      return;
    }

    // 还原内存中的 plan
    if (currentPlanData?.plan?.days?.[dayIdx]) {
      currentPlanData.plan.days[dayIdx].timeline = originalTimeline;
    }

    // 重新渲染
    buildTimeline(originalTimeline);
    renderDayMap({ ...(currentPlanData?.plan?.days?.[dayIdx] || {}), timeline: originalTimeline });

    // 从 Map 中删除，恢复"未优化"状态
    optimizedDays.delete(dayIdx);
    // 移除回退按钮，恢复优化按钮
    revertBtn.remove();
    optimizeBtn.textContent = '🔀 优化路线';
    optimizeBtn.disabled = false;

  } catch {
    revertBtn.textContent = '❌ 失败';
    revertBtn.disabled = false;
  }
}

/* ─── 渲染计划头部 ─────────────────────────────── */
function buildHeader(plan) {
  document.getElementById('plan-title').textContent =
    `${plan.destination}  ${plan.days_count} 日游`;

  document.getElementById('plan-dates').textContent =
    `${plan.start_date || ''} ~ ${plan.end_date || ''}`;

  const badgesEl = document.getElementById('plan-badges');
  badgesEl.innerHTML = '';

  const addBadge = (text, cls = '') => {
    const b = document.createElement('span');
    b.className = 'badge' + (cls ? ' ' + cls : '');
    b.textContent = text;
    badgesEl.appendChild(b);
  };

  if (plan.preferences?.attraction) addBadge('🏛 ' + plan.preferences.attraction);
  if (plan.preferences?.food)       addBadge('🍴 ' + plan.preferences.food);
  if (plan.preferences?.habit)      addBadge('🧘 ' + plan.preferences.habit);

  if (plan.approved) {
    addBadge(`✅ 评审通过（${plan.review_rounds} 轮）`, 'approved');
  } else {
    addBadge(`⚠️ 达最大轮数（${plan.review_rounds}）`, 'unapproved');
  }
}

/* ─── 渲染历史日志 ─────────────────────────────── */
function buildHistory(history) {
  const ul = document.getElementById('history-list');
  ul.innerHTML = '';
  (history || []).forEach(line => {
    const li = document.createElement('li');
    li.textContent = line;
    ul.appendChild(li);
  });
}

/* ─── 天气降级 banner ──────────────────────────── */
function renderWeatherNoteBanner(note) {
  const old = document.getElementById('weather-note-banner');
  if (old) old.remove();
  if (!note) return;
  const banner = document.createElement('div');
  banner.id = 'weather-note-banner';
  banner.className = 'weather-note-banner';
  banner.textContent = `ℹ️ ${note}`;
  document.querySelector('.plan-header').insertAdjacentElement('afterend', banner);
}

/* ─── 路线问题 bullet 卡 ───────────────────────── */
function renderRouteIssuesCard(issues) {
  const old = document.getElementById('route-issues-card');
  if (old) old.remove();
  if (!issues || issues.length === 0) return;
  const card = document.createElement('div');
  card.id = 'route-issues-card';
  card.className = 'route-issues-card';
  card.innerHTML = `
    <div class="route-issues-title">⚠️ 路线注意事项（已达最大优化轮次）</div>
    <ul class="route-issues-list">
      ${issues.map(i => `<li>${escHtml(i)}</li>`).join('')}
    </ul>`;
  document.getElementById('history-details').insertAdjacentElement('beforebegin', card);
}

/* ─── 主渲染入口 ───────────────────────────────── */
function renderPlan(data) {
  optimizedDays.clear(); // 新 plan 加载时重置优化状态
  currentPlanData = data;
  if (data.plan_id) currentPlanId = data.plan_id;

  buildHeader(data.plan);
  buildDayTabs(data.plan.days, data.plan.weather_forecast || []);
  switchDay(0);
  buildHistory(data.history);

  renderWeatherNoteBanner(data.plan.weather_note);

  renderRouteIssuesCard(!data.plan.approved ? (data.plan.route_issues || []) : []);

  showSection('result');
  updateSubmitMode();
  resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ─── 缺必填错误 ───────────────────────────────── */
const FIELD_HINTS = {
  'destination（目的地）':                   '去哪里玩？比如「南京」「成都」「云南大理」',
  'travel_start_date（开始日期）':           '出发日期是哪天？比如「6月20日」「2026-06-20」',
  'travel_end_date（结束日期）':             '结束日期或玩几天？比如「玩3天」「到6月23日」',
  'travel_end_date（结束日期早于开始日期）': '结束日期好像比出发日期还早，检查一下？',
};

function showError(missingFields, threadId) {
  errorList.innerHTML = '';
  missingFields.forEach(f => {
    const li = document.createElement('li');
    li.textContent = FIELD_HINTS[f] || f;
    errorList.appendChild(li);
  });
  const titleEl = document.getElementById('error-title');
  if (threadId) {
    pendingThreadId = threadId;
    if (titleEl) titleEl.textContent = '还差一点点 🙈 补充下面的信息，直接重新提交就好：';
  } else {
    if (titleEl) titleEl.textContent = '还差一点点 🙈 请补充以下信息后重试：';
  }
  showSection('error');
}

/* ─── 修改顾虑 Human-in-the-Loop 模态框 ─────────── */
let _pendingId    = null;
let _parentPlanId = null;

function showConcernModal(concern, pendingId, parentPlanId) {
  _pendingId    = pendingId;
  _parentPlanId = parentPlanId || null;
  document.getElementById('concern-body').textContent = concern;
  document.getElementById('concern-modal').style.display = 'flex';
}
function closeConcernModal() {
  document.getElementById('concern-modal').style.display = 'none';
  _pendingId    = null;
  _parentPlanId = null;
}

document.getElementById('concern-cancel').addEventListener('click', () => {
  closeConcernModal();
  // 恢复到展示原行程（result-section 仍在）
  showSection('result');
});

document.getElementById('concern-confirm').addEventListener('click', async () => {
  const pid = _pendingId;
  const ppid = _parentPlanId;
  closeConcernModal();
  if (!pid) return;
  // 调 confirm 端点，走 SSE
  await runConfirmStream(pid, ppid);
});

async function runConfirmStream(pendingId, parentPlanId) {
  const btn = submitBtn;
  if (btn) btn.disabled = true;
  resetProgress();
  showSection('loading');
  try {
    const res = await fetch('/api/plan/confirm_modification', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ pending_id: pendingId, parent_plan_id: parentPlanId }),
    });
    if (!res.ok || !res.body) throw new Error(`服务器错误 ${res.status}`);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let settled = false;

    const handle = (raw) => {
      let ev;
      try { ev = JSON.parse(raw); } catch { return; }
      if (ev.type === 'stage') {
        appendProgressStep(ev);
      } else if (ev.type === 'result') {
        settled = true;
        finishProgress();
        if (!ev.success) {
          showError(ev.missing_fields || ['未知错误'], null);
        } else {
          renderPlan(ev);
        }
      } else if (ev.type === 'error') {
        settled = true;
        showError([`规划失败：${ev.message || '未知错误'}`]);
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep;
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        for (const line of frame.split('\n')) {
          const trimmed = line.replace(/\r$/, '');
          if (trimmed.startsWith('data:')) handle(trimmed.slice(5).trim());
        }
      }
    }
    if (!settled) showError(['连接已中断，请重试']);
  } catch (err) {
    showError([`请求失败：${err.message}`]);
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* ─── 实时阶段清单 ─────────────────────────────── */
function resetProgress() {
  const box = document.getElementById('progress-steps');
  if (box) box.innerHTML = '';
}

/* 收到一条 stage 事件：把上一条标记为完成，追加当前进行中的一条 */
function appendProgressStep(ev) {
  const box = document.getElementById('progress-steps');
  if (!box) return;

  const active = box.querySelector('.progress-step.active');
  if (active) {
    active.classList.remove('active');
    active.classList.add('done');
    const icon = active.querySelector('.step-icon');
    if (icon) icon.textContent = '✓';
  }

  const step = document.createElement('div');
  step.className = 'progress-step active';
  step.innerHTML =
    `<span class="step-icon"><span class="step-spinner"></span></span>` +
    `<span class="step-label"></span>`;
  step.querySelector('.step-label').textContent = ev.label || ev.node || '处理中…';
  box.appendChild(step);
}

/* 全部完成：最后一条也打勾 */
function finishProgress() {
  const box = document.getElementById('progress-steps');
  if (!box) return;
  const active = box.querySelector('.progress-step.active');
  if (active) {
    active.classList.remove('active');
    active.classList.add('done');
    const icon = active.querySelector('.step-icon');
    if (icon) icon.textContent = '✓';
  }
}

/* ─── 通用 SSE 规划请求 ─────────────────────────── */
async function runPlanStream(payload, btn) {
  if (btn) btn.disabled = true;
  resetProgress();
  showSection('loading');

  try {
    const res = await fetch('/api/plan/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(payload),
    });

    if (res.status === 401) { openModal('login'); if (btn) btn.disabled = false; return; }
    if (!res.ok || !res.body) throw new Error(`服务器错误 ${res.status}`);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let settled = false;

    const handle = (raw) => {
      let ev;
      try { ev = JSON.parse(raw); } catch { return; }

      if (ev.type === 'stage') {
        appendProgressStep(ev);
      } else if (ev.type === 'result') {
        settled = true;
        finishProgress();
        if (!ev.success) {
          showError(ev.missing_fields || ['未知错误，请检查输入'], ev.thread_id);
        } else {
          renderPlan(ev);
        }
      } else if (ev.type === 'modification_warning') {
        // Human-in-the-Loop：planner 有顾虑，暂停等用户确认
        settled = true;
        finishProgress();
        showSection('result'); // 保持原行程可见
        showConcernModal(ev.concern, ev.pending_id, ev.parent_plan_id);
      } else if (ev.type === 'error') {
        settled = true;
        showError([`规划失败：${ev.message || '未知错误'}`]);
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep;
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        for (const line of frame.split('\n')) {
          const trimmed = line.replace(/\r$/, '');
          if (trimmed.startsWith('data:')) handle(trimmed.slice(5).trim());
        }
      }
    }
    if (!settled) showError(['连接已中断，请重试']);
  } catch (err) {
    showError([`请求失败：${err.message}`]);
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* ─── 顶部框提交（新建 / 修改 二合一）───────────── */
submitBtn.addEventListener('click', async () => {
  if (!getAuth()) { openModal('login'); return; }
  const text = queryInput.value.trim();
  if (!text) { queryInput.focus(); return; }

  let payload;
  if (currentPlanId) {
    // 正在查看某行程 → 输入即为修改意见
    payload = { query: '修改行程', plan_id: currentPlanId, modification_notes: text };
  } else {
    payload = { query: text };
    if (pendingThreadId) {
      payload.thread_id = pendingThreadId;
      pendingThreadId = null;
    }
  }
  queryInput.value = '';
  await runPlanStream(payload, submitBtn);
});

/* 回车（Ctrl/Cmd + Enter）提交 */
queryInput.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    submitBtn.click();
  }
});

/* ─── 高德地图：每日动线可视化 ─────────────────── */
let amapConfig    = null;
let amapPromise   = null;
let mapInstance   = null;
let mapOverlays   = [];
let mapInfoWindow = null;

async function loadAmapConfig() {
  if (amapConfig) return amapConfig;
  try { amapConfig = await fetch('/api/config').then(r => r.json()); }
  catch { amapConfig = { amap_js_key: '', amap_js_security_code: '' }; }
  return amapConfig;
}

function ensureAMap() {
  if (amapPromise) return amapPromise;
  amapPromise = (async () => {
    const cfg = await loadAmapConfig();
    if (!cfg.amap_js_key) throw new Error('未配置 AMAP_JS_KEY');
    if (cfg.amap_js_security_code)
      window._AMapSecurityConfig = { securityJsCode: cfg.amap_js_security_code };
    return AMapLoader.load({
      key: cfg.amap_js_key, version: '2.0',
      plugins: ['AMap.Marker', 'AMap.Polyline', 'AMap.InfoWindow'],
    });
  })();
  return amapPromise;
}

function showMapEmpty(msg) {
  const mapEl = document.getElementById('day-map');
  const empty = document.getElementById('day-map-empty');
  if (mapEl) mapEl.style.display = 'none';
  if (empty) {
    empty.style.display = 'flex';
    if (msg && msg !== false) empty.textContent = msg;
  }
}

function mapInfoContent(item) {
  const photoHtml = item.photo
    ? `<img class="map-info-photo" src="${escHtml(item.photo)}" alt="${escHtml(item.name||'')}"
           onerror="this.outerHTML='<div class=\\'map-info-photo-placeholder\\'>🖼</div>'">`
    : `<div class="map-info-photo-placeholder">🖼</div>`;
  let meta = '';
  if (item.type === 'attraction') {
    const p  = periodInfo(item.period);
    const tr = (item.start_time && item.end_time)
      ? `🕐 ${escHtml(item.start_time)} – ${escHtml(item.end_time)}` : '';
    meta = `
      <div class="map-info-meta">
        <span class="period-badge ${p.cls}">${p.icon} ${p.label}</span>
        ${tr ? `<span>${tr}</span>` : ''}
        ${item.rating != null ? `<span>${starRating(item.rating)}</span>` : ''}
      </div>
      ${item.open_time ? `<div class="map-info-sub">🕒 ${escHtml(item.open_time)}</div>` : ''}`;
  } else {
    const lbl = item.type === 'lunch' ? '🍜 午餐' : '🍽 晚餐';
    meta = `
      <div class="map-info-meta">
        <span class="meal-type-label">${lbl}</span>
        ${item.rating != null ? `<span>${starRating(item.rating)}</span>` : ''}
        ${item.cost ? `<span>💰 ¥${escHtml(item.cost)}/人</span>` : ''}
      </div>
      ${item.address ? `<div class="map-info-sub">📍 ${escHtml(item.address)}</div>` : ''}
      ${item.reason  ? `<div class="map-info-reason">${escHtml(item.reason)}</div>` : ''}`;
  }
  return `<div class="map-info">${photoHtml}
    <div class="map-info-body">
      <div class="map-info-title">${escHtml(item.name||'—')}</div>
      ${meta}
    </div></div>`;
}

function markerContent(index, isAttraction) {
  return `<div class="map-pin ${isAttraction ? 'map-pin-attraction' : 'map-pin-meal'}">${index}</div>`;
}

async function renderDayMap(day) {
  const points = (day.timeline || []).filter(
    it => it.location && it.location.lng != null && it.location.lat != null
  );
  if (points.length === 0) { showMapEmpty('本日暂无可定位的地点'); return; }

  let AMap;
  try { AMap = await ensureAMap(); }
  catch { showMapEmpty(false); return; }

  try {
    const mapEl = document.getElementById('day-map');
    const empty = document.getElementById('day-map-empty');
    if (mapEl) mapEl.style.display = 'block';
    if (empty) empty.style.display = 'none';

    if (!mapInstance) {
      mapInstance   = new AMap.Map('day-map', { zoom: 12 });
      mapInfoWindow = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -32), autoMove: true });
    }
    if (mapOverlays.length) { mapInstance.remove(mapOverlays); mapOverlays = []; }
    mapInfoWindow.close();

    const path = [];
    points.forEach((item, i) => {
      const pos = [item.location.lng, item.location.lat];
      path.push(pos);
      const marker = new AMap.Marker({
        position: pos,
        content: markerContent(i + 1, item.type === 'attraction'),
        offset: new AMap.Pixel(-14, -14),
        zIndex: 100 + i,
      });
      marker.on('click', () => {
        mapInfoWindow.setContent(mapInfoContent(item));
        mapInfoWindow.open(mapInstance, pos);
      });
      mapOverlays.push(marker);
    });

    if (path.length >= 2) {
      const poly = new AMap.Polyline({
        path, strokeColor: '#2e9898', strokeWeight: 4,
        strokeOpacity: 0.85, strokeStyle: 'solid',
        showDir: true, lineJoin: 'round',
      });
      mapOverlays.push(poly);
    }

    mapInstance.add(mapOverlays);
    mapInstance.setFitView(mapOverlays, false, [40, 40, 40, 40]);
  } catch { showMapEmpty('地图加载失败，已为你保留行程清单'); }
}

/* ─── URL 参数处理 ──────────────────────────────── */
(async function handleUrlParams() {
  const params = new URLSearchParams(window.location.search);

  // ?login=1 → 自动打开登录框
  if (params.get('login') === '1' && !getAuth()) {
    openModal('login');
    // 清理 URL
    history.replaceState({}, '', '/');
  }

  // ?view_plan_id=xxx → 从历史加载并渲染行程
  const viewId = params.get('view_plan_id');
  if (viewId) {
    const a = getAuth();
    if (!a) { openModal('login'); return; }
    try {
      const res = await fetch(`/api/history/${viewId}`, {
        headers: authHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        currentPlanId = viewId;
        renderPlan({ plan: data.plan, history: [], plan_id: viewId });
      }
    } catch {}
    history.replaceState({}, '', '/');
  }
})();
