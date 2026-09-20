// ===== 事件选择与编辑 =====

// 处理事件项点击（支持多选）
function handleEventClick(e, index) {
  if (e.metaKey || e.ctrlKey) {
    // Ctrl/Cmd+点击：切换多选
    if (state.multiSelected.has(index)) {
      state.multiSelected.delete(index);
    } else {
      state.multiSelected.add(index);
    }
    state.selectedIndex = index;
    renderEventList();
    renderCanvas();
    showEditPanel(index);
    showScreenshot(index);
  } else if (e.shiftKey && state.selectedIndex >= 0) {
    // Shift+点击：范围选择
    const start = Math.min(state.selectedIndex, index);
    const end = Math.max(state.selectedIndex, index);
    for (let i = start; i <= end; i++) {
      state.multiSelected.add(i);
    }
    state.selectedIndex = index;
    renderEventList();
    renderCanvas();
  } else {
    // 普通点击：单选
    state.multiSelected.clear();
    selectEvent(index);
  }
}

function selectEvent(index) {
  if (state.isPlaying) return;
  
  state.selectedIndex = index;
  renderEventList();
  renderCanvas();
  
  // 显示截屏（直接在手机屏幕上）
  showScreenshot(index);
  
  // 显示编辑面板
  showEditPanel(index);
  
  updateStatusBar();
}

function clearSelection() {
  state.selectedIndex = -1;
  state.multiSelected.clear();
  renderEventList();
  renderCanvas();
  document.getElementById('edit-panel').style.display = 'none';
  const emptyEl = document.getElementById('edit-empty');
  if (emptyEl) emptyEl.style.display = 'block';
}

function showEditPanel(index) {
  const panel = document.getElementById('edit-panel');
  const emptyEl = document.getElementById('edit-empty');
  const ev = state.events[index];
  if (!ev) {
    panel.style.display = 'none';
    if (emptyEl) emptyEl.style.display = 'block';
    return;
  }

  panel.style.display = 'block';
  if (emptyEl) emptyEl.style.display = 'none';
  document.getElementById('edit-index').textContent = index + 1;

  const fields = document.getElementById('edit-fields');

  // 按平台动态渲染编辑面板
  const type = ev.type || 'tap';
  const plat = window.__FLOW_PLATFORM || 'adb';
  const types = (typeof PLATFORM_EVENT_TYPES !== 'undefined' && PLATFORM_EVENT_TYPES[plat]) || PLATFORM_EVENT_TYPES?.adb || [
    {value:'tap',label:'点击'},{value:'swipe',label:'滑动'},{value:'keyevent',label:'按键'},
    {value:'text',label:'文本'},{value:'adb',label:'ADB命令'},{value:'tips',label:'提示'}
  ];

  let html = '';

  // 类型选择器（按平台）
  const typeOpts = types.filter(t => t.value !== 'favorite').map(t =>
    `<option value="${t.value}" ${type === t.value ? 'selected' : ''}>${t.label}</option>`
  ).join('');
  html += `<div class="edit-row"><label>类型</label>
    <select onchange="changeEventType(${index}, this.value)" style="flex:1;padding:4px 8px;border:1px solid #444;border-radius:4px;background:#1a1a2e;color:#eee;font-size:12px;max-width:140px">${typeOpts}</select>
  </div>`;

  // 名称（所有类型通用）
  html += `<div class="edit-row"><label>名称</label><input type="text" value="${ev.name || ''}" onchange="updateTextField(${index}, 'name', this.value)" placeholder="可选备注"></div>`;

  // 按类型渲染专属字段
  if (type === 'tap' || type === 'click' || type === 'dblclick' || type === 'rclick' || type === 'rightclick' || type === 'hover' || type === 'move') {
    html += `<div class="edit-row"><label>X</label><input type="number" value="${ev.x ?? ''}" onchange="updateField(${index}, 'x', this.value)"></div>`;
    html += `<div class="edit-row"><label>Y</label><input type="number" value="${ev.y ?? ''}" onchange="updateField(${index}, 'y', this.value)"></div>`;
  } else if (type === 'multitap') {
    html += `<div class="edit-row"><label>X</label><input type="number" value="${ev.x ?? ''}" onchange="updateField(${index}, 'x', this.value)"></div>`;
    html += `<div class="edit-row"><label>Y</label><input type="number" value="${ev.y ?? ''}" onchange="updateField(${index}, 'y', this.value)"></div>`;
    html += `<div class="edit-row"><label>点击次数</label><input type="number" value="${ev.count ?? 2}" step="1" min="1" onchange="updateField(${index}, 'count', this.value)"></div>`;
  } else if (type === 'swipe' || type === 'drag') {
    html += `<div class="edit-row"><label>起点 X</label><input type="number" value="${ev.x1 ?? ''}" onchange="updateField(${index}, 'x1', this.value)"></div>`;
    html += `<div class="edit-row"><label>起点 Y</label><input type="number" value="${ev.y1 ?? ''}" onchange="updateField(${index}, 'y1', this.value)"></div>`;
    html += `<div class="edit-row"><label>终点 X</label><input type="number" value="${ev.x2 ?? ''}" onchange="updateField(${index}, 'x2', this.value)"></div>`;
    html += `<div class="edit-row"><label>终点 Y</label><input type="number" value="${ev.y2 ?? ''}" onchange="updateField(${index}, 'y2', this.value)"></div>`;
    if (type === 'swipe') html += `<div class="edit-row"><label>时长(ms)</label><input type="number" value="${ev.duration_ms ?? 300}" step="1" min="0" onchange="updateField(${index}, 'duration_ms', this.value)"></div>`;
  } else if (type === 'scroll') {
    html += `<div class="edit-row"><label>X</label><input type="number" value="${ev.x ?? ''}" onchange="updateField(${index}, 'x', this.value)"></div>`;
    html += `<div class="edit-row"><label>Y</label><input type="number" value="${ev.y ?? ''}" onchange="updateField(${index}, 'y', this.value)"></div>`;
    html += `<div class="edit-row"><label>滚动量(δY)</label><input type="number" value="${ev.delta_y ?? ev.dy ?? 0}" step="50" onchange="updateField(${index}, 'delta_y', this.value)"></div>`;
  } else if (type === 'keyevent') {
    html += `<div class="edit-row"><label>键码</label><input type="number" value="${ev.code ?? ''}" onchange="updateField(${index}, 'code', this.value)"><a href="https://developer.android.google.cn/reference/android/view/KeyEvent" target="_blank" title="查看 Android KeyEvent 文档" style="margin-left:6px;color:#4fc3f7;font-size:12px;text-decoration:none;white-space:nowrap">📖 参考</a></div>`;
  } else if (type === 'keyboard' || type === 'hotkey') {
    const keysVal = Array.isArray(ev.keys) ? ev.keys.join(', ') : (ev.keys || '');
    html += `<div class="edit-row"><label>按键</label><input type="text" value="${keysVal}" onchange="state.events[${index}].keys=this.value.split(',').map(k=>k.trim()).filter(k=>k);state.isDirty=true" placeholder="如：Enter 或 Control,c"></div>`;
  } else if (type === 'text' || type === 'type') {
    html += `<div class="edit-row"><label>文本</label><input type="text" value="${ev.content || ''}" onchange="updateTextField(${index}, 'content', this.value)"></div>`;
  } else if (type === 'navigate') {
    html += `<div class="edit-row"><label>URL</label><input type="text" value="${ev.url || ev.value || ''}" onchange="updateTextField(${index}, 'url', this.value);updateTextField(${index}, 'value', this.value)" placeholder="https://..."></div>`;
  } else if (type === 'select') {
    html += `<div class="edit-row"><label>选择器</label><input type="text" value="${ev.selector || ''}" onchange="updateTextField(${index}, 'selector', this.value)"></div>`;
    html += `<div class="edit-row"><label>选项值</label><input type="text" value="${ev.value || ''}" onchange="updateTextField(${index}, 'value', this.value)"></div>`;
  } else if (type === 'check') {
    html += `<div class="edit-row"><label>选择器</label><input type="text" value="${ev.selector || ''}" onchange="updateTextField(${index}, 'selector', this.value)"></div>`;
  } else if (type === 'wait') {
    html += `<div class="edit-row"><label>等待(ms)</label><input type="number" value="${ev.duration_ms ?? 5000}" step="100" min="0" onchange="updateField(${index}, 'duration_ms', this.value)"></div>`;
  } else if (type === 'launch' || type === 'quit') {
    html += `<div class="edit-row"><label>目标程序</label><input type="text" value="${ev.target || ''}" onchange="updateTextField(${index}, 'target', this.value)" placeholder="${type==='launch'?'路径或命令':'进程名'}"></div>`;
  } else if (type === 'tips') {
    html += `<div class="edit-row"><label>提示文本</label><input type="text" value="${ev.content || ''}" onchange="updateTextField(${index}, 'content', this.value)" placeholder="回放时显示的提示信息"></div>`;
  } else if (type === 'adb') {
    const isWifi = ev.action === 'wifi-connect';
    const isSchema = ev.action === 'open-schema';
    const isInstall = ev.action === 'install';
    html += `<div class="edit-row"><label>操作</label>
      <select onchange="updateTextField(${index}, 'action', this.value);showEditPanel(${index})" style="flex:1;padding:4px 8px;border:1px solid #444;border-radius:4px;background:#1a1a2e;color:#eee;font-size:12px;max-width:140px">
        <option value="force-stop" ${ev.action === 'force-stop' ? 'selected' : ''}>杀掉应用</option>
        <option value="clear" ${ev.action === 'clear' ? 'selected' : ''}>清理缓存</option>
        <option value="restart" ${ev.action === 'restart' ? 'selected' : ''}>应用重启</option>
        <option value="launch" ${ev.action === 'launch' ? 'selected' : ''}>拉起应用</option>
        <option value="clear-all" ${ev.action === 'clear-all' ? 'selected' : ''}>清理所有后台</option>
        <option value="lock-screen" ${ev.action === 'lock-screen' ? 'selected' : ''}>锁屏</option>
        <option value="wifi-connect" ${ev.action === 'wifi-connect' ? 'selected' : ''}>连接 WiFi</option>
        <option value="open-schema" ${ev.action === 'open-schema' ? 'selected' : ''}>打开 Schema</option>
        <option value="uninstall" ${ev.action === 'uninstall' ? 'selected' : ''}>卸载应用</option>
        <option value="install" ${ev.action === 'install' ? 'selected' : ''}>安装 APK</option>
      </select>
    </div>`;
    if (isWifi) {
      html += `<div class="edit-row"><label>SSID</label><input type="text" value="${ev.ssid || ''}" onchange="updateTextField(${index}, 'ssid', this.value)" style="flex:1;padding:4px 8px;border:1px solid #444;border-radius:4px;background:#1a1a2e;color:#eee"></div>`;
      html += `<div class="edit-row"><label>密码</label><input type="password" value="${ev.password || ''}" onchange="updateTextField(${index}, 'password', this.value)" style="flex:1;padding:4px 8px;border:1px solid #444;border-radius:4px;background:#1a1a2e;color:#eee"></div>`;
    } else if (isSchema) {
      html += `<div class="edit-row"><label>Schema URI</label><input type="text" value="${ev.content || ''}" oninput="updateTextField(${index}, 'content', this.value)" style="flex:1;padding:4px 8px;border:1px solid #444;border-radius:4px;background:#1a1a2e;color:#eee" placeholder="zixie://zweb?url=https://..."></div>`;
    } else if (isInstall) {
      html += `<div class="edit-row"><label>文件名</label><input type="text" value="${ev.content || ''}" onchange="updateTextField(${index}, 'content', this.value)" placeholder="APK 文件名（可省略 .apk，放 ~/.zixiekit/skill/replay/install/）"></div>`;
    } else {
      html += `<div class="edit-row"><label>包名</label><input type="text" value="${ev.package || ''}" onchange="updateTextField(${index}, 'package', this.value)" ${ev.action !== 'clear-all' ? '' : 'disabled'}></div>`;
    }
  }

  // 延迟（所有类型通用，毫秒）
  const delayBeforeMs = ev.delay_before_ms || ev.delay_ms || EVENT_DEFAULTS.delay_before_ms;
  const delayAfterMs = ev.delay_after_ms || getDelayAfterDefault(ev.type, ev.action);
  html += `<div class="edit-row edit-separator"><label>前延迟(ms)</label><input type="number" value="${delayBeforeMs}" step="100" min="0" onchange="updateDelayField(${index}, 'delay_before_ms', this.value)" title="执行前等待"></div>`;
  html += `<div class="edit-row"><label>后延迟(ms)</label><input type="number" value="${delayAfterMs}" step="100" min="0" onchange="updateDelayField(${index}, 'delay_after_ms', this.value)" title="执行后等待"></div>`;

  // 关键事件标记（开关样式）
  html += `<div class="edit-row edit-separator"><label>关键事件</label>
    <label class="critical-switch" title="标记为关键事件">
      <input type="checkbox" ${ev.is_critical ? 'checked' : ''} onchange="updateBoolField(${index}, 'is_critical', this.checked)">
      <span class="critical-slider"></span>
    </label>
  </div>`;

  // 采集模式
  html += `<div class="edit-row"><label>采集模式</label>
    <select onchange="updateTextField(${index}, 'capture_mode', this.value)" style="flex:1;padding:4px 8px;border:1px solid #444;border-radius:4px;background:#1a1a2e;color:#eee;font-size:12px;max-width:140px">
      <option value="screenshot" ${(ev.capture_mode || 'screenshot') === 'screenshot' ? 'selected' : ''}>截屏</option>
      <option value="video" ${ev.capture_mode === 'video' ? 'selected' : ''}>录屏</option>
      <option value="none" ${ev.capture_mode === 'none' ? 'selected' : ''}>跳过采集</option>
    </select>
  </div>`;

  fields.innerHTML = html;
}

function updateField(index, field, value) {
  state.events[index][field] = parseInt(value) || 0;
  state.isDirty = true;
  renderCanvas();
  updateStats();
}

// 延迟字段专用更新函数：存储毫秒值
function updateDelayField(index, field, valueMs) {
  state.events[index][field] = parseInt(valueMs) || 0;
  state.isDirty = true;
  renderEventList();
  renderCanvas();
  updateStats();
}

function updateBoolField(index, field, value) {
  state.events[index][field] = !!value;
  state.isDirty = true;
  renderEventList();
  updateStats();
}

function updateTextField(index, field, value) {
  state.events[index][field] = value;
  state.isDirty = true;
  renderEventList();
  updateStats();
}

function changeEventType(index, newType) {
  const ev = state.events[index];
  if (!ev) return;

  // 保存通用字段
  const name = ev.name || '';
  const delay_before_ms = ev.delay_before_ms || ev.delay_ms || EVENT_DEFAULTS.delay_before_ms;
  const is_critical = ev.is_critical || false;
  const capture_mode = ev.capture_mode || 'screenshot';

  // 根据新类型重置事件对象
  const newEvent = { type: newType, name, delay_before_ms, is_critical, capture_mode };

  // 根据类型设置默认值
  switch (newType) {
    case 'tap':
      newEvent.x = ev.x || 0;
      newEvent.y = ev.y || 0;
      newEvent.delay_after_ms = ev.delay_after_ms || getDelayAfterDefault('tap');
      break;
    case 'multitap':
      newEvent.x = ev.x || 0;
      newEvent.y = ev.y || 0;
      newEvent.count = ev.count || 2;
      newEvent.delay_after_ms = ev.delay_after_ms || getDelayAfterDefault('multitap');
      break;
    case 'swipe':
      newEvent.x1 = ev.x1 || 0;
      newEvent.y1 = ev.y1 || 0;
      newEvent.x2 = ev.x2 || 0;
      newEvent.y2 = ev.y2 || 0;
      newEvent.duration_ms = ev.duration_ms || EVENT_DEFAULTS.duration_ms;
      newEvent.delay_after_ms = ev.delay_after_ms || getDelayAfterDefault('swipe');
      break;
    case 'keyevent':
      newEvent.code = ev.code || EVENT_DEFAULTS.key_code;
      newEvent.delay_after_ms = ev.delay_after_ms || getDelayAfterDefault('keyevent');
      break;
    case 'text':
      newEvent.content = ev.content || EVENT_DEFAULTS.text_content;
      newEvent.delay_after_ms = ev.delay_after_ms || getDelayAfterDefault('text');
      break;
    case 'adb':
      newEvent.action = ev.action || EVENT_DEFAULTS.adb_action;
      newEvent.package = ev.package || '';
      if (newEvent.action === 'wifi-connect') {
        newEvent.ssid = ev.ssid || '';
        newEvent.password = ev.password || '';
        newEvent.security = ev.security || 'wpa2';
      } else if (newEvent.action === 'open-schema' || newEvent.action === 'install') {
        newEvent.content = ev.content || '';
      }
      newEvent.delay_after_ms = ev.delay_after_ms || getDelayAfterDefault('adb', newEvent.action);
      break;
    case 'tips':
      newEvent.content = ev.content || EVENT_DEFAULTS.tips_content;
      newEvent.delay_after_ms = ev.delay_after_ms || getDelayAfterDefault('tips');
      break;
  }

  // 保留截屏数据
  if (ev.screenshots) {
    newEvent.screenshots = ev.screenshots;
  }

  // 更新事件
  state.events[index] = newEvent;
  state.isDirty = true;

  // 刷新界面
  showEditPanel(index);
  renderEventList();
  renderCanvas();
  updateStats();
  updateStatistics();
  updateStatusBar();
}

// ===== 事件操作 =====
function moveEvent(index, direction) {
  const newIndex = index + direction;
  if (newIndex < 0 || newIndex >= state.events.length) return;

  const temp = state.events[index];
  state.events[index] = state.events[newIndex];
  state.events[newIndex] = temp;

  if (state.selectedIndex === index) state.selectedIndex = newIndex;
  else if (state.selectedIndex === newIndex) state.selectedIndex = index;

  state.isDirty = true;
  renderEventList();
  renderCanvas();
}

function duplicateEvent(index) {
  const copy = JSON.parse(JSON.stringify(state.events[index]));
  state.events.splice(index + 1, 0, copy);
  state.isDirty = true;
  updateStats();
  renderEventList();
  renderCanvas();
}

function deleteEvent(index) {
  state.events.splice(index, 1);
  
  // 删除后自动选中下一个事件
  if (state.selectedIndex === index) {
    if (state.events.length > 0) {
      // 如果删除的不是最后一个事件，选中下一个（如果删除的是最后一个，选中前一个）
      state.selectedIndex = Math.min(index, state.events.length - 1);
      showEditPanel(state.selectedIndex);
      showScreenshot(state.selectedIndex);
    } else {
      state.selectedIndex = -1;
      document.getElementById('edit-panel').style.display = 'none';
    }
  } else if (state.selectedIndex > index) {
    state.selectedIndex--;
  }
  
  state.isDirty = true;
  updateStats();
  renderEventList();
  renderCanvas();
}

function deleteSelected() {
  // 多选删除
  if (state.multiSelected.size > 0) {
    const indices = Array.from(state.multiSelected).sort((a, b) => b - a);
    indices.forEach(i => state.events.splice(i, 1));
    state.multiSelected.clear();
    
    // 多选删除后自动选中第一个可用的事件
    if (state.events.length > 0) {
      state.selectedIndex = 0;
      showEditPanel(state.selectedIndex);
      showScreenshot(state.selectedIndex);
    } else {
      state.selectedIndex = -1;
      document.getElementById('edit-panel').style.display = 'none';
    }
    
    state.isDirty = true;
    updateStats();
    renderEventList();
    renderCanvas();
    return;
  }
  // 单选删除
  if (state.selectedIndex < 0) return;
  deleteEvent(state.selectedIndex);
}

// 批量复制选中事件
function duplicateSelected() {
  let indices = [];
  if (state.multiSelected.size > 0) {
    indices = Array.from(state.multiSelected).sort((a, b) => a - b);
  } else if (state.selectedIndex >= 0) {
    indices = [state.selectedIndex];
  }
  if (!indices.length) {
    alert('请先选择要复制的事件（Ctrl/Cmd+点击多选）');
    return;
  }

  // 复制所有选中事件，插入到最后一个选中项之后
  const copies = indices.map(i => JSON.parse(JSON.stringify(state.events[i])));
  const insertAt = indices[indices.length - 1] + 1;
  state.events.splice(insertAt, 0, ...copies);
  state.isDirty = true;

  // 更新多选为新复制的事件
  state.multiSelected.clear();
  for (let i = 0; i < copies.length; i++) {
    state.multiSelected.add(insertAt + i);
  }
  state.selectedIndex = insertAt;

  updateStats();
  renderEventList();
  renderCanvas();
}

// ===== 拖拽排序（支持多选拖动） =====
let dragIndex = -1;

function dragStart(e, index) {
  dragIndex = index;
  e.dataTransfer.effectAllowed = 'move';
  e.target.classList.add('dragging');

  // 如果拖动的不在多选中，清除多选并单选当前
  if (state.multiSelected.size > 0 && !state.multiSelected.has(index)) {
    state.multiSelected.clear();
    state.selectedIndex = index;
  }
}

function dragOver(e, index) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
}

function drop(e, index) {
  e.preventDefault();
  if (dragIndex === index) return;

  // 多选拖动
  if (state.multiSelected.size > 1 && state.multiSelected.has(dragIndex)) {
    const sortedIndices = Array.from(state.multiSelected).sort((a, b) => a - b);
    // 提取选中的事件
    const items = sortedIndices.map(i => state.events[i]);
    // 从后往前删除
    for (let i = sortedIndices.length - 1; i >= 0; i--) {
      state.events.splice(sortedIndices[i], 1);
    }
    // 计算插入位置（删除后的新索引）
    let insertAt = index;
    const removedBefore = sortedIndices.filter(i => i < index).length;
    insertAt -= removedBefore;
    if (insertAt < 0) insertAt = 0;
    // 插入
    state.events.splice(insertAt, 0, ...items);
    // 更新多选索引
    state.multiSelected.clear();
    for (let i = 0; i < items.length; i++) {
      state.multiSelected.add(insertAt + i);
    }
    state.selectedIndex = insertAt;
  } else {
    // 单个拖动
    const item = state.events.splice(dragIndex, 1)[0];
    state.events.splice(index, 0, item);
    if (state.selectedIndex === dragIndex) state.selectedIndex = index;
  }

  state.isDirty = true;
  renderEventList();
  renderCanvas();
}

function dragEnd(e) {
  e.target.classList.remove('dragging');
  dragIndex = -1;
}
