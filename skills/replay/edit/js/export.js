// ===== 导出功能 =====

// 导出为 JSON 文件
function exportAsJson() {
  if (!state.events || state.events.length === 0) {
    alert('没有事件数据可导出');
    return;
  }

  const exportData = {
    device: state.device,
    resolution: state.resolution,
    events: state.events.map(ev => {
      const copy = {...ev};
      delete copy.screenshots;
      return copy;
    }),
  };

  const jsonStr = JSON.stringify(exportData, null, 2);
  const blob = new Blob([jsonStr], { type: 'application/json' });
  const url = URL.createObjectURL(blob);

  const a = document.createElement('a');
  a.href = url;
  a.download = `adb-replay-export.json`;
  a.click();

  URL.revokeObjectURL(url);
  alert('✅ JSON 文件已导出');
}

// 导出为 Shell 脚本
function exportAsScript() {
  if (!state.events || state.events.length === 0) {
    alert('没有事件数据可导出');
    return;
  }

  let script = '#!/bin/bash\n\n';
  script += '# ADB Replay Shell Script\n';
  script += `# Device: ${state.device}\n`;
  script += `# Resolution: ${state.resolution[0]}x${state.resolution[1]}\n`;
  script += `# Events: ${state.events.length}\n\n`;
  script += 'echo "Starting ADB replay..."\n\n';

  state.events.forEach((event, index) => {
    script += `# Event ${index + 1}: ${event.type}${event.name ? ' - ' + event.name : ''}\n`;

    const delayBefore = event.delay_before_ms || event.delay_ms || EVENT_DEFAULTS.delay_before_ms;
    if (delayBefore > 0) {
      script += `sleep ${(delayBefore / 1000).toFixed(2)}\n`;
    }

    switch (event.type) {
      case 'tap':
        script += `adb shell input tap ${event.x} ${event.y}\n`;
        break;
      case 'multitap':
        script += `for i in $(seq 1 ${event.count || 2}); do\n`;
        script += `  adb shell input tap ${event.x} ${event.y}\n`;
        script += `done\n`;
        break;
      case 'swipe':
script += `adb shell input swipe ${event.x1} ${event.y1} ${event.x2} ${event.y2} ${event.duration_ms || 300}\n`;
        break;
      case 'keyevent':
        script += `adb shell input keyevent ${event.code}\n`;
        break;
      case 'text':
        script += `adb shell input text "${event.content}"\n`;
        break;
      case 'adb':
        if (event.action === 'wifi-connect') {
          script += `adb shell cmd wifi connect-network "${event.ssid || ''}" ${event.security || 'wpa2'} "${event.password || ''}"\n`;
        } else if (event.action === 'lock-screen') {
          script += `# 检测屏幕状态，亮屏则锁屏\n`;
          script += `if adb shell dumpsys deviceidle | grep -q 'mScreenOn=true'; then\n`;
          script += `  adb shell input keyevent 26\n`;
          script += `fi\n`;
        } else if (event.action === 'launch') {
          script += `adb shell monkey -p ${event.package || ''} -c android.intent.category.LAUNCHER 1\n`;
        } else {
          script += `adb shell ${event.action} ${event.package || ''}\n`;
        }
        break;
      case 'tips':
        script += `echo "💡 ${event.content || ''}"\n`;
        script += `read -p "按回车继续..."\n`;
        break;
    }

    const delayAfter = event.delay_after_ms || getDelayAfterDefault(event.type, event.action);
    if (delayAfter > 0) {
      script += `sleep ${(delayAfter / 1000).toFixed(2)}\n`;
    }
    script += '\n';
  });

  script += 'echo "ADB replay completed!"\n';

  const blob = new Blob([script], { type: 'text/x-shellscript' });
  const url = URL.createObjectURL(blob);

  const a = document.createElement('a');
  a.href = url;
  a.download = `adb-replay.sh`;
  a.click();

  URL.revokeObjectURL(url);
  alert('✅ Shell 脚本已导出');
}

// 导出为 ZIP 包（JSON + Shell）
function exportToZip() {
  alert('ZIP 导出功能暂未实现');
}

// 生成视频演示（占位）
function generateVideo() {
  alert('视频生成功能暂未实现');
}

// 导出收藏夹
function exportFavorites() {
  const favorites = JSON.parse(localStorage.getItem('adb-replay-favorites') || '[]');
  if (favorites.length === 0) {
    alert('没有收藏数据可导出');
    return;
  }

  const jsonStr = JSON.stringify(favorites, null, 2);
  const blob = new Blob([jsonStr], { type: 'application/json' });
  const url = URL.createObjectURL(blob);

  const a = document.createElement('a');
  a.href = url;
  a.download = `adb-replay-favorites.json`;
  a.click();

  URL.revokeObjectURL(url);
  alert('✅ 收藏夹已导出');
}

// 辅助函数
function calculateTotalDuration() {
  return (state.events.reduce((sum, event) => {
return sum + (event.delay_before_ms || event.delay_ms || EVENT_DEFAULTS.delay_before_ms) + (event.delay_after_ms || getDelayAfterDefault(event.type, event.action));
  }, 0) / 1000).toFixed(1);
}

function getEventDescription(event) {
  switch (event.type) {
    case 'tap':
      return `点击坐标 (${event.x}, ${event.y})`;
    case 'multitap':
      return `连续点击坐标 (${event.x}, ${event.y}) ${event.count || 2} 次`;
    case 'swipe':
      return `从 (${event.x1}, ${event.y1}) 滑动到 (${event.x2}, ${event.y2})`;
    case 'keyevent':
      return `按键事件: ${event.code}`;
    case 'text':
      return `文本输入: "${event.content}"`;
    case 'adb':
      return event.action === 'wifi-connect' ? `连接 WiFi: ${event.ssid || ''}` : event.action === 'open-schema' ? `打开 Schema: ${event.content || ''}` : event.action === 'lock-screen' ? '🔒 锁屏（检测屏幕状态后锁定）' : event.action === 'launch' ? `拉起应用: ${event.package || ''}` : event.action === 'uninstall' ? `卸载应用: ${event.package || ''}` : event.action === 'install' ? `安装 APK: ${event.content || ''}` : `ADB 命令: ${event.action} ${event.package || ''}`;
    case 'tips':
      return `提示: "${event.content || ''}"`;
    default:
      return event.type;
  }
}

function getEventCommand(event) {
  switch (event.type) {
    case 'tap':
      return `adb shell input tap ${event.x} ${event.y}`;
    case 'multitap':
      return `adb shell input tap ${event.x} ${event.y} ×${event.count || 2}`;
    case 'swipe':
return `adb shell input swipe ${event.x1} ${event.y1} ${event.x2} ${event.y2} ${event.duration_ms || 300}`;
    case 'keyevent':
      return `adb shell input keyevent ${event.code}`;
    case 'text':
      return `adb shell input text "${event.content}"`;
    case 'adb':
      if (event.action === 'wifi-connect') {
        return `adb shell cmd wifi connect-network "${event.ssid || ''}" ${event.security || 'wpa2'} "${event.password || ''}"`;
      }
      if (event.action === 'open-schema') {
        return `adb shell am start -a android.intent.action.VIEW -d "${event.content || ''}" -f 0x14000000`;
      }
      if (event.action === 'lock-screen') {
        return `adb shell dumpsys deviceidle | grep -q 'mScreenOn=true' && adb shell input keyevent 26`;
      }
      if (event.action === 'launch') {
        return `adb shell monkey -p ${event.package || ''} -c android.intent.category.LAUNCHER 1`;
      }
      if (event.action === 'uninstall') {
        return `adb uninstall ${event.package || ''}`;
      }
      if (event.action === 'install') {
        return `adb install -r ${event.content || ''}`;
      }
      return `adb shell ${event.action} ${event.package || ''}`;
    case 'tips':
      return `echo "${event.content || ''}" && read`;
    default:
      return `Unknown command for ${event.type}`;
  }
}