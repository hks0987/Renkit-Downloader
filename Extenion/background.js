const APP = "http://127.0.0.1:18123";
const APP_HEADERS = { "Content-Type": "application/json", "X-ResumeFetch": "1" };
const FALLBACK_TYPES = ("3gp 7z aac ace aif apk arj asf avi bin bz2 exe gz gzip img iso lzh m4a m4v mkv mov mp3 mp4 " +
  "mpa mpe mpeg mpg msi msu ogg ogv pdf plj pps ppt qt r0* r1* ra rar rm rmvb sea sit sitx tar tif tiff wav wma wmv z zip").split(" ");
let cached = { at: 0, cfg: null };

// The app decides which file types / sites to catch (Options > File types).
async function getConfig() {
  if (cached.cfg && Date.now() - cached.at < 30000) return cached.cfg;
  try {
    const r = await fetch(APP + "/config", { headers: { "X-ResumeFetch": "1" } });
    if (r.ok) { cached = { at: Date.now(), cfg: await r.json() }; return cached.cfg; }
  } catch (e) { /* app not running */ }
  return cached.cfg || { enabled: true, catch_all: false, types: FALLBACK_TYPES, exclude_sites: [] };
}

function baseName(p) { return (p || "").split(/[\\/]/).pop(); }
function extOf(name) { const m = /\.([A-Za-z0-9]+)$/.exec(name || ""); return m ? m[1].toLowerCase() : ""; }
function wildcard(pattern, text) {
  const re = new RegExp("^" + pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$", "i");
  return re.test(text);
}

function shouldIntercept(item, cfg) {
  if (!cfg.enabled) return false;
  const url = item.finalUrl || item.url || "";
  if (!/^https?:/i.test(url)) return false;
  let host = "", path = "";
  try { const u = new URL(url); host = u.hostname; path = u.pathname; } catch (e) { return false; }
  if ((cfg.exclude_sites || []).some(p => wildcard(p, host))) return false;
  if (cfg.catch_all) return true;
  const ext = extOf(baseName(item.filename)) || extOf(path);
  return (cfg.types || []).some(t => wildcard(t.toLowerCase(), ext));
}

async function copyToClipboard(text) {
  try {
    await chrome.offscreen.createDocument({
      url: "offscreen.html", reasons: ["CLIPBOARD"],
      justification: "Copy the grabbed download link so you can paste it by hand if anything goes wrong"
    });
  } catch (e) { /* already exists */ }
  for (let i = 0; i < 5; i++) {
    try { await chrome.runtime.sendMessage({ target: "offscreen", type: "copy", text }); return; }
    catch (e) { await new Promise(r => setTimeout(r, 120)); }
  }
}

function badge(ok) {
  chrome.action.setBadgeText({ text: ok ? "OK" : "!" });
  chrome.action.setBadgeBackgroundColor({ color: ok ? "#2e7d32" : "#c62828" });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 5000);
}

async function handoff(payload) {
  await copyToClipboard(payload.url);             // always keep a copy of the link on the clipboard
  try { payload.cookie = (await chrome.cookies.getAll({ url: payload.url })).map(c => c.name + "=" + c.value).join("; "); } catch (e) {}
  try {
    const r = await fetch(APP, { method: "POST", headers: APP_HEADERS, body: JSON.stringify(payload) });
    badge(r.ok);
    return r.ok;
  } catch (e) { badge(false); return false; }
}

chrome.downloads.onDeterminingFilename.addListener((item, suggest) => {
  (async () => {
    try {
      const cfg = await getConfig();
      if (!shouldIntercept(item, cfg)) return;
      const ok = await handoff({
        url: item.finalUrl || item.url, filename: baseName(item.filename), referer: item.referrer || "",
        user_agent: navigator.userAgent, size: item.fileSize > 0 ? item.fileSize : 0, mime: item.mime || ""
      });
      if (ok) {                                    // only cancel the browser download once the app has it
        try { await chrome.downloads.cancel(item.id); await chrome.downloads.erase({ id: item.id }); } catch (e) {}
      }                                            // app not running? let the browser download normally
    } catch (e) { console.error(e); }
    finally { suggest(); }
  })();
  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "sendToResumeFetch", title: "Send Link to Resume Fetch", contexts: ["link"] });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "sendToResumeFetch" && info.linkUrl)
    handoff({ url: info.linkUrl, referer: info.pageUrl || "", user_agent: navigator.userAgent });
});
