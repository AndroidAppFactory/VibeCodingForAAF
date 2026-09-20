// ===== 手机屏幕点击（仅 adb 平台）=====
if ((window.__FLOW_PLATFORM || 'adb') !== 'adb') {
  // 非 adb 平台：注册空函数避免报错
  window.zoomIn = window.zoomOut = function(){};
} else {

document.getElementById('phone-overlay').addEventListener('click', (e) => {
  const rect = e.target.getBoundingClientRect();
  const px = e.offsetX;
  const py = e.offsetY;

  // 转换为设备坐标（竖屏自然方向，直接缩放）
  const devX = Math.round(px / PHONE_W * state.resolution[0]);
  const devY = Math.round(py / PHONE_H * state.resolution[1]);

  // 查找最近的事件
  let closest = -1;
  let minDist = Infinity;

  state.events.forEach((ev, i) => {
    let dist = Infinity;
    if (ev.type === 'tap') {
      const ex = ev.x / state.resolution[0] * PHONE_W;
      const ey = ev.y / state.resolution[1] * PHONE_H;
      dist = Math.hypot(px - ex, py - ey);
    } else if (ev.type === 'swipe') {
      const ex1 = ev.x1 / state.resolution[0] * PHONE_W;
      const ey1 = ev.y1 / state.resolution[1] * PHONE_H;
      const ex2 = ev.x2 / state.resolution[0] * PHONE_W;
      const ey2 = ev.y2 / state.resolution[1] * PHONE_H;
      dist = Math.min(Math.hypot(px - ex1, py - ey1), Math.hypot(px - ex2, py - ey2));
    }
    if (dist < minDist) {
      minDist = dist;
      closest = i;
    }
  });

  if (closest >= 0 && minDist < 30) {
    selectEvent(closest);
  } else {
    clearSelection();
  }
});

// ===== 缩放 =====
function applyZoom() {
  const panel = document.querySelector('.left-panel');
  const frame = document.getElementById('phone-frame');
  // 缩放手机区域
  frame.style.transform = `scale(${state.scale})`;
  frame.style.transformOrigin = 'top center';
  // 补偿 transform scale 不影响文档流的问题
  const frameHeight = frame.offsetHeight || 680;
  const extraHeight = frameHeight * (state.scale - 1);
  frame.style.marginBottom = extraHeight > 0 ? `${extraHeight}px` : '0';
  // 更新左侧面板宽度以适应缩放
  const baseWidth = 380;
  panel.style.minWidth = `${Math.round(baseWidth * state.scale)}px`;
  // 更新显示
  const levelEl = document.getElementById('zoom-level');
  if (levelEl) levelEl.textContent = `${Math.round(state.scale * 100)}%`;
}

function zoomIn() {
  state.scale = Math.min(state.scale + 0.1, 2.0);
  applyZoom();
}

function zoomOut() {
  state.scale = Math.max(state.scale - 0.1, 0.5);
  applyZoom();
}

} // 平台守卫结束
