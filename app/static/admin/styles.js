(function () {
  const initial = window.STYLES_INITIAL?.styles ?? [];
  const container = document.getElementById('styles-container');
  const template = document.getElementById('style-template');
  const addStyleBtn = document.getElementById('add-style-btn');
  let styleIndex = 0;

  function escapeHtml(value) {
    return String(value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function renderStyle(style) {
    const index = styleIndex++;
    const isDefault = String(style.key || '').toLowerCase() === 'default';
    let html = template.innerHTML;
    html = html.replaceAll('__S_INDEX__', String(index));
    html = html.replaceAll('__S_NAME__', escapeHtml(style.key || ''));
    html = html.replaceAll('__S_TITLE__', escapeHtml(style.title || ''));
    html = html.replaceAll('__S_INSTRUCTION__', escapeHtml(style.instruction || ''));
    html = html.replaceAll('__S_NAME_READONLY__', isDefault ? 'readonly' : '');
    html = html.replaceAll('__S_SYSTEM__', isDefault ? 'default' : '');
    html = html.replaceAll(
      '__S_REMOVE_BUTTON__',
      isDefault ? '' : '<button type="button" class="remove-style">Remove style</button>'
    );

    const wrapper = document.createElement('div');
    wrapper.innerHTML = html;
    const node = wrapper.firstElementChild;
    const removeBtn = node.querySelector('.remove-style');
    if (removeBtn) {
      removeBtn.addEventListener('click', () => node.remove());
    }
    container.appendChild(node);
  }

  initial.forEach(renderStyle);

  addStyleBtn.addEventListener('click', () => {
    renderStyle({ key: '', title: '', instruction: '' });
  });
})();
