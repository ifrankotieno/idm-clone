const status = document.getElementById("status");
async function request(message) {
  status.textContent = "Connecting…";
  try {
    const response = await chrome.runtime.sendMessage(message);
    status.textContent = response.status === "ok" ? "Accepted by IDM Clone" : response.message;
  } catch (error) { status.textContent = error.message; }
}
document.getElementById("extensionId").textContent = `Setup extension ID: ${chrome.runtime.id}`;
document.getElementById("openApp").onclick = () => request({action: "open"});
document.getElementById("capture").onchange = event => chrome.storage.local.set({captureDownloads: event.target.checked});
(async () => {
  const settings = await chrome.storage.local.get(["captureDownloads", "lastError"]);
  document.getElementById("capture").checked = settings.captureDownloads || false;
  status.textContent = settings.lastError || "";
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  document.getElementById("page").onclick = () => request({action: "download", url: tab.url, referrer: tab.url});
  const result = await chrome.runtime.sendMessage({action: "media", tabId: tab.id});
  for (const [index, media] of (result.media || []).entries()) {
    const button = document.createElement("button");
    button.className = "source";
    button.textContent = `Media ${index + 1}: ${new URL(media.url).pathname.split("/").pop() || media.type}`;
    button.title = media.url;
    button.onclick = () => request({action: "download", url: media.url, referrer: tab.url});
    document.getElementById("sources").append(button);
  }
})();
