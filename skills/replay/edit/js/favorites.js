// ===== 收藏库 = 直接使用 Flow =====
const FAVORITES_KEY = 'adb-replay-favorites';

function toast(msg, warn) {
  let t = document.getElementById('toast');
  if (!t) { alert(msg); return; }
  t.textContent = msg;
  t.className = 'toast' + (warn ? ' warn' : '');
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2000);
}

function loadFavorites() {
  try { return JSON.parse(localStorage.getItem(FAVORITES_KEY) || '[]'); }
  catch { return []; }
}

function saveFavoritesToStorage(favs) {
  localStorage.setItem(FAVORITES_KEY, JSON.stringify(favs));
}

// 启动时从服务端同步（Flow API 替代 /api/favorites）
(async function autoSyncFavorites() {
  try {
    const resp = await fetch('/api/flows?_=' + Date.now());
    const data = await resp.json();
    const flows = (data.flows || data) || [];
    if (!flows.length) return;
    const plat = window.__FLOW_PLATFORM || '';
    // 只保留同平台原子 flow
    const atomic = flows.filter(f => {
      if (!f.is_atomic) return false;
      const fp = f.platform || '';
      if (plat && fp && fp !== plat && fp !== 'mixed' && plat !== 'mixed') return false;
      if (plat && !fp) return false;
      return true;
    });
    const favs = atomic.map(f => ({
      id: f.id,
      name: f.name,
      count: f.steps || 0,
      device: {model: 'unknown', resolution: '1080x2340'}
    }));
    localStorage.setItem(FAVORITES_KEY, JSON.stringify(favs));
    console.log(`⭐ 已同步 ${favs.length} 个同平台 Flow`);
  } catch (e) {}
})();

// 从 Flow 插入事件（替代 /api/favorites）
async function insertFavorite(favIndex) {
  const favs = loadFavorites();
  const fav = favs[favIndex];
  if (!fav) return;
  try {
    const resp = await fetch('/api/flow?name=' + encodeURIComponent(fav.id || fav.name));
    const data = await resp.json();
    const flow = data.flow || data;
    if (!flow || !flow.steps) return;
    // 转换 flow steps 为编辑器事件
    const events = [];
    for (const s of flow.steps) {
      const stype = s.type || 'event';
      if (stype === 'event') {
        const ev = {type: s.action || 'tap'};
        for (const k of ['x','y','x1','y1','x2','y2','duration_ms','count','code','content','delay_before_ms','delay_after_ms']) {
          if (s[k] !== undefined) ev[k] = s[k];
        }
        if (s.action === 'adb') {
          ev.action = s.adb_action || s.action;
          if (s.package) ev.package = s.package;
          if (s.ssid) ev.ssid = s.ssid;
          if (s.password) ev.password = s.password;
        }
        if (s.is_critical) ev.is_critical = true;
        events.push(ev);
      } else if (stype === 'pause') {
        events.push({type: 'pause', _task_type: 'pause', _task_hint: s.hint || ''});
      } else if (stype === 'adb_cmd') {
        events.push({type: 'adb_cmd', _task_type: 'adb_cmd', _task_command: s.command || ''});
      }
    }
    if (!events.length) return;
    // 插入事件
    const pos = state.selectedIndex >= 0 ? state.selectedIndex + 1 : state.events.length;
    state.events.splice(pos, 0, ...events);
    state.isDirty = true;
    updateStats();
    renderEventList();
    renderCanvas();
    closeFavoritesModal();
  } catch (e) { console.error(e); }
}

// 选中的事件保存为收藏（即保存为 Flow）
async function saveToFavorites() {
  if (state.multiSelected.size) {
    const name = prompt('收藏名称', '');
    if (!name || !name.trim()) return;
    const events = state.events.filter((_, i) => state.multiSelected.has(i));
    const steps = events.map(ev => {
      if (ev._task_type === 'pause') return {type: 'pause', hint: ev._task_hint || ''};
      if (ev._task_type === 'adb_cmd') return {type: 'adb_cmd', command: ev._task_command || ''};
      const step = {type: 'event', action: ev.type || 'tap'};
      for (const k of ['x','y','x1','y1','x2','y2','duration_ms','count','code','content','delay_before_ms','delay_after_ms']) {
        if (ev[k] !== undefined) step[k] = ev[k];
      }
      if (ev.type === 'adb') {
        step.adb_action = ev.action || 'restart';
        if (ev.package) step.package = ev.package;
        if (ev.ssid) step.ssid = ev.ssid;
        if (ev.password) step.password = ev.password;
      }
      if (ev.is_critical) step.is_critical = true;
      return step;
    });
    await fetch('/api/flow/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({flow: {name: name.trim(), platform: window.__FLOW_PLATFORM, steps: steps, group: '⭐收藏', device: state.device, resolution: state.resolution}})
    });
    state.multiSelected.clear();
    toast('已保存 → ' + name.trim());
    
    // 同步收藏列表
    const favs = loadFavorites();
    favs.push({name: name.trim(), count: steps.length, device: {model: 'unknown', resolution: '1080x2340'}});
    saveFavoritesToStorage(favs);
  } else {
    alert('请先选中要收藏的事件（点击序号多选）');
  }
}

async function deleteFavorite(i) {
  const favs = loadFavorites();
  const fav = favs[i];
  if (!fav) return;
  if (!confirm('删除收藏「' + fav.name + '」？')) return;
  // 也删除对应的 flow
  try {
    await fetch('/api/flow/delete', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: fav.id})
    });
  } catch (e) {}
  favs.splice(i, 1);
  saveFavoritesToStorage(favs);
  showFavoritesModal();
}

// 收藏库弹窗（点击即插入）
async function showFavoritesModal() {
  let modal = document.getElementById('favorites-modal');
  if (!modal) {
    modal = document.createElement('div'); modal.id = 'favorites-modal'; modal.className = 'modal-overlay';
    document.body.appendChild(modal);
  }
  modal.innerHTML = '<div class="modal"><h3>📦 原子 Flow</h3><p style="color:#78909c">加载中...</p></div>';
  modal.classList.add('show');

  let favs = [];
  try {
    const resp = await fetch('/api/flows?_=' + Date.now());
    const data = await resp.json();
    const flows = (data.flows || data) || [];
    const plat = window.__FLOW_PLATFORM || '';
    console.log(`📦 favorites: platform=${plat}, total=${flows.length}, atomic=${flows.filter(f=>f.is_atomic).length}`);
    favs = flows.filter(f => {
      if (!f.is_atomic) return false;
      // 平台过滤：当前有明确平台时，只显示同平台或 mixed 的
      const fp = f.platform || '';
      if (plat && fp && fp !== plat && fp !== 'mixed' && plat !== 'mixed') return false;
      if (plat && !fp) return false;  // 无平台标记的 flow 不显示
      return true;
    }).map(f => ({id: f.id, name: f.name, steps: f.steps || 0, platform: f.platform || ''}));
    saveFavoritesToStorage(favs.map(f => ({...f, device: {model: 'unknown', resolution: '1080x2340'}})));
  } catch (e) {}

  if (!favs.length) {
    modal.innerHTML = `<div class="modal"><h3>📦 原子 Flow</h3><p style="color:#78909c;margin:20px 0;font-size:14px">暂无原子 Flow。选中事件后「⭐ 收藏」即可创建。</p><button class="btn" onclick="closeFavoritesModal()">关闭</button></div>`;
    return;
  }

  const list = favs.map((f, i) =>
    `<div data-fav-idx="${i}" class="fav-item" style="padding:10px 14px;cursor:pointer;border-radius:6px;border-bottom:1px solid #161b22;display:flex;align-items:center;gap:8px" onmouseover="this.style.background='#161b22'" onmouseout="this.style.background=''">
      <span style="font-size:14px;color:#c9d1d9;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(f.name)}</span>
      ${f.platform ? `<span style="font-size:11px;padding:1px 5px;border-radius:3px;background:rgba(139,148,158,.1);color:#8b949e">${escHtml(f.platform)}</span>` : ''}
      <span style="font-size:12px;color:#484f58;flex-shrink:0">${f.steps} 步</span>
    </div>`
  ).join('');

  modal.innerHTML = `<div class="modal" style="width:500px;max-width:95vw">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
      <h3 style="margin:0">📦 原子 Flow（${favs.length} 个）</h3>
      <button class="btn btn-sm" id="fav-modal-close">关闭</button>
    </div>
    <div style="max-height:60vh;overflow-y:auto" id="fav-list">${list}</div>
  </div>`;

  // 用 addEventListener 代替内联 onclick 避免转义问题
  document.getElementById('fav-modal-close').onclick = closeFavoritesModal;
  document.getElementById('fav-list').onclick = function(e) {
    var el = e.target.closest('.fav-item');
    if (el) insertFavorite(+el.dataset.favIdx);
  };
}

function closeFavoritesModal() {
  const modal = document.getElementById('favorites-modal');
  if (modal) modal.classList.remove('show');
}

function escHtml(s) {
  const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
}

// 兼容旧导出
async function exportFavorites() {
  alert('收藏即 Flow，无需导出。');
}
