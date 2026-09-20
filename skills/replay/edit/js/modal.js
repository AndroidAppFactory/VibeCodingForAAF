// ===== 平台事件类型配置 =====
const PLATFORM_EVENT_TYPES = {
  adb: [
    {value:'tap', label:'tap（点击）'},
    {value:'multitap', label:'multitap（连续点击）'},
    {value:'swipe', label:'swipe（滑动）'},
    {value:'keyevent', label:'keyevent（按键）'},
    {value:'text', label:'text（文本）'},
    {value:'adb', label:'adb（应用控制）'},
    {value:'tips', label:'tips（提示）'},
    {value:'favorite', label:'📦 从 Flow 插入'},
  ],
  web: [
    {value:'click', label:'click（点击）'},
    {value:'navigate', label:'navigate（导航）'},
    {value:'type', label:'type（输入文本）'},
    {value:'scroll', label:'scroll（滚动）'},
    {value:'keyboard', label:'keyboard（按键）'},
    {value:'hover', label:'hover（悬停）'},
    {value:'select', label:'select（选择）'},
    {value:'check', label:'check（勾选）'},
    {value:'wait', label:'wait（等待）'},
    {value:'tips', label:'tips（提示）'},
    {value:'favorite', label:'📦 从 Flow 插入'},
  ],
  win: [
    {value:'click', label:'click（点击）'},
    {value:'dblclick', label:'dblclick（双击）'},
    {value:'rclick', label:'rclick（右键）'},
    {value:'type', label:'type（输入文本）'},
    {value:'keyboard', label:'keyboard（按键）'},
    {value:'hotkey', label:'hotkey（快捷键）'},
    {value:'scroll', label:'scroll（滚动）'},
    {value:'drag', label:'drag（拖拽）'},
    {value:'move', label:'move（移动）'},
    {value:'launch', label:'launch（拉起应用）'},
    {value:'quit', label:'quit（退出应用）'},
    {value:'tips', label:'tips（提示）'},
    {value:'favorite', label:'📦 从 Flow 插入'},
  ],
  mac: [
    {value:'click', label:'click（点击）'},
    {value:'dblclick', label:'dblclick（双击）'},
    {value:'rightclick', label:'rightclick（右键）'},
    {value:'type', label:'type（输入文本）'},
    {value:'scroll', label:'scroll（滚动）'},
    {value:'drag', label:'drag（拖拽）'},
    {value:'tips', label:'tips（提示）'},
    {value:'favorite', label:'📦 从 Flow 插入'},
  ],
};

function initTypeOptions() {
  const plat = window.__FLOW_PLATFORM || 'adb';
  const types = PLATFORM_EVENT_TYPES[plat] || PLATFORM_EVENT_TYPES.adb;
  const sel = document.getElementById('add-type');
  sel.innerHTML = types.map(t => `<option value="${t.value}">${t.label}</option>`).join('');
}

// ===== 添加事件模态框 =====
function showAddModal() {
  initTypeOptions();
  document.getElementById('add-modal').classList.add('show');
  updateAddForm();
}

function closeAddModal() {
  document.getElementById('add-modal').classList.remove('show');
}

async function insertFlowEvents(name) {
  try {
    const resp = await fetch('/api/flow?name=' + encodeURIComponent(name));
    const data = await resp.json();
    const flow = data.flow || data;
    if (!flow || !flow.steps) return;
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
    const pos = state.selectedIndex >= 0 ? state.selectedIndex + 1 : state.events.length;
    state.events.splice(pos, 0, ...events);
    state.isDirty = true;
    updateStats();
    renderEventList();
    renderCanvas();
  } catch (e) { console.error(e); }
}

function updateAddForm() {
  const type = document.getElementById('add-type').value;
  const fields = document.getElementById('add-fields');

  if (type === 'tap') {
    fields.innerHTML = `
      <div class="form-group"><label>X</label><input type="number" id="add-x" value="${Math.round(state.resolution[0]/2)}"></div>
      <div class="form-group"><label>Y</label><input type="number" id="add-y" value="${Math.round(state.resolution[1]/2)}"></div>`;
  } else if (type === 'multitap') {
    fields.innerHTML = `
      <div class="form-group"><label>X</label><input type="number" id="add-x" value="${Math.round(state.resolution[0]/2)}"></div>
      <div class="form-group"><label>Y</label><input type="number" id="add-y" value="${Math.round(state.resolution[1]/2)}"></div>
      <div class="form-group"><label>点击次数</label><input type="number" id="add-count" value="2" step="1" min="1"></div>`;
  } else if (type === 'swipe') {
    fields.innerHTML = `
      <div class="form-group"><label>起点 X</label><input type="number" id="add-x1" value="${Math.round(state.resolution[0]/2)}"></div>
      <div class="form-group"><label>起点 Y</label><input type="number" id="add-y1" value="${Math.round(state.resolution[1]*0.7)}"></div>
      <div class="form-group"><label>终点 X</label><input type="number" id="add-x2" value="${Math.round(state.resolution[0]/2)}"></div>
      <div class="form-group"><label>终点 Y</label><input type="number" id="add-y2" value="${Math.round(state.resolution[1]*0.3)}"></div>
<div class="form-group"><label>时长 (ms)</label><input type="number" id="add-duration" value="300" step="1" min="0"></div>`;
  } else if (type === 'keyevent') {
    fields.innerHTML = `
      <div class="form-group"><label>键码</label><input type="number" id="add-code" value="4" placeholder="4=BACK, 3=HOME"></div>`;
  } else if (type === 'text') {
    fields.innerHTML = `
      <div class="form-group"><label>文本内容</label><input type="text" id="add-content" value=""></div>`;
  } else if (type === 'adb') {
    fields.innerHTML = `
      <div class="form-group"><label>操作</label>
        <select id="add-action" onchange="togglePackageField()">
          <option value="force-stop">force-stop（杀掉应用）</option>
          <option value="clear">clear（清理缓存）</option>
          <option value="restart">restart（应用重启）</option>
          <option value="launch">launch（拉起应用）</option>
          <option value="clear-all">clear-all（清理所有后台）</option>
          <option value="lock-screen">lock-screen（锁屏）</option>
          <option value="wifi-connect">wifi-connect（连接 WiFi）</option>
          <option value="open-schema">open-schema（打开 Schema）</option>
          <option value="uninstall">uninstall（卸载应用）</option>
          <option value="install">install（安装 APK）</option>
        </select>
      </div>
      <div class="form-group" id="add-package-group"><label>包名</label><input type="text" id="add-package" value="" placeholder="com.example.app"></div>
      <div class="form-group" id="add-install-group" style="display:none"><label>文件名</label><input type="text" id="add-install-content" value="" placeholder="APK 文件名（可省略 .apk）"></div>
      <div class="form-group" id="add-wifi-group" style="display:none">
        <label>SSID</label><input type="text" id="add-wifi-ssid" value="" placeholder="WiFi 名称">
        <label style="margin-top:8px">密码</label><input type="password" id="add-wifi-password" value="" placeholder="WiFi 密码">
      </div>
      <div class="form-group" id="add-schema-group" style="display:none"><label>Schema URI</label><input type="text" id="add-schema-content" value="" placeholder="zixie://zweb?url=https://..."></div>`;
  } else if (type === 'click' || type === 'dblclick' || type === 'rclick' || type === 'rightclick') {
    fields.innerHTML = `
      <div class="form-group"><label>X</label><input type="number" id="add-x" value="${Math.round(state.resolution[0]/2)}"></div>
      <div class="form-group"><label>Y</label><input type="number" id="add-y" value="${Math.round(state.resolution[1]/2)}"></div>`;
  } else if (type === 'navigate') {
    fields.innerHTML = `
      <div class="form-group"><label>URL</label><input type="text" id="add-url" value="" placeholder="https://example.com"></div>`;
  } else if (type === 'type') {
    fields.innerHTML = `
      <div class="form-group"><label>文本内容</label><input type="text" id="add-content" value="" placeholder="输入的文本"></div>`;
  } else if (type === 'keyboard' || type === 'hotkey') {
    fields.innerHTML = `
      <div class="form-group"><label>按键（多个用逗号分隔）</label><input type="text" id="add-keys" value="" placeholder="如：Enter 或 Control,c"></div>`;
  } else if (type === 'scroll') {
    fields.innerHTML = `
      <div class="form-group"><label>X</label><input type="number" id="add-x" value="${Math.round(state.resolution[0]/2)}"></div>
      <div class="form-group"><label>Y</label><input type="number" id="add-y" value="${Math.round(state.resolution[1]/2)}"></div>
      <div class="form-group"><label>滚动量 (δY)</label><input type="number" id="add-delta-y" value="-200" step="50"></div>`;
  } else if (type === 'hover' || type === 'move') {
    fields.innerHTML = `
      <div class="form-group"><label>X</label><input type="number" id="add-x" value="${Math.round(state.resolution[0]/2)}"></div>
      <div class="form-group"><label>Y</label><input type="number" id="add-y" value="${Math.round(state.resolution[1]/2)}"></div>`;
  } else if (type === 'drag') {
    fields.innerHTML = `
      <div class="form-group"><label>起点 X</label><input type="number" id="add-x1" value="${Math.round(state.resolution[0]/3)}"></div>
      <div class="form-group"><label>起点 Y</label><input type="number" id="add-y1" value="${Math.round(state.resolution[1]/2)}"></div>
      <div class="form-group"><label>终点 X</label><input type="number" id="add-x2" value="${Math.round(state.resolution[0]*2/3)}"></div>
      <div class="form-group"><label>终点 Y</label><input type="number" id="add-y2" value="${Math.round(state.resolution[1]/2)}"></div>`;
  } else if (type === 'select') {
    fields.innerHTML = `
      <div class="form-group"><label>选择器</label><input type="text" id="add-selector" value="" placeholder="CSS 选择器"></div>
      <div class="form-group"><label>选项值</label><input type="text" id="add-value" value="" placeholder="option value"></div>`;
  } else if (type === 'check') {
    fields.innerHTML = `
      <div class="form-group"><label>选择器</label><input type="text" id="add-selector" value="" placeholder="CSS 选择器"></div>`;
  } else if (type === 'wait') {
    fields.innerHTML = `
      <div class="form-group"><label>等待时间 (ms)</label><input type="number" id="add-wait-ms" value="5000" step="100" min="0"></div>`;
  } else if (type === 'launch') {
    fields.innerHTML = `
      <div class="form-group"><label>目标程序（路径或命令）</label><input type="text" id="add-target" value="" placeholder="如：notepad.exe 或 C:\\Program Files\\App\\app.exe"></div>`;
  } else if (type === 'quit') {
    fields.innerHTML = `
      <div class="form-group"><label>进程名</label><input type="text" id="add-target" value="" placeholder="如：notepad.exe"></div>`;
  } else if (type === 'tips') {
    fields.innerHTML = `
      <div class="form-group"><label>提示文本</label><input type="text" id="add-tips-content" value="" placeholder="回放时显示的提示信息"></div>`;
  } else if (type === 'favorite') {
    // 从 Flow 插入（异步加载列表）
    loadFlowList();
    document.getElementById('add-name-group').style.display = 'none';
    document.getElementById('add-delay-group').style.display = 'none';
    return;
  }
  async function loadFlowList() {
    try {
      const resp = await fetch('/api/flows?_=' + Date.now());
      const data = await resp.json();
      const flows = (data.flows || data) || [];
      const plat = window.__FLOW_PLATFORM || '';
      const atomicFlows = flows.filter(f => {
        if (!f.is_atomic) return false;
        const fp = f.platform || '';
        if (plat && fp && fp !== plat && fp !== 'mixed' && plat !== 'mixed') return false;
        if (plat && !fp) return false;
        return true;
      });
      if (!atomicFlows.length) {
        fields.innerHTML = `<p style="color:#888;font-size:13px">暂无同平台原子 Flow。创建纯事件 Flow 后可用。</p>`;
      } else {
        const opts = atomicFlows.map(f => `<option value="${f.id||escHtml(f.name)}">${escHtml(f.name)}（${f.steps||0} 步）</option>`).join('');
        fields.innerHTML = `<div class="form-group"><label>选择 Flow</label><select id="add-favorite-name">${opts}</select></div>`;
      }
    } catch(e) {
      fields.innerHTML = `<p style="color:#888">加载失败</p>`;
    }
  }
  // 非收藏模式显示名称和延迟字段
  document.getElementById('add-name-group').style.display = '';
  document.getElementById('add-delay-group').style.display = '';
  document.getElementById('add-delay-group').innerHTML = `
    <div class="form-group"><label>前延迟 (ms)</label><input type="number" id="add-delay-before" value="${EVENT_DEFAULTS.delay_before_ms}" step="100" min="0"></div>
    <div class="form-group"><label>后延迟 (ms)</label><input type="number" id="add-delay-after" value="${getDelayAfterDefault(type)}" step="100" min="0"></div>
  `;

  // 根据类型动态设置后延迟默认值
  updateAddDelayDefaults(type);
}

// 根据事件类型更新添加弹窗的后延迟默认值
function updateAddDelayDefaults(type) {
  const delayAfterInput = document.getElementById('add-delay-after');
  if (!delayAfterInput) return;

  const action = document.getElementById('add-action') ? document.getElementById('add-action').value : undefined;
  const defaultDelayAfter = getDelayAfterDefault(type, action);
  delayAfterInput.value = defaultDelayAfter;
}

function togglePackageField() {
  const action = document.getElementById('add-action').value;
  const pkgGroup = document.getElementById('add-package-group');
  const installGroup = document.getElementById('add-install-group');
  const wifiGroup = document.getElementById('add-wifi-group');
  const schemaGroup = document.getElementById('add-schema-group');
  if (action === 'wifi-connect') {
    pkgGroup.style.display = 'none';
    if (installGroup) installGroup.style.display = 'none';
    if (wifiGroup) wifiGroup.style.display = '';
    if (schemaGroup) schemaGroup.style.display = 'none';
  } else if (action === 'open-schema') {
    pkgGroup.style.display = 'none';
    if (installGroup) installGroup.style.display = 'none';
    if (wifiGroup) wifiGroup.style.display = 'none';
    if (schemaGroup) schemaGroup.style.display = '';
  } else if (action === 'install') {
    pkgGroup.style.display = 'none';
    if (installGroup) installGroup.style.display = '';
    if (wifiGroup) wifiGroup.style.display = 'none';
    if (schemaGroup) schemaGroup.style.display = 'none';
  } else if (action === 'clear-all') {
    pkgGroup.style.display = 'none';
    if (installGroup) installGroup.style.display = 'none';
    if (wifiGroup) wifiGroup.style.display = 'none';
    if (schemaGroup) schemaGroup.style.display = 'none';
  } else {
    pkgGroup.style.display = '';
    if (installGroup) installGroup.style.display = 'none';
    if (wifiGroup) wifiGroup.style.display = 'none';
    if (schemaGroup) schemaGroup.style.display = 'none';
  }

  const delayAfterInput = document.getElementById('add-delay-after');
  if (delayAfterInput) {
    delayAfterInput.value = getDelayAfterDefault('adb', action);
  }
}

function confirmAdd() {
  const type = document.getElementById('add-type').value;

  // 从 Flow 插入
  if (type === 'favorite') {
    const sel = document.getElementById('add-favorite-name');
    if (!sel) { closeAddModal(); return; }
    const name = sel.value;
    if (!name) { closeAddModal(); return; }
    insertFlowEvents(name);
    closeAddModal();
    return;
  }

  const delayBefore = parseInt(document.getElementById('add-delay-before').value) || EVENT_DEFAULTS.delay_before_ms;
  const delayAfter = parseInt(document.getElementById('add-delay-after').value) || getDelayAfterDefault(type, document.getElementById('add-action') ? document.getElementById('add-action').value : undefined);
  const name = (document.getElementById('add-name').value || '').trim();
  const isCritical = document.getElementById('add-is-critical') ? document.getElementById('add-is-critical').checked : false;
  const captureMode = document.getElementById('add-capture-mode') ? document.getElementById('add-capture-mode').value : 'screenshot';
  let ev = { type, delay_before_ms: delayBefore, delay_after_ms: delayAfter };
  if (name) ev.name = name;
  if (isCritical) ev.is_critical = true;
  if (captureMode === 'video' || captureMode === 'none') ev.capture_mode = captureMode;

  if (type === 'tap') {
    ev.x = parseInt(document.getElementById('add-x').value) || 0;
    ev.y = parseInt(document.getElementById('add-y').value) || 0;
  } else if (type === 'multitap') {
    ev.x = parseInt(document.getElementById('add-x').value) || 0;
    ev.y = parseInt(document.getElementById('add-y').value) || 0;
    ev.count = parseInt(document.getElementById('add-count').value) || 2;
  } else if (type === 'swipe') {
    ev.x1 = parseInt(document.getElementById('add-x1').value) || 0;
    ev.y1 = parseInt(document.getElementById('add-y1').value) || 0;
    ev.x2 = parseInt(document.getElementById('add-x2').value) || 0;
    ev.y2 = parseInt(document.getElementById('add-y2').value) || 0;
    ev.duration_ms = parseInt(document.getElementById('add-duration').value) || 300;
  } else if (type === 'keyevent') {
    ev.code = parseInt(document.getElementById('add-code').value) || 0;
  } else if (type === 'text') {
    ev.content = document.getElementById('add-content').value || '';
  } else if (type === 'adb') {
    ev.action = document.getElementById('add-action').value;
    if (ev.action === 'wifi-connect') {
      ev.ssid = document.getElementById('add-wifi-ssid').value || '';
      ev.password = document.getElementById('add-wifi-password').value || '';
      ev.security = 'wpa2';
    } else if (ev.action === 'open-schema') {
      ev.content = document.getElementById('add-schema-content').value || '';
    } else if (ev.action === 'install') {
      ev.content = document.getElementById('add-install-content').value || '';
    } else {
      ev.package = document.getElementById('add-package').value || '';
    }
  } else if (type === 'click' || type === 'dblclick' || type === 'rclick' || type === 'rightclick') {
    ev.x = parseInt(document.getElementById('add-x').value) || 0;
    ev.y = parseInt(document.getElementById('add-y').value) || 0;
  } else if (type === 'navigate') {
    ev.url = document.getElementById('add-url').value || '';
    ev.value = ev.url;
  } else if (type === 'type') {
    ev.content = document.getElementById('add-content').value || '';
  } else if (type === 'keyboard' || type === 'hotkey') {
    const keysStr = document.getElementById('add-keys').value || '';
    ev.keys = keysStr.split(',').map(k => k.trim()).filter(k => k);
  } else if (type === 'scroll') {
    ev.x = parseInt(document.getElementById('add-x').value) || 0;
    ev.y = parseInt(document.getElementById('add-y').value) || 0;
    ev.delta_y = parseInt(document.getElementById('add-delta-y').value) || -200;
  } else if (type === 'hover' || type === 'move') {
    ev.x = parseInt(document.getElementById('add-x').value) || 0;
    ev.y = parseInt(document.getElementById('add-y').value) || 0;
  } else if (type === 'drag') {
    ev.x1 = parseInt(document.getElementById('add-x1').value) || 0;
    ev.y1 = parseInt(document.getElementById('add-y1').value) || 0;
    ev.x2 = parseInt(document.getElementById('add-x2').value) || 0;
    ev.y2 = parseInt(document.getElementById('add-y2').value) || 0;
  } else if (type === 'select') {
    ev.selector = document.getElementById('add-selector').value || '';
    ev.value = document.getElementById('add-value').value || '';
  } else if (type === 'check') {
    ev.selector = document.getElementById('add-selector').value || '';
  } else if (type === 'wait') {
    ev.duration_ms = parseInt(document.getElementById('add-wait-ms').value) || 1000;
  } else if (type === 'launch' || type === 'quit') {
    ev.target = document.getElementById('add-target').value || '';
  } else if (type === 'tips') {
    ev.content = document.getElementById('add-tips-content').value || '';
  }

  // 插入到选中位置之后，或末尾
  const insertAt = state.selectedIndex >= 0 ? state.selectedIndex + 1 : state.events.length;
  state.events.splice(insertAt, 0, ev);
  state.isDirty = true;

  closeAddModal();
  updateStats();
  renderEventList();
  renderCanvas();
  selectEvent(insertAt);
}
