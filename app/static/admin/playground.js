(function () {
  const root = document.getElementById('playground-root');
  if (!root) {
    return;
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function setError(node, message) {
    if (!node) return;
    if (!message) {
      node.hidden = true;
      node.textContent = '';
      return;
    }
    node.hidden = false;
    node.textContent = message;
  }

  function formatPayload(payload) {
    return JSON.stringify(payload, null, 2);
  }

  function parseResponseError(status, payload) {
    if (!payload) {
      return `HTTP ${status}`;
    }
    if (typeof payload === 'string') {
      return `HTTP ${status}: ${payload}`;
    }
    const message = payload.message || payload.detail || 'Request failed';
    return `HTTP ${status}: ${message}\n${formatPayload(payload)}`;
  }

  async function requestJson(url, options) {
    const response = await fetch(url, options);
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await response.json() : await response.text();

    if (!response.ok) {
      throw new Error(parseResponseError(response.status, payload));
    }
    return payload;
  }

  function boolFromSelect(value) {
    return String(value).toLowerCase() === 'true';
  }

  function cleanOptional(value) {
    const trimmed = value.trim();
    return trimmed.length ? trimmed : null;
  }

  function setSubtab(groupId, selector, onSelect) {
    const container = byId(groupId);
    if (!container) return;
    const buttons = container.querySelectorAll(selector);
    buttons.forEach((button) => {
      button.addEventListener('click', function () {
        buttons.forEach((item) => item.classList.remove('active'));
        button.classList.add('active');
        onSelect(button);
      });
    });
  }

  // Chat mode
  const chatForm = byId('chat-form');
  const chatPreviewBtn = byId('chat-preview-btn');
  const chatResetBtn = byId('chat-reset-btn');
  const chatDeleteTestDataBtn = byId('chat-delete-test-data-btn');
  const chatFormError = byId('chat-form-error');
  const chatContextError = byId('chat-context-error');
  const chatResultError = byId('chat-result-error');
  const chatDeleteStatus = byId('chat-delete-status');

  const chatContextOutput = byId('chat-context-output');
  const chatRoute = byId('chat-route');
  const chatShouldReply = byId('chat-should-reply');
  const chatReplyText = byId('chat-reply-text');
  const chatResultRaw = byId('chat-result-raw');
  const chatResultView = byId('chat-result-view');

  let chatContext = null;
  let chatResult = null;
  let isDeletingChatTestData = false;

  function clearChatOutputs() {
    chatContext = null;
    chatResult = null;
    renderChatContext('global_recent');
    renderChatResult();
  }

  function getChatPayload() {
    const form = new FormData(chatForm);
    const streamId = String(form.get('stream_id') || '').trim();
    const username = String(form.get('username') || '').trim();
    const text = String(form.get('text') || '').trim();

    if (!streamId || !username || !text) {
      throw new Error('stream_id, username and text are required.');
    }

    return {
      stream_id: streamId,
      username,
      text,
      mentions_bot: boolFromSelect(form.get('mentions_bot')),
      role: String(form.get('role') || 'viewer'),
      channel: cleanOptional(String(form.get('channel') || '')),
      message_id: cleanOptional(String(form.get('message_id') || '')),
      reply_to_message_id: cleanOptional(String(form.get('reply_to_message_id') || '')),
      reply_to_username: cleanOptional(String(form.get('reply_to_username') || '')),
      reply_to_text: cleanOptional(String(form.get('reply_to_text') || '')),
      is_mod: boolFromSelect(form.get('is_mod')),
      is_broadcaster: boolFromSelect(form.get('is_broadcaster')),
    };
  }

  function renderChatContext(tabName) {
    if (!chatContext) {
      chatContextOutput.textContent = 'No preview yet.';
      return;
    }
    const value = chatContext[tabName];
    if (Array.isArray(value)) {
      chatContextOutput.textContent = value.join('\n') || '(empty)';
      return;
    }
    chatContextOutput.textContent = value || '(empty)';
  }

  function renderChatResult() {
    if (!chatResult) {
      chatRoute.textContent = '—';
      chatShouldReply.textContent = '—';
      chatReplyText.textContent = '—';
      chatResultRaw.textContent = 'No result yet.';
      return;
    }
    chatRoute.textContent = String(chatResult.route ?? '');
    chatShouldReply.textContent = String(chatResult.should_reply ?? '');
    chatReplyText.textContent = String(chatResult.reply_text ?? '');
    chatResultRaw.textContent = formatPayload(chatResult);
  }

  if (chatForm && chatPreviewBtn) {
    function updateDeleteTestDataButtonState() {
      const streamField = chatForm.elements.namedItem('stream_id');
      const streamId = String(streamField?.value || '').trim();
      chatDeleteTestDataBtn.disabled = !streamId || isDeletingChatTestData;
    }

    chatPreviewBtn.addEventListener('click', async function () {
      setError(chatFormError, '');
      setError(chatContextError, '');
      try {
        const payload = getChatPayload();
        const params = new URLSearchParams({
          stream_id: payload.stream_id,
          username: payload.username,
          text: payload.text,
        });
        chatContext = await requestJson(`${root.dataset.contextEndpoint}?${params.toString()}`);
        renderChatContext('global_recent');
      } catch (error) {
        setError(chatContextError, error.message || 'Failed to preview context.');
      }
    });

    chatForm.addEventListener('submit', async function (event) {
      event.preventDefault();
      setError(chatFormError, '');
      setError(chatResultError, '');
      try {
        const payload = getChatPayload();
        chatResult = await requestJson(root.dataset.chatEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        renderChatResult();
      } catch (error) {
        setError(chatResultError, error.message || 'Failed to run chat reply.');
      }
    });

    chatResetBtn.addEventListener('click', function () {
      chatForm.reset();
      clearChatOutputs();
      setError(chatFormError, '');
      setError(chatContextError, '');
      setError(chatResultError, '');
      setError(chatDeleteStatus, '');
      updateDeleteTestDataButtonState();
    });

    chatForm.elements.namedItem('stream_id').addEventListener('input', function () {
      updateDeleteTestDataButtonState();
    });

    chatDeleteTestDataBtn.addEventListener('click', async function () {
      setError(chatDeleteStatus, '');
      setError(chatFormError, '');
      const streamId = String(chatForm.elements.namedItem('stream_id')?.value || '').trim();
      if (!streamId) {
        return;
      }

      const confirmed = window.confirm(`Delete all Playground test data for stream_id "${streamId}"?`);
      if (!confirmed) {
        return;
      }

      isDeletingChatTestData = true;
      updateDeleteTestDataButtonState();
      try {
        const payload = await requestJson(root.dataset.chatResetStreamEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ stream_id: streamId }),
        });
        clearChatOutputs();
        const deletedCount = payload.deleted_count;
        setError(
          chatDeleteStatus,
          `Deleted Playground test data for "${streamId}"${typeof deletedCount === 'number' ? ` (deleted_count: ${deletedCount})` : ''}.`
        );
      } catch (error) {
        setError(chatFormError, error.message || 'Failed to delete test data.');
      } finally {
        isDeletingChatTestData = false;
        updateDeleteTestDataButtonState();
      }
    });

    setSubtab('chat-context-tabs', 'button[data-context-tab]', function (button) {
      renderChatContext(button.dataset.contextTab);
    });

    setSubtab('chat-result-tabs', 'button[data-result-tab]', function (button) {
      const showRaw = button.dataset.resultTab === 'raw';
      chatResultView.hidden = showRaw;
      chatResultRaw.hidden = !showRaw;
    });

    updateDeleteTestDataButtonState();
  }

  // Dynamic mode
  const dynamicForm = byId('dynamic-form');
  const dynamicPromptSelect = byId('dynamic-prompt-select');
  const dynamicData = byId('dynamic-data');
  const dynamicResetBtn = byId('dynamic-reset-btn');
  const dynamicPayloadTemplate = byId('dynamic-payload-template');
  const dynamicCopyTemplateBtn = byId('dynamic-copy-template-btn');
  const dynamicCopyStatus = byId('dynamic-copy-status');

  const dynamicFormError = byId('dynamic-form-error');
  const dynamicMetaError = byId('dynamic-meta-error');
  const dynamicResultError = byId('dynamic-result-error');

  const dynamicRequired = byId('dynamic-required-fields');
  const dynamicSystem = byId('dynamic-system-prompt');
  const dynamicTemplate = byId('dynamic-template-prompt');

  const dynamicResult = byId('dynamic-result');
  const dynamicMessage = byId('dynamic-message');
  const dynamicResultRaw = byId('dynamic-result-raw');
  const dynamicResultView = byId('dynamic-result-view');

  let dynamicPromptMeta = null;
  let dynamicRunPayload = null;
  let dynamicDataSkeleton = {};

  function getRequiredDataFields() {
    if (!dynamicPromptMeta) {
      return [];
    }
    if (Array.isArray(dynamicPromptMeta.required_data_fields)) {
      return dynamicPromptMeta.required_data_fields;
    }
    return (dynamicPromptMeta.required_fields || []).filter((field) => field !== 'user');
  }

  function renderDynamicMeta() {
    if (!dynamicPromptMeta) {
      dynamicRequired.textContent = '—';
      dynamicSystem.textContent = 'No prompt selected.';
      dynamicTemplate.textContent = 'No prompt selected.';
      return;
    }

    dynamicRequired.textContent = getRequiredDataFields().length
      ? getRequiredDataFields().join(', ')
      : '(none)';
    dynamicSystem.textContent = dynamicPromptMeta.system_prompt || '(empty)';
    dynamicTemplate.textContent = dynamicPromptMeta.template_prompt || '(empty)';
  }

  function isDynamicDataFieldRequired(fieldName) {
    return fieldName !== 'user';
  }

  function renderDynamicResult() {
    if (!dynamicRunPayload) {
      dynamicResult.textContent = '—';
      dynamicMessage.textContent = '—';
      dynamicResultRaw.textContent = 'No result yet.';
      return;
    }

    dynamicResult.textContent = String(dynamicRunPayload.result ?? '');
    dynamicMessage.textContent = String(dynamicRunPayload.message ?? '');
    dynamicResultRaw.textContent = formatPayload(dynamicRunPayload);
  }

  function currentDataObject() {
    const raw = dynamicData.value.trim();
    if (!raw) {
      return {};
    }
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('data must be a JSON object.');
      }
      return parsed;
    } catch (error) {
      throw new Error(`Invalid JSON in data: ${error.message}`);
    }
  }

  function optionalNumber(value) {
    const cleaned = cleanOptional(value);
    if (cleaned === null) {
      return null;
    }
    return Number(cleaned);
  }

  function buildDataSkeleton() {
    const skeleton = {};
    getRequiredDataFields().forEach((field) => {
      skeleton[field] = '';
    });
    return skeleton;
  }

  function buildDynamicPayloadTemplate() {
    const form = new FormData(dynamicForm);
    const prompt = String(form.get('prompt') || '').trim();
    const payload = {
      prompt,
      user: '',
      data: dynamicDataSkeleton,
    };

    const llm = {};
    const provider = cleanOptional(String(form.get('provider') || ''));
    const style = cleanOptional(String(form.get('style') || ''));
    const temperature = optionalNumber(String(form.get('temperature') || ''));
    const maxOutputTokens = optionalNumber(String(form.get('max_output_tokens') || ''));

    if (provider) llm.provider = provider;
    if (style) llm.style = style;
    if (temperature !== null) llm.temperature = temperature;
    if (maxOutputTokens !== null) llm.max_output_tokens = maxOutputTokens;

    if (Object.keys(llm).length > 0) {
      payload.llm = llm;
    }

    return payload;
  }

  function renderDynamicPayloadTemplate() {
    dynamicPayloadTemplate.textContent = formatPayload(buildDynamicPayloadTemplate());
  }

  async function loadDynamicPromptNames() {
    const response = await requestJson(root.dataset.dynamicListEndpoint);
    const items = Array.isArray(response.items) ? response.items : [];
    items.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.name;
      option.textContent = item.name;
      dynamicPromptSelect.appendChild(option);
    });
  }

  async function loadDynamicPromptMeta(name) {
    if (!name) {
      dynamicPromptMeta = null;
      dynamicDataSkeleton = {};
      renderDynamicMeta();
      renderDynamicPayloadTemplate();
      return;
    }

    const endpoint = `${root.dataset.dynamicMetaBase}/${encodeURIComponent(name)}`;
    dynamicPromptMeta = await requestJson(endpoint);
    dynamicDataSkeleton = buildDataSkeleton();
    renderDynamicMeta();

    const rawData = dynamicData.value.trim();
    if (rawData === '{}' || rawData === '') {
      dynamicData.value = formatPayload(dynamicDataSkeleton);
    }

    renderDynamicPayloadTemplate();
  }

  function buildDynamicPayload() {
    const form = new FormData(dynamicForm);
    const prompt = String(form.get('prompt') || '').trim();
    const user = String(form.get('user') || '').trim();
    if (!prompt || !user) {
      throw new Error('prompt and user are required.');
    }

    const data = currentDataObject();
    if ('user' in data) {
      throw new Error('data must not contain "user". Use the top-level user field.');
    }

    if (dynamicPromptMeta && Array.isArray(dynamicPromptMeta.required_fields)) {
      const missing = dynamicPromptMeta.required_fields.filter(
        (key) => isDynamicDataFieldRequired(key) && !(key in data)
      );
      if (missing.length) {
        throw new Error(`Missing required fields in data: ${missing.join(', ')}`);
      }
    }

    const llm = {};
    const provider = cleanOptional(String(form.get('provider') || ''));
    const style = cleanOptional(String(form.get('style') || ''));
    const temperatureRaw = cleanOptional(String(form.get('temperature') || ''));
    const maxTokensRaw = cleanOptional(String(form.get('max_output_tokens') || ''));

    if (provider) llm.provider = provider;
    if (style) llm.style = style;
    if (temperatureRaw !== null) llm.temperature = Number(temperatureRaw);
    if (maxTokensRaw !== null) llm.max_output_tokens = Number(maxTokensRaw);

    const payload = { prompt, user, data };
    if (Object.keys(llm).length > 0) {
      payload.llm = llm;
    }
    return payload;
  }

  if (dynamicForm) {
    renderDynamicPayloadTemplate();

    loadDynamicPromptNames().catch((error) => {
      setError(dynamicMetaError, error.message || 'Failed to load dynamic prompt names.');
    });

    dynamicPromptSelect.addEventListener('change', function () {
      setError(dynamicMetaError, '');
      loadDynamicPromptMeta(dynamicPromptSelect.value).catch((error) => {
        setError(dynamicMetaError, error.message || 'Failed to load prompt metadata.');
      });
    });

    ['prompt', 'provider', 'style', 'temperature', 'max_output_tokens'].forEach((name) => {
      const field = dynamicForm.elements.namedItem(name);
      field.addEventListener('input', renderDynamicPayloadTemplate);
      field.addEventListener('change', renderDynamicPayloadTemplate);
    });

    dynamicForm.addEventListener('submit', async function (event) {
      event.preventDefault();
      setError(dynamicFormError, '');
      setError(dynamicResultError, '');
      try {
        const payload = buildDynamicPayload();
        dynamicRunPayload = await requestJson(root.dataset.dynamicEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        renderDynamicResult();
      } catch (error) {
        setError(dynamicResultError, error.message || 'Failed to run dynamic prompt.');
      }
    });

    dynamicResetBtn.addEventListener('click', function () {
      dynamicForm.reset();
      dynamicPromptMeta = null;
      dynamicRunPayload = null;
      dynamicDataSkeleton = {};
      dynamicData.value = '{}';
      renderDynamicMeta();
      renderDynamicResult();
      renderDynamicPayloadTemplate();
      setError(dynamicFormError, '');
      setError(dynamicMetaError, '');
      setError(dynamicResultError, '');
      setError(dynamicCopyStatus, '');
    });

    dynamicCopyTemplateBtn.addEventListener('click', async function () {
      setError(dynamicCopyStatus, '');
      try {
        await navigator.clipboard.writeText(dynamicPayloadTemplate.textContent);
        setError(dynamicCopyStatus, 'Copied.');
      } catch (_) {
        setError(dynamicCopyStatus, 'Copy failed.');
      }
    });

    setSubtab('dynamic-result-tabs', 'button[data-result-tab]', function (button) {
      const showRaw = button.dataset.resultTab === 'raw';
      dynamicResultView.hidden = showRaw;
      dynamicResultRaw.hidden = !showRaw;
    });
  }
})();
