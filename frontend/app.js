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
  document.getElementById('day-theme').textContent =
    day.theme ? `📅 ${day.date || ''}  ${day.theme}` : (day.date || '');
  buildTimeline(day.timeline);
  renderDayMap(day);
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
  currentPlanData = data;

  buildHeader(data.plan);
  buildDayTabs(data.plan.days, data.plan.weather_forecast || []);
  switchDay(0);
  buildHistory(data.history);

  renderWeatherNoteBanner(data.plan.weather_note);

  if (!data.plan.approved && data.plan.route_issues?.length > 0) {
    renderRouteIssuesCard(data.plan.route_issues);
  }

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

/* ─── 提交（SSE 流式）──────────────────────────── */
submitBtn.addEventListener('click', async () => {
  const query = queryInput.value.trim();
  if (!query) {
    queryInput.focus();
    return;
  }

  submitBtn.disabled = true;
  resetProgress();
  showSection('loading');

  try {
    const res = await fetch('/api/plan/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });

    if (!res.ok || !res.body) {
      throw new Error(`服务器错误 ${res.status}`);
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let settled = false;

    // 处理一条 SSE 事件（已剥离 data: 前缀的 JSON 文本）
    const handle = (payload) => {
      let ev;
      try { ev = JSON.parse(payload); } catch { return; }

      if (ev.type === 'stage') {
        appendProgressStep(ev);
      } else if (ev.type === 'result') {
        settled = true;
        finishProgress();
        if (!ev.success) {
          showError(ev.missing_fields || ['未知错误，请检查输入']);
        } else {
          renderPlan(ev);
        }
      } else if (ev.type === 'error') {
        settled = true;
        showError([`规划失败：${ev.message || '未知错误'}`]);
      }
    };

    // 逐 chunk 读取，按 SSE 帧（\n\n 分隔）解析
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
          if (trimmed.startsWith('data:')) {
            handle(trimmed.slice(5).trim());
          }
        }
      }
    }

    if (!settled) {
      showError(['连接已中断，请重试']);
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
