(() => {
  const overlays = new Map();
  const http = url => /^https?:\/\//i.test(url || "");
  const preferPage = () => /(^|\.)(youtube\.com|youtu\.be)$/i.test(location.hostname);
  async function send(url, status) {
    status.textContent = "Sending…";
    try {
      const reply = await chrome.runtime.sendMessage({action: "download", url});
      status.textContent = reply.status === "ok" ? "Added to IDM Clone" : reply.message;
    } catch (error) {
      status.textContent = "Extension reloaded. Refresh this page and retry.";
    }
  }
  function attach(video) {
    if (overlays.has(video)) return;
    const host = document.createElement("div");
    host.style.cssText = "position:absolute;z-index:2147483647;display:none;";
    const shadow = host.attachShadow({mode: "closed"});
    shadow.innerHTML = `<style>
      :host {font:13px Arial,sans-serif;color:#fff;}
      button {background:#176b3a;color:white;border:1px solid #86dca9;border-radius:6px;padding:7px 10px;cursor:pointer;font:13px Arial,sans-serif;}
      .menu {display:none;background:#17202a;border-radius:6px;padding:8px;max-width:320px;max-height:230px;overflow:auto;}
      .menu button {display:block;margin-bottom:5px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
      .status {max-width:300px;white-space:normal;overflow-wrap:anywhere;font:12px Arial,sans-serif;}
    </style><button class="download">↓ Download this video</button><div class="menu"><div class="choices"></div><div class="status" role="status"></div></div>`;
    const menu = shadow.querySelector(".menu");
    const choices = shadow.querySelector(".choices");
    const status = shadow.querySelector(".status");
    shadow.querySelector(".download").addEventListener("click", async event => {
      event.preventDefault();
      event.stopPropagation();
      menu.style.display = "block";
      choices.replaceChildren();
      status.textContent = "Finding video…";
      const direct = video.currentSrc || video.src || video.querySelector("source[src]")?.src;
      if (http(direct) && !preferPage()) {
        await send(direct, status);
        return;
      }
      try {
        const result = await chrome.runtime.sendMessage({action: "media"});
        const media = preferPage() ? [] : result.media || [];
        for (const [index, item] of media.entries()) {
          const button = document.createElement("button");
          button.textContent = `Source ${index + 1}: ${new URL(item.url).pathname.split("/").pop() || item.type}`;
          button.title = item.url;
          button.addEventListener("click", () => send(item.url, status));
          choices.append(button);
        }
        const page = document.createElement("button");
        page.textContent = "Resolve video from this page";
        page.addEventListener("click", () => send(location.href, status));
        choices.append(page);
        status.textContent = media.length ? "Choose a media source or resolve the page." : "Use page resolution for streamed videos. Protected videos may be unavailable.";
      } catch (error) {
        status.textContent = "Refresh the page after reloading the extension.";
      }
    });
    document.documentElement.append(host);
    overlays.set(video, host);
  }
  function update() {
    document.querySelectorAll("video").forEach(attach);
    for (const [video, host] of overlays) {
      if (!video.isConnected) { host.remove(); overlays.delete(video); continue; }
      const rect = video.getBoundingClientRect();
      const visible = rect.width > 100 && rect.height > 60 && rect.bottom > 0 && rect.top < innerHeight;
      host.style.display = visible ? "block" : "none";
      host.style.left = `${Math.max(0, rect.left + scrollX + 8)}px`;
      host.style.top = `${Math.max(0, rect.top + scrollY + 8)}px`;
    }
  }
  update();
  setInterval(update, 750);
  addEventListener("scroll", update, {passive: true});
  addEventListener("resize", update, {passive: true});
})();
