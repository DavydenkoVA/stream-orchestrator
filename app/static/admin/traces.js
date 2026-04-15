(function () {
  const root = document.getElementById('traces-root');
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

  async function requestJson(url) {
    const response = await fetch(url);
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await response.json() : await response.text();

    if (!response.ok) {
      const detail = payload && typeof payload === 'object' ? (payload.detail || payload.message) : payload;
      const error = new Error(detail || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }

    return payload;
  }

  function fmtDate(value) {
    if (!value) return '—';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return String(value);
    }
    return parsed.toISOString();
  }

  function asPrettyJson(value) {
    return JSON.stringify(value, null, 2);
  }

  function trimText(value, maxLength) {
    if (!value) return '—';
    const text = String(value);
    if (text.length <= maxLength) return text;
    return `${text.slice(0, maxLength - 1)}…`;
  }

  function updateUrlRunId(runId) {
    const url = new URL(window.location.href);
    if (!runId) {
      url.searchParams.delete('run_id');
    } else {
      url.searchParams.set('run_id', runId);
    }
    window.history.replaceState({}, '', url);
  }

  const filtersForm = byId('traces-filters');
  const listError = byId('traces-list-error');
  const runsEmpty = byId('traces-runs-empty');
  const runsList = byId('traces-runs-list');

  const detailError = byId('traces-detail-error');
  const detailEmpty = byId('traces-detail-empty');
  const detailNotFound = byId('traces-detail-not-found');
  const detailContent = byId('traces-detail-content');

  const overview = byId('traces-overview');
  const finalOutcome = byId('traces-final-outcome');
  const eventsEmpty = byId('traces-events-empty');
  const eventsList = byId('traces-events-list');
  const runJson = byId('traces-run-json');
  const eventJson = byId('traces-event-json');

  const limitInput = byId('traces-limit');
  const streamInput = byId('traces-stream-id');
  const statusSelect = byId('traces-status');

  let selectedRunId = (root.dataset.selectedRunId || '').trim();
  let selectedEventId = null;
  let currentDetail = null;

  function renderKeyValue(node, rows) {
    node.innerHTML = '';
    rows.forEach((row) => {
      if (row.value === undefined || row.value === null || row.value === '') {
        return;
      }
      const dt = document.createElement('dt');
      dt.textContent = row.label;
      const dd = document.createElement('dd');
      dd.textContent = String(row.value);
      node.appendChild(dt);
      node.appendChild(dd);
    });
  }

  function eventSummary(event) {
    if (event.message) {
      return trimText(event.message, 140);
    }
    if (event.payload !== null && event.payload !== undefined) {
      return trimText(asPrettyJson(event.payload).replace(/\s+/g, ' '), 140);
    }
    return '—';
  }

  function styleResolutionTone(status) {
    const normalized = String(status || '').trim().toLowerCase();
    if (normalized === 'success') return 'success';
    if (normalized === 'fallback') return 'warning';
    if (normalized === 'failed') return 'failure';
    return 'neutral';
  }

  function eventStyleResolution(event) {
    const payload = event && event.payload && typeof event.payload === 'object' ? event.payload : null;
    if (!payload) return null;

    const kind = String(event.kind || '');
    const isLlmEvent = kind.startsWith('llm.') || kind.startsWith('dynamic_prompt.llm.');
    if (!isLlmEvent) return null;

    const requested = String(payload.requested_style || '').trim();
    const applied = String(payload.applied_style || payload.style || '').trim();
    const status = String(payload.style_resolution_status || '').trim();
    const reason = String(payload.style_resolution_reason || '').trim();

    if (!requested && !applied && !status && !reason) return null;
    return { requested, applied, status, reason };
  }

  function eventStyleResolutionBlock(event) {
    const resolution = eventStyleResolution(event);
    if (!resolution) return '';

    const tone = styleResolutionTone(resolution.status);
    return `
      <div class="traces-style-resolution traces-style-resolution--${tone}">
        <div class="traces-style-resolution-title">Style resolution</div>
        <div class="traces-style-resolution-grid">
          <div>requested: ${trimText(resolution.requested || 'unknown', 48)}</div>
          <div>applied: ${trimText(resolution.applied || 'unknown', 48)}</div>
          <div>status: ${trimText(resolution.status || 'unknown', 24)}</div>
          ${resolution.reason ? `<div>reason: ${trimText(resolution.reason, 48)}</div>` : ''}
        </div>
      </div>
    `;
  }

  function renderEvents() {
    const events = currentDetail ? currentDetail.events || [] : [];
    eventsList.innerHTML = '';

    if (!events.length) {
      eventsEmpty.hidden = false;
      eventJson.textContent = 'No events in this run.';
      return;
    }

    eventsEmpty.hidden = true;

    if (!selectedEventId || !events.find((event) => event.id === selectedEventId)) {
      selectedEventId = events[0].id;
    }

    events.forEach((event) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'traces-event-item';
      const tone = String(event.tone || 'neutral');
      button.dataset.tone = tone;
      button.classList.add(`traces-event-item--${tone}`);
      if (event.id === selectedEventId) {
        button.classList.add('selected');
      }
      button.innerHTML = `
        <div class="traces-event-title">${fmtDate(event.timestamp)} · ${event.kind || 'unknown'}</div>
        <div class="traces-event-meta">status=${event.status || '—'} level=${event.level || '—'} seq=${event.seq_no || '—'}</div>
        ${eventStyleResolutionBlock(event)}
        <div class="traces-event-summary">${eventSummary(event)}</div>
      `;
      button.addEventListener('click', function () {
        selectedEventId = event.id;
        renderEvents();
      });
      eventsList.appendChild(button);
    });

    const selectedEvent = events.find((event) => event.id === selectedEventId);
    eventJson.textContent = selectedEvent ? asPrettyJson(selectedEvent.payload) : 'Select an event to inspect payload.';
  }

  function renderDetail() {
    const detail = currentDetail;
    if (!detail) {
      detailEmpty.hidden = false;
      detailNotFound.hidden = true;
      detailContent.hidden = true;
      return;
    }

    detailEmpty.hidden = true;
    detailNotFound.hidden = true;
    detailContent.hidden = false;

    const run = detail.run || {};
    renderKeyValue(overview, [
      { label: 'id', value: run.id },
      { label: 'request_id', value: run.request_id },
      { label: 'started_at', value: fmtDate(run.started_at) },
      { label: 'finished_at', value: fmtDate(run.finished_at) },
      { label: 'duration_ms', value: run.duration_ms },
      { label: 'status', value: run.status },
      { label: 'requested_style', value: run.requested_style },
      { label: 'style', value: run.applied_style },
      { label: 'style_resolution_status', value: run.style_resolution_status },
      { label: 'style_resolution_reason', value: run.style_resolution_reason },
      { label: 'route', value: run.route },
      { label: 'stream_id', value: run.stream_id },
    ]);

    renderKeyValue(finalOutcome, [
      { label: 'completion_state', value: run.status },
      { label: 'error_code', value: run.error_code },
      { label: 'summary', value: run.summary },
    ]);

    runJson.textContent = asPrettyJson(run);
    renderEvents();
  }

  function renderNotFound() {
    detailEmpty.hidden = true;
    detailContent.hidden = true;
    detailNotFound.hidden = false;
  }

  async function loadDetail() {
    setError(detailError, '');

    if (!selectedRunId) {
      currentDetail = null;
      renderDetail();
      return;
    }

    try {
      const detail = await requestJson(`${root.dataset.detailEndpointBase}/${encodeURIComponent(selectedRunId)}`);
      currentDetail = detail;
      renderDetail();
    } catch (error) {
      currentDetail = null;
      if (error.status === 404) {
        renderNotFound();
      } else {
        renderDetail();
        setError(detailError, error.message || 'Failed to load trace run detail.');
      }
    }
  }

  function renderRuns(items) {
    runsList.innerHTML = '';

    if (!items.length) {
      runsEmpty.hidden = false;
      return;
    }

    runsEmpty.hidden = true;

    items.forEach((run) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'traces-run-item';
      const tone = String(run.status_tone || 'neutral');
      button.dataset.statusTone = tone;
      button.classList.add(`traces-run-item--${tone}`);
      if (run.id === selectedRunId) {
        button.classList.add('selected');
      }

      const top = document.createElement('div');
      top.className = 'traces-run-top';

      const runId = document.createElement('span');
      runId.className = 'traces-run-id';
      runId.textContent = String(run.id || '—');

      const runStatus = document.createElement('span');
      runStatus.className = 'traces-run-status';
      runStatus.textContent = String(run.status || '—');

      top.appendChild(runId);
      top.appendChild(runStatus);

      const meta = document.createElement('div');
      meta.className = 'traces-run-meta';
      meta.textContent = `${run.route || '—'} · stream=${run.stream_id || '—'}`;

      const startedAt = document.createElement('div');
      startedAt.className = 'traces-run-meta';
      startedAt.textContent = `start=${fmtDate(run.started_at)}`;

      button.appendChild(top);
      button.appendChild(meta);
      button.appendChild(startedAt);
      button.addEventListener('click', function () {
        selectedRunId = run.id;
        selectedEventId = null;
        updateUrlRunId(selectedRunId);
        renderRuns(items);
        loadDetail();
      });
      runsList.appendChild(button);
    });
  }

  function buildRunsUrl() {
    const params = new URLSearchParams();
    const limit = Number.parseInt(limitInput.value, 10);
    params.set('limit', String(Number.isFinite(limit) ? limit : 50));

    const stream = String(streamInput.value || '').trim();
    if (stream) {
      params.set('stream_id', stream);
    }

    const status = String(statusSelect.value || '').trim();
    if (status && status !== 'all') {
      params.set('status', status);
    }

    return `${root.dataset.runsEndpoint}?${params.toString()}`;
  }

  async function loadRuns() {
    setError(listError, '');
    try {
      const payload = await requestJson(buildRunsUrl());
      const items = Array.isArray(payload.items) ? payload.items : [];
      renderRuns(items);
    } catch (error) {
      renderRuns([]);
      setError(listError, error.message || 'Failed to load trace runs list.');
    }
  }

  filtersForm.addEventListener('submit', async function (event) {
    event.preventDefault();
    await loadRuns();
    await loadDetail();
  });

  loadRuns().then(loadDetail);
})();
