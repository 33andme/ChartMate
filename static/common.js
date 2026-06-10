// ══════════════════════════════════════════════════════
// common.js  v2 — 全局工具 + 光标星尘 + 主题切换
// ══════════════════════════════════════════════════════

const API_BASE = '';

// ── Token / 用户管理 ────────────────────────────────
const Auth = {
  getToken()  { return localStorage.getItem('astro_token'); },
  setToken(t) { localStorage.setItem('astro_token', t); },
  getUser()   { try { return JSON.parse(localStorage.getItem('astro_user')); } catch { return null; } },
  setUser(u)  { localStorage.setItem('astro_user', JSON.stringify(u)); },
  logout() {
    localStorage.removeItem('astro_token');
    localStorage.removeItem('astro_user');
    window.location.href = '/static/login.html';
  },
  requireLogin() {
    if (!this.getToken()) { window.location.href = '/static/login.html'; return false; }
    return true;
  },
};

// ── HTTP 请求封装 ────────────────────────────────────
async function request(path, options = {}) {
  const token = Auth.getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };
  try {
    const res = await fetch(API_BASE + path, {
      ...options,
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    if (res.status === 401) { Auth.logout(); return null; }
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || data.message || `请求失败 (${res.status})`);
    return data;
  } catch (err) {
    if (err.name === 'TypeError') throw new Error('网络连接失败，请检查网络');
    throw err;
  }
}

const api = {
  get:    (path)       => request(path, { method: 'GET' }),
  post:   (path, body) => request(path, { method: 'POST', body }),
  put:    (path, body) => request(path, { method: 'PUT', body }),
  delete: (path)       => request(path, { method: 'DELETE' }),
};

// ── Toast ────────────────────────────────────────────
function toast(message, type = 'info', duration = 3000) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }
  const icons = { success: '✅', error: '❌', info: 'ℹ️' };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${icons[type] || ''}</span><span>${message}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.cssText += 'opacity:0;transition:opacity .3s';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

// ── 时间格式 ─────────────────────────────────────────
function timeAgo(isoStr) {
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (diff < 60)    return '刚刚';
  if (diff < 3600)  return `${Math.floor(diff/60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff/3600)}小时前`;
  if (diff < 2592000) return `${Math.floor(diff/86400)}天前`;
  return new Date(isoStr).toLocaleDateString('zh-CN');
}

// ── 模态框 ───────────────────────────────────────────
function openModal(id)  { document.getElementById(id)?.classList.add('show'); }
function closeModal(id) { document.getElementById(id)?.classList.remove('show'); }

// ── 星座 Emoji ───────────────────────────────────────
const SIGN_EMOJI = {
  '白羊座':'♈','金牛座':'♉','双子座':'♊','巨蟹座':'♋',
  '狮子座':'♌','处女座':'♍','天秤座':'♎','天蝎座':'♏',
  '射手座':'♐','摩羯座':'♑','水瓶座':'♒','双鱼座':'♓',
};
function signEmoji(s) { return SIGN_EMOJI[s] || '⭐'; }

// ── 运势分数色 ───────────────────────────────────────
function scoreColor(s) {
  return s >= 85 ? '#10b981' : s >= 70 ? '#f59e0b' : '#ef4444';
}

// ── 底部导航高亮 ─────────────────────────────────────
function highlightNav() {
  const path = window.location.pathname;
  document.querySelectorAll('.nav-item').forEach(el => {
    const href = el.getAttribute('href');
    el.classList.toggle('active', href && path.endsWith(href.split('/').pop()));
  });
}

// ══════════════════════════════════════════════════════
// 主题切换系统
// ══════════════════════════════════════════════════════
const Theme = {
  current: localStorage.getItem('astro_theme') || 'dark',
  apply(theme) {
    this.current = theme;
    localStorage.setItem('astro_theme', theme);
    document.body.classList.toggle('light', theme === 'light');
    // 更新页面上所有的主题切换按钮状态
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      btn.textContent = theme === 'dark' ? '☀️ 浅色模式' : '🌙 深色模式';
    });
    // 触发主题切换事件，让其他组件可以监听并响应
    document.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme } }));
  },
  toggle() { this.apply(this.current === 'dark' ? 'light' : 'dark'); },
  init()   { this.apply(this.current); },
};

// ══════════════════════════════════════════════════════
// 光标星尘粒子系统（Canvas）
// ══════════════════════════════════════════════════════
function initCursorSparkle() {
  // 仅桌面设备（有鼠标）启用
  if (window.matchMedia('(hover: none)').matches) return;

  const canvas = document.createElement('canvas');
  canvas.id = 'cursor-canvas';
  canvas.style.cssText = [
    'position:fixed', 'top:0', 'left:0',
    'width:100%', 'height:100%',
    'pointer-events:none',
    'z-index:9997',
  ].join(';');
  document.body.appendChild(canvas);

  const ctx = canvas.getContext('2d');
  let W = canvas.width  = window.innerWidth;
  let H = canvas.height = window.innerHeight;
  window.addEventListener('resize', () => {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  });

  const particles = [];
  let lastX = 0, lastY = 0;

  document.addEventListener('mousemove', e => {
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
    const speed = Math.hypot(dx, dy);
    if (speed < 2) return;

    const count = Math.min(4, Math.floor(speed / 6) + 1);
    for (let i = 0; i < count; i++) {
      // 色调在 紫色(260°) 到 金色(45°) 之间随机
      const hue = Math.random() > .5
        ? 250 + Math.random() * 40   // 紫调
        : 35  + Math.random() * 20;  // 金调
      particles.push({
        x: e.clientX + (Math.random() - .5) * 8,
        y: e.clientY + (Math.random() - .5) * 8,
        vx: (Math.random() - .5) * 1.8,
        vy: Math.random() * -1.6 - .4,
        size: Math.random() * 3 + 1,
        alpha: .75 + Math.random() * .25,
        hue,
        decay: .022 + Math.random() * .014,
      });
    }
  });

  // 绘制四角星
  function star4(cx, cy, r) {
    ctx.beginPath();
    for (let i = 0; i < 8; i++) {
      const angle = (i * Math.PI) / 4;
      const radius = i % 2 === 0 ? r : r * .38;
      const x = cx + Math.cos(angle) * radius;
      const y = cy + Math.sin(angle) * radius;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.closePath();
  }

  function animate() {
    ctx.clearRect(0, 0, W, H);
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.x   += p.vx;
      p.y   += p.vy;
      p.vy  += .04;   // 微重力
      p.alpha -= p.decay;
      if (p.alpha <= 0) { particles.splice(i, 1); continue; }

      const lightness = document.body.classList.contains('light') ? '65%' : '72%';
      ctx.save();
      ctx.globalAlpha = p.alpha;
      ctx.fillStyle = `hsl(${p.hue},80%,${lightness})`;
      ctx.shadowColor = `hsl(${p.hue},80%,${lightness})`;
      ctx.shadowBlur  = 6;
      star4(p.x, p.y, p.size);
      ctx.fill();
      ctx.restore();
    }
    requestAnimationFrame(animate);
  }
  animate();
}

// ══════════════════════════════════════════════════════
// SVG 图标系统
// ══════════════════════════════════════════════════════
const SVG_ICONS = {
  gear: `<svg class="svg-icon" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="gi_gear" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#5a3d91" stop-opacity="0.3"/><stop offset="50%" stop-color="#a87bff" stop-opacity="1"/><stop offset="100%" stop-color="#5a3d91" stop-opacity="0.3"/></linearGradient></defs><path d="M645.5296 932.62336h-0.01024c-16.19968 0-31.9488-6.70208-42.12224-17.92512-13.86496-15.20128-57.7792-54.72256-93.73184-54.72256-35.70176 0-80.29696 39.75168-93.1072 53.67296-10.14784 11.02848-25.78944 17.61792-41.84064 17.61792-7.63904 0-14.85824-1.46944-21.44256-4.36224l-1.14688-0.50688-109.27616-61.1072-1.08032-0.75776c-19.89632-13.93152-27.45856-41.1648-17.60768-63.35488 0.0768-0.17408 10.07616-23.24992 10.07616-44.29824 0-63.86688-51.95264-115.82464-115.83488-115.82464h-3.8656l-0.71168 0.01024c-18.28864 0-33.18784-16.256-37.94944-41.41568-0.37376-1.99168-9.3184-49.69984-9.3184-87.29088 0-37.59104 8.94464-85.2992 9.3184-87.31648 4.81792-25.472 20.03968-41.83552 38.66112-41.38496h3.8656c63.87712 0 115.83488-51.968 115.83488-115.84 0-21.03296-9.98912-44.11904-10.09664-44.3392-9.84576-22.17984-2.2272-49.40288 17.74592-63.28832l1.13152-0.78336 115.32288-63.34976 1.19808-0.50688c6.49216-2.76992 13.60896-4.1728 21.14048-4.1728 16.01536 0 31.67744 6.44096 41.92256 17.23904 13.64992 14.28992 56.79616 51.456 91.7248 51.456 34.57536 0 77.45536-36.43392 91.06944-50.47296 10.17856-10.5728 25.74848-16.90624 41.6-16.90624 7.69024 0 14.93504 1.45408 21.5296 4.3264l1.16736 0.50688 111.3856 61.88544 1.1008 0.76288c19.92704 13.91104 27.50464 41.14432 17.65888 63.35488-0.08704 0.16384-10.08128 23.25504-10.08128 44.29312 0 63.872 51.95264 115.84 115.82464 115.84h3.87584c18.59072-0.42496 33.82784 15.90784 38.65088 41.38496 0.37888 2.01216 9.32864 49.72032 9.32864 87.31136 0 37.5808-8.94976 85.2992-9.32864 87.30112-4.81792 25.48224-20.06016 41.7792-38.65088 41.40544h-3.87584c-63.872 0-115.82464 51.95776-115.82464 115.82464 0 21.0432 9.99424 44.11392 10.09664 44.34944 9.8304 22.14912 2.24256 49.38752-17.70496 63.28832l-1.12128 0.77312-113.25952 62.60224-1.1776 0.50688c-6.48192 2.80064-13.57312 4.21376-21.06368 4.21376z" fill="url(#gi_gear)" stroke="#a87bff" stroke-width="8"><animate attributeName="stroke-dashoffset" from="1200" to="0" dur="6s" repeatCount="indefinite"/></path><path d="M510.03904 666.03008c-85.05344 0-154.25024-69.20192-154.25024-154.25536 0-85.05344 69.1968-154.25024 154.25024-154.25024 85.0688 0 154.26048 69.1968 154.26048 154.25024s-69.19168 154.25536-154.26048 154.25536z m0-256.04608c-56.12032 0-101.7856 45.66528-101.7856 101.7856 0 56.12544 45.66016 101.7856 101.7856 101.7856 56.13568 0 101.80096-45.66016 101.80096-101.7856 0-56.12032-45.66528-101.7856-101.80096-101.7856z" fill="#a87bff"><animate attributeName="opacity" values="0.6;1;0.6" dur="3s" repeatCount="indefinite"/></path></svg>`,
  home: `<svg class="svg-icon" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="gi_hL" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#5a3d91" stop-opacity="0.2"/><stop offset="50%" stop-color="#a87bff" stop-opacity="1"/><stop offset="100%" stop-color="#5a3d91" stop-opacity="0.2"/></linearGradient><linearGradient id="gi_hF" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#8c68d6" stop-opacity="0"/><stop offset="100%" stop-color="#704fc2" stop-opacity="0.35"/></linearGradient></defs><path d="M50,15 L80,40 L80,85 L20,85 L20,40 Z" fill="url(#gi_hF)"/><rect x="42" y="55" width="16" height="30" fill="url(#gi_hF)"/><path d="M50,15 L80,40 L80,85 L20,85 L20,40 Z" fill="none" stroke="url(#gi_hL)" stroke-width="2.8" stroke-linecap="round"><animate attributeName="stroke-dasharray" from="0 250" to="250 250" dur="4s" repeatCount="indefinite"/></path><rect x="42" y="55" width="16" height="30" fill="none" stroke="url(#gi_hL)" stroke-width="2.8"><animate attributeName="stroke-dasharray" from="0 92" to="92 92" dur="4s" repeatCount="indefinite"/></rect><circle cx="15" cy="35" r="2" fill="#c9b4ff"><animate attributeName="opacity" values="0.2;0.8;0.2" dur="3.2s" repeatCount="indefinite"/></circle><circle cx="85" cy="12" r="2.5" fill="#c9b4ff"><animate attributeName="opacity" values="0.2;0.8;0.2" dur="3.8s" repeatCount="indefinite"/></circle></svg>`,
  mail: `<svg class="svg-icon" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="gi_mL" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#5a3d91" stop-opacity="0.2"/><stop offset="50%" stop-color="#a87bff" stop-opacity="1"/><stop offset="100%" stop-color="#5a3d91" stop-opacity="0.2"/></linearGradient><linearGradient id="gi_mF" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#8c68d6" stop-opacity="0"/><stop offset="100%" stop-color="#704fc2" stop-opacity="0.35"/></linearGradient></defs><rect x="15" y="25" width="70" height="50" rx="3" fill="url(#gi_mF)"/><path d="M15,25 L50,50 L85,25" fill="url(#gi_mF)"/><rect x="15" y="25" width="70" height="50" rx="3" fill="none" stroke="url(#gi_mL)" stroke-width="2.8"><animate attributeName="stroke-dasharray" from="0 240" to="240 240" dur="4s" repeatCount="indefinite"/></rect><path d="M15,25 L50,50 L85,25" fill="none" stroke="url(#gi_mL)" stroke-width="2.8" stroke-linecap="round"><animate attributeName="stroke-dasharray" from="0 100" to="100 100" dur="4s" repeatCount="indefinite"/></path><circle cx="10" cy="45" r="2" fill="#c9b4ff"><animate attributeName="opacity" values="0.2;0.8;0.2" dur="3.3s" repeatCount="indefinite"/></circle><circle cx="90" cy="18" r="2.5" fill="#c9b4ff"><animate attributeName="opacity" values="0.2;0.8;0.2" dur="3.6s" repeatCount="indefinite"/></circle></svg>`,
  planet: `<svg class="svg-icon" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="gi_pL" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#5a3d91" stop-opacity="0.2"/><stop offset="50%" stop-color="#a87bff" stop-opacity="1"/><stop offset="100%" stop-color="#5a3d91" stop-opacity="0.2"/></linearGradient><linearGradient id="gi_pF" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#8c68d6" stop-opacity="0"/><stop offset="100%" stop-color="#704fc2" stop-opacity="0.35"/></linearGradient></defs><circle cx="45" cy="55" r="25" fill="url(#gi_pF)"/><circle cx="45" cy="55" r="25" fill="none" stroke="url(#gi_pL)" stroke-width="2.8"><animate attributeName="stroke-dasharray" from="0 157" to="157 157" dur="4s" repeatCount="indefinite"/></circle><ellipse cx="45" cy="55" rx="35" ry="8" fill="none" stroke="url(#gi_pL)" stroke-width="2.8" transform="rotate(-20 45 55)"><animate attributeName="stroke-dasharray" from="0 220" to="220 220" dur="4s" repeatCount="indefinite"/></ellipse><circle cx="8" cy="78" r="2" fill="#c9b4ff"><animate attributeName="opacity" values="0.2;0.8;0.2" dur="3.1s" repeatCount="indefinite"/></circle><circle cx="28" cy="22" r="2.5" fill="#c9b4ff"><animate attributeName="opacity" values="0.2;0.8;0.2" dur="3.9s" repeatCount="indefinite"/></circle></svg>`,
  user: `<svg class="svg-icon" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="gi_uL" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#5a3d91" stop-opacity="0.2"/><stop offset="50%" stop-color="#a87bff" stop-opacity="1"/><stop offset="100%" stop-color="#5a3d91" stop-opacity="0.2"/></linearGradient><linearGradient id="gi_uF" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#8c68d6" stop-opacity="0"/><stop offset="100%" stop-color="#704fc2" stop-opacity="0.35"/></linearGradient></defs><circle cx="50" cy="35" r="18" fill="url(#gi_uF)"/><path d="M30,85 Q30,65 50,60 Q70,65 70,85" fill="url(#gi_uF)"/><circle cx="50" cy="35" r="18" fill="none" stroke="url(#gi_uL)" stroke-width="2.8"><animate attributeName="stroke-dasharray" from="0 113" to="113 113" dur="4s" repeatCount="indefinite"/></circle><path d="M30,85 Q30,65 50,60 Q70,65 70,85" fill="none" stroke="url(#gi_uL)" stroke-width="2.8" stroke-linecap="round"><animate attributeName="stroke-dasharray" from="0 100" to="100 100" dur="4s" repeatCount="indefinite"/></path><circle cx="12" cy="70" r="2" fill="#c9b4ff"><animate attributeName="opacity" values="0.2;0.8;0.2" dur="3.4s" repeatCount="indefinite"/></circle><circle cx="88" cy="25" r="2.5" fill="#c9b4ff"><animate attributeName="opacity" values="0.2;0.8;0.2" dur="3.5s" repeatCount="indefinite"/></circle></svg>`,
  pin: `<svg class="svg-icon" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="gi_pinL" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#5a3d91" stop-opacity="0.2"/><stop offset="50%" stop-color="#a87bff" stop-opacity="1"/><stop offset="100%" stop-color="#5a3d91" stop-opacity="0.2"/></linearGradient><linearGradient id="gi_pinF" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#8c68d6" stop-opacity="0"/><stop offset="100%" stop-color="#704fc2" stop-opacity="0.35"/></linearGradient></defs><path d="M50,15 C35,15 25,30 25,45 C25,60 50,90 50,90 C50,90 75,60 75,45 C75,30 65,15 50,15 Z" fill="url(#gi_pinF)"/><ellipse cx="50" cy="90" rx="18" ry="5" fill="url(#gi_pinF)"/><circle cx="50" cy="45" r="8" fill="url(#gi_pinF)"/><path d="M50,15 C35,15 25,30 25,45 C25,60 50,90 50,90 C50,90 75,60 75,45 C75,30 65,15 50,15 Z" fill="none" stroke="url(#gi_pinL)" stroke-width="2.8" stroke-linecap="round"><animate attributeName="stroke-dasharray" from="0 200" to="200 200" dur="4s" repeatCount="indefinite"/></path><ellipse cx="50" cy="90" rx="18" ry="5" fill="none" stroke="url(#gi_pinL)" stroke-width="2.8"><animate attributeName="stroke-dasharray" from="0 113" to="113 113" dur="4s" repeatCount="indefinite"/></ellipse><circle cx="10" cy="55" r="2" fill="#c9b4ff"><animate attributeName="opacity" values="0.2;0.8;0.2" dur="3.6s" repeatCount="indefinite"/></circle><circle cx="92" cy="30" r="2.5" fill="#c9b4ff"><animate attributeName="opacity" values="0.2;0.8;0.2" dur="3.2s" repeatCount="indefinite"/></circle></svg>`,
  robot: `<svg class="svg-icon" viewBox="0 0 1095 1024" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="gi_robFlow" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#CECEF9" stop-opacity="0.5"/><stop offset="50%" stop-color="#ffffff" stop-opacity="1"/><stop offset="100%" stop-color="#CECEF9" stop-opacity="0.5"/></linearGradient></defs><path d="M130 148 L130 908 L866 1018 L866 258 L216 259 L216 823 Z" fill="none" stroke="url(#gi_robFlow)" stroke-width="20" stroke-dasharray="2200" stroke-dashoffset="2200"><animate attributeName="stroke-dashoffset" from="2200" to="0" dur="5s" repeatCount="indefinite"/></path><path d="M606.082246 72.596211l-216.459228-32.336843 89.824561-40.259368 216.477193 32.336842-89.824561 40.259369z" fill="#CECEF9"/><path d="M389.640982 40.259368v98.088421l89.824562-40.277333v-98.088421l-89.824562 40.277333z" fill="#CECEF9"/><path d="M389.640982 138.329825l64.925193 9.701052 89.824562-40.241403-64.925193-9.719018-89.824562 40.259369z" fill="#CECEF9"/><path d="M454.566175 148.030877v49.044211l89.824562-40.259369v-49.04421l-89.824562 40.259368z" fill="#CECEF9"/><path d="M454.566175 197.075088L129.886316 148.569825l89.824561-40.277334 324.697825 48.505263-89.824562 40.277334z" fill="#CECEF9"/><path d="M129.886316 148.569825v760.095438l89.824561-40.241403V108.274526l-89.824561 40.277334z" fill="#CECEF9"/><path d="M129.886316 908.665263l735.950596 109.981193 89.824562-40.259368-735.950597-109.981193-89.824561 40.277333z" fill="#CECEF9"/><path d="M865.836912 1018.646456v-760.095438l89.824562-40.277334v760.095439l-89.824562 40.277333zM865.836912 258.533053l-324.679859-48.505264 89.824561-40.277333 324.67986 48.505263-89.824562 40.277334z" fill="#CECEF9"/><path d="M541.157053 210.009825V160.965614l89.824561-40.241403v49.026245l-89.824561 40.259369z" fill="#CECEF9"/><path d="M541.157053 160.965614l64.925193 9.701053 89.824561-40.241404-64.925193-9.701052-89.824561 40.241403z" fill="#CECEF9"/><path d="M606.082246 170.684632v-98.088421l89.824561-40.259369v98.088421l-89.824561 40.259369z" fill="#CECEF9"/><path d="M216.459228 823.529544V259.592982l89.824561-40.259368V783.270175l-89.824561 40.259369z" fill="#CECEF9"/><path d="M216.459228 259.592982l562.786807 84.07579 89.824561-40.259368-562.786807-84.093755-89.824561 40.259369zM779.264 343.668772v563.972491l89.824561-40.277333V303.427368l-89.824561 40.277334z" fill="#CECEF9"/><path d="M779.246035 907.641263L216.477193 823.511579l89.824561-40.259368 562.786807 84.093754-89.824561 40.277333zM0 374.352842v269.725193l89.824561-40.277333V334.093474l-89.824561 40.259368z" fill="#CECEF9"/><path d="M0 644.078035l86.590877 12.934737 89.824562-40.277333L89.824561 603.800702l-89.824561 40.277333z" fill="#CECEF9"/><path d="M86.590877 657.012772V387.287579l89.824562-40.259368V616.735439l-89.824562 40.241403z" fill="#CECEF9"/><path d="M86.590877 387.287579L0 374.352842l89.824561-40.259368 86.590878 12.934737-89.824562 40.259368zM909.132351 510.203509v269.725193l89.824561-40.277334V469.962105l-89.824561 40.259369z" fill="#CECEF9"/><path d="M909.132351 779.928702l86.590877 12.934737 89.824561-40.277334-86.590877-12.934737-89.824561 40.277334z" fill="#CECEF9"/><path d="M995.723228 792.863439V523.138246l89.824561-40.259369v269.707228l-89.824561 40.277334z" fill="#CECEF9"/><path d="M432.918456 512.610807l-108.220631-16.168421 89.824561-40.277333 108.220632 16.168421-89.824562 40.259368z" fill="#CECEF9"/><path d="M324.697825 496.424421v122.610526l89.824561-40.277333v-122.592561l-89.824561 40.259368z" fill="#CECEF9"/><path d="M324.697825 619.034947l108.220631 16.168421 89.824562-40.259368-108.220632-16.168421-89.824561 40.241403z" fill="#CECEF9"/><path d="M432.918456 635.203368v-122.592561l89.824562-40.277333v122.610526l-89.824562 40.259368zM671.025404 548.181333l-108.220632-16.168421 89.824561-40.259368 108.220632 16.168421-89.824561 40.259368z" fill="#CECEF9"/><path d="M562.804772 532.012912v122.592562l89.824561-40.259369v-122.592561l-89.824561 40.259368z" fill="#CECEF9"/><path d="M562.804772 654.605474l108.220632 16.168421 89.824561-40.259369-108.220632-16.168421-89.824561 40.259369z" fill="#CECEF9"/><path d="M671.025404 670.79186v-122.610527l89.824561-40.259368v122.592561l-89.824561 40.277334z" fill="#CECEF9"/><path d="M606.082246 72.596211l-216.459228-32.336843v98.088421l64.943157 9.701053v49.044211L129.868351 148.569825v760.095438l735.968561 109.981193v-760.095438L541.157053 210.009825V160.965614l64.925193 9.701053V72.578246z m-389.623018 750.933333V259.592982l562.804772 84.11172v563.954526L216.459228 823.511579zM0 374.352842v269.725193l86.590877 12.934737V387.287579L0 374.352842zM909.132351 510.203509v269.725193l86.590877 12.934737V523.138246l-86.590877-12.934737z m-476.213895 2.407298l-108.220631-16.168421v122.592561l108.220631 16.168421v-122.592561z m238.106948 35.570526l-108.220632-16.168421v122.592562l108.220632 16.168421v-122.592562z" fill="#4E5969"/></svg>`,
};

// emoji → SVG 图标名映射
const EMOJI_TO_SVG = {
  '🏠': 'home', '🤖': 'robot', '💫': 'planet', '👤': 'user',
  '⚙️': 'gear', '📍': 'pin', '✉️': 'mail', '💌': 'mail',
};

// 返回内联 SVG 字符串，找不到时返回 null
function svgIcon(name) {
  return SVG_ICONS[name] || null;
}

// 把页面中 data-svg-icon 属性的元素替换为 SVG
function initSvgIcons() {
  // 替换底部导航 nav-icon span
  document.querySelectorAll('.nav-icon').forEach(el => {
    const emoji = el.textContent.trim();
    const iconName = EMOJI_TO_SVG[emoji];
    if (iconName && SVG_ICONS[iconName]) {
      el.innerHTML = SVG_ICONS[iconName];
      el.classList.add('nav-icon--svg');
    }
  });

  // 替换 data-svg-icon 属性标记的元素
  document.querySelectorAll('[data-svg-icon]').forEach(el => {
    const name = el.dataset.svgIcon;
    if (SVG_ICONS[name]) {
      el.innerHTML = SVG_ICONS[name];
    }
  });
}

// ── 初始化 ───────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  Theme.init();
  highlightNav();
  initCursorSparkle();
  initSvgIcons();
});
