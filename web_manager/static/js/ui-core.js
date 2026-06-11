/* Shared UI core — theme toggle, lang switcher utilities.
   Source: tool-pages-theme/assets/shared/ui-core.js (verbatim copy) */
(function () {
  if (window.SharedUiCore) return;

  function getPreferredTheme() {
    var saved = localStorage.getItem('theme');
    if (saved === 'dark' || saved === 'light') return saved;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  }

  function themeToggleMarkup(themeButtonId) {
    var id = themeButtonId || 'btn-theme';
    return '' +
      '<button id="' + id + '" class="theme-toggle" type="button" aria-label="Toggle theme" title="Toggle theme" aria-pressed="false">' +
      '<span class="theme-icon sun" aria-hidden="true"><svg viewBox="0 0 24 24" role="presentation" focusable="false"><path d="M12 4.75a.75.75 0 0 1 .75-.75h0a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-.75.75h0a.75.75 0 0 1-.75-.75zm0 13a.75.75 0 0 1 .75-.75h0a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-.75.75h0a.75.75 0 0 1-.75-.75zM5.97 6.78a.75.75 0 0 1 1.06 0l1.06 1.06a.75.75 0 1 1-1.06 1.06L5.97 7.84a.75.75 0 0 1 0-1.06zm9.9 9.9a.75.75 0 0 1 1.06 0l1.06 1.06a.75.75 0 1 1-1.06 1.06l-1.06-1.06a.75.75 0 0 1 0-1.06zM4.75 12a.75.75 0 0 1 .75-.75H7a.75.75 0 0 1 0 1.5H5.5a.75.75 0 0 1-.75-.75zm13.5 0a.75.75 0 0 1 .75-.75h1.5a.75.75 0 0 1 0 1.5H19a.75.75 0 0 1-.75-.75zM6.78 18.03a.75.75 0 0 1 0-1.06l1.06-1.06a.75.75 0 1 1 1.06 1.06l-1.06 1.06a.75.75 0 0 1-1.06 0zm9.9-9.9a.75.75 0 0 1 0-1.06l1.06-1.06a.75.75 0 0 1 1.06 1.06l-1.06 1.06a.75.75 0 0 1-1.06 0z"></path><circle cx="12" cy="12" r="3.75"></circle></svg></span>' +
      '<span class="theme-track" aria-hidden="true"><span class="theme-thumb"></span></span>' +
      '<span class="theme-icon moon" aria-hidden="true"><svg viewBox="0 0 24 24" role="presentation" focusable="false"><path d="M14.5 3.5a.75.75 0 0 1 .92-.73 8.75 8.75 0 1 1-10.65 10.65.75.75 0 0 1 .73-.92A7.25 7.25 0 0 0 14.5 3.5z"></path></svg></span>' +
      '</button>';
  }

  function ensureThemeToggleMarkup(config) {
    var opts = config || {};
    var themeButtonId = opts.themeButtonId || 'btn-theme';
    var existing = document.getElementById(themeButtonId);
    if (existing) return existing;

    var host = null;
    if (opts.hostElement && opts.hostElement.nodeType === 1) host = opts.hostElement;
    else host = document.querySelector(opts.hostSelector || '[data-theme-toggle-host]');
    if (!host) return null;

    host.innerHTML = themeToggleMarkup(themeButtonId);
    return document.getElementById(themeButtonId);
  }

  function applyBodyTheme(theme) {
    var isDark = theme === 'dark';
    document.body.classList.toggle('dark', isDark);
    document.documentElement.classList.toggle('dark', isDark);
  }

  function setThemeForDocument(theme, options) {
    var opts = options || {};
    var resolved = theme === 'light' ? 'light' : 'dark';

    applyBodyTheme(resolved);

    if (opts.syncDataTheme !== false) {
      document.documentElement.setAttribute('data-theme', resolved);
    }

    var button = document.getElementById(opts.themeButtonId || 'btn-theme');
    if (button) {
      button.setAttribute('aria-pressed', String(resolved === 'dark'));
      button.setAttribute('title', resolved === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
      button.setAttribute('aria-label', resolved === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    }

    return resolved;
  }

  function toggleThemeValue(theme) {
    return theme === 'dark' ? 'light' : 'dark';
  }

  function animateThemeButton(button, duration) {
    if (!button) return;
    var ms = Number.isFinite(duration) ? duration : 420;
    button.classList.remove('is-animating');
    void button.offsetWidth;
    button.classList.add('is-animating');
    window.setTimeout(function () {
      button.classList.remove('is-animating');
    }, ms);
  }

  function initThemeToggle(config) {
    var opts = config || {};
    var buttonId = opts.themeButtonId || 'btn-theme';
    var themeButton = ensureThemeToggleMarkup({ themeButtonId: buttonId, hostSelector: opts.hostSelector, hostElement: opts.hostElement });
    if (!themeButton) return;

    var initial = getPreferredTheme();
    setThemeForDocument(initial, { themeButtonId: buttonId, syncDataTheme: opts.syncDataTheme !== false });

    if (themeButton.dataset.themeToggleBound === 'true') return;
    themeButton.dataset.themeToggleBound = 'true';

    themeButton.addEventListener('click', function (event) {
      if (opts.preventBubble !== false) event.stopPropagation();
      var current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
      var next = toggleThemeValue(current);
      try { localStorage.setItem('theme', next); } catch (_e) {}
      animateThemeButton(themeButton, Number.isFinite(opts.animationMs) ? opts.animationMs : 420);
      var applied = setThemeForDocument(next, { themeButtonId: buttonId, syncDataTheme: opts.syncDataTheme !== false });
      if (typeof opts.onThemeChange === 'function') opts.onThemeChange(applied);
    });
  }

  window.SharedUiCore = {
    getPreferredTheme: getPreferredTheme,
    applyBodyTheme: applyBodyTheme,
    setThemeForDocument: setThemeForDocument,
    toggleThemeValue: toggleThemeValue,
    animateThemeButton: animateThemeButton,
    initThemeToggle: initThemeToggle,
  };
})();
