(function () {
  const endpoint = window.location.protocol === "file:"
    ? "http://127.0.0.1:4173/api/presence"
    : "/api/presence";
  const storageKey = "rakashii-presence-client-id";
  const heartbeatInterval = 7_000;
  const tool = document.body.dataset.presenceTool || "";
  const toolOrder = ["views-calculator", "video-downloader", "drive-clipper"];
  const toolLabels = {
    "views-calculator": "Views and Earnings Calculator",
    "video-downloader": "Video Downloader",
    "drive-clipper": "Drive Clipper",
  };

  function getClientId() {
    try {
      let clientId = localStorage.getItem(storageKey);
      if (!clientId) {
        clientId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
        localStorage.setItem(storageKey, clientId);
      }
      return clientId;
    } catch {
      return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }
  }

  const badge = document.createElement("button");
  badge.className = "presence-badge";
  badge.type = "button";
  badge.setAttribute("aria-label", "Show active users by tool");
  badge.setAttribute("aria-expanded", "false");
  badge.innerHTML = `
    <span class="presence-summary">
      <span class="presence-mark" aria-hidden="true">
        <svg class="presence-user-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="7" r="4"></circle>
          <path d="M5.5 21a6.5 6.5 0 0 1 13 0"></path>
        </svg>
        <span class="presence-dot"></span>
      </span>
      <strong class="presence-count">--</strong>
    </span>
    <span class="presence-tooltip" role="status" aria-live="polite" hidden></span>
  `;
  document.body.append(badge);

  const countOutput = badge.querySelector(".presence-count");
  const tooltip = badge.querySelector(".presence-tooltip");
  const clientId = getClientId();

  function renderToolCounts(counts) {
    const activeTools = toolOrder
      .map((toolName) => ({ name: toolName, count: Number(counts?.[toolName]) || 0 }))
      .filter((item) => item.count > 0);

    tooltip.innerHTML = activeTools.length
      ? activeTools.map((item) => `<span class="presence-tool-row"><span>${toolLabels[item.name]}</span><strong>${item.count}</strong></span>`).join("")
      : "<span class=\"presence-empty\">No tool users are active.</span>";
  }

  function setDetailsVisible(visible) {
    tooltip.hidden = !visible;
    badge.setAttribute("aria-expanded", String(visible));
  }

  async function sendHeartbeat() {
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clientId, tool }),
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Presence request failed");
      const data = await response.json();
      countOutput.textContent = Number.isFinite(data.count) ? String(data.count) : "--";
      renderToolCounts(data.counts);
      badge.dataset.status = "online";
    } catch {
      countOutput.textContent = "--";
      renderToolCounts({});
      badge.dataset.status = "offline";
    }
  }

  badge.addEventListener("mouseenter", () => setDetailsVisible(true));
  badge.addEventListener("mouseleave", () => setDetailsVisible(false));
  badge.addEventListener("focusin", () => setDetailsVisible(true));
  badge.addEventListener("focusout", (event) => {
    if (!badge.contains(event.relatedTarget)) setDetailsVisible(false);
  });
  badge.addEventListener("click", () => setDetailsVisible(tooltip.hidden));

  sendHeartbeat();
  window.setInterval(sendHeartbeat, heartbeatInterval);
})();
