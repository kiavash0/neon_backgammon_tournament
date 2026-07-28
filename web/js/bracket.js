import { api } from "./api.js";

function short(id) {
  return id ? `Player ${id.slice(0, 6)}` : "TBD";
}

export async function renderBracket(tid, bracket, status) {
  const container = document.getElementById("bracket-view");
  const statusEl = document.getElementById("bracket-status");
  statusEl.textContent = `Status: ${status}`;
  container.innerHTML = "";

  const rounds = Object.keys(bracket.rounds || {})
    .map(Number)
    .sort((a, b) => a - b);

  for (const roundNum of rounds) {
    const col = document.createElement("div");
    col.className = "bracket-round";
    const matchIds = bracket.rounds[String(roundNum)];
    const matches = await Promise.all(matchIds.map((mid) => api.tournamentMatch(tid, mid)));
    for (const m of matches) {
      const div = document.createElement("div");
      div.className = "bracket-match";
      const whiteWon = m.winner_id && m.winner_id === m.player_white_id;
      const blackWon = m.winner_id && m.winner_id === m.player_black_id;
      div.innerHTML = `
        <div class="p ${whiteWon ? "winner" : ""}">${short(m.player_white_id)}</div>
        <div class="p ${blackWon ? "winner" : ""}">${short(m.player_black_id)}</div>
      `;
      col.appendChild(div);
    }
    container.appendChild(col);
  }
}
