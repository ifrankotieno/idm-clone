// Create right-click menu
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "download-with-idm",
    title: "Download with IDM Clone",
    contexts: ["link", "video", "audio", "image"]
  });
});

// Handle right-click
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "download-with-idm") {
    const url = info.linkUrl || info.srcUrl;
    if (url) {
      sendToNativeHost({ action: "download", url: url });
    }
  }
});

// Listen for messages from content script (for video detection later)
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "download") {
    sendToNativeHost({ action: "download", url: message.url });
    sendResponse({ status: "sent" });
  }
});

// Send message to Native Host
function sendToNativeHost(message) {
  const hostName = "com.idmclone.host";

  chrome.runtime.sendNativeMessage(hostName, message, (response) => {
    if (chrome.runtime.lastError) {
      console.error("Native Messaging Error:", chrome.runtime.lastError.message);
      // Optional: show notification
    } else {
      console.log("Response from native host:", response);
    }
  });
}