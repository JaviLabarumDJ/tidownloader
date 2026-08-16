/* tidownloader — UI */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const STATE = {
  themes: [],
  currentTheme: localStorage.getItem("td-theme") || "dark-cyan",
  isLoggedIn: false,
  currentTab: localStorage.getItem("td-tab") || "queue",
  expandedJobs: new Set(JSON.parse(localStorage.getItem("td-expanded") || "[]")),
  filesCache: [],
  filesSearch: "",
  inputMode: "url",
  searchQuery: "",
  searchAbort: null,
  // Job DOM cache — patched in place rather than rebuilt.
  jobNodes: new Map(),
  currentJobsById: new Map(),
  pollTimer: null,
};

const COVER_SIZES = [320, 640, 1280, 1920, 3000];

// Hook for i18n: when locale changes, app re-renders dynamic UI.
window.__td_retranslate = function () {
  // Re-fill static dynamic parts.
  refreshQualityHint();
  refreshAuth();
  // Re-render the active panel content.
  if (STATE.currentTab === "queue") refreshJobs();
  if (STATE.currentTab === "files") refreshFiles();
  if (STATE.currentTab === "settings") refreshSettings();
  updatePageTitle();
};

// ---------- Themes ----------

async function loadThemes() {
  const res = await fetch("/api/themes");
  const data = await res.json();
  STATE.themes = data.themes;
  renderThemeSwatches();
  renderLocaleSwitcher($("#locale-options"));
}

function renderThemeSwatches() {
  const container = $("#theme-swatches");
  if (!container) return;
  container.innerHTML = "";
  STATE.themes.forEach((theme) => {
    const btn = document.createElement("button");
    btn.className = "theme-swatch" + (theme.id === STATE.currentTheme ? " active" : "");
    btn.style.setProperty("--swatch", theme.swatch);
    btn.title = theme.name;
    btn.addEventListener("click", () => setTheme(theme.id));
    container.appendChild(btn);
  });
}

function setTheme(id) {
  STATE.currentTheme = id;
  document.documentElement.dataset.theme = id;
  localStorage.setItem("td-theme", id);
  renderThemeSwatches();
}

document.documentElement.dataset.theme = STATE.currentTheme;

// ---------- Helpers ----------

function fmtSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return bytes + " B";
  const units = ["KB", "MB", "GB"];
  let v = bytes / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return v.toFixed(1) + " " + units[i];
}

function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString();
}

function escapeHtml(s) {
  return (s ?? "").toString().replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;",
    '"': "&quot;", "'": "&#39;",
  }[c]));
}

function coverUrl(imageId, size = 320) {
  if (!imageId) return null;
  return `https://resources.tidal.com/images/${imageId.replace(/-/g, "/")}/${size}x${size}.jpg`;
}

const QUALITY_LABEL = {
  "mp3_128": "MP3 128",
  "mp3_256": "MP3 256",
  "mp3_320": "MP3 320",
  "m4a":      "M4A",
  "flac":     "FLAC",
};

const KIND_ICON = {
  track:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
  album:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>',
  playlist: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>',
  artist:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
  video:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
};

// ---------- i18n hookup ----------
// Apply translations once the DOM is parsed.
document.addEventListener("DOMContentLoaded", () => applyTranslations());

// Patch document.title too (with localised product name if you want).
document.title = "tidownloader";

// ---------- Toasts ----------

function toast(message, kind = "success") {
  const stack = $("#toast-stack");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  const iconSvg = {
    success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>',
    error:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    warn:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  }[kind] || "";
  el.innerHTML = `${iconSvg}<span>${escapeHtml(message)}</span>`;
  stack.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateX(20px)";
    setTimeout(() => el.remove(), 300);
  }, 3500);
}

// ---------- Confirm modal ----------

function confirmDialog(message, title = null) {
  return new Promise((resolve) => {
    const modal = $("#confirm-modal");
    $("#confirm-message").textContent = message;
    $("#confirm-title").textContent = title || t("confirm.title");
    modal.classList.remove("hidden");
    const cleanup = (val) => {
      modal.classList.add("hidden");
      $("#confirm-ok").removeEventListener("click", okHandler);
      $("#confirm-cancel").removeEventListener("click", cancelHandler);
      resolve(val);
    };
    const okHandler = () => cleanup(true);
    const cancelHandler = () => cleanup(false);
    $("#confirm-ok").addEventListener("click", okHandler);
    $("#confirm-cancel").addEventListener("click", cancelHandler);
  });
}

// ---------- Tabs ----------

function switchTab(tab) {
  STATE.currentTab = tab;
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${tab}`));
  updatePageTitle();
  if (tab === "files") refreshFiles();
  if (tab === "settings") refreshSettings();
  localStorage.setItem("td-tab", tab);
}

function updatePageTitle() {
  const keyTitle = `page.${STATE.currentTab}.title`;
  const keySubtitle = `page.${STATE.currentTab}.subtitle`;
  $("#page-title").textContent = t(keyTitle);
  $("#page-subtitle").textContent = t(keySubtitle);
}

$$(".nav-item").forEach((b) => {
  b.addEventListener("click", () => switchTab(b.dataset.tab));
});

switchTab(STATE.currentTab);

// ---------- Auth ----------

async function refreshAuth() {
  const res = await fetch("/api/auth/status");
  const data = await res.json();
  STATE.isLoggedIn = data.logged_in;
  const status = $("#auth-status");
  const loginBtn = $("#login-btn");
  const dot = status.querySelector(".login-dot");
  const text = status.querySelector(".login-text");

  if (data.logged_in) {
    const u = data.user || {};
    const name = u.name || u.email || t("auth.status.logged");
    text.textContent = name;
    dot.classList.add("connected");
    text.classList.add("connected");
    loginBtn.textContent = t("auth.signOut");
  } else {
    text.textContent = t("auth.status.notLogged");
    dot.classList.remove("connected", "connecting");
    text.classList.remove("connected");
    loginBtn.textContent = t("auth.login");
  }
}

$("#login-btn").addEventListener("click", async () => {
  if (STATE.isLoggedIn) {
    if (!await confirmDialog(t("toast.signoutConfirm"))) return;
    await fetch("/api/auth/logout", { method: "POST" });
    await refreshAuth();
    toast(t("toast.signedOut"));
    return;
  }
  const res = await fetch("/api/auth/login", { method: "POST" });
  if (!res.ok) { toast(t("toast.signinFailed"), "error"); return; }
  const data = await res.json();
  if (data.already_logged_in) {
    await refreshAuth();
    toast(t("toast.alreadyLogged"), "success");
    return;
  }
  $("#login-modal").classList.remove("hidden");
  $("#login-url").textContent = data.verification_uri;
  $("#login-url").href = data.verification_uri;
  $("#login-code").textContent = data.user_code;
  $("#login-hint").textContent = t("login.waiting");

  const poll = setInterval(async () => {
    const r = await fetch("/api/auth/status");
    const d = await r.json();
    if (d.logged_in) {
      clearInterval(poll);
      $("#login-modal").classList.add("hidden");
      await refreshAuth();
      toast(t("toast.signedIn"));
    }
  }, 2500);

  setTimeout(() => {
    clearInterval(poll);
    $("#login-hint").textContent = t("login.expired");
  }, (data.expires_in || 600) * 1000);
});

$("#login-close").addEventListener("click", () => {
  $("#login-modal").classList.add("hidden");
});

$("#login-close").addEventListener("click", () => {
  $("#login-modal").classList.add("hidden");
});

// ---------- Add form (URL mode) ----------

function refreshQualityHint() {
  const sel = $("#quality");
  if (!sel) return;
  const opt = sel.selectedOptions[0];
  $("#quality-hint").textContent = opt ? (opt.dataset.desc || "") : "";
}
$("#quality").addEventListener("change", refreshQualityHint);
refreshQualityHint();

async function queueUrl(url, quality, downloadPath) {
  const body = { url, quality };
  if (downloadPath) body.download_path = downloadPath;
  const res = await fetch("/api/downloads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "unknown" }));
    toast(err.error || t("toast.queueFailed"), "error");
    return false;
  }
  toast(t("toast.addedQueue"));
  return true;
}

$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = $("#url").value.trim();
  const quality = $("#quality").value;
  const downloadPath = $("#download_path").value.trim();
  if (!url) return;
  if (await queueUrl(url, quality, downloadPath)) {
    $("#url").value = "";
    $("#download_path").value = "";
    refreshJobs();
  }
});

// ---------- Input mode toggle ----------

function setInputMode(mode) {
  STATE.inputMode = mode;
  $$(".mode-btn").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $$("[data-mode-panel]").forEach((p) => {
    p.classList.toggle("active", p.dataset.modePanel === mode);
  });
  if (mode === "search") {
    setTimeout(() => $("#search-input").focus(), 50);
  } else {
    setTimeout(() => $("#url").focus(), 50);
  }
}

$$(".mode-btn").forEach((b) => {
  b.addEventListener("click", () => setInputMode(b.dataset.mode));
});

setInputMode(STATE.inputMode);

// ---------- Search ----------

let searchTimer = null;

$("#search-input").addEventListener("input", (e) => {
  const q = e.target.value.trim();
  STATE.searchQuery = q;
  clearTimeout(searchTimer);
  $("#search-spinner").hidden = !q;
  if (!q) {
    $("#search-results").innerHTML = "";
    if (STATE.searchAbort) STATE.searchAbort.abort();
    return;
  }
  searchTimer = setTimeout(() => runSearch(q), 350);
});

async function runSearch(q) {
  if (STATE.searchAbort) STATE.searchAbort.abort();
  STATE.searchAbort = new AbortController();
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`, {
      signal: STATE.searchAbort.signal,
    });
    $("#search-spinner").hidden = true;
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      $("#search-results").innerHTML = `<div class="search-error">${
        escapeHtml(err.error || `Search failed (HTTP ${res.status})`)
      }</div>`;
      return;
    }
    const data = await res.json();
    renderSearchResults(data.results || []);
  } catch (e) {
    $("#search-spinner").hidden = true;
    if (e.name !== "AbortError") {
      console.error("search error:", e);
      $("#search-results").innerHTML = `<div class="search-error">${
        escapeHtml(e.message || "Network error")
      }</div>`;
    }
  }
}

const KIND_LABEL = {
  track:    "Tracks",
  album:    "Albums",
  playlist: "Playlists",
  artist:   "Artists",
  video:    "Videos",
};

const KIND_SECTION_ICON = {
  track:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
  album:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>',
  playlist: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>',
  artist:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
  video:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
};

function renderSearchResults(results) {
  const container = $("#search-results");
  container.innerHTML = "";

  if (!results.length) {
    container.innerHTML = `<div class="search-empty">
      <div class="empty-state-icon">🔍</div>
      <h3 style="margin:8px 0 4px 0;color:var(--text);font-weight:600">${escapeHtml(t("search.empty.title"))}</h3>
      <p>${escapeHtml(t("search.empty.body", { query: STATE.searchQuery }))}</p>
    </div>`;
    $("#search-filter-bar").innerHTML = "";
    return;
  }

  // Group by kind while preserving the order Tidal gave them.
  const order = ["track", "album", "playlist", "artist", "video"];
  const groups = { track: [], album: [], playlist: [], artist: [], video: [] };
  results.forEach((r) => {
    const k = groups[r.kind] ? r.kind : "track";
    groups[k].push(r);
  });

  // Render filter bar (All / Tracks / Albums / Playlists / Artists / Videos).
  const filterBar = $("#search-filter-bar");
  const totalCount = results.length;
  const presentKinds = order.filter((k) => groups[k].length > 0);
  filterBar.innerHTML = `
    <button class="filter-chip active" data-filter="all">${escapeHtml(t("search.all"))} <span class="chip-count">${totalCount}</span></button>
    ${presentKinds.map((k) => `
      <button class="filter-chip" data-filter="${k}">${escapeHtml(KIND_LABEL[k])} <span class="chip-count">${groups[k].length}</span></button>
    `).join("")}
  `;
  filterBar.querySelectorAll(".filter-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      filterBar.querySelectorAll(".filter-chip").forEach((b) =>
        b.classList.toggle("active", b === btn));
      const filter = btn.dataset.filter;
      container.querySelectorAll(".search-section").forEach((s) => {
        s.hidden = filter !== "all" && s.dataset.kind !== filter;
      });
    });
  });

  // Render each kind as its own section.
  presentKinds.forEach((kind) => {
    const section = document.createElement("div");
    section.className = `search-section search-section-${kind}`;
    section.dataset.kind = kind;

    const header = document.createElement("div");
    header.className = "search-section-header";
    header.innerHTML = `
      <span class="search-section-icon ${kind}">${KIND_SECTION_ICON[kind]}</span>
      <span class="search-section-title">${escapeHtml(KIND_LABEL[kind])}</span>
      <span class="search-section-count">${groups[kind].length}</span>
    `;
    section.append(header);

    const list = document.createElement("div");
    list.className = "search-list";
    groups[kind].forEach((r) => {
      list.append(buildResultRow(r));
    });
    section.append(list);

    container.append(section);
  });
}

function buildResultRow(r) {
  const row = document.createElement("div");
  row.className = "search-result";
  row.tabIndex = 0;
  const thumbUrl = coverUrl(r.image_id, 160);
  const fallbackIcon = KIND_ICON[r.kind] || KIND_ICON.track;

  const thumb = document.createElement("div");
  thumb.className = "search-result-thumb";
  const badge = document.createElement("div");
  badge.className = `search-result-kind-badge ${r.kind}`;
  badge.textContent = t(`search.kind.${r.kind}`, { count: 1 }).replace(/s$/, "");
  // Simpler: just use the kind as text
  badge.textContent = r.kind;
  thumb.append(badge);

  if (thumbUrl) {
    const img = document.createElement("img");
    img.src = thumbUrl;
    img.alt = "";
    img.loading = "lazy";
    img.addEventListener("error", () => {
      thumb.innerHTML = "";
      const fb = document.createElement("div");
      fb.className = "search-result-thumb-fallback";
      fb.innerHTML = fallbackIcon;
      const b = document.createElement("div");
      b.className = `search-result-kind-badge ${r.kind}`;
      b.textContent = r.kind;
      thumb.append(fb, b);
    });
    thumb.append(img);
  } else {
    const fb = document.createElement("div");
    fb.className = "search-result-thumb-fallback";
    fb.innerHTML = fallbackIcon;
    thumb.append(fb);
  }
  thumb.classList.add(r.kind);
  row.append(thumb);

  const info = document.createElement("div");
  info.className = "search-result-info";
  const titleEl = document.createElement("div");
  titleEl.className = "search-result-title";
  titleEl.textContent = r.title;
  const subtitleEl = document.createElement("div");
  subtitleEl.className = "search-result-subtitle";
  subtitleEl.textContent = r.subtitle;
  info.append(titleEl, subtitleEl);
  row.append(info);

  const action = document.createElement("button");
  action.className = "search-result-action";
  action.title = t("search.actionTitle", { kind: r.kind });
  action.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>';
  row.append(action);

  const onSelect = () => {
    setInputMode("url");
    $("#url").value = r.url;
    $("#url").focus();
    toast(t("toast.loadedPreview", { title: r.title }), "success");
  };
  row.addEventListener("click", (e) => {
    if (e.target.closest(".search-result-action")) return;
    onSelect();
  });
  action.addEventListener("click", async (e) => {
    e.stopPropagation();
    action.disabled = true;
    const ok = await queueUrl(r.url, $("#quality").value, $("#download_path").value.trim());
    if (ok) {
      toast(t("toast.queued", { title: r.title }));
      refreshJobs();
      onSelect();
    } else {
      action.disabled = false;
    }
  });
  return row;
}

// ---------- Queue: incremental DOM patching ----------

function trackIconSVG(status) {
  const icons = {
    pending:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>',
    downloading: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>',
    done:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>',
    failed:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    skipped:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="5 4 15 12 5 20"/><line x1="19" y1="5" x2="19" y2="19"/></svg>',
  };
  return icons[status] || icons.pending;
}

function buildJobCard(j) {
  const expanded = STATE.expandedJobs.has(j.id);
  const card = document.createElement("div");
  card.className = "job-card" + (j.status === "running" ? " running" : "");
  card.dataset.jobId = String(j.id);

  // Head
  const head = document.createElement("div");
  head.className = "job-head";
  const titleEl = document.createElement("div");
  titleEl.className = "job-title";
  const h3 = document.createElement("h3");
  h3.textContent = j.name || j.url;
  const urlEl = document.createElement("div");
  urlEl.className = "job-url";
  urlEl.textContent = j.url;
  titleEl.append(h3, urlEl);
  const meta = document.createElement("div");
  meta.className = "job-meta";
  const qualityPill = document.createElement("span");
  qualityPill.className = "quality-pill";
  qualityPill.textContent = QUALITY_LABEL[j.quality] || j.quality;
  const statusChip = document.createElement("span");
  statusChip.className = `status-chip ${j.status}`;
  statusChip.innerHTML = `<span class="dot"></span>${escapeHtml(j.status)}`;
  const actions = document.createElement("div");
  actions.className = "job-actions";
  actions.innerHTML = `
    <button class="btn btn-ghost" data-action="retry" title="Retry">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
    </button>
    <button class="btn btn-ghost" data-action="delete" title="Remove">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
    </button>
  `;
  meta.append(qualityPill, statusChip, actions);
  head.append(titleEl, meta);
  card.append(head);

  // Progress
  const progressWrap = document.createElement("div");
  progressWrap.className = "job-progress";
  const trackEl = document.createElement("div");
  trackEl.className = "progress-track";
  const fillEl = document.createElement("div");
  fillEl.className = "progress-fill";
  trackEl.append(fillEl);
  const stats = document.createElement("div");
  stats.className = "progress-stats";
  progressWrap.append(trackEl, stats);
  card.append(progressWrap);

  // Tracks toggle + list
  const tracksWrap = document.createElement("div");
  const toggle = document.createElement("button");
  toggle.className = "tracks-toggle";
  toggle.dataset.action = "toggle-tracks";
  const toggleLabel = document.createElement("span");
  toggle.append(toggleLabel);
  const chevron = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  chevron.setAttribute("viewBox", "0 0 24 24");
  chevron.setAttribute("fill", "none");
  chevron.setAttribute("stroke", "currentColor");
  chevron.setAttribute("stroke-width", "2");
  chevron.classList.add("chevron");
  chevron.innerHTML = '<polyline points="6 9 12 15 18 9"/>';
  toggle.append(chevron);
  tracksWrap.append(toggle);
  const list = document.createElement("div");
  list.className = "tracks-list";
  tracksWrap.append(list);
  card.append(tracksWrap);

  // Error
  const errorEl = document.createElement("div");
  errorEl.className = "job-error";
  errorEl.hidden = true;
  card.append(errorEl);

  const refs = {
    card,
    h3, urlEl,
    qualityPill, statusChip,
    fillEl, stats,
    toggle, toggleLabel, chevron, list,
    errorEl,
    trackNodes: new Map(), // trackId → { row, status, fill, pct, label }
  };
  STATE.jobNodes.set(j.id, refs);

  // Action handlers (bound once)
  card.addEventListener("click", (e) => handleJobClick(e, j.id));
  return card;
}

function handleJobClick(e, jobId) {
  const btn = e.target.closest("button");
  if (!btn) return;
  const action = btn.dataset.action;
  if (action === "retry") retryJob(jobId);
  else if (action === "delete") removeJob(jobId);
  else if (action === "toggle-tracks") toggleTracks(jobId);
}

async function retryJob(jobId) {
  await fetch(`/api/downloads/${jobId}/retry`, { method: "POST" });
  toast(t("toast.requeued"));
  refreshJobs();
}
async function removeJob(jobId) {
  if (!await confirmDialog(t("job.error.removeJob"))) return;
  await fetch(`/api/downloads/${jobId}`, { method: "DELETE" });
  toast(t("toast.jobRemoved"));
  refreshJobs();
}
function toggleTracks(jobId) {
  if (STATE.expandedJobs.has(jobId)) STATE.expandedJobs.delete(jobId);
  else STATE.expandedJobs.add(jobId);
  localStorage.setItem("td-expanded", JSON.stringify([...STATE.expandedJobs]));
  const j = STATE.currentJobsById.get(jobId);
  if (j) patchJob(j, STATE.jobNodes.get(jobId));
}

function buildTrackRow(t) {
  const row = document.createElement("div");
  row.className = "track-row";
  row.dataset.trackId = String(t.track_id);
  const statusEl = document.createElement("div");
  statusEl.className = `track-status ${t.status}`;
  statusEl.innerHTML = trackIconSVG(t.status);
  row.append(statusEl);
  const info = document.createElement("div");
  info.className = "track-info";
  const title = document.createElement("div");
  title.className = "track-title-text";
  title.textContent = t.title;
  const artists = document.createElement("div");
  artists.className = "track-artist-text";
  artists.textContent = (t.artists || []).join(", ");
  const bar = document.createElement("div");
  bar.className = "track-mini-bar";
  const fill = document.createElement("div");
  fill.className = "track-mini-fill";
  bar.append(fill);
  info.append(title, artists, bar);
  row.append(info);
  const pct = document.createElement("div");
  pct.className = "track-progress";
  pct.textContent = "0%";
  row.append(pct);
  return { row, statusEl, fill, pct };
}

function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}
function setClass(el, cls) {
  const newCls = el.className.split(" ").filter((c) => c && c !== el.dataset._lastClass).join(" ");
  if (el.className !== cls) el.className = cls;
}

function patchJob(j, refs) {
  if (!refs) return;

  // Title / url / quality pill
  setText(refs.h3, j.name || j.url);
  setText(refs.urlEl, j.url);
  setText(refs.qualityPill, QUALITY_LABEL[j.quality] || j.quality);

  // Status chip
  const statusCls = `status-chip ${j.status}`;
  if (refs.statusChip.className !== statusCls) refs.statusChip.className = statusCls;
  const chipHtml = `<span class="dot"></span>${escapeHtml(j.status)}`;
  if (refs.statusChip.innerHTML !== chipHtml) refs.statusChip.innerHTML = chipHtml;

  // Card running border
  const cardCls = "job-card" + (j.status === "running" ? " running" : "");
  if (refs.card.className !== cardCls) refs.card.className = cardCls;

  // Job-level progress
  const total = j.total_tracks || 0;
  const done = (j.downloaded || 0) + (j.skipped || 0);
  const pct = total ? Math.round((done / total) * 100) : (j.status === "done" ? 100 : 0);
  refs.fillEl.style.width = pct + "%";
  const statsParts = [`${done}/${total}`];
  if (j.failed) statsParts.push(`<span style="color:var(--error)">${escapeHtml(t("job.failedSuffix", { n: j.failed }))}</span>`);
  if (j.skipped) statsParts.push(`<span style="color:var(--warning)">${escapeHtml(t("job.skippedSuffix", { n: j.skipped }))}</span>`);
  const statsHtml = statsParts.join(" ");
  if (refs.stats.innerHTML !== statsHtml) refs.stats.innerHTML = statsHtml;

  // Tracks toggle visibility + label
  const tracks = j.tracks || [];
  const expanded = STATE.expandedJobs.has(j.id);
  if (tracks.length === 0) {
    refs.toggle.hidden = true;
    refs.list.hidden = true;
    refs.list.classList.remove("open");
  } else {
    refs.toggle.hidden = false;
    setText(refs.toggleLabel,
      expanded
        ? t("job.collapseTracks", { n: tracks.length })
        : t("job.expandTracks", { n: tracks.length }));
    refs.toggle.classList.toggle("open", expanded);
    refs.list.classList.toggle("open", expanded);

    // Track rows — patch in place.
    const seenIds = new Set();
    tracks.forEach((t) => {
      seenIds.add(t.track_id);
      let entry = refs.trackNodes.get(t.track_id);
      if (!entry) {
        entry = buildTrackRow(t);
        refs.list.appendChild(entry.row);
        refs.trackNodes.set(t.track_id, entry);
      }
      const statusCls = `track-status ${t.status}`;
      if (entry.statusEl.className !== statusCls) entry.statusEl.className = statusCls;
      const pctValue = Math.max(0, Math.min(100, t.progress_pct || 0));
      entry.fill.style.width = pctValue + "%";
      setText(entry.pct, pctValue + "%");
    });
    // Remove track rows that no longer exist
    for (const [tid, entry] of refs.trackNodes) {
      if (!seenIds.has(tid)) {
        entry.row.remove();
        refs.trackNodes.delete(tid);
      }
    }
  }

  // Error message
  if (j.error) {
    refs.errorEl.hidden = false;
    setText(refs.errorEl, j.error);
  } else {
    refs.errorEl.hidden = true;
  }
}

function patchJobs(jobs) {
  const list = $("#jobs-list");
  const seenIds = new Set();

  // Live indicator
  const hasActive = jobs.some((j) => j.status === "running" || j.status === "pending");
  $("#live-indicator").classList.toggle("idle", !hasActive);

  if (!jobs.length) {
    list.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">🎵</div>
        <h3>${escapeHtml(t("add.title"))}</h3>
        <p>${escapeHtml(t("add.subtitle"))}</p>
      </div>`;
    // Drop any cached nodes — they've been removed from the DOM.
    for (const id of [...STATE.jobNodes.keys()]) {
      STATE.jobNodes.delete(id);
    }
    STATE.currentJobsById.clear();
    return;
  }

  jobs.forEach((j) => {
    seenIds.add(j.id);
    STATE.currentJobsById.set(j.id, j);
    let refs = STATE.jobNodes.get(j.id);
    if (!refs) {
      refs = null;
      const card = buildJobCard(j);
      list.appendChild(card);
      refs = STATE.jobNodes.get(j.id);
    }
    patchJob(j, refs);
  });

  // Remove cards that no longer exist.
  for (const id of [...STATE.jobNodes.keys()]) {
    if (!seenIds.has(id)) {
      const refs = STATE.jobNodes.get(id);
      if (refs && refs.card.parentNode) refs.card.remove();
      STATE.jobNodes.delete(id);
      STATE.currentJobsById.delete(id);
    }
  }
}

async function refreshJobs() {
  try {
    const res = await fetch("/api/downloads");
    const jobs = await res.json();
    patchJobs(jobs);
  } catch (e) {
    console.error(e);
  }
}

// Polling — slower (5s) and pauses when tab is hidden.
function schedulePoll() {
  clearTimeout(STATE.pollTimer);
  STATE.pollTimer = setTimeout(async () => {
    if (document.hidden) {
      schedulePoll();
      return;
    }
    await refreshJobs();
    schedulePoll();
  }, 5000);
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshJobs();
});
schedulePoll();
refreshJobs();

// ---------- Files: tree view (file manager) ----------

let fileSearchTimer = null;
let filesTreeCache = [];
let expandedFolders = new Set(JSON.parse(localStorage.getItem("td-expanded-folders") || "[]"));

async function refreshFiles() {
  const res = await fetch("/api/files/tree");
  filesTreeCache = await res.json();
  renderFiles();
}

function isAudioFile(name) {
  return /\.(flac|mp3|m4a|ogg|opus|wav|aac)$/i.test(name);
}
function isImageFile(name) {
  return /\.(jpe?g|png|webp)$/i.test(name);
}
function isPlaylistFile(name) {
  return /\.m3u8?$/i.test(name);
}

function fileIconSVG(name) {
  if (isAudioFile(name)) return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>';
  if (isImageFile(name))  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>';
  if (isPlaylistFile(name)) return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/></svg>';
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
}

function iconCls(name) {
  if (isAudioFile(name)) return "audio";
  if (isImageFile(name)) return "image";
  if (isPlaylistFile(name)) return "playlist";
  return "";
}

function renderFiles() {
  const container = $("#files-tree");
  const search = STATE.filesSearch.toLowerCase();

  let totalFiles = 0;
  let totalSize = 0;
  filesTreeCache.forEach((g) => { totalFiles += g.count; totalSize += g.size; });
  $("#files-root-hint").textContent =
    t("library.fileCount", { root: "/downloads", count: totalFiles }) +
    ` · ${fmtSize(totalSize)}`;

  if (!filesTreeCache.length) {
    container.innerHTML = `
      <div class="tree-empty">
        <div class="empty-state-icon">📁</div>
        <h3 style="margin:0 0 6px 0;color:var(--text);font-weight:600">${escapeHtml(t("library.empty.title"))}</h3>
        <p>${escapeHtml(t("library.empty.body"))}</p>
      </div>`;
    return;
  }

  container.innerHTML = "";
  filesTreeCache.forEach((group) => {
    // Filter: keep group if any file matches search OR no search active.
    let visibleFiles = group.files;
    if (search) {
      visibleFiles = group.files.filter((f) =>
        f.name.toLowerCase().includes(search) ||
        f.path.toLowerCase().includes(search) ||
        group.folder.toLowerCase().includes(search)
      );
    }
    if (search && !visibleFiles.length && !group.folder.toLowerCase().includes(search)) return;

    const folderDiv = document.createElement("div");
    const open = expandedFolders.has(group.folder || "__root__");
    folderDiv.className = "tree-folder" + (open ? " open" : "");

    const head = document.createElement("button");
    head.className = "tree-folder-head";
    head.type = "button";
    head.innerHTML = `
      <div class="tree-folder-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
      </div>
      <div class="tree-folder-info">
        <div class="tree-folder-name">${escapeHtml(group.name || "(root)")}</div>
        <div class="tree-folder-meta">
          <span>${escapeHtml(t("library.showingOf", { count: visibleFiles.length, total: group.count }))}</span>
          <span>${fmtSize(visibleFiles.reduce((s, f) => s + f.size, 0))}</span>
          ${group.folder ? `<span style="opacity:0.5">${escapeHtml(group.folder)}</span>` : ""}
        </div>
      </div>
      <svg class="tree-folder-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
      <div class="tree-folder-actions">
        <button class="icon-btn danger" data-action="delete-folder" data-i18n-title="library.deleteFolder" title="Delete entire folder">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
        </button>
      </div>
    `;
    folderDiv.append(head);

    const body = document.createElement("div");
    body.className = "tree-folder-body";
    visibleFiles.forEach((f) => {
      const row = document.createElement("div");
      row.className = "tree-file";
      const cls = iconCls(f.name);
      row.innerHTML = `
        <div class="tree-file-icon ${cls}">${fileIconSVG(f.name)}</div>
        <div class="tree-file-name">${escapeHtml(f.name)}</div>
        <div class="tree-file-size">${fmtSize(f.size)}</div>
        <div class="tree-file-meta">${fmtDate(f.modified)}</div>
        <div class="tree-file-actions">
          <a class="icon-btn" href="/api/files/${encodeURI(f.path)}" title="Download">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          </a>
          <button class="icon-btn danger" data-action="delete-file" title="Delete">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          </button>
        </div>
      `;
      body.append(row);
    });
    folderDiv.append(body);

    // Toggle expand/collapse
    head.addEventListener("click", (e) => {
      // Ignore clicks on the delete-folder button
      if (e.target.closest("[data-action]")) return;
      toggleFolder(group.folder || "__root__");
    });
    // Delete entire folder
    head.querySelector("[data-action='delete-folder']").addEventListener("click", async (e) => {
      e.stopPropagation();
      const noun = visibleFiles.length === 1 ? "file" : "files";
      if (!await confirmDialog(
        t("library.confirmDeleteFolder", {
          name: group.name,
          count: visibleFiles.length,
          noun,
        })
      )) return;
      const res = await fetch(`/api/files/folder/${encodeURI(group.folder)}`, { method: "DELETE" });
      if (!res.ok) { toast(t("library.deleteFolderFail"), "error"); return; }
      const data = await res.json();
      toast(t("library.deletedFolder", { count: data.deleted_files }));
      refreshFiles();
    });
    // Delete individual files
    body.querySelectorAll("[data-action='delete-file']").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!await confirmDialog(t("library.confirmDeleteFile", { name: f.name }))) return;
        const res = await fetch(`/api/files/file/${encodeURI(f.path)}`, { method: "DELETE" });
        if (!res.ok) { toast(t("library.deleteFileFail"), "error"); return; }
        toast(t("library.deletedFile", { name: f.name }));
        refreshFiles();
      });
    });

    container.append(folderDiv);
  });
}

function toggleFolder(key) {
  if (expandedFolders.has(key)) expandedFolders.delete(key);
  else expandedFolders.add(key);
  localStorage.setItem("td-expanded-folders", JSON.stringify([...expandedFolders]));
  renderFiles();
}

$("#files-search").addEventListener("input", (e) => {
  clearTimeout(fileSearchTimer);
  STATE.filesSearch = e.target.value;
  fileSearchTimer = setTimeout(renderFiles, 150);
});

$("#refresh-files").addEventListener("click", () => {
  refreshFiles();
  toast(t("library.refreshed"));
});

// ---------- Settings ----------

const ESSENTIAL = new Set([
  "download_path", "quality", "embed_lyrics", "save_cover_in_folder",
  "create_m3u8", "concurrent_downloads", "skip_existing",
]);

const SECTIONS = [
  { titleKey: "settings.audio",     hintKey: "settings.audioHint",
    keys: ["download_path", "quality"] },
  { titleKey: "settings.metadata",  hintKey: "settings.metadataHint",
    keys: ["embed_lyrics", "save_cover_in_folder", "create_m3u8"] },
  { titleKey: "settings.speed",     hintKey: "settings.speedHint",
    keys: ["concurrent_downloads"] },
  { titleKey: "settings.behaviour", hintKey: "settings.behaviourHint",
    keys: ["skip_existing"] },
];

let SETTINGS_STATE = {};

function settingRow(field, value) {
  const id = `s-${field.key}`;
  const wrap = document.createElement("div");
  wrap.className = `setting ${field.type === "text" || field.type === "select" || field.type === "path" ? "full" : ""}`;

  let input = "";
  if (field.type === "select") {
    const opts = (field.options || []).map((o) => {
      const v = Array.isArray(o) ? o[0] : o;
      const label = Array.isArray(o) ? o[1] : o;
      return `<option value="${escapeHtml(String(v))}" ${String(v) === String(value) ? "selected" : ""}>${escapeHtml(label)}</option>`;
    }).join("");
    input = `<select id="${id}">${opts}</select>`;
  } else if (field.type === "bool") {
    input = `
      <label class="toggle">
        <input type="checkbox" id="${id}" ${value ? "checked" : ""} />
        <span class="toggle-slider"></span>
      </label>`;
  } else if (field.type === "int") {
    input = `<input type="number" id="${id}" value="${value}" />`;
  } else {
    input = `<input type="text" id="${id}" value="${escapeHtml(value ?? "")}" />`;
  }

  wrap.innerHTML = `
    <label>${escapeHtml(field.label)}</label>
    ${input}
    ${field.help ? `<span class="help">${escapeHtml(field.help)}</span>` : ""}
  `;
  return wrap;
}

async function refreshSettings() {
  const res = await fetch("/api/settings");
  const data = await res.json();
  SETTINGS_STATE = data.settings;
  const schema = data.schema;
  const byKey = Object.fromEntries(schema.map((s) => [s.key, s]));

  const form = $("#settings-form");
  form.innerHTML = "";

  for (const section of SECTIONS) {
    const sec = document.createElement("div");
    sec.className = "settings-section";
    sec.innerHTML = `
      <h3>${escapeHtml(t(section.titleKey))}</h3>
      ${section.hintKey ? `<p class="section-hint">${escapeHtml(t(section.hintKey))}</p>` : ""}
    `;
    for (const k of section.keys) {
      if (byKey[k]) sec.appendChild(settingRow(byKey[k], SETTINGS_STATE[k]));
    }
    form.appendChild(sec);
  }

  const advancedKeys = schema.filter((f) => !ESSENTIAL.has(f.key));
  if (advancedKeys.length) {
    const adv = document.createElement("details");
    adv.className = "settings-section";
    adv.innerHTML = `<summary style="cursor:pointer;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--accent);font-weight:700">${escapeHtml(t("settings.advanced"))} (${advancedKeys.length})</summary>`;
    const advGrid = document.createElement("div");
    advGrid.style.cssText = "display:grid;grid-template-columns:1fr 1fr;gap:16px 24px;margin-top:16px;";
    advancedKeys.forEach((f) => {
      const wrap = document.createElement("div");
      wrap.className = `setting ${f.type === "text" || f.type === "select" ? "full" : ""}`;
      wrap.appendChild(settingRow(f, SETTINGS_STATE[f.key]));
      advGrid.appendChild(wrap);
    });
    adv.appendChild(advGrid);
    form.appendChild(adv);
  }
}

async function collectSettings() {
  const out = {};
  for (const [k, v] of Object.entries(SETTINGS_STATE)) {
    const el = $("#s-" + k);
    if (!el) { out[k] = v; continue; }
    if (typeof v === "boolean") out[k] = el.checked;
    else if (typeof v === "number") out[k] = parseInt(el.value, 10) || 0;
    else out[k] = el.value;
  }
  return out;
}

$("#save-settings").addEventListener("click", async () => {
  const body = await collectSettings();
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) { toast(t("toast.saveFailed"), "error"); return; }
  toast(t("settings.saved"));
  refreshSettings();
});

$("#reset-settings").addEventListener("click", async () => {
  if (!await confirmDialog(t("settings.confirmReset"))) return;
  const res = await fetch("/api/settings/reset", { method: "POST" });
  if (!res.ok) { toast(t("toast.resetFailed"), "error"); return; }
  toast(t("settings.resetDone"));
  refreshSettings();
});

// ---------- Keyboard ----------

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    $("#login-modal").classList.add("hidden");
  }
  if (e.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
    e.preventDefault();
    switchTab("queue");
    setInputMode("url");
    $("#url").focus();
  }
});

// ---------- Init ----------

loadThemes();
refreshAuth();