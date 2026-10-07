/* global window, document, setTimeout */
// Shared by the upload-form mocks: reveal the form after a file is set (like the real pages), record clicks on
// the publish button, and report what the page holds.
window.__clicked = false;
window.__reveal = (input, id, key) => {
  input.addEventListener('change', () => {
    window[key || '__file'] = input.files[0] && input.files[0].name;
    if (id) setTimeout(() => (document.getElementById(id).style.display = 'block'), 300);
  });
};
window.__text = (sel) => {
  const el = document.querySelector(sel);
  return el ? (el.value !== undefined && el.tagName === 'INPUT' ? el.value : el.innerText) : null;
};
