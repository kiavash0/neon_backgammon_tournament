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

export function renderRooms(rooms, myRoomId = null) {
  const grid = document.getElementById("room-grid");
  const bySize = new Map();
  for (const r of rooms) {
    if (!bySize.has(r.capacity)) bySize.set(r.capacity, []);
    bySize.get(r.capacity).push(r);
  }

  grid.innerHTML = "";
  for (const capacity of [...bySize.keys()].sort((a, b) => a - b)) {
    const list = bySize.get(capacity);
    // Show the room the user is already seated in, if it's this size —
    // otherwise the most joinable one.
    const mine = myRoomId ? list.find((r) => r.id === myRoomId) : null;
    const shown = mine || list.find((r) => r.joined < r.capacity) || list[0];
    const card = document.createElement("div");
    card.className = "room-card";
    const button = mine
      ? `<button disabled>Joined — waiting</button>`
      : `<button data-room-id="${shown.id}">Join</button>`;
    card.innerHTML = `
      <div class="cap">${capacity}</div>
      <div class="occ">${shown.joined} / ${shown.capacity} joined · ${list.length} open</div>
      ${button}
    `;
    grid.appendChild(card);
  }
}
