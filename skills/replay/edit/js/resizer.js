// 三栏拖拽调整宽度（不持久化，刷新后恢复默认）
(function () {
  function makeResizable(id, varName, minW, dir) {
    const resizer = document.getElementById(id);
    const app = document.querySelector('.app');
    if (!resizer || !app) return;

    function currentWidth() {
      const v = getComputedStyle(app).getPropertyValue(varName).trim();
      const n = parseInt(v, 10);
      return isNaN(n) ? 500 : n;
    }

    resizer.addEventListener('mousedown', function (e) {
      e.preventDefault();
      const startX = e.clientX;
      const startW = currentWidth();
      resizer.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';

      function onMove(ev) {
        const dx = ev.clientX - startX;
        const newW = Math.max(minW, startW + dx * dir);
        app.style.setProperty(varName, newW + 'px');
      }

      function onUp() {
        resizer.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        // 拖拽结束后重算手机框尺寸
        if (typeof fitPhoneFrame === 'function') fitPhoneFrame();
      }

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  // 左分隔条：向右拖 → 左栏变宽
  makeResizable('resizer-left', '--left-w', 500, 1);
  // 右分隔条：向左拖 → 右栏变宽
  makeResizable('resizer-right', '--right-w', 400, -1);

  // 窗口尺寸变化时重算手机框
  window.addEventListener('resize', function () {
    if (typeof fitPhoneFrame === 'function') fitPhoneFrame();
  });
})();
