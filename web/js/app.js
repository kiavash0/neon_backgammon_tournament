import { api, isLoggedIn, clearTokens } from "./api.js";
import { ws } from "./ws.js";
import { initAuthScreen } from "./auth.js";
import { initLobby, renderRooms } from "./lobby.js";
import { renderBracket } from "./bracket.js";
import { MatchController } from "./match.js";
import { Board3D } from "./board3d.js";
import {
  boardUrl,
  checkersUrl,
  diceCupUrl,
  diceUrl,
  getPrefs,
  populateThemeSelectors,
  setPrefs,
  STARTING_STATE,
} from "./theme.js";

const screens = ["auth", "lobby", "bracket", "match"];
let currentUser = null;
let currentTournamentId = null;
let countdownInterval = null;
let matchController = null;

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

let lobbyBannerAction = null;

function renderLobbyBanner() {
  const banner = document.getElementById("lobby-banner");
  const text = document.getElementById("lobby-banner-text");
  const button = document.getElementById("lobby-banner-action");
  const room = currentUser?.current_room;

  if (!room) {
    banner.hidden = true;
    lobbyBannerAction = null;
    return;
  }

  banner.hidden = false;
  if (room.state === "OPEN") {
    text.textContent =
      `You're registered in a ${room.capacity}-player room ` +
      `(${room.joined}/${room.capacity}) — it starts when it fills.`;
    button.textContent = "Leave room";
    lobbyBannerAction = async () => {
      try {
        await api.leaveRoom(room.id);
      } catch {
        /* stale registration; refresh below clears it */
      }
      showLobby();
    };
  } else if (currentUser.active_match_id) {
    text.textContent = "You have a tournament match in progress.";
    button.textContent = "Rejoin match";
    lobbyBannerAction = () => {
      currentTournamentId = currentUser.active_tournament_id;
      ws.send({ type: "subscribe_tournament", tid: currentTournamentId });
      showScreen("match");
      matchController.start(currentUser.active_match_id);
    };
  } else {
    text.textContent = "Your tournament is running — waiting for your next round.";
    button.textContent = "View bracket";
    lobbyBannerAction = () => {
      currentTournamentId = currentUser.active_tournament_id;
      if (currentTournamentId) ws.send({ type: "subscribe_tournament", tid: currentTournamentId });
      showScreen("bracket");
    };
  }
}

async function showLobby() {
  stopCountdown();
  showScreen("lobby");
  await refreshBalance();
  renderLobbyBanner();
  try {
    const { rooms } = await api.lobby();
    renderRooms(rooms, currentUser?.current_room?.id);
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

let themeManifest = null;
let themePreviewBoard = null;

async function initThemePicker() {
  const { manifest } = await populateThemeSelectors();
  themeManifest = manifest;

  themePreviewBoard = new Board3D(document.getElementById("theme-preview"), {
    onMoveChosen: () => {}, // decorative — never interactive
  });

  const applyPreview = async () => {
    const current = getPrefs(themeManifest);
    await themePreviewBoard.setTheme({
      boardUrl: boardUrl(themeManifest, current.board),
      checkersUrl: checkersUrl(themeManifest, current.checkers),
      diceUrl: diceUrl(themeManifest, current.dice),
      diceCupUrl: diceCupUrl(themeManifest),
    });
    themePreviewBoard.render(structuredClone(STARTING_STATE), [], 1, false);
  };

  const boardSel = document.getElementById("theme-board");
  const checkersSel = document.getElementById("theme-checkers");
  const diceSel = document.getElementById("theme-dice");

  const onChange = async () => {
    setPrefs({ board: boardSel.value, checkers: checkersSel.value, dice: diceSel.value });
    await applyPreview();
    if (matchController) await matchController.reloadTheme();
  };
  boardSel.addEventListener("change", onChange);
  checkersSel.addEventListener("change", onChange);
  diceSel.addEventListener("change", onChange);

  await applyPreview();
}

async function main() {
  matchController = new MatchController(() => currentUser?.id);
  initThemePicker().catch((err) => console.error("theme picker failed to load", err));

  initAuthScreen({ onLoggedIn });
  initLobby({
    onJoined: () => {
      // If the room just filled, the server-pushed `tournament_start` WS
      // message (already wired below) switches screens on its own — and
      // may well have already fired by the time this join POST resolves.
      // Calling showLobby() unconditionally would race it and stomp the
      // bracket screen right back to the lobby for whoever's own click
      // was the one that filled the room. Only refresh if we're still here.
      if (document.getElementById("screen-lobby").classList.contains("active")) {
        showLobby();
      }
    },
  });

  document.getElementById("lobby-banner-action").addEventListener("click", () => {
    if (lobbyBannerAction) lobbyBannerAction();
  });

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
        renderRooms(rooms, currentUser?.current_room?.id);
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
