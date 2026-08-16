/* tidownloader — translations */

const I18N = {
  en: {
    // Sidebar / nav
    "nav.queue":            "Queue",
    "nav.library":          "Library",
    "nav.settings":         "Settings",
    "sidebar.theme":        "Theme",
    "sidebar.language":     "Language",
    "auth.checking":        "Checking…",
    "auth.login":           "Log in",
    "auth.signOut":         "Sign out",

    // Page titles
    "page.queue.title":     "Queue",
    "page.queue.subtitle":  "Active and completed downloads",
    "page.library.title":   "Library",
    "page.library.subtitle":"Files saved on disk",
    "page.settings.title":  "Settings",
    "page.settings.subtitle":"Customise the app",
    "live.indicator":       "Live",

    // Add form
    "add.title":            "Add to queue",
    "add.subtitle":         "Paste a link or search Tidal for what you want.",
    "add.mode.url":         "Paste URL",
    "add.mode.search":      "Search Tidal",
    "add.url.label":        "Tidal URL",
    "add.url.placeholder":  "https://tidal.com/playlist/…",
    "add.quality.label":    "Quality",
    "add.submit":           "Add to queue",
    "add.advanced":         "Advanced options",
    "add.advanced.path.label": "Custom download path (optional)",
    "add.advanced.path.hint":   "Inside Docker, paths must live inside a bind-mounted volume.",

    // Quality labels (overrides for the dropdown)
    "quality.low.label":    "Low (MP3 128 kbps)",
    "quality.medium.label": "Medium (MP3 256 kbps)",
    "quality.high.label":   "High (MP3 320 kbps)",
    "quality.m4a.label":    "M4A (AAC 320 kbps)",
    "quality.flac.label":   "FLAC (Lossless)",

    // Search
    "search.placeholder":   "Search Tidal · artist, track, album, playlist…",
    "search.empty.title":   "No matches",
    "search.empty.body":    "Nothing in Tidal matched \"{query}\". Try a different spelling or artist name.",
    "search.kind.track":    "Tracks",
    "search.kind.album":    "Albums",
    "search.kind.playlist": "Playlists",
    "search.kind.artist":   "Artists",
    "search.kind.video":    "Videos",
    "search.all":           "All",
    "search.actionTitle":   "Queue {kind}",

    // Library
    "library.title":        "Library",
    "library.filter":       "Filter…",
    "library.refresh":      "Refresh",
    "library.empty.title":  "No files yet",
    "library.empty.body":   "Download something from the Queue tab and it'll appear here.",
    "library.fileCount":    "Root: {root} · {count} files",
    "library.confirmDeleteFolder":  "Delete folder \"{name}\" and all {count} {noun} inside? This cannot be undone.",
    "library.confirmDeleteFile":    "Delete \"{name}\"? This cannot be undone.",
    "library.deletedFolder":         "Deleted folder ({count} files)",
    "library.deletedFile":           "Deleted {name}",
    "library.refreshed":             "Library refreshed",
    "library.deleteFolderFail":      "Failed to delete folder",
    "library.deleteFileFail":        "Failed to delete file",
    "library.fileType.audio":        "audio",
    "library.fileType.image":        "image",
    "library.fileType.playlist":     "playlist",
    "library.fileType.file":         "file",
    "library.of":                    "of",
    "library.showingOf":             "Showing {count} of {total}",

    // Settings
    "settings.title":       "Preferences",
    "settings.save":        "Save",
    "settings.reset":       "Reset",
    "settings.note":        "Changes apply to new jobs.",
    "settings.saved":       "Settings saved",
    "settings.resetDone":   "Settings reset",
    "settings.confirmReset":"Reset all settings to defaults?",
    "settings.audio":       "Audio",
    "settings.audioHint":   "Pick the format that suits you. MP3 320 is the default.",
    "settings.metadata":    "Metadata",
    "settings.metadataHint":"Cover art, lyrics, and playlist files.",
    "settings.speed":       "Speed",
    "settings.speedHint":   "Concurrency is throttled by Tidal above ~4 tracks.",
    "settings.behaviour":   "Behaviour",
    "settings.behaviourHint":"Mostly leave these alone unless something's wrong.",
    "settings.advanced":    "Advanced settings",

    // Toasts
    "toast.addedQueue":     "Added to queue",
    "toast.queueFailed":    "Failed to add job",
    "toast.queued":         "Queued \"{title}\"",
    "toast.loadedPreview":  "Loaded \"{title}\" — press Queue",
    "toast.alreadyLogged":   "Already signed in",
    "toast.signedIn":       "Signed in to Tidal",
    "toast.signedOut":      "Signed out",
    "toast.signinFailed":   "Failed to start login",
    "toast.signoutConfirm": "You'll need to log in again to use the app. Continue?",
    "toast.jobRemoved":     "Job removed",
    "toast.requeued":       "Re-queued",
    "toast.saveFailed":     "Failed to save settings",
    "toast.resetFailed":    "Failed to reset",

    // Auth status labels
    "auth.status.notLogged":"Not signed in",
    "auth.status.logged":  "Logged in",

    // Job cards
    "job.error.removeJob":      "Remove this job from the queue?",
    "job.run":                  "{done}/{total}",
    "job.failedSuffix":         "· {n} failed",
    "job.skippedSuffix":        "· {n} skipped",
    "job.expandTracks":         "Show {n} tracks",
    "job.collapseTracks":       "Hide {n} tracks",
    "job.noStream":             "{title}: stream not available",
    "job.track.fail":           "{title}: {error}",

    // Login modal
    "login.title":          "Link your Tidal account",
    "login.step1":          "Visit",
    "login.step2":          "Enter the code below",
    "login.step3":          "Approve on the website",
    "login.waiting":        "Waiting for authorization…",
    "login.expired":        "Code expired. Click Log in to try again.",

    // Confirm modal
    "confirm.title":        "Are you sure?",
    "confirm.cancel":       "Cancel",
    "confirm.ok":           "Confirm",
    "modal.close":          "Close",

    // Keyboard hints (title attributes)
    "kbd.focusInput":       "Focus URL field",

    // Local folder sync
    "localFolder.title":       "Local folder",
    "localFolder.help":        "Pick a folder on your computer and downloaded files appear there automatically.",
    "localFolder.pick":        "Choose folder…",
    "localFolder.unlink":      "Unlink",
    "localFolder.syncNow":     "Sync all now",
    "localFolder.notLinked":   "Not linked.",
    "localFolder.linked":      "Linked to ",
    "localFolder.unsupported": "Your browser doesn't support picking folders natively. Try Chrome, Edge or Firefox.",
    "localFolder.permission":  "Permission denied. Click again and grant access.",
    "localFolder.syncedOne":  "Synced 1 file to local folder",
    "localFolder.syncedMany": "Synced {count} files to local folder",
    "localFolder.syncFailed":  "Could not sync — permission may have been revoked.",
    "localFolder.syncing":     "Syncing…",
    "localFolder.pickFailed":  "Could not open folder picker.",
  },

  es: {
    "nav.queue":            "Cola",
    "nav.library":          "Biblioteca",
    "nav.settings":         "Ajustes",
    "sidebar.theme":        "Tema",
    "sidebar.language":     "Idioma",
    "auth.checking":        "Comprobando…",
    "auth.login":           "Iniciar sesión",
    "auth.signOut":         "Cerrar sesión",

    "page.queue.title":     "Cola",
    "page.queue.subtitle":  "Descargas activas y completadas",
    "page.library.title":   "Biblioteca",
    "page.library.subtitle":"Archivos guardados en disco",
    "page.settings.title":  "Ajustes",
    "page.settings.subtitle":"Personaliza la aplicación",
    "live.indicator":       "En vivo",

    "add.title":            "Añadir a la cola",
    "add.subtitle":         "Pega un enlace o busca en Tidal lo que quieras.",
    "add.mode.url":         "Pegar URL",
    "add.mode.search":      "Buscar en Tidal",
    "add.url.label":        "URL de Tidal",
    "add.url.placeholder":  "https://tidal.com/playlist/…",
    "add.quality.label":    "Calidad",
    "add.submit":           "Añadir a la cola",
    "add.advanced":         "Opciones avanzadas",
    "add.advanced.path.label": "Ruta personalizada (opcional)",
    "add.advanced.path.hint":   "En Docker, las rutas deben estar dentro de un volumen montado.",

    "quality.low.label":    "Baja (MP3 128 kbps)",
    "quality.medium.label": "Media (MP3 256 kbps)",
    "quality.high.label":   "Alta (MP3 320 kbps)",
    "quality.m4a.label":    "M4A (AAC 320 kbps)",
    "quality.flac.label":   "FLAC (sin pérdida)",

    "search.placeholder":   "Busca en Tidal · artista, canción, álbum, lista…",
    "search.empty.title":   "Sin resultados",
    "search.empty.body":    "No hay nada en Tidal que coincida con \"{query}\". Prueba con otro nombre.",
    "search.kind.track":    "Canciones",
    "search.kind.album":    "Álbumes",
    "search.kind.playlist": "Listas",
    "search.kind.artist":   "Artistas",
    "search.kind.video":    "Vídeos",
    "search.all":           "Todo",
    "search.actionTitle":   "Añadir {kind}",

    "library.title":        "Biblioteca",
    "library.filter":       "Filtrar…",
    "library.refresh":      "Actualizar",
    "library.empty.title":  "Sin archivos",
    "library.empty.body":   "Descarga algo desde la pestaña Cola y aparecerá aquí.",
    "library.fileCount":    "Raíz: {root} · {count} archivos",
    "library.confirmDeleteFolder":  "¿Borrar la carpeta \"{name}\" y los {count} {noun} que contiene? No se puede deshacer.",
    "library.confirmDeleteFile":    "¿Borrar \"{name}\"? No se puede deshacer.",
    "library.deletedFolder":         "Carpeta borrada ({count} archivos)",
    "library.deletedFile":           "{name} borrado",
    "library.refreshed":             "Biblioteca actualizada",
    "library.deleteFolderFail":      "Error al borrar la carpeta",
    "library.deleteFileFail":        "Error al borrar el archivo",
    "library.fileType.audio":        "audio",
    "library.fileType.image":        "imagen",
    "library.fileType.playlist":     "lista",
    "library.fileType.file":         "archivo",
    "library.of":                    "de",
    "library.showingOf":             "Mostrando {count} de {total}",

    "settings.title":       "Preferencias",
    "settings.save":        "Guardar",
    "settings.reset":       "Restablecer",
    "settings.note":        "Los cambios aplican a nuevos jobs.",
    "settings.saved":       "Ajustes guardados",
    "settings.resetDone":   "Ajustes restablecidos",
    "settings.confirmReset":"¿Restablecer todos los ajustes?",
    "settings.audio":       "Audio",
    "settings.audioHint":   "Elige el formato. MP3 320 es el recomendado.",
    "settings.metadata":    "Metadatos",
    "settings.metadataHint":"Carátulas, letras y listas de reproducción.",
    "settings.speed":       "Velocidad",
    "settings.speedHint":   "Tidal limita a ~4 descargas simultáneas.",
    "settings.behaviour":   "Comportamiento",
    "settings.behaviourHint":"Normalmente no hace falta cambiar nada aquí.",
    "settings.advanced":    "Opciones avanzadas",

    "toast.addedQueue":     "Añadido a la cola",
    "toast.queueFailed":    "No se pudo añadir el job",
    "toast.queued":         "En cola: \"{title}\"",
    "toast.loadedPreview":  "Cargado \"{title}\" — pulsa Añadir",
    "toast.alreadyLogged":   "Ya tienes la sesión iniciada",
    "toast.signedIn":       "Sesión iniciada en Tidal",
    "toast.signedOut":      "Sesión cerrada",
    "toast.signinFailed":   "No se pudo iniciar el login",
    "toast.signoutConfirm": "Tendrás que volver a iniciar sesión para usar la app. ¿Continuar?",
    "toast.jobRemoved":     "Job eliminado",
    "toast.requeued":       "Re-encolado",
    "toast.saveFailed":     "Error al guardar",
    "toast.resetFailed":    "Error al restablecer",

    "auth.status.notLogged":"Sin sesión",
    "auth.status.logged":  "Sesión iniciada",

    "job.error.removeJob":      "¿Eliminar este job de la cola?",
    "job.run":                  "{done}/{total}",
    "job.failedSuffix":         "· {n} fallidas",
    "job.skippedSuffix":        "· {n} saltadas",
    "job.expandTracks":         "Mostrar {n} pistas",
    "job.collapseTracks":       "Ocultar {n} pistas",
    "job.noStream":             "{title}: stream no disponible",
    "job.track.fail":           "{title}: {error}",

    "login.title":          "Vincula tu cuenta de Tidal",
    "login.step1":          "Visita",
    "login.step2":          "Introduce el código de abajo",
    "login.step3":          "Aprueba en la web",
    "login.waiting":        "Esperando autorización…",
    "login.expired":        "Código caducado. Pulsa Iniciar sesión para reintentar.",

    "confirm.title":        "¿Estás seguro?",
    "confirm.cancel":       "Cancelar",
    "confirm.ok":           "Confirmar",
    "modal.close":          "Cerrar",

    "kbd.focusInput":       "Foco en el campo de URL",

    // Local folder sync
    "localFolder.title":       "Carpeta local",
    "localFolder.help":        "Elige una carpeta en tu ordenador y los archivos descargados aparecerán ahí automáticamente.",
    "localFolder.pick":        "Elegir carpeta…",
    "localFolder.unlink":      "Desvincular",
    "localFolder.syncNow":     "Sincronizar todo",
    "localFolder.notLinked":   "Sin vincular.",
    "localFolder.linked":      "Vinculado a ",
    "localFolder.unsupported": "Tu navegador no permite elegir carpetas. Prueba Chrome, Edge o Firefox.",
    "localFolder.permission":  "Permiso denegado. Pulsa otra vez y concede acceso.",
    "localFolder.syncedOne":  "1 archivo sincronizado a la carpeta local",
    "localFolder.syncedMany": "{count} archivos sincronizados a la carpeta local",
    "localFolder.syncFailed":  "No se pudo sincronizar — puede que se haya revocado el permiso.",
    "localFolder.syncing":     "Sincronizando…",
    "localFolder.pickFailed":  "No se pudo abrir el selector de carpetas.",
  },
};

const AVAILABLE_LOCALES = [
  { code: "en", label: "English", flag: "🇬🇧" },
  { code: "es", label: "Español", flag: "🇪🇸" },
];

function getInitialLocale() {
  try {
    const saved = localStorage.getItem("td-locale");
    if (saved && I18N[saved]) return saved;
  } catch {}
  try {
    const nav = navigator.language || navigator.userLanguage || "en";
    const code = (nav.split("-")[0] || "en").toLowerCase();
    if (I18N[code]) return code;
  } catch {}
  return "en";
}

let CURRENT_LOCALE = "en";

function t(key, vars) {
  const table = I18N[CURRENT_LOCALE] || I18N.en;
  let str = table[key] || I18N.en[key] || key;
  if (vars) {
    str = str.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`));
  }
  return str;
}

function applyTranslations(root) {
  root = root || document;
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  root.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
  root.querySelectorAll("[data-i18n-aria]").forEach((el) => {
    el.setAttribute("aria-label", t(el.dataset.i18nAria));
  });
  root.querySelectorAll("[data-i18n-html]").forEach((el) => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
}

function setLocale(code) {
  if (!I18N[code]) return;
  CURRENT_LOCALE = code;
  try { localStorage.setItem("td-locale", code); } catch {}
  document.documentElement.dataset.locale = code;
  applyTranslations();
  // Re-render dynamic content that uses t()
  if (typeof window.__td_retranslate === "function") {
    window.__td_retranslate();
  }
}

function renderLocaleSwitcher(container) {
  container.innerHTML = "";
  AVAILABLE_LOCALES.forEach((loc) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "locale-btn" + (loc.code === CURRENT_LOCALE ? " active" : "");
    btn.textContent = loc.flag;
    btn.title = loc.label;
    btn.dataset.locale = loc.code;
    btn.addEventListener("click", () => {
      setLocale(loc.code);
      renderLocaleSwitcher(container);
    });
    container.append(btn);
  });
}

CURRENT_LOCALE = getInitialLocale();
document.documentElement.dataset.locale = CURRENT_LOCALE;