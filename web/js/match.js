import { Board } from "./board.js";
import { ws } from "./ws.js";

export class MatchController {
  constructor(getUserId) {
    this.getUserId = getUserId;
    this.mid = null;
    this.yourColor = null;
    this.board = new Board(document.getElementById("board-root"), {
      onMoveChosen: (seq) => this._submitMove(seq),
    });
    this.timerInterval = null;
    document.getElementById("btn-resign").addEventListener("click", () => this._resign());
  }

  start(mid) {
    this.mid = mid;
    this.yourColor = null;
    document.getElementById("match-result").hidden = true;
    document.getElementById("match-status").textContent = "Waiting for opponent…";
    document.getElementById("dice-display").innerHTML = "";
    this._clearTimer();
    this.board.render(null, [], null, false);
    ws.send({ type: "match_ready", mid });
  }

  handleMatchStart(msg) {
    if (msg.mid !== this.mid) return;
    this.yourColor = msg.your_color;
    document.getElementById("match-status").textContent = "Match started!";
  }

  handleDice(msg) {
    if (msg.mid !== this.mid) return;
    const el = document.getElementById("dice-display");
    el.innerHTML = `<div class="die">${msg.d1}</div><div class="die">${msg.d2}</div>`;
  }

  handleState(msg) {
    if (msg.mid !== this.mid) return;
    this.board.render(msg.game_state, msg.legal_moves, this.yourColor, msg.your_turn);
    document.getElementById("match-status").textContent = msg.your_turn
      ? "Your turn — click a checker, then a highlighted point."
      : "Opponent's turn…";
    this._startTimer(30);
  }

  handleMatchResult(msg) {
    if (msg.mid !== this.mid) return;
    this._clearTimer();
    const resultEl = document.getElementById("match-result");
    resultEl.hidden = false;
    const youWon = msg.winner_user_id && msg.winner_user_id === this.getUserId();
    resultEl.textContent = youWon
      ? `You won this match! (${msg.reason})`
      : `Match over — opponent won. (${msg.reason})`;
    document.getElementById("match-status").textContent = "Match finished.";
  }

  _submitMove(seq) {
    ws.send({ type: "move", mid: this.mid, seq });
  }

  _resign() {
    if (!this.mid) return;
    if (confirm("Resign this match?")) {
      ws.send({ type: "resign", mid: this.mid });
    }
  }

  _startTimer(seconds) {
    this._clearTimer();
    let remaining = seconds;
    const el = document.getElementById("match-timer");
    el.textContent = `${remaining}s`;
    this.timerInterval = setInterval(() => {
      remaining -= 1;
      el.textContent = remaining > 0 ? `${remaining}s` : "";
      if (remaining <= 0) this._clearTimer();
    }, 1000);
  }

  _clearTimer() {
    if (this.timerInterval) clearInterval(this.timerInterval);
    this.timerInterval = null;
    const el = document.getElementById("match-timer");
    if (el) el.textContent = "";
  }
}
