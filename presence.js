(function () {
  const endpoint = window.location.protocol === "file:"
    ? "http://127.0.0.1:4173/api/presence"
    : "/api/presence";
  const storageKey = "rakashii-presence-client-id";
  const heartbeatInterval = 7_000;

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

  const badge = document.createElement("div");
  badge.className = "presence-badge";
  badge.setAttribute("role", "status");
  badge.setAttribute("aria-live", "polite");
  badge.setAttribute("aria-label", "Users online now");
  badge.title = "Users online now";
  badge.innerHTML = `
    <span class="presence-mark" aria-hidden="true">
      <svg class="presence-user-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="7" r="4"></circle>
        <path d="M5.5 21a6.5 6.5 0 0 1 13 0"></path>
      </svg>
      <span class="presence-dot"></span>
    </span>
    <strong class="presence-count">--</strong>
  `;
  document.body.append(badge);

  const countOutput = badge.querySelector(".presence-count");
  const clientId = getClientId();

  async function sendHeartbeat() {
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clientId }),
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Presence request failed");
      const data = await response.json();
      countOutput.textContent = Number.isFinite(data.count) ? String(data.count) : "--";
      badge.dataset.status = "online";
    } catch {
      countOutput.textContent = "--";
      badge.dataset.status = "offline";
    }
  }

  sendHeartbeat();
  window.setInterval(sendHeartbeat, heartbeatInterval);
})();
