// ===== 模拟重放（仅 adb 平台）=====
if ((window.__FLOW_PLATFORM || 'adb') !== 'adb') {
  window.toggleReplay = function(){};
} else {

let replayTimer = null;

function toggleReplay() {
  if (state.isPlaying) {
    stopReplay();
  } else {
    startReplay();
  }
}

function startReplay() {
  if (!state.events.length) {
    alert('没有事件可重放');
    return;
  }

  state.isPlaying = true;
  state.playIndex = 0;
  state.selectedIndex = -1;

  const btn = document.getElementById('btn-play');
  btn.textContent = '⏹️ 停止';
  btn.classList.add('active');

  // 隐藏事件编辑面板（在手机框下方，不影响手机框位置）
  document.getElementById('edit-panel').style.display = 'none';

  playNextEvent();
}

function stopReplay() {
  state.isPlaying = false;
  state.playIndex = -1;

  if (replayTimer) {
    clearTimeout(replayTimer);
    replayTimer = null;
  }

  const btn = document.getElementById('btn-play');
  btn.textContent = '▶️ 重放';
  btn.classList.remove('active');

  renderEventList();
  renderCanvas();
  showScreenshot(-1);
  // 清除手机屏幕背景和视频
  clearPhoneMedia();
  // 恢复 canvas 显示
  document.getElementById('phone-canvas').style.opacity = '1';
}

function playNextEvent() {
  if (!state.isPlaying || state.playIndex >= state.events.length) {
    stopReplay();
    return;
  }

  const ev = state.events[state.playIndex];
  const index = state.playIndex;

  // 高亮当前事件
  renderEventList();
  renderCanvas();

  // 高亮当前播放项
  const items = document.querySelectorAll('.event-item');
  if (items[index]) {
    items[index].classList.add('playing');
    items[index].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  // 重放间隔从界面输入框读取（毫秒）
  const delayMs = parseInt(document.getElementById('replay-delay').value) || 500;
  const delay = delayMs;
  const canvas = document.getElementById('phone-canvas');
  const ss = ev.screenshots || {};
  const hasScreenshot = !!(ss.before || ss.after);
  const hasVideo = ss.before_type === 'video' || ss.after_type === 'video';

  // 进入下一个事件的公共逻辑
  const goNext = () => {
    if (!state.isPlaying) return;
    state.playIndex++;
    // 最后一步：停留，不清除画面
    if (state.playIndex >= state.events.length) {
      state.isPlaying = false;
      state.playIndex = -1;
      if (replayTimer) {
        clearTimeout(replayTimer);
        replayTimer = null;
      }
      const btn = document.getElementById('btn-play');
      btn.textContent = '▶️ 重放';
      btn.classList.remove('active');
      // 恢复工具栏和面板显示
      document.querySelectorAll('.phone-panel .toolbar').forEach(tb => {
        tb.style.display = '';
      });
      return;
    }
    playNextEvent();
  };

  if (!hasScreenshot) {
    // 无截图：只显示路径高亮（黑底红点，因为确实没截图）
    clearPhoneMedia();
    canvas.style.opacity = '1';
    renderCanvas();
    replayTimer = setTimeout(goNext, delay);
    return;
  }

  // 有截图：路径只在「操作前截图」上显示，「操作后截图」不显示路径。
  // 时序：操作前截图（路径叠加）→ delay → 操作后截图（无路径）→ delay → 下一个
  canvas.style.opacity = '1';
  currentScreenshotView = 'before';
  showScreenshot(index);
  renderCanvas();

  const afterDelay = hasVideo && ss.after_type === 'video' ? Math.max(delay, 2000) : delay;
  setTimeout(() => {
    if (!state.isPlaying) return;
    currentScreenshotView = 'after';
    showScreenshot(index);
    canvas.style.opacity = '0';  // 操作后截图不显示路径
  }, delay);

  replayTimer = setTimeout(goNext, delay + afterDelay);
}

} // 平台守卫结束

// showScreenshot / showScreenshotBefore / showScreenshotAfter 定义在 shortcuts.js 中
