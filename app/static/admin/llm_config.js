let providerIndex = 0;
let featureIndex = 0;

const providerTypeOptions = window.LLM_CONFIG_INITIAL?.providerTypeOptions ?? [];
const globalStyleOptions = window.LLM_CONFIG_INITIAL?.styleOptions ?? [];
const initialProviderOptions = window.LLM_CONFIG_INITIAL?.providerOptions ?? [];

function htmlFromTemplate(templateId, replacements) {
  let html = document.getElementById(templateId).innerHTML;
  for (const [key, value] of Object.entries(replacements)) {
    html = html.replaceAll(key, value ?? "");
  }
  return html;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function buildOptions(options, selectedValue = "", placeholder = null) {
  const rendered = [];
  if (placeholder !== null) {
    rendered.push(`<option value="">${escapeHtml(placeholder)}</option>`);
  }

  options.forEach((optionValue) => {
    const selected = optionValue === selectedValue ? ' selected' : '';
    rendered.push(`<option value="${escapeHtml(optionValue)}"${selected}>${escapeHtml(optionValue)}</option>`);
  });
  return rendered.join('');
}

function collectProviderNames() {
  const names = [];
  document.querySelectorAll('.provider-item .provider-name-input').forEach((input) => {
    const value = String(input.value || '').trim();
    if (value && !names.includes(value)) {
      names.push(value);
    }
  });
  return names;
}

function syncFeatureProviderOptions() {
  const providerNames = collectProviderNames();
  document.querySelectorAll('.feature-provider-select').forEach((select) => {
    const currentValue = select.dataset.currentValue || select.value || '';
    select.innerHTML = buildOptions(providerNames, currentValue, '-- select provider --');
    const hasCurrentValue = providerNames.includes(currentValue);
    if (!hasCurrentValue) {
      select.value = '';
      select.dataset.currentValue = '';
      return;
    }
    select.value = currentValue;
    select.dataset.currentValue = currentValue;
  });
}

function bindTemperaturePreview(node) {
  const rangeInput = node.querySelector('.temperature-range');
  const valueNode = node.querySelector('.temperature-value');
  if (!rangeInput || !valueNode) {
    return;
  }

  const render = () => {
    valueNode.textContent = Number(rangeInput.value).toFixed(2);
  };

  rangeInput.addEventListener('input', render);
  rangeInput.addEventListener('change', render);
  render();
}

function addProvider(provider = { name: '', provider: providerTypeOptions[0] ?? '', models: [] }) {
  const currentIndex = providerIndex++;
  const container = document.getElementById('providers-container');
  const wrapper = document.createElement('div');
  wrapper.innerHTML = htmlFromTemplate('provider-template', {
    __P_INDEX__: String(currentIndex),
    __P_NAME__: provider.name,
    __P_TYPE_OPTIONS__: buildOptions(providerTypeOptions, provider.provider),
  });
  const node = wrapper.firstElementChild;
  container.appendChild(node);

  const providerNameInput = node.querySelector(`input[name="providers[${currentIndex}][name]"]`);
  const modelsContainer = node.querySelector('.models-container');
  const addModelButton = node.querySelector('.add-model');

  let modelIndex = 0;
  function addModel(model = { name: '', api_key: '', base_url: '', model: '' }) {
    const currentModelIndex = modelIndex++;
    const modelWrap = document.createElement('div');
    modelWrap.innerHTML = htmlFromTemplate('model-template', {
      __P_INDEX__: String(currentIndex),
      __M_INDEX__: String(currentModelIndex),
      __M_NAME__: model.name,
      __M_API__: model.api_key,
      __M_BASE__: model.base_url,
      __M_MODEL__: model.model,
    });
    const modelNode = modelWrap.firstElementChild;
    modelNode
      .querySelector('.remove-model')
      .addEventListener('click', () => modelNode.remove());
    modelsContainer.appendChild(modelNode);
  }

  addModelButton.addEventListener('click', () => addModel());
  node
    .querySelector('.remove-provider')
    .addEventListener('click', () => {
      node.remove();
      syncFeatureProviderOptions();
    });

  providerNameInput.addEventListener('input', syncFeatureProviderOptions);
  providerNameInput.addEventListener('change', syncFeatureProviderOptions);

  if (provider.models && provider.models.length) {
    provider.models.forEach(addModel);
  } else {
    addModel();
  }
}

function addFeature(
  feature = {
    name: '',
    provider: '',
    temperature: '0.7',
    max_output_tokens: '200',
    style: 'default',
  }
) {
  const currentIndex = featureIndex++;
  const container = document.getElementById('features-container');
  const wrapper = document.createElement('div');
  wrapper.innerHTML = htmlFromTemplate('feature-template', {
    __F_INDEX__: String(currentIndex),
    __F_NAME__: feature.name,
    __F_PROVIDER_OPTIONS__: buildOptions(
      initialProviderOptions,
      feature.provider ?? '',
      '-- select provider --'
    ),
    __F_TEMP__: String(feature.temperature ?? ''),
    __F_TOKENS__: String(feature.max_output_tokens ?? ''),
    __F_STYLE__: feature.style,
  });
  const node = wrapper.firstElementChild;
  const providerSelect = node.querySelector('.feature-provider-select');
  providerSelect.dataset.currentValue = feature.provider ?? '';
  const styleSelect = node.querySelector('.feature-style-select');
  const styleOptions = Array.isArray(feature.style_options) && feature.style_options.length
    ? feature.style_options
    : globalStyleOptions;
  styleSelect.innerHTML = styleOptions
    .map((item) => {
      const value = String(item.value ?? '');
      const label = String(item.label ?? value);
      const selected = value === String(feature.style ?? '') ? ' selected' : '';
      const cssClass = item.kind === 'missing' ? ' class="style-option-missing"' : '';
      return `<option value="${escapeHtml(value)}"${selected}${cssClass}>${escapeHtml(label)}</option>`;
    })
    .join('');

  bindTemperaturePreview(node);
  container.appendChild(node);
}

const initialProviders = window.LLM_CONFIG_INITIAL?.providers ?? [];
const initialFeatures = window.LLM_CONFIG_INITIAL?.features ?? [];

if (initialProviders.length === 0) {
  addProvider();
} else {
  initialProviders.forEach(addProvider);
}

initialFeatures.forEach(addFeature);
syncFeatureProviderOptions();
