// ===== 渲染 =====

// 筛选状态
let filterCriticalOnly = false;

function toggleCriticalFilter() {
  filterCriticalOnly = !filterCriticalOnly;
  const btn = document.getElementById('btn-filter-critical');
  if (btn) {
    btn.classList.toggle('active', filterCriticalOnly);
  }
  renderEventList();
}

function updateStats() {
  const total = state.events.length;
  const totalDelay = state.events.reduce((s, e) => s + (e.delay_before_ms || e.delay_ms || EVENT_DEFAULTS.delay_before_ms) + (e.delay_after_ms || getDelayAfterDefault(e.type, e.action)), 0);
  document.getElementById('stats').textContent =
    `${total} 个事件 · 总时长 ${totalDelay >= 60000 ? (totalDelay / 60000).toFixed(1) + 'm' : (totalDelay / 1000).toFixed(1) + 's'}`;
}

function updateFlowName() {
  const el = document.getElementById('panel-title');
  if (!el) return;
  const name = window.__FLOW_NAME || (state.data && (state.data._flow_name || state.data.name)) || '';
  el.textContent = name ? `📋 ${name} 事件列表` : '📋 事件列表';
}

function renderEventList() {
  const list = document.getElementById('event-list');

  if (!state.events.length) {
    list.innerHTML = `
      <div class="empty-state">
        <div class="icon">📱</div>
        <p>暂无事件</p>
      </div>`;
    document.getElementById('edit-panel').style.display = 'none';
    updateFlowName();
    return;
  }

  list.innerHTML = state.events.map((ev, i) => {
    // 筛选：仅显示关键事件
    if (filterCriticalOnly && !ev.is_critical) {
      return '';
    }
    const selected = i === state.selectedIndex ? 'selected' : '';
    const multiSel = state.multiSelected.has(i) ? 'multi-selected' : '';
    const criticalClass = ev.is_critical ? 'critical' : '';
    const icon = getEventIcon(ev.type);
    const detail = getEventDetail(ev);
  const delayBefore = ev.delay_before_ms || ev.delay_ms || EVENT_DEFAULTS.delay_before_ms;
  const delayAfter = ev.delay_after_ms || getDelayAfterDefault(ev.type, ev.action);
  const delayParts = [];
  if (delayBefore >= 1000) delayParts.push(`前${(delayBefore / 1000).toFixed(1)}s`);
  else if (delayBefore > 0) delayParts.push(`前${delayBefore}ms`);
  if (delayAfter >= 1000) delayParts.push(`后${(delayAfter / 1000).toFixed(1)}s`);
  else if (delayAfter > 0) delayParts.push(`后${delayAfter}ms`);
  const delay = delayParts.length ? delayParts.join(' ') : '';
    const nameTag = ev.name ? `<span style="color:#f39c12;font-size:11px;margin-left:4px">[${ev.name}]</span>` : '';
    const criticalTag = ev.is_critical ? '<span class="critical-badge">⭐ 关键</span>' : '';
    const captureIcon = ev.capture_mode === 'video' ? '🎬' : '';
    const screenshotIcon = ev.screenshots ? (ev.screenshots.before_type === 'video' || ev.screenshots.after_type === 'video' ? '🎬' : '📸') : '';

    return `
      <div class="event-item ${selected} ${multiSel} ${criticalClass}" data-index="${i}"
           onclick="handleEventClick(event, ${i})"
           draggable="true"
           ondragstart="dragStart(event, ${i})"
           ondragover="dragOver(event, ${i})"
           ondrop="drop(event, ${i})"
           ondragend="dragEnd(event)">
        <span class="event-index">${i + 1}</span>
        <div class="event-icon ${ev.type}">${icon}</div>
        <div class="event-info">
          <div class="event-type">${ev.type}${nameTag}${criticalTag}${captureIcon ? ' ' + captureIcon : ''} ${screenshotIcon}</div>
          <div class="event-detail">${detail}</div>
        </div>
        <span class="event-delay">${delay}</span>
        <div class="event-actions">
          <button class="move-btn" onclick="moveEvent(${i}, -1); event.stopPropagation();" title="上移">↑</button>
          <button class="move-btn" onclick="moveEvent(${i}, 1); event.stopPropagation();" title="下移">↓</button>
          <button onclick="duplicateEvent(${i}); event.stopPropagation();" title="复制">⎎</button>
          <button onclick="deleteEvent(${i}); event.stopPropagation();" title="删除">✕</button>
        </div>
      </div>`;  }).join('');

  updateFlowName();
}

function getEventIcon(type) {
  switch (type) {
    case 'tap': return '👆';
    case 'multitap': return '👆👆';
    case 'swipe': return '👉';
    case 'keyevent': return '⌨️';
    case 'text': return '📝';
    case 'adb': return '📦';
    case 'tips': return '💡';
    case 'click': return '👆';
    case 'dblclick': return '👆👆';
    case 'rclick': case 'rightclick': return '🖱️';
    case 'move': case 'hover': case 'scroll': return '🖱️';
    case 'drag': return '✋';
    case 'type': return '📝';
    case 'keyboard': case 'hotkey': return '⌨️';
    case 'launch': return '🚀';
    case 'quit': return '⏏️';
    default: return '❓';
  }
}

function getEventDetail(ev) {
  switch (ev.type) {
    case 'tap': return `(${ev.x}, ${ev.y})`;
    case 'multitap': return `(${ev.x}, ${ev.y}) ×${ev.count || 2}`;
case 'swipe': return `(${ev.x1},${ev.y1}) → (${ev.x2},${ev.y2}) ${ev.duration_ms}ms`;
    case 'keyevent': return `code: ${ev.code}`;
    case 'text': return `"${ev.content}"`;
    case 'adb': return ev.action === 'wifi-connect' ? `WiFi: ${ev.ssid || ''}` : ev.action === 'open-schema' ? `Schema: ${ev.content || ''}` : ev.action === 'clear-all' ? '清理所有后台应用' : ev.action === 'lock-screen' ? '🔒 锁屏' : ev.action === 'launch' ? `拉起应用: ${ev.package || ''}` : ev.action === 'uninstall' ? `卸载应用: ${ev.package || ''}` : ev.action === 'install' ? `安装 APK: ${ev.content || ''}` : `${ev.action} ${ev.package || ''}`;
    case 'tips': return ev.content ? `"${ev.content}"` : '(空提示)';
    case 'click': case 'move': case 'hover': return `(${ev.x}, ${ev.y})`;
    case 'dblclick': return `(${ev.x}, ${ev.y}) ×2`;
    case 'rclick': case 'rightclick': return `右键 (${ev.x}, ${ev.y})`;
    case 'drag': return `(${ev.x1},${ev.y1}) → (${ev.x2},${ev.y2}) ${ev.duration_ms || 0}ms`;
    case 'scroll': return `(${ev.x}, ${ev.y}) dx=${ev.delta_x} dy=${ev.delta_y}`;
    case 'type': return `"${ev.content}"`;
    case 'keyboard': case 'hotkey': return (ev.keys || []).join('+');
    case 'launch': return `启动 ${ev.target || ''}`;
    case 'quit': return `退出 ${ev.target || ''}`;
    default: return JSON.stringify(ev);
  }
}

function renderCanvas() {
  const canvas = document.getElementById('phone-canvas');
  const ctx = canvas.getContext('2d');

  // 确保路径可见（重放自然结束后 opacity 可能残留 0）
  canvas.style.opacity = '1';

  // 设置 canvas 实际尺寸
  canvas.width = PHONE_W * 2;
  canvas.height = PHONE_H * 2;
  ctx.scale(2, 2); // HiDPI

  ctx.clearRect(0, 0, PHONE_W, PHONE_H);

  // 仅 adb 平台画点击位置：win/web 截图已含标记，且画布为手机竖屏比例、坐标对不上
  if ((window.__FLOW_PLATFORM || 'adb') !== 'adb') return;

  if (!state.events.length) return;

  const scaleX = PHONE_W / state.resolution[0];
  const scaleY = PHONE_H / state.resolution[1];

  state.events.forEach((ev, i) => {
    const isSelected = i === state.selectedIndex || (state.isPlaying && i === state.playIndex);
    // 默认只显示当前选中/播放的操作路径
    if (!isSelected) return;

    if (ev.type === 'tap') {
      const x = ev.x * scaleX;
      const y = ev.y * scaleY;

      // 外圈（大圆，半透明）
      ctx.beginPath();
      ctx.arc(x, y, isSelected ? 30 : 25, 0, Math.PI * 2);
      ctx.fillStyle = isSelected ? 'rgba(233, 69, 96, 0.2)' : 'rgba(41, 128, 185, 0.2)';
      ctx.fill();

      // 中圈（中圆，半透明）
      ctx.beginPath();
      ctx.arc(x, y, isSelected ? 20 : 15, 0, Math.PI * 2);
      ctx.fillStyle = isSelected ? 'rgba(233, 69, 96, 0.4)' : 'rgba(41, 128, 185, 0.4)';
      ctx.fill();

      // 内圈（实心小圆）
      ctx.beginPath();
      ctx.arc(x, y, isSelected ? 12 : 8, 0, Math.PI * 2);
      ctx.fillStyle = isSelected ? 'rgba(233, 69, 96, 0.9)' : 'rgba(41, 128, 185, 0.9)';
      ctx.fill();

      // 标签：事件名 > flow名 > 序号
      let label = ev.name || ev._flow_name || String(i + 1);
      if (label.length > 6) label = label.slice(0, 5) + '…';
      ctx.fillStyle = '#ffffff';
      ctx.font = `bold ${isSelected ? 11 : 9}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.shadowColor = 'rgba(0, 0, 0, 0.9)';
      ctx.shadowBlur = 4;
      ctx.fillText(label, x, y);
      ctx.shadowBlur = 0;

    } else if (ev.type === 'swipe') {
      const x1 = ev.x1 * scaleX;
      const y1 = ev.y1 * scaleY;
      const x2 = ev.x2 * scaleX;
      const y2 = ev.y2 * scaleY;

      // 线条
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.strokeStyle = isSelected ? 'rgba(233, 69, 96, 0.9)' : 'rgba(142, 68, 173, 1)';
      ctx.lineWidth = isSelected ? 3 : 2;
      ctx.stroke();

      // 起点
      ctx.beginPath();
      ctx.arc(x1, y1, 4, 0, Math.PI * 2);
      ctx.fillStyle = ctx.strokeStyle;
      ctx.fill();

      // 终点箭头
      const angle = Math.atan2(y2 - y1, x2 - x1);
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(x2 - 8 * Math.cos(angle - 0.4), y2 - 8 * Math.sin(angle - 0.4));
      ctx.lineTo(x2 - 8 * Math.cos(angle + 0.4), y2 - 8 * Math.sin(angle + 0.4));
      ctx.closePath();
      ctx.fill();

      // 标签：事件名 > flow名 > 序号
      const mx = (x1 + x2) / 2;
      const my = (y1 + y2) / 2;
      let label = ev.name || ev._flow_name || String(i + 1);
      if (label.length > 6) label = label.slice(0, 5) + '…';
      ctx.fillStyle = '#fff';
      ctx.font = 'bold 9px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.shadowColor = 'rgba(0, 0, 0, 0.9)';
      ctx.shadowBlur = 3;
      ctx.fillText(label, mx, my - 8);
      ctx.shadowBlur = 0;
    }
  });
}
