// ===== 键盘快捷键 =====
document.addEventListener('keydown', (e) => {
  // 如果焦点在 input 中，不处理
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

  if (e.key === 'Delete' || e.key === 'Backspace') {
    deleteSelected();
  } else if (e.key === 'ArrowUp' && state.selectedIndex > 0) {
    e.preventDefault();
    if (e.shiftKey) {
      // Shift+上：扩展多选
      state.multiSelected.add(state.selectedIndex);
      state.selectedIndex--;
      state.multiSelected.add(state.selectedIndex);
      renderEventList();
      renderCanvas();
    } else {
      state.multiSelected.clear();
      selectEvent(state.selectedIndex - 1);
    }
  } else if (e.key === 'ArrowDown' && state.selectedIndex < state.events.length - 1) {
    e.preventDefault();
    if (e.shiftKey) {
      // Shift+下：扩展多选
      state.multiSelected.add(state.selectedIndex);
      state.selectedIndex++;
      state.multiSelected.add(state.selectedIndex);
      renderEventList();
      renderCanvas();
    } else {
      state.multiSelected.clear();
      selectEvent(state.selectedIndex + 1);
    }
  } else if (e.key === 'd' && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    duplicateSelected();
  } else if (e.key === 'a' && (e.metaKey || e.ctrlKey)) {
    // Ctrl/Cmd+A：全选
    e.preventDefault();
    state.multiSelected.clear();
    for (let i = 0; i < state.events.length; i++) {
      state.multiSelected.add(i);
    }
    renderEventList();
  } else if (e.key === 'Escape') {
    clearSelection();
    closeAddModal();
  }
});

// ===== 截屏/录屏展示（直接在手机屏幕上显示） =====
let currentScreenshotView = 'before'; // before | after

function getScreenshotUrl(localPath) {
  return localPath;
}

/**
 * 计算截图/录屏路径（非存储，根据 event index + type 推断）。
 * 兼容旧格式 data.json（直接含 before/after 路径）。
 */
function getScreenshotPath(index, phase, ss) {
  if (ss[phase]) return ss[phase];
  var type = ss[phase + '_type'] || 'screenshot';
  var ext = (type === 'video') ? 'mp4' : 'png';
  var slot = (phase === 'before') ? '0_before' : '1_after';
  return 'screenshots/event_' + String(index).padStart(3, '0') + '_' + slot + '.' + ext;
}

function isVideoFile(path) {
  return path && (path.endsWith('.mp4') || path.endsWith('.webm'));
}

function clearPhoneMedia() {
  const phoneScreen = document.getElementById('phone-screen');
  phoneScreen.style.backgroundImage = '';
  // 移除已有的 video 元素
  const existingVideo = phoneScreen.querySelector('video');
  if (existingVideo) {
    existingVideo.pause();
    existingVideo.remove();
  }
  // 恢复 overlay 的事件拦截
  const overlay = document.getElementById('phone-overlay');
  if (overlay) overlay.style.pointerEvents = '';
}

function showVideoOnPhone(path) {
  const phoneScreen = document.getElementById('phone-screen');
  clearPhoneMedia();
  const video = document.createElement('video');
  video.src = getScreenshotUrl(path);
  video.controls = true;
  video.autoplay = true;
  video.loop = false;
  video.muted = false;
  video.style.cssText = 'width:100%;height:100%;object-fit:contain;position:absolute;top:0;left:0;z-index:10;border-radius:inherit;';
  phoneScreen.appendChild(video);
  // 禁用 overlay 的事件拦截，让视频控件可以被点击
  const overlay = document.getElementById('phone-overlay');
  if (overlay) overlay.style.pointerEvents = 'none';
}

function showScreenshot(index) {
  const switchEl = document.getElementById('screenshot-switch');
  const phoneScreen = document.getElementById('phone-screen');

  if (index < 0 || !state.events[index] || !state.events[index].screenshots) {
    // 无截图：禁用前/后按钮，但保留栏（旋转按钮始终可用）
    document.getElementById('btn-ss-before').disabled = true;
    document.getElementById('btn-ss-after').disabled = true;
    document.getElementById('screenshot-label').textContent = '无截屏';
    clearPhoneMedia();
    return;
  }

  const ss = state.events[index].screenshots;
  document.getElementById('btn-ss-before').disabled = false;
  document.getElementById('btn-ss-after').disabled = false;
  switchEl.style.display = 'flex';

  const path = getScreenshotPath(index, currentScreenshotView, ss);
  const mediaType = ss[currentScreenshotView + '_type'] || 'screenshot';
  const typeLabel = mediaType === 'video' ? '录屏' : '截屏';
  document.getElementById('screenshot-label').textContent = `#${index + 1} ${currentScreenshotView === 'before' ? '前' : '后'} (${typeLabel})`;

  if (path) {
    if (isVideoFile(path) || mediaType === 'video') {
      // 视频文件：用 video 元素播放
      phoneScreen.style.backgroundImage = '';
      showVideoOnPhone(path);
    } else {
      // 图片文件：用背景图显示
      clearPhoneMedia();
      phoneScreen.style.backgroundImage = `url('${getScreenshotUrl(path)}')`;
    }
  } else {
    clearPhoneMedia();
  }

  // 更新按钮状态
  document.getElementById('btn-ss-before').classList.toggle('active', currentScreenshotView === 'before');
  document.getElementById('btn-ss-after').classList.toggle('active', currentScreenshotView === 'after');
}

function showScreenshotBefore() {
  currentScreenshotView = 'before';
  showScreenshot(state.selectedIndex >= 0 ? state.selectedIndex : state.playIndex);
}

function showScreenshotAfter() {
  currentScreenshotView = 'after';
  showScreenshot(state.selectedIndex >= 0 ? state.selectedIndex : state.playIndex);
}

// ===== 离开提醒 =====
window.addEventListener('beforeunload', (e) => {
  if (state.isDirty) {
    e.preventDefault();
    e.returnValue = '';
  }
});
