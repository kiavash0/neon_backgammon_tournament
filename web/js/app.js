import { api, isLoggedIn, clearTokens } from "./api.js";
import { ws } from "./ws.js";
import { initAuthScreen } from "./auth.js";
import { initLobby, renderRooms } from "./lobby.js";
import { renderBracket } from "./bracket.js";
import { MatchController } from "./match.js";

const screens = ["auth", "lobby", "bracket", "match"];
let currentUser = null;
let currentTournamentId = null;
let countdownInterval = null;

function showScreen(name) {
  for (const s of screens) {
    document.getElementById(`screen-${s}`).classList.toggle("active", s === name);
  }
  document.getElementById("topnav").hidden = name === "auth";
}

function startCountdown(seconds) {
  stopCountdown();
  const container = document.getElementById("bracket-countdown");
  const numberEl = document.getElementById("countdown-number");
  const labelEl = document.getElementById("countdown-label");
  container.hidden = false;
  labelEl.textContent = "Get ready…";

  let remaining = Math.max(0, Math.ceil(seconds));
  numberEl.textContent = remaining;
  countdownInterval = setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      numberEl.textContent = "0";
      labelEl.textContent = "Starting your match…";
      clearInterval(countdownInterval);
      countdownInterval = null;
      return;
    }
    numberEl.textContent = remaining;
  }, 1000);
}

function stopCountdown() {
  if (countdownInterval) clearInterval(countdownInterval);
  countdownInterval = null;
  document.getElementById("bracket-countdown").hidden = true;
}

async function refreshBalance() {
  try {
    const me = await api.me();
    currentUser = me;
    document.getElementById("balance-display").textContent = `$${me.balance_usd.toFixed(2)}`;
  } catch {
    // ignore transient failures; balance just won't update this tick
  }
}

async function showLobby() {
  stopCountdown();
  showScreen("lobby");
  await refreshBalance();
  try {
    const { rooms } = await api.lobby();
    renderRooms(rooms);
  } catch (err) {
    console.error("failed to load lobby", err);
  }
}

async function onLoggedIn() {
  await refreshBalance();
  ws.connect();
  showLobby();
}

function logout() {
  stopCountdown();
  clearTokens();
  ws.close();
  currentUser = null;
  showScreen("auth");
}

async function main() {
  initAuthScreen({ onLoggedIn });
  initLobby({
    onJoined: () => {
      // If the room just filled, the server-pushed `tournament_start` WS
      // message (already wired below) will switch screens on its own.
      // Otherwise just refresh so the joined room's occupancy updates.
      showLobby();
    },
  });

  const matchController = new MatchController(() => currentUser?.id);

  document.getElementById("nav-lobby").addEventListener("click", (e) => {
    e.preventDefault();
    showLobby();
  });
  document.getElementById("nav-logout").addEventListener("click", (e) => {
    e.preventDefault();
    logout();
  });
  document.getElementById("bracket-back").addEventListener("click", () => showLobby());

  ws.on("room_update", async () => {
    if (document.getElementById("screen-lobby").classList.contains("active")) {
      try {
        const { rooms } = await api.lobby();
        renderRooms(rooms);
      } catch {
        /* ignore */
      }
    }
  });

  ws.on("tournament_start", async (msg) => {
    currentTournamentId = msg.tid;
    showScreen("bracket");
    document.getElementById("bracket-status").textContent = `${msg.capacity}-player tournament`;
    startCountdown(msg.get_ready_seconds ?? 0);
    ws.send({ type: "subscribe_tournament", tid: msg.tid });
  });

  ws.on("bracket_update", (msg) => {
    if (msg.tid !== currentTournamentId) return;
    renderBracket(msg.tid, msg.bracket);
  });

  ws.on("round_start", (msg) => {
    stopCountdown();
    showScreen("match");
    matchController.start(msg.mid);
  });

  ws.on("match_start", (msg) => matchController.handleMatchStart(msg));
  ws.on("dice", (msg) => matchController.handleDice(msg));
  ws.on("state", (msg) => matchController.handleState(msg));
  ws.on("opponent_move", (msg) => matchController.handleOpponentMove(msg));
  ws.on("match_result", (msg) => {
    matchController.handleMatchResult(msg);
    refreshBalance();
  });

  ws.on("tournament_result", (msg) => {
    stopCountdown();
    refreshBalance();
    const el = document.getElementById("bracket-status");
    if (el) {
      const youWon = currentUser && msg.winner_user_id === currentUser.id;
      el.textContent = youWon
        ? `You are the champion! Prize: $${msg.prize_usd_est.toFixed(2)}`
        : `Tournament finished. Prize pool: $${msg.prize_usd_est.toFixed(2)}`;
    }
  });

  ws.on("error", (msg) => {
    console.warn("server error:", msg.code, msg.msg);
    matchController.clearSubmitting();
  });

  if (isLoggedIn()) {
    await onLoggedIn();
  } else {
    showScreen("auth");
  }
}

main();
