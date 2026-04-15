let providerIndex = 0;
let featureIndex = 0;

function htmlFromTemplate(templateId, replacements) {
  let html = document.getElementById(templateId).innerHTML;
  for (const [key, value] of Object.entries(replacements)) {
    html = html.replaceAll(key, value ?? "");
  }
  return html;
}

function addProvider(provider = { name: "", provider: "", models: [] }) {
  const currentIndex = providerIndex++;
  const container = document.getElementById("providers-container");
  const wrapper = document.createElement("div");
  wrapper.innerHTML = htmlFromTemplate("provider-template", {
    __P_INDEX__: String(currentIndex),
    __P_NAME__: provider.name,
    __P_TYPE__: provider.provider,
  });
  const node = wrapper.firstElementChild;
  container.appendChild(node);

  const modelsContainer = node.querySelector(".models-container");
  const addModelButton = node.querySelector(".add-model");

  let modelIndex = 0;
  function addModel(model = { name: "", api_key: "", base_url: "", model: "" }) {
    const currentModelIndex = modelIndex++;
    const modelWrap = document.createElement("div");
    modelWrap.innerHTML = htmlFromTemplate("model-template", {
      __P_INDEX__: String(currentIndex),
      __M_INDEX__: String(currentModelIndex),
      __M_NAME__: model.name,
      __M_API__: model.api_key,
      __M_BASE__: model.base_url,
      __M_MODEL__: model.model,
    });
    const modelNode = modelWrap.firstElementChild;
    modelNode
      .querySelector(".remove-model")
      .addEventListener("click", () => modelNode.remove());
    modelsContainer.appendChild(modelNode);
  }

  addModelButton.addEventListener("click", () => addModel());
  node
    .querySelector(".remove-provider")
    .addEventListener("click", () => node.remove());

  if (provider.models && provider.models.length) {
    provider.models.forEach(addModel);
  } else {
    addModel();
  }
}

function addFeature(
  feature = {
    name: "",
    provider: "",
    temperature: "0.7",
    max_output_tokens: "200",
    style: "default",
  }
) {
  const currentIndex = featureIndex++;
  const container = document.getElementById("features-container");
  const wrapper = document.createElement("div");
  wrapper.innerHTML = htmlFromTemplate("feature-template", {
    __F_INDEX__: String(currentIndex),
    __F_NAME__: feature.name,
    __F_PROVIDER__: feature.provider,
    __F_TEMP__: String(feature.temperature ?? ""),
    __F_TOKENS__: String(feature.max_output_tokens ?? ""),
    __F_STYLE__: feature.style,
  });
  const node = wrapper.firstElementChild;
  node
    .querySelector(".remove-feature")
    .addEventListener("click", () => node.remove());
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
