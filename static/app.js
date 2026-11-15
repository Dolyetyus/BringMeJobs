const state = {
  status: "",
  companies: [],
  deleted: [],
};

const $ = (selector) => document.querySelector(selector);

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
}[character]));

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }

  return data;
}

function show(message) {
  const notice = $("#notice");

  if (!notice) {
    return;
  }

  notice.textContent = message;
  notice.hidden = !message;
}

async function loadJobs() {
  const query = state.status
    ? `?status=${encodeURIComponent(state.status)}`
    : "";
  const jobs = await api(`/api/jobs${query}`);

  $("#job-count").textContent = jobs.length;
  $("#jobs").innerHTML = jobs.length
    ? jobs.map((job) => `
      <article class="card">
        <div class="card-head">
          <span class="company-name">${escapeHtml(job.company_name)}</span>
          <span class="score">${job.score}/100</span>
        </div>
        <h3>${escapeHtml(job.title)}</h3>
        <div class="meta">
          ${escapeHtml(job.location)} · posted ${escapeHtml((job.posted_at || "").slice(0, 10))}
        </div>
        <div class="reasons">
          ${job.match_reasons.map((reason) => `<span class="pill">${escapeHtml(reason)}</span>`).join("")}
        </div>
        <p class="muted">${escapeHtml(job.description).slice(0, 180)}</p>
        <div class="actions">
          <a href="${escapeHtml(job.url)}" target="_blank" rel="noreferrer">Open listing</a>
          <button data-job="${escapeHtml(job.id)}" data-status="saved">Save</button>
          <button data-job="${escapeHtml(job.id)}" data-status="archived">Archive</button>
        </div>
      </article>
    `).join("")
    : `
      <div class="card">
        <h3>No matching jobs yet</h3>
        <p class="muted">Run a search or configure a careers source.</p>
      </div>
    `;
}

async function setStatus(id, status) {
  try {
    await api(`/api/jobs/${encodeURIComponent(id)}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    await loadJobs();
  } catch (error) {
    show(error.message);
  }
}

async function loadRuns() {
  const runs = await api("/api/runs");

  $("#runs").innerHTML = runs.length
    ? runs.map((run) => `
      <div class="run-entry">
        <button class="run-button" data-run="${run.id}">
          <span>${escapeHtml(run.started_at.slice(0, 19).replace("T", " "))} · ${run.fetched} fetched · ${run.inserted} new</span>
          <strong class="${run.status === "success" ? "ok" : "bad"}">${escapeHtml(run.status)}</strong>
        </button>
        <div class="run-logs" id="run-logs-${run.id}" hidden></div>
      </div>
    `).join("")
    : '<p class="muted">No runs yet.</p>';
}

async function showRunLogs(runId) {
  const container = $(`#run-logs-${runId}`);

  if (!container.hidden) {
    container.hidden = true;
    return;
  }

  try {
    const logs = await api(`/api/runs/${runId}/logs`);
    container.innerHTML = logs.length
      ? logs.map((log) => `
        <div class="log-entry ${escapeHtml(log.level)}">
          <time>${escapeHtml(log.logged_at.slice(11, 19))}</time>
          <strong>${escapeHtml(log.step)}</strong>
          <span>${escapeHtml(log.message)}</span>
        </div>
      `).join("")
      : '<p class="muted">No logs recorded.</p>';
    container.hidden = false;
  } catch (error) {
    show(error.message);
  }
}

async function refreshDashboard() {
  try {
    await Promise.all([loadJobs(), loadRuns()]);
  } catch (error) {
    show(error.message);
  }
}

function companySource(company) {
  return (company.sources || []).find((source) => source.enabled && source.source_type !== "fixture")
    || (company.sources || []).find((source) => source.enabled)
    || (company.sources || [])[0]
    || {};
}

function renderCompanies() {
  $("#company-rows").innerHTML = state.companies.map((company, index) => {
    const source = companySource(company);

    return `
      <div class="company-row" data-index="${index}">
        <input data-field="name" value="${escapeHtml(company.name)}" placeholder="Company name">
        <input data-field="source_url" value="${escapeHtml(source.url || company.careers_url)}" placeholder="https://company.com/careers">
        <select data-field="source_type">
          <option value="careers" ${source.source_type !== "json" ? "selected" : ""}>Careers page</option>
          <option value="json" ${source.source_type === "json" ? "selected" : ""}>JSON feed</option>
        </select>
        <div class="source-health ${escapeHtml(source.health_status || "unknown")}">
          <strong>${escapeHtml(source.health_status || "Not checked")}</strong>
          <small>${escapeHtml(source.health_checked_at ? source.health_checked_at.slice(0, 16).replace("T", " ") : "—")}</small>
        </div>
        <button class="icon-button" title="Remove company" data-remove="${index}">
          <svg aria-hidden="true"><use href="#icon-trash"></use></svg>
        </button>
      </div>
    `;
  }).join("");
}

async function loadConfig() {
  state.companies = await api("/api/companies");
  renderCompanies();
}

function collectCompanies() {
  document.querySelectorAll(".company-row").forEach((row) => {
    const company = state.companies[Number(row.dataset.index)];

    row.querySelectorAll("[data-field]").forEach((field) => {
      company[field.dataset.field] = field.value.trim();
    });
  });

  return state.companies.map((company) => ({
    id: company.id,
    name: company.name,
    careers_url: company.source_url || company.careers_url || "",
    source_url: company.source_url || company.careers_url || "",
    source_type: company.source_type || "careers",
    enabled: true,
    notes: company.notes || "",
  }));
}

async function saveConfig() {
  try {
    await api("/api/companies/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        companies: collectCompanies(),
        deleted_ids: state.deleted,
      }),
    });

    state.deleted = [];
    await loadConfig();
    show("Changes saved.");
    setTimeout(() => show(""), 1800);
  } catch (error) {
    show(error.message);
  }
}

async function checkHealth() {
  $("#check-health").disabled = true;
  show("Checking source access…");

  try {
    const result = await api("/api/sources/health", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    await loadConfig();
    show(`Checked ${result.checked} sources: ${result.healthy} healthy, ${result.blocked} blocked, ${result.errors} errors.`);
  } catch (error) {
    show(error.message);
  } finally {
    $("#check-health").disabled = false;
  }
}

function setupConfig() {
  loadConfig().catch((error) => show(error.message));

  $("#add-company").onclick = () => {
    state.companies.push({
      id: null,
      name: "",
      careers_url: "",
      sources: [],
    });
    renderCompanies();
    document.querySelector(".company-row:last-child input").focus();
  };

  $("#save-config").onclick = saveConfig;
  $("#check-health").onclick = checkHealth;

  $("#company-rows").addEventListener("click", (event) => {
    const remove = event.target.closest("[data-remove]");

    if (!remove) {
      return;
    }

    const index = Number(remove.dataset.remove);

    if (state.companies[index].id) {
      state.deleted.push(state.companies[index].id);
    }

    state.companies.splice(index, 1);
    renderCompanies();
  });
}

function setupDashboard() {
  refreshDashboard();

  $("#run-search").onclick = async () => {
    $("#run-search").disabled = true;
    show("Search running…");

    try {
      const result = await api("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });

      show(`Search ${result.status}: ${result.inserted} new jobs, ${result.errors.length} source errors.`);
      await refreshDashboard();
    } catch (error) {
      show(error.message);
    } finally {
      $("#run-search").disabled = false;
    }
  };

  $("#refresh").onclick = refreshDashboard;

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
      tab.classList.add("active");
      state.status = tab.dataset.status;
      loadJobs();
    };
  });

  $("#runs").addEventListener("click", (event) => {
    const runButton = event.target.closest("[data-run]");

    if (runButton) {
      showRunLogs(runButton.dataset.run);
    }
  });

  $("#jobs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-job]");

    if (button) {
      setStatus(button.dataset.job, button.dataset.status);
    }
  });
}

if ($("#company-rows")) {
  setupConfig();
}

if ($("#jobs")) {
  setupDashboard();
}
