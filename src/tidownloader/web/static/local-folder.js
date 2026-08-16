/* tidownloader — local folder sync (File System Access API) */

const LOCAL_FOLDER_DB = "td-local-folder";
const LOCAL_FOLDER_STORE = "handles";
const HANDLE_KEY = "current";

const LocalFolder = {
  supported: typeof window !== "undefined" && "showDirectoryPicker" in window,
  handle: null,
  name: null,

  async restore() {
    if (!this.supported) return;
    try {
      const db = await openDB();
      const handle = await db.get(LOCAL_FOLDER_STORE, HANDLE_KEY);
      if (!handle) return;
      // Re-request permission — handles lose permission across sessions.
      const perm = await handle.queryPermission({ mode: "readwrite" });
      if (perm === "granted") {
        this.handle = handle;
        this.name = handle.name;
      }
    } catch (e) {
      console.warn("local folder restore failed:", e);
    }
  },

  async pick() {
    if (!this.supported) {
      throw new Error("Tu navegador no soporta el picker nativo de carpetas");
    }
    const handle = await window.showDirectoryPicker({
      id: "tidownloader",
      mode: "readwrite",
    });
    this.handle = handle;
    this.name = handle.name;
    const db = await openDB();
    await db.put(LOCAL_FOLDER_STORE, handle, HANDLE_KEY);
    return handle;
  },

  async forget() {
    this.handle = null;
    this.name = null;
    try {
      const db = await openDB();
      await db.delete(LOCAL_FOLDER_STORE, HANDLE_KEY);
    } catch {}
  },

  async verifyPermission() {
    if (!this.handle) return false;
    const perm = await this.handle.queryPermission({ mode: "readwrite" });
    if (perm === "granted") return true;
    const requested = await this.handle.requestPermission({ mode: "readwrite" });
    return requested === "granted";
  },

  isLinked() {
    return !!this.handle;
  },

  async writeFile(relPath, blob) {
    if (!this.handle) throw new Error("No folder linked");
    const segments = relPath.split("/").filter(Boolean);
    let dir = this.handle;
    for (let i = 0; i < segments.length - 1; i++) {
      dir = await dir.getDirectoryHandle(segments[i], { create: true });
    }
    const fileHandle = await dir.getFileHandle(segments.at(-1), { create: true });
    const writable = await fileHandle.createWritable();
    await writable.write(blob);
    await writable.close();
  },

  async syncOne(relPath) {
    const ok = await this.verifyPermission();
    if (!ok) return { ok: false, reason: "permission-denied" };
    const res = await fetch(`/api/files/${encodeURI(relPath)}`);
    if (!res.ok) return { ok: false, reason: `http-${res.status}` };
    const blob = await res.blob();
    await this.writeFile(relPath, blob);
    return { ok: true };
  },

  async syncAll(files) {
    if (!this.handle) return { ok: false, count: 0 };
    const ok = await this.verifyPermission();
    if (!ok) return { ok: false, count: 0, reason: "permission-denied" };
    let count = 0;
    for (const f of files) {
      try {
        await this.syncOne(f.path);
        count++;
      } catch (e) {
        console.warn("sync failed for", f.path, e);
      }
    }
    return { ok: true, count };
  },
};

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(LOCAL_FOLDER_DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(LOCAL_FOLDER_STORE)) {
        db.createObjectStore(LOCAL_FOLDER_STORE);
      }
    };
    req.onsuccess = () => {
      const db = req.result;
      const wrap = {
        get(store, key) {
          return new Promise((res, rej) => {
            const r = db.transaction(store, "readonly").objectStore(store).get(key);
            r.onsuccess = () => res(r.result);
            r.onerror = () => rej(r.error);
          });
        },
        put(store, value, key) {
          return new Promise((res, rej) => {
            const r = db.transaction(store, "readwrite").objectStore(store).put(value, key);
            r.onsuccess = () => res();
            r.onerror = () => rej(r.error);
          });
        },
        delete(store, key) {
          return new Promise((res, rej) => {
            const r = db.transaction(store, "readwrite").objectStore(store).delete(key);
            r.onsuccess = () => res();
            r.onerror = () => rej(r.error);
          });
        },
      };
      resolve(wrap);
    };
    req.onerror = () => reject(req.error);
  });
}
