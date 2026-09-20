/**
 * ADB Replay 事件默认值配置
 * 
 * 所有时间字段的默认值集中在此配置。
 * 各事件类型的 delay_before_ms 和 delay_after_ms 统一在此定义。
 * 修改默认值只需编辑本文件即可。
 */

const EVENT_DEFAULTS = {
  // ===== 通用默认值 =====
  // 所有事件类型共享的前延迟（毫秒）
  delay_before_ms: 5000,

  // ===== 各事件类型的后延迟（毫秒，下限 5000）=====
  delay_after_ms: {
    tap:       5000,
    multitap:  5000,
    swipe:     5000,
    keyevent:  5000,
    text:      5000,
    tips:      0,
    adb: {
      'force-stop': 5000,
      'clear':      5000,
      'restart':    10000,
      'launch':     8000,
      'clear-all':  5000,
      'lock-screen': 5000,
      'wifi-connect': 15000,
      'open-schema': 5000,
      'uninstall':  5000,
      'install':    15000,
      '_default':   5000,
    },
    '_default': 5000,
  },

  // ===== swipe 专属 =====
  duration_ms: 500,

  // ===== keyevent 专属 =====
  key_code: 3,  // HOME

  // ===== adb 专属 =====
  adb_action: 'force-stop',

  // ===== tap 专属 =====
  // 无额外字段，使用屏幕分辨率中心点

  // ===== text 专属 =====
  text_content: '',

  // ===== tips 专属 =====
  tips_content: '',
};

/**
 * 获取指定事件类型的后延迟默认值
 * @param {string} type - 事件类型 (tap/swipe/keyevent/text/adb)
 * @param {string} [action] - ADB 操作类型 (force-stop/clear/restart/clear-all)
 * @returns {number} 后延迟默认值（毫秒）
 */
function getDelayAfterDefault(type, action) {
  const config = EVENT_DEFAULTS.delay_after_ms;
  if (type === 'adb' && action) {
    return (config.adb && config.adb[action]) || config.adb._default || config._default;
  }
  return (config[type]) || config._default;
}

/**
 * 获取指定事件类型的前延迟默认值
 * @returns {number} 前延迟默认值（毫秒）
 */
function getDelayBeforeDefault() {
  return EVENT_DEFAULTS.delay_before_ms;
}
