const SVG_NS = "http://www.w3.org/2000/svg";
const WIDTH = 820;
const HEIGHT = 500;
const COL_W = 55;
const BAR_W = 40;
const BOARD_LEFT = 50;
const BOARD_TOP = 40;
const BOARD_BOTTOM = 460;
const TRI_H = 160;
const CHECKER_R = 17;
const OFF_X = 792;

// Standard backgammon layout matching the engine's point numbering (SPEC §4.1):
// index i == point (i+1). White home = points 1-6 (index 0-5), bears off toward
// index -1; Black home = points 19-24 (index 18-23), bears off toward index 24.
const TOP_ROW = [12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]; // indices, left->right
const BOTTOM_ROW = [11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]; // indices, left->right

function slotX(col) {
  return col < 6 ? BOARD_LEFT + col * COL_W : BOARD_LEFT + 6 * COL_W + BAR_W + (col - 6) * COL_W;
}

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

export class Board {
  constructor(rootEl, { onMoveChosen }) {
    this.rootEl = rootEl;
    this.onMoveChosen = onMoveChosen;
    this.state = null; // last authoritative state from the server
    this.displayState = null; // state + locally-applied picks this turn, for instant feedback
    this.legalMoves = [];
    this.yourColor = 1;
    this.yourTurn = false;
    this.prefix = [];
    this.selectedFrom = null;
  }

  render(gameState, legalMoves, yourColor, yourTurn) {
    this.state = gameState;
    this.displayState = gameState ? JSON.parse(JSON.stringify(gameState)) : null;
    this.legalMoves = legalMoves || [];
    this.yourColor = yourColor;
    this.yourTurn = yourTurn;
    this.prefix = [];
    this.selectedFrom = null;
    this._draw();
  }

  // Mirrors the server engine's single-atomic-move application (SPEC §4.5
  // apply_move) just enough to update the board instantly, before the
  // server round-trip confirms it.
  _applyLocal(move, color) {
    const [frm, to] = move;
    const s = this.displayState;
    const points = s.points.slice();

    if (frm === "bar") {
      if (color === 1) s.bar_white -= 1;
      else s.bar_black -= 1;
    } else {
      points[frm] -= color;
    }

    if (to === "off") {
      if (color === 1) s.off_white += 1;
      else s.off_black += 1;
    } else {
      if (points[to] * color < 0) {
        if (color === 1) s.bar_black += 1;
        else s.bar_white += 1;
        points[to] = 0;
      }
      points[to] += color;
    }

    s.points = points;
  }

  _candidates() {
    return this.legalMoves.filter((seq) =>
      this.prefix.every((mv, i) => seq[i] && seq[i][0] === mv[0] && seq[i][1] === mv[1] && seq[i][2] === mv[2])
    );
  }

  _fromTargets() {
    const idx = this.prefix.length;
    const froms = new Set();
    for (const seq of this._candidates()) {
      if (seq.length > idx) froms.add(seq[idx][0]);
    }
    return froms;
  }

  _toTargetsFor(from) {
    const idx = this.prefix.length;
    const moves = [];
    for (const seq of this._candidates()) {
      if (seq.length > idx && seq[idx][0] === from) moves.push(seq[idx]);
    }
    return moves;
  }

  _pick(from, to) {
    const options = this._toTargetsFor(from);
    const match = options.find((mv) => mv[1] === to);
    if (!match) return;
    this.prefix.push(match);
    this.selectedFrom = null;
    this._applyLocal(match, this.yourColor); // move this checker on screen right now

    // Each atomic move is submitted to the server independently, the moment
    // it's picked — never buffered into an end-of-turn batch. `done` just
    // tells the controller the turn has no continuations left.
    const remaining = this._candidates();
    const done = remaining.every((seq) => seq.length === this.prefix.length);
    this.onMoveChosen([match], done);
    this._draw();
  }

  // A single move made by the opponent, pushed live from the server.
  applyRemote(move) {
    if (!this.displayState) return;
    this._applyLocal(move, -this.yourColor);
    this._draw();
  }

  _draw() {
    this.rootEl.innerHTML = "";
    const svg = svgEl("svg", { viewBox: `0 0 ${WIDTH} ${HEIGHT}`, width: "100%" });
    svg.appendChild(svgEl("rect", { x: 0, y: 0, width: WIDTH, height: HEIGHT, fill: "#0d0d18", rx: 12 }));
    svg.appendChild(
      svgEl("rect", {
        x: BOARD_LEFT + 6 * COL_W,
        y: BOARD_TOP,
        width: BAR_W,
        height: BOARD_BOTTOM - BOARD_TOP,
        fill: "#1a1a2e",
      })
    );

    if (!this.displayState) {
      this.rootEl.appendChild(svg);
      return;
    }

    const interactive = this.yourTurn && this.legalMoves.length > 0;
    const fromTargets = interactive ? this._fromTargets() : new Set();
    const toTargets = interactive && this.selectedFrom !== null ? this._toTargetsFor(this.selectedFrom) : [];
    const toIndexSet = new Set(toTargets.map((mv) => mv[1]));

    TOP_ROW.forEach((idx, col) => this._drawPoint(svg, idx, col, "top", fromTargets, toIndexSet));
    BOTTOM_ROW.forEach((idx, col) => this._drawPoint(svg, idx, col, "bottom", fromTargets, toIndexSet));

    this._drawBar(svg, fromTargets);
    this._drawOff(svg, toIndexSet);

    this.rootEl.appendChild(svg);
  }

  _drawPoint(svg, idx, col, side, fromTargets, toIndexSet) {
    const x = slotX(col);
    const isSelectableFrom = fromTargets.has(idx);
    const isTarget = toIndexSet.has(idx);
    const g = svgEl("g", {
      class: `point${isSelectableFrom ? " selectable" : ""}${isTarget ? " target" : ""}`,
      "data-point": idx,
    });

    const points =
      side === "top"
        ? `${x},${BOARD_TOP} ${x + COL_W},${BOARD_TOP} ${x + COL_W / 2},${BOARD_TOP + TRI_H}`
        : `${x},${BOARD_BOTTOM} ${x + COL_W},${BOARD_BOTTOM} ${x + COL_W / 2},${BOARD_BOTTOM - TRI_H}`;
    const fill = (side === "top" ? TOP_ROW.indexOf(idx) : BOTTOM_ROW.indexOf(idx)) % 2 === 0 ? "#1c2333" : "#241a33";
    g.appendChild(svgEl("polygon", { points, fill, class: "point-tri" }));

    const count = this.displayState.points[idx];
    if (count !== 0) {
      const color = count > 0 ? "white" : "black";
      const n = Math.abs(count);
      const cx = x + COL_W / 2;
      for (let i = 0; i < Math.min(n, 5); i++) {
        const cy = side === "top" ? BOARD_TOP + 20 + i * 34 : BOARD_BOTTOM - 20 - i * 34;
        g.appendChild(svgEl("circle", { cx, cy, r: CHECKER_R, class: `checker ${color}` }));
      }
      if (n > 5) {
        const cy = side === "top" ? BOARD_TOP + 20 + 4 * 34 : BOARD_BOTTOM - 20 - 4 * 34;
        const label = svgEl("text", {
          x: cx,
          y: cy + 5,
          "text-anchor": "middle",
          fill: color === "white" ? "#0a0a12" : "#fff",
          "font-size": 13,
          "font-weight": 700,
        });
        label.textContent = `+${n - 4}`;
        g.appendChild(label);
      }
    }

    g.addEventListener("click", () => this._onPointClick(idx));
    svg.appendChild(g);
  }

  _onPointClick(idx) {
    if (!this.yourTurn || this.legalMoves.length === 0) return;
    if (this.selectedFrom === null) {
      if (this._fromTargets().has(idx)) {
        const options = this._toTargetsFor(idx);
        if (options.length === 1) {
          this._pick(idx, options[0][1]);
        } else {
          this.selectedFrom = idx;
          this._draw();
        }
      }
    } else if (this._toTargetsFor(this.selectedFrom).some((mv) => mv[1] === idx)) {
      this._pick(this.selectedFrom, idx);
    } else if (idx === this.selectedFrom) {
      this.selectedFrom = null;
      this._draw();
    }
  }

  _drawBar(svg, fromTargets) {
    const x = BOARD_LEFT + 6 * COL_W + BAR_W / 2;
    const barSelectable = fromTargets.has("bar");
    const g = svgEl("g", { class: `point${barSelectable ? " selectable" : ""}`, "data-point": "bar" });

    // Always-present, invisible hit area: without this, an empty bar (no
    // checkers rendered yet) has no shape for the click listener to land
    // on, and the background bar rect underneath intercepts the click.
    g.appendChild(
      svgEl("rect", {
        x: x - BAR_W / 2,
        y: BOARD_TOP,
        width: BAR_W,
        height: BOARD_BOTTOM - BOARD_TOP,
        fill: "transparent",
      })
    );

    if (this.displayState.bar_white > 0) {
      for (let i = 0; i < this.displayState.bar_white; i++) {
        g.appendChild(svgEl("circle", { cx: x, cy: HEIGHT / 2 - 30 - i * 34, r: CHECKER_R, class: "checker white" }));
      }
    }
    if (this.displayState.bar_black > 0) {
      for (let i = 0; i < this.displayState.bar_black; i++) {
        g.appendChild(svgEl("circle", { cx: x, cy: HEIGHT / 2 + 30 + i * 34, r: CHECKER_R, class: "checker black" }));
      }
    }
    g.addEventListener("click", () => this._onPointClick("bar"));
    svg.appendChild(g);
  }

  _drawOff(svg, toIndexSet) {
    const isTarget = toIndexSet.has("off");
    const g = svgEl("g", { class: `point${isTarget ? " target" : ""}`, "data-point": "off" });
    g.appendChild(
      svgEl("rect", { x: OFF_X, y: BOARD_TOP, width: 20, height: BOARD_BOTTOM - BOARD_TOP, fill: "#161624", rx: 6 })
    );
    const whiteLabel = svgEl("text", {
      x: OFF_X + 10,
      y: BOARD_TOP + 24,
      "text-anchor": "middle",
      fill: "#f4f4ff",
      "font-size": 14,
      "font-weight": 700,
    });
    whiteLabel.textContent = this.displayState.off_white;
    const blackLabel = svgEl("text", {
      x: OFF_X + 10,
      y: BOARD_BOTTOM - 12,
      "text-anchor": "middle",
      fill: "#f4f4ff",
      "font-size": 14,
      "font-weight": 700,
    });
    blackLabel.textContent = this.displayState.off_black;
    g.appendChild(whiteLabel);
    g.appendChild(blackLabel);
    g.addEventListener("click", () => this._onPointClick("off"));
    svg.appendChild(g);
  }
}
