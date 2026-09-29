const HOST = "com.idmclone.host";
const validUrl = value => typeof value === "string" && /^https?:\/\//i.test(value);
let storageQueue = Promise.resolve();
function changeMedia(operation) {
  storageQueue = storageQueue.then(operation).catch(console.error);
  return storageQueue;
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => chrome.contextMenus.create({
    id: "download-with-idm", title: "Download with IDM Clone", contexts: ["link", "video", "audio", "image"]
  }));
});

async function sendToNativeHost(message) {
  try {
    const response = await chrome.runtime.sendNativeMessage(HOST, message);
    if (response?.status !== "ok") throw new Error(response?.message || "No acknowledgement from the desktop app");
    await chrome.action.setBadgeText({text: ""});
    await chrome.storage.local.remove("lastError");
    return response;
  } catch (error) {
    const message = `${error.message}. Open BrowserSetup.exe and register this extension ID if setup is incomplete.`;
    await chrome.storage.local.set({lastError: message});
    await chrome.action.setBadgeText({text: "!"});
    await chrome.action.setBadgeBackgroundColor({color: "#b42318"});
    return {status: "error", message};
  }
}

async function requestDownload(url, referrer, userAgent) {
  if (!validUrl(url)) return {status: "error", message: "This is a browser-only URL. Use the video-page download option instead."};
  const headers = {};
  if (validUrl(referrer)) headers.Referer = referrer;
  if (userAgent) headers["User-Agent"] = userAgent;
  return sendToNativeHost({action: "download", url, headers});
}

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "download-with-idm") {
    const source = info.srcUrl || info.linkUrl;
    requestDownload(validUrl(source) ? source : info.frameUrl || info.pageUrl, info.frameUrl || info.pageUrl, navigator.userAgent);
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message.action === "download") {
      return requestDownload(message.url, sender.url || message.referrer, navigator.userAgent);
    }
    if (message.action === "open") return sendToNativeHost({action: "open"});
    if (message.action === "media") {
      await storageQueue;
      const tabId = sender.tab?.id ?? message.tabId;
      const data = await chrome.storage.session.get(`media-${tabId}`);
      let media = data[`media-${tabId}`] || [];
      if (sender.tab) media = media.filter(item => item.frameId === sender.frameId);
      return {status: "ok", media};
    }
    return {status: "error", message: "Unknown request"};
  })().then(sendResponse).catch(error => sendResponse({status: "error", message: error.message}));
  return true;
});

chrome.webRequest.onHeadersReceived.addListener(details => {
  if (details.tabId < 0) return;
  const key = `media-${details.tabId}`;
  if (details.type === "main_frame") {
    changeMedia(() => chrome.storage.session.remove(key));
    return;
  }
  if (details.type === "sub_frame") {
    changeMedia(async () => {
      const state = await chrome.storage.session.get(key);
      await chrome.storage.session.set({[key]: (state[key] || []).filter(item => item.frameId !== details.frameId)});
    });
    return;
  }
  const type = details.responseHeaders?.find(header => header.name.toLowerCase() === "content-type")?.value || "";
  const path = new URL(details.url).pathname;
  if (/\.(ts|m4s|vtt|key)$/i.test(path) || details.statusCode >= 400) return;
  if (!/^(video\/|audio\/)|mpegurl|dash\+xml/i.test(type) && !/\.(mp4|webm|m3u8|mpd|mp3|m4a)$/i.test(path)) return;
  changeMedia(async () => {
    const state = await chrome.storage.session.get(key);
    const media = (state[key] || []).filter(item => item.url !== details.url);
    media.push({url: details.url, type, frameId: details.frameId, referrer: details.initiator});
    await chrome.storage.session.set({[key]: media.slice(-40)});
  });
}, {urls: ["http://*/*", "https://*/*"]}, ["responseHeaders"]);

chrome.tabs.onRemoved.addListener(tabId => changeMedia(() => chrome.storage.session.remove(`media-${tabId}`)));

// Opt-in handoff. Keep the browser's download when the desktop bridge fails.
chrome.downloads.onCreated.addListener(async item => {
  const {captureDownloads = false} = await chrome.storage.local.get("captureDownloads");
  if (!captureDownloads || !validUrl(item.finalUrl || item.url) || item.byExtensionId) return;
  let paused = false;
  try {
    await chrome.downloads.pause(item.id);
    paused = true;
    const result = await requestDownload(item.finalUrl || item.url, item.referrer, navigator.userAgent);
    if (result.status === "ok") {
      await chrome.downloads.cancel(item.id);
    } else {
      await chrome.downloads.resume(item.id);
    }
  } catch (error) {
    if (paused) await chrome.downloads.resume(item.id).catch(() => {});
    console.warn("Browser download was kept:", error.message);
  }
});
