import { api, ApiError } from "./api.js";

export function initLobby({ onJoined }) {
  const grid = document.getElementById("room-grid");
  grid.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-room-id]");
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = "Joining…";
    try {
      const room = await api.joinRoom(btn.dataset.roomId);
      onJoined(room);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "Join";
      alert(err instanceof ApiError ? err.message : "Could not join room.");
    }
  });
}

export function renderRooms(rooms) {
  const grid = document.getElementById("room-grid");
  const bySize = new Map();
  for (const r of rooms) {
    if (!bySize.has(r.capacity)) bySize.set(r.capacity, []);
    bySize.get(r.capacity).push(r);
  }

  grid.innerHTML = "";
  for (const capacity of [...bySize.keys()].sort((a, b) => a - b)) {
    const list = bySize.get(capacity);
    const openest = list.find((r) => r.joined < r.capacity) || list[0];
    const card = document.createElement("div");
    card.className = "room-card";
    card.innerHTML = `
      <div class="cap">${capacity}</div>
      <div class="occ">${openest.joined} / ${openest.capacity} joined · ${list.length} open</div>
      <button data-room-id="${openest.id}">Join</button>
    `;
    grid.appendChild(card);
  }
}
