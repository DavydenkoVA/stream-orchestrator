(function () {
  const root = document.getElementById('playground-root');
  if (!root) return;

  function byId(id) { return document.getElementById(id); }
  function formatPayload(payload) { return JSON.stringify(payload, null, 2); }
  function cleanOptional(v) { const t = String(v || '').trim(); return t ? t : null; }
  function boolFromSelect(v) { return String(v).toLowerCase() === 'true'; }

  function setError(node, message) {
    if (!node) return;
    node.hidden = !message;
    node.textContent = message || '';
  }

  async function requestJsonWithResponse(url, options) {
    const response = await fetch(url, options);
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) {
      const message = typeof payload === 'string' ? payload : payload.detail || payload.message || `HTTP ${response.status}`;
      throw new Error(`HTTP ${response.status}: ${message}`);
    }
    return { payload, response };
  }

  async function requestJson(url, options) {
    const { payload } = await requestJsonWithResponse(url, options);
    return payload;
  }

  function setTraceLink(linkNode, traceId) {
    if (!linkNode) return;
    if (!traceId) {
      linkNode.hidden = true;
      linkNode.removeAttribute('href');
      return;
    }
    linkNode.hidden = false;
    linkNode.href = `/traces?run_id=${encodeURIComponent(traceId)}`;
  }

  const saveManagers = [];
  function createPromptAutosave({ scope, nameProvider, part, textarea, statusNode }) {
    const state = { dirty: false, inflight: null };

    function setStatus(text) { if (statusNode) statusNode.textContent = text || ''; }

    async function saveNow() {
      if (!state.dirty) return true;
      if (state.inflight) return state.inflight;
      const name = typeof nameProvider === 'function' ? nameProvider() : null;
      const body = { scope, name, part, content: textarea.value };
      setStatus('Saving...');
      state.inflight = requestJson(root.dataset.promptSaveEndpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }).then(() => {
        state.dirty = false;
        setStatus('Saved');
        return true;
      }).catch((error) => {
        setStatus('Error');
        throw error;
      }).finally(() => {
        state.inflight = null;
      });
      return state.inflight;
    }

    textarea.addEventListener('input', () => {
      state.dirty = true;
      setStatus('Unsaved');
    });
    textarea.addEventListener('blur', () => { saveNow().catch(() => {}); });

    const manager = {
      async flush() { return saveNow(); },
      setClean() { state.dirty = false; setStatus('Saved'); },
      setIdle() { state.dirty = false; setStatus(''); },
    };
    saveManagers.push(manager);
    return manager;
  }

  async function flushPendingSaves() {
    for (const manager of saveManagers) {
      await manager.flush();
    }
  }

  function setSubtab(groupId, selector, onSelect) {
    const container = byId(groupId); if (!container) return;
    const buttons = container.querySelectorAll(selector);
    buttons.forEach((button) => button.addEventListener('click', () => {
      buttons.forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      onSelect(button);
    }));
  }

  // Chat
  const chatForm = byId('chat-form');
  const chatPreviewBtn = byId('chat-preview-btn');
  const chatResetBtn = byId('chat-reset-btn');
  const chatDeleteBtn = byId('chat-delete-test-data-btn');
  const chatContextOutput = byId('chat-context-output');
  const chatFormError = byId('chat-form-error');
  const chatContextError = byId('chat-context-error');
  const chatResultError = byId('chat-result-error');
  const chatDeleteStatus = byId('chat-delete-status');
  const chatTraceLink = byId('chat-trace-link');
  const chatSystemEditor = byId('chat-system-editor');
  const chatTemplateEditor = byId('chat-template-editor');
  let chatContext = null;
  let chatResult = null;

  function getChatPayload() {
    const form = new FormData(chatForm);
    return {
      stream_id: String(form.get('stream_id') || '').trim(),
      username: String(form.get('username') || '').trim(),
      text: String(form.get('text') || '').trim(),
      mentions_bot: boolFromSelect(form.get('mentions_bot')),
      role: String(form.get('role') || 'viewer'),
    };
  }

  function renderChatContext(tabName) {
    if (!chatContext) { chatContextOutput.textContent = 'No preview yet.'; return; }
    const value = chatContext[tabName];
    chatContextOutput.textContent = Array.isArray(value) ? (value.join('\n') || '(empty)') : (value || '(empty)');
  }

  function renderChatResult() {
    byId('chat-route').textContent = chatResult ? String(chatResult.route ?? '') : '—';
    byId('chat-should-reply').textContent = chatResult ? String(chatResult.should_reply ?? '') : '—';
    byId('chat-reply-text').textContent = chatResult ? String(chatResult.reply_text ?? '') : '—';
    byId('chat-result-raw').textContent = chatResult ? formatPayload(chatResult) : 'No result yet.';
  }

  async function loadPromptEditors(scope, mapping) {
    const response = await requestJson(`${root.dataset.promptLoadBase}/${scope}`);
    const items = Array.isArray(response.items) ? response.items : [];
    items.forEach((item) => {
      const node = mapping[item.part];
      if (node) node.value = item.content || '';
    });
  }

  let chatSystemManager = null;
  let chatTemplateManager = null;
  if (chatForm) {
    loadPromptEditors('chat', { system_prompt: chatSystemEditor, user_template: chatTemplateEditor }).catch((e) => setError(chatFormError, e.message));
    chatSystemManager = createPromptAutosave({ scope: 'chat', part: 'system_prompt', textarea: chatSystemEditor, statusNode: byId('chat-system-status') });
    chatTemplateManager = createPromptAutosave({ scope: 'chat', part: 'user_template', textarea: chatTemplateEditor, statusNode: byId('chat-template-status') });
    chatSystemManager.setClean(); chatTemplateManager.setClean();

    chatPreviewBtn.addEventListener('click', async () => {
      setError(chatContextError, '');
      try {
        await flushPendingSaves();
        const payload = getChatPayload();
        const params = new URLSearchParams({ stream_id: payload.stream_id, username: payload.username, text: payload.text });
        chatContext = await requestJson(`${root.dataset.contextEndpoint}?${params.toString()}`);
        renderChatContext('global_recent');
      } catch (error) { setError(chatContextError, error.message || 'Failed to preview context.'); }
    });

    chatForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      setError(chatResultError, ''); setError(chatFormError, '');
      try {
        await flushPendingSaves();
        const { payload, response } = await requestJsonWithResponse(root.dataset.chatEndpoint, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(getChatPayload()),
        });
        chatResult = payload;
        setTraceLink(chatTraceLink, response.headers.get('X-Trace-Id'));
        renderChatResult();
      } catch (error) { setError(chatResultError, error.message || 'Failed to run chat reply.'); }
    });

    chatDeleteBtn.addEventListener('click', async () => {
      const streamId = String(chatForm.elements.namedItem('stream_id').value || '').trim();
      if (!streamId) return;
      const confirmed = window.confirm(`Delete all Playground test data for stream_id "${streamId}"?`);
      if (!confirmed) return;
      try {
        const payload = await requestJson(root.dataset.chatResetStreamEndpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ stream_id: streamId }) });
        setError(chatDeleteStatus, `Deleted Playground test data for "${streamId}" (deleted_count: ${payload.deleted_count || 0}).`);
      } catch (error) { setError(chatFormError, error.message || 'Delete failed.'); }
    });

    chatResetBtn.addEventListener('click', () => {
      chatForm.reset(); chatContext = null; chatResult = null; renderChatContext('global_recent'); renderChatResult(); setTraceLink(chatTraceLink, null);
      setError(chatFormError, ''); setError(chatContextError, ''); setError(chatResultError, ''); setError(chatDeleteStatus, '');
    });

    setSubtab('chat-context-tabs', 'button[data-context-tab]', (button) => renderChatContext(button.dataset.contextTab));
    setSubtab('chat-result-tabs', 'button[data-result-tab]', (button) => {
      const showRaw = button.dataset.resultTab === 'raw';
      byId('chat-result-view').hidden = showRaw; byId('chat-result-raw').hidden = !showRaw;
    });
  }

  // Dynamic
  const dynamicForm = byId('dynamic-form');
  const dynamicPromptSelect = byId('dynamic-prompt-select');
  const dynamicData = byId('dynamic-data');
  const dynamicNewPromptBtn = byId('dynamic-new-prompt-btn');
  const dynamicMetaError = byId('dynamic-meta-error');
  const dynamicFormError = byId('dynamic-form-error');
  const dynamicResultError = byId('dynamic-result-error');
  const dynamicTraceLink = byId('dynamic-trace-link');
  const dynamicSystemEditor = byId('dynamic-system-editor');
  const dynamicTemplateEditor = byId('dynamic-template-editor');
  const dynamicCopyStatus = byId('dynamic-copy-status');
  let dynamicPromptMeta = null;
  let dynamicRunPayload = null;
  let dynamicCopyTimeout = null;

  function renderDynamicResult() {
    byId('dynamic-result').textContent = dynamicRunPayload ? String(dynamicRunPayload.result ?? '') : '—';
    byId('dynamic-message').textContent = dynamicRunPayload ? String(dynamicRunPayload.message ?? '') : '—';
    byId('dynamic-result-raw').textContent = dynamicRunPayload ? formatPayload(dynamicRunPayload) : 'No result yet.';
  }

  async function loadDynamicPromptNames(selectName) {
    const response = await requestJson(root.dataset.dynamicListEndpoint);
    dynamicPromptSelect.innerHTML = '<option value="">-- select prompt --</option>';
    (response.items || []).forEach((item) => {
      const option = document.createElement('option'); option.value = item.name; option.textContent = item.name; dynamicPromptSelect.appendChild(option);
    });
    if (selectName) dynamicPromptSelect.value = selectName;
  }

  async function loadDynamicMeta(name) {
    if (!name) {
      dynamicPromptMeta = null;
      byId('dynamic-required-fields').textContent = '—';
      dynamicSystemEditor.value = '';
      dynamicTemplateEditor.value = '';
      return;
    }
    dynamicPromptMeta = await requestJson(`${root.dataset.dynamicMetaBase}/${encodeURIComponent(name)}`);
    byId('dynamic-required-fields').textContent = (dynamicPromptMeta.required_data_fields || []).join(', ') || '(none)';
    const promptsPayload = await requestJson(`${root.dataset.promptLoadBase}/dynamic?name=${encodeURIComponent(name)}`);
    const map = {};
    (promptsPayload.items || []).forEach((item) => { map[item.part] = item.content || ''; });
    dynamicSystemEditor.value = map.system_prompt || '';
    dynamicTemplateEditor.value = map.template_prompt || '';
  }

  function buildDynamicPayloadTemplate() {
    const prompt = String(dynamicPromptSelect.value || '').trim();
    const fields = dynamicPromptMeta?.required_data_fields || [];
    const data = {};
    fields.forEach((f) => { data[f] = ''; });
    const payload = { prompt, user: '', data };
    const form = new FormData(dynamicForm);
    const llm = {};
    const provider = cleanOptional(form.get('provider'));
    const style = cleanOptional(form.get('style'));
    const maxTokens = cleanOptional(form.get('max_output_tokens'));
    const temperatureField = dynamicForm.elements.namedItem('temperature');
    if (provider) llm.provider = provider;
    if (style) llm.style = style;
    if (temperatureField && temperatureField.dataset.touched === 'true') llm.temperature = Number(temperatureField.value);
    if (maxTokens) llm.max_output_tokens = Number(maxTokens);
    if (Object.keys(llm).length) payload.llm = llm;
    byId('dynamic-payload-template').textContent = formatPayload(payload);
  }

  function buildDynamicPayload() {
    const form = new FormData(dynamicForm);
    const payload = {
      prompt: String(form.get('prompt') || '').trim(),
      user: String(form.get('user') || '').trim(),
      data: JSON.parse(String(form.get('data') || '{}')),
    };
    const llm = {};
    const provider = cleanOptional(form.get('provider'));
    const style = cleanOptional(form.get('style'));
    const maxTokens = cleanOptional(form.get('max_output_tokens'));
    const temperatureField = dynamicForm.elements.namedItem('temperature');
    if (provider) llm.provider = provider;
    if (style) llm.style = style;
    if (temperatureField && temperatureField.dataset.touched === 'true') llm.temperature = Number(temperatureField.value);
    if (maxTokens) llm.max_output_tokens = Number(maxTokens);
    if (Object.keys(llm).length) payload.llm = llm;
    return payload;
  }

  let dynamicSystemManager = null;
  let dynamicTemplateManager = null;
  if (dynamicForm) {
    loadDynamicPromptNames().catch((e) => setError(dynamicMetaError, e.message));

    dynamicSystemManager = createPromptAutosave({ scope: 'dynamic', nameProvider: () => dynamicPromptSelect.value, part: 'system_prompt', textarea: dynamicSystemEditor, statusNode: byId('dynamic-system-status') });
    dynamicTemplateManager = createPromptAutosave({ scope: 'dynamic', nameProvider: () => dynamicPromptSelect.value, part: 'template_prompt', textarea: dynamicTemplateEditor, statusNode: byId('dynamic-template-status') });

    dynamicPromptSelect.addEventListener('change', async () => {
      try {
        await flushPendingSaves();
        await loadDynamicMeta(dynamicPromptSelect.value);
        dynamicSystemManager.setClean(); dynamicTemplateManager.setClean();
        buildDynamicPayloadTemplate();
      } catch (error) { setError(dynamicMetaError, error.message || 'Failed to load dynamic prompt'); }
    });

    dynamicNewPromptBtn.addEventListener('click', async () => {
      const rawName = window.prompt('New prompt name (slug):', 'new_prompt');
      if (rawName === null) return;
      try {
        const { payload } = await requestJsonWithResponse(root.dataset.dynamicCreateEndpoint, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: rawName }),
        });
        await loadDynamicPromptNames(payload.name);
        await loadDynamicMeta(payload.name);
        dynamicSystemManager.setClean(); dynamicTemplateManager.setClean();
        buildDynamicPayloadTemplate();
      } catch (error) {
        setError(dynamicMetaError, error.message || 'Failed to create prompt.');
      }
    });

    dynamicForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      setError(dynamicFormError, ''); setError(dynamicResultError, '');
      try {
        await flushPendingSaves();
        const { payload, response } = await requestJsonWithResponse(root.dataset.dynamicEndpoint, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildDynamicPayload()),
        });
        dynamicRunPayload = payload;
        setTraceLink(dynamicTraceLink, response.headers.get('X-Trace-Id'));
        renderDynamicResult();
      } catch (error) {
        setError(dynamicResultError, error.message || 'Failed to run dynamic prompt.');
      }
    });

    const temperatureField = dynamicForm.elements.namedItem('temperature');
    if (temperatureField) {
      const valueNode = byId('dynamic-temperature-value');
      temperatureField.dataset.touched = 'false';
      if (valueNode) valueNode.textContent = Number(temperatureField.value).toFixed(2);
      const onChange = () => {
        temperatureField.dataset.touched = 'true';
        if (valueNode) valueNode.textContent = Number(temperatureField.value).toFixed(2);
        buildDynamicPayloadTemplate();
      };
      temperatureField.addEventListener('input', onChange);
      temperatureField.addEventListener('change', onChange);
    }

    ['provider', 'style', 'max_output_tokens'].forEach((fieldName) => {
      const field = dynamicForm.elements.namedItem(fieldName);
      if (field) {
        field.addEventListener('input', buildDynamicPayloadTemplate);
        field.addEventListener('change', buildDynamicPayloadTemplate);
      }
    });

    byId('dynamic-reset-btn').addEventListener('click', () => {
      dynamicForm.reset(); dynamicPromptMeta = null; dynamicRunPayload = null;
      byId('dynamic-required-fields').textContent = '—';
      dynamicSystemEditor.value = ''; dynamicTemplateEditor.value = '';
      renderDynamicResult(); setTraceLink(dynamicTraceLink, null); buildDynamicPayloadTemplate();
      setError(dynamicFormError, ''); setError(dynamicResultError, ''); setError(dynamicMetaError, '');
    });

    byId('dynamic-copy-template-btn').addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(byId('dynamic-payload-template').textContent);
        dynamicCopyStatus.hidden = false;
        dynamicCopyStatus.textContent = 'Copied';
        if (dynamicCopyTimeout) clearTimeout(dynamicCopyTimeout);
        dynamicCopyTimeout = window.setTimeout(() => { dynamicCopyStatus.hidden = true; dynamicCopyStatus.textContent = ''; }, 1500);
      } catch (_) {
        dynamicCopyStatus.hidden = false;
        dynamicCopyStatus.textContent = 'Copy failed';
      }
    });

    setSubtab('dynamic-result-tabs', 'button[data-result-tab]', (button) => {
      const showRaw = button.dataset.resultTab === 'raw';
      byId('dynamic-result-view').hidden = showRaw;
      byId('dynamic-result-raw').hidden = !showRaw;
    });
  }

  // Dossier
  const dossierForm = byId('dossier-form');
  if (dossierForm) {
    const dossierFormError = byId('dossier-form-error');
    const dossierResultError = byId('dossier-result-error');
    const dossierTraceLink = byId('dossier-trace-link');
    const dossierSystemEditor = byId('dossier-system-editor');
    const dossierTemplateEditor = byId('dossier-template-editor');
    const dossierSystemManager = createPromptAutosave({ scope: 'dossier', part: 'system_prompt', textarea: dossierSystemEditor, statusNode: byId('dossier-system-status') });
    const dossierTemplateManager = createPromptAutosave({ scope: 'dossier', part: 'user_template', textarea: dossierTemplateEditor, statusNode: byId('dossier-template-status') });
    loadPromptEditors('dossier', { system_prompt: dossierSystemEditor, user_template: dossierTemplateEditor }).then(() => {
      dossierSystemManager.setClean(); dossierTemplateManager.setClean();
    }).catch((e) => setError(dossierFormError, e.message));

    dossierForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      setError(dossierFormError, ''); setError(dossierResultError, '');
      try {
        await flushPendingSaves();
        const form = new FormData(dossierForm);
        const requestBody = {
          stream_id: String(form.get('stream_id') || '').trim(),
          username: String(form.get('username') || '').trim(),
          dossier_target: String(form.get('dossier_target') || '').trim(),
        };
        const { payload, response } = await requestJsonWithResponse(root.dataset.dossierEndpoint, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(requestBody),
        });
        byId('dossier-route').textContent = String(payload.route ?? '');
        byId('dossier-should-reply').textContent = String(payload.should_reply ?? '');
        byId('dossier-reply-text').textContent = String(payload.reply_text ?? '');
        byId('dossier-result-raw').textContent = formatPayload(payload);
        setTraceLink(dossierTraceLink, response.headers.get('X-Trace-Id'));
      } catch (error) { setError(dossierResultError, error.message || 'Failed to run dossier'); }
    });

    byId('dossier-reset-btn').addEventListener('click', () => {
      dossierForm.reset();
      byId('dossier-route').textContent = '—'; byId('dossier-should-reply').textContent = '—'; byId('dossier-reply-text').textContent = '—';
      byId('dossier-result-raw').textContent = 'No result yet.';
      setTraceLink(dossierTraceLink, null);
      setError(dossierFormError, ''); setError(dossierResultError, '');
    });
  }
})();
