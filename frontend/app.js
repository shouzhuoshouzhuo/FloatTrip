/* ─── 全局状态 ─────────────────────────────────── */
let currentPlanData = null;

/* ─── DOM 引用 ─────────────────────────────────── */
const queryInput   = document.getElementById('query-input');
const submitBtn    = document.getElementById('submit-btn');
const querySection = document.getElementById('query-section');
const loadingSection = document.getElementById('loading-section');
const errorSection = document.getElementById('error-section');
const errorList    = document.getElementById('error-list');
const resultSection = document.getElementById('result-section');

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
    return `<div class="card-photo-placeholder">🖼</div>`;
  }
  // 用占位 div 兜底，图片加载失败时替换
  const id = 'img_' + Math.random().toString(36).slice(2);
  return `
    <div id="${id}_wrap">
      <img class="card-photo"
           src="${escHtml(url)}"
           alt="${escHtml(alt)}"
           id="${id}"
           loading="lazy"
           onerror="this.parentNode.innerHTML='<div class=\\'card-photo-placeholder\\'>🖼</div>'" />
    </div>`;
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

  let extras = '';
  if (item.reason)          extras += `<div class="reason-box">${escHtml(item.reason)}</div>`;
  if (item.fallback_reason) extras += `<div class="fallback-box">${escHtml(item.fallback_reason)}</div>`;

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

/* ─── 渲染天标签 ───────────────────────────────── */
function buildDayTabs(days) {
  const tabsEl = document.getElementById('day-tabs');
  tabsEl.innerHTML = '';

  days.forEach((day, i) => {
    const btn = document.createElement('button');
    btn.className = 'tab' + (i === 0 ? ' active' : '');
    btn.textContent = `Day ${day.day}`;
    if (day.date) btn.title = day.date;
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
  document.getElementById('day-theme').textContent =
    day.theme ? `📅 ${day.date || ''}  ${day.theme}` : (day.date || '');
  buildTimeline(day.timeline);
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

/* ─── 主渲染入口 ───────────────────────────────── */
function renderPlan(data) {
  currentPlanData = data;

  buildHeader(data.plan);
  buildDayTabs(data.plan.days);
  switchDay(0);
  buildHistory(data.history);

  showSection('result');
  resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ─── 缺必填错误 ───────────────────────────────── */
function showError(missingFields) {
  errorList.innerHTML = '';
  missingFields.forEach(f => {
    const li = document.createElement('li');
    li.textContent = f;
    errorList.appendChild(li);
  });
  showSection('error');
}

/* ─── 提交 ─────────────────────────────────────── */
submitBtn.addEventListener('click', async () => {
  const query = queryInput.value.trim();
  if (!query) {
    queryInput.focus();
    return;
  }

  submitBtn.disabled = true;
  showSection('loading');

  try {
    const res = await fetch('/api/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });

    if (!res.ok) {
      throw new Error(`服务器错误 ${res.status}`);
    }

    const data = await res.json();

    if (!data.success) {
      showError(data.missing_fields || ['未知错误，请检查输入']);
    } else {
      renderPlan(data);
    }
  } catch (err) {
    showError([`请求失败：${err.message}`]);
  } finally {
    submitBtn.disabled = false;
  }
});

/* 回车（Ctrl/Cmd + Enter）提交 */
queryInput.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    submitBtn.click();
  }
});
