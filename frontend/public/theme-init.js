// Applies the saved colour theme before first paint, so a light-theme user never sees a dark flash.
// A separate file (not inline) because the CSP allows scripts from 'self' only. Keep in sync with
// src/theme/theme.js (same key, same values).
(function () {
  var theme = 'dark'
  try {
    var saved = localStorage.getItem('swarmind_theme')
    if (saved === 'light' || saved === 'dark') theme = saved
  } catch (e) { /* storage blocked: default theme */ }
  document.documentElement.setAttribute('data-theme', theme)
})()
