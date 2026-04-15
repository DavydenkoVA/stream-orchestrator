(function () {
  const container = document.getElementById('styles-container');
  const template = document.getElementById('style-template');
  const addStyleBtn = document.getElementById('add-style-btn');
  if (!container || !template || !addStyleBtn) {
    return;
  }

  let nextIndex = Number(container.dataset.nextIndex || '0');

  function bindRemoveButton(node) {
    const removeBtn = node.querySelector('.remove-style');
    if (!removeBtn) {
      return;
    }
    removeBtn.addEventListener('click', () => node.remove());
  }

  container.querySelectorAll('.style-item').forEach(bindRemoveButton);

  addStyleBtn.addEventListener('click', () => {
    const index = nextIndex++;
    const wrapper = document.createElement('div');
    wrapper.innerHTML = template.innerHTML.replaceAll('__S_INDEX__', String(index));
    const node = wrapper.firstElementChild;
    bindRemoveButton(node);
    container.appendChild(node);
    container.dataset.nextIndex = String(nextIndex);
  });
})();
