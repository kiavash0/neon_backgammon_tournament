import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const loader = new GLTFLoader();
const gltfCache = new Map(); // url -> Promise<GLTF>

function loadGltf(url) {
  if (!gltfCache.has(url)) {
    gltfCache.set(
      url,
      new Promise((resolve, reject) => loader.load(url, resolve, undefined, reject))
    );
  }
  return gltfCache.get(url);
}

function findByName(root, name) {
  let found = null;
  root.traverse((obj) => {
    if (!found && obj.name === name) found = obj;
  });
  return found;
}

function findAllByPrefix(root, prefix) {
  const out = [];
  root.traverse((obj) => {
    if (obj.name && obj.name.startsWith(prefix)) out.push(obj);
  });
  return out;
}

const CHECKER_STACK_FIRST = 0.028;
const CHECKER_STACK_STEP = 0.037;
const CHECKER_HALF_HEIGHT = 0.0045;
// A point/bar visually fits LAYER_SIZE checkers in one row before the next
// checker piles on top (a new vertical layer), same as a real board — not
// an arbitrary display cutoff. Only beyond MAX_LAYERS worth do we fall back
// to a "+N" label, purely so a 15-high stack doesn't run off the board.
const LAYER_SIZE = 5;
const MAX_LAYERS = 3;
const MAX_STACKED = LAYER_SIZE * MAX_LAYERS;
const CHECKER_LAYER_HEIGHT = CHECKER_HALF_HEIGHT * 2 + 0.001;

// Where thrown dice land: the mover's own home board, right side (positive
// x is "right" for both players under the fixed-camera/world-mirror scheme),
// and safely inside the board's actual footprint (points reach z ~0.204,
// the base edge ~0.24) rather than past its edge.
const DICE_LAND_X = 0.15;
const DICE_LAND_Z = 0.13;

// Which LOCAL axis of the die_1 rigid body (cube + baked pips) each rolled
// value sits on — decoded directly from the asset's actual pip node
// positions (grouped by face-normal axis, then pip count per group), not
// guessed. Consistent across all four dice color themes. Real dice always
// have opposite faces summing to 7 (1<->6, 2<->5, 3<->4), confirmed here.
const DIE_FACE_LOCAL_AXIS = {
  1: new THREE.Vector3(0, 1, 0),
  6: new THREE.Vector3(0, -1, 0),
  3: new THREE.Vector3(0, 0, 1),
  4: new THREE.Vector3(0, 0, -1),
  2: new THREE.Vector3(1, 0, 0),
  5: new THREE.Vector3(-1, 0, 0),
};
const WORLD_UP = new THREE.Vector3(0, 1, 0);

export class Board3D {
  constructor(rootEl, { onMoveChosen }) {
    this.rootEl = rootEl;
    this.onMoveChosen = onMoveChosen;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.05, 10);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.rootEl.appendChild(this.renderer.domElement);

    this._addLights();

    this.boardGroup = null; // loaded board scene
    this.pointWorldPos = new Map(); // 1..24 -> THREE.Vector3
    this.barWorldPos = new THREE.Vector3(0, 0.035, 0);
    this.checkerTemplates = null; // { light: Mesh, dark: Mesh }
    this.dieTemplate = null; // Mesh (cube)
    this.cupGroup = null;

    // Both home boards sit on the SAME physical x-side of this asset's board
    // (split by z, not x — see ADR), so relocating the camera to "the other
    // end of the table" for Black would flip left/right too (Black's home
    // would land bottom-LEFT). Instead the camera is fixed for both players,
    // and this wrapper group is mirrored on z for Black's view: that flips
    // which end is "near/bottom" without touching which side is "right."
    this.worldGroup = new THREE.Group();
    this.scene.add(this.worldGroup);

    this.checkerGroup = new THREE.Group();
    this.worldGroup.add(this.checkerGroup);
    this.diceGroup = new THREE.Group();
    this.worldGroup.add(this.diceGroup);

    this.state = null;
    this.legalMoves = [];
    this.yourColor = 1;
    this.yourTurn = false;
    this.prefix = [];
    this.selectedFrom = null;

    this._raycaster = new THREE.Raycaster();
    this.renderer.domElement.addEventListener("click", (e) => this._onCanvasClick(e));

    this._resizeObserver = new ResizeObserver(() => this._onResize());
    this._resizeObserver.observe(this.rootEl);

    this._animating = false;
    this._tick();
  }

  _addLights() {
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(0.4, 1, 0.6);
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x8a5cff, 0.4);
    rim.position.set(-0.5, 0.4, -0.6);
    this.scene.add(rim);
  }

  _onResize() {
    const w = this.rootEl.clientWidth || 1;
    const h = this.rootEl.clientHeight || 1;
    // Moving the window to a monitor with a different DPI doesn't fire a
    // resize on its own reliably across browsers, but devicePixelRatio
    // changes with it — re-read it here rather than only once at construction.
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this._positionCamera();
  }

  _tick() {
    requestAnimationFrame(() => this._tick());
    this.renderer.render(this.scene, this.camera);
  }

  // -- theme loading -----------------------------------------------------

  async setTheme({ boardUrl, checkersUrl, diceUrl, diceCupUrl }) {
    const [boardGltf, checkersGltf, diceGltf, cupGltf] = await Promise.all([
      loadGltf(boardUrl),
      loadGltf(checkersUrl),
      loadGltf(diceUrl),
      loadGltf(diceCupUrl),
    ]);

    if (this.boardGroup) this.worldGroup.remove(this.boardGroup);
    this.boardGroup = boardGltf.scene.clone(true);
    this.worldGroup.add(this.boardGroup);
    this._makeDoubleSided(this.boardGroup);

    this.pointWorldPos.clear();
    this.pointMeshes = new Map(); // pointNum -> mesh (own material clone, for highlighting)
    for (let i = 1; i <= 24; i++) {
      const node = findByName(this.boardGroup, `point_${i}`);
      if (node) {
        const v = new THREE.Vector3();
        node.getWorldPosition(v);
        this.pointWorldPos.set(i, v);
        if (node.material) {
          node.material = node.material.clone();
          node.userData.baseEmissive = (node.material.emissive || new THREE.Color(0, 0, 0)).clone();
        }
        this.pointMeshes.set(i, node);
      }
    }
    const barNode = findByName(this.boardGroup, "bar");
    if (barNode) {
      barNode.getWorldPosition(this.barWorldPos);
      // Hit checkers must sit visibly ON TOP of the bar's raised surface,
      // not at its center pivot — that had them partially embedded in the
      // bar geometry, effectively invisible. Measure the real top surface
      // instead of guessing an offset, so it's correct on any board theme.
      this.barTopY = new THREE.Box3().setFromObject(barNode).max.y;
      if (barNode.material) {
        barNode.material = barNode.material.clone();
        barNode.userData.baseEmissive = (barNode.material.emissive || new THREE.Color(0, 0, 0)).clone();
      }
      this.barMesh = barNode;
    }

    this._setupOffTrays();

    // These are cloned as standalone objects and always explicitly
    // positioned later (_redrawCheckers / _makeDieMesh), so whatever local
    // transform the source node carried in the original asset is irrelevant
    // — every placement below sets absolute position itself.
    const lightSrc = findByName(checkersGltf.scene, "checker_light_0");
    const darkSrc = findByName(checkersGltf.scene, "checker_dark_0");
    this.checkerTemplates = { light: lightSrc.clone(), dark: darkSrc.clone() };
    this._makeDoubleSided(this.checkerTemplates.light);
    this._makeDoubleSided(this.checkerTemplates.dark);

    // The asset bakes real pips onto all 6 faces of the cube (like a
    // physical die), as siblings under "die_1" — cube + all pip meshes,
    // not one geometry per rolled value. Clone that whole rigid group and
    // zero its own transform (the source node's matrix is just some
    // arbitrary static "resting pose" for the asset preview) so it's a
    // clean body in local space; DIE_FACE_LOCAL_AXIS below then rotates
    // whichever face should show the rolled value to point up.
    const dieSrc = findByName(diceGltf.scene, "die_1");
    this.dieTemplate = dieSrc.clone();
    this.dieTemplate.position.set(0, 0, 0);
    this.dieTemplate.quaternion.identity();
    this.dieTemplate.scale.set(1, 1, 1);
    this._makeDoubleSided(this.dieTemplate);

    if (this.cupGroup) this.worldGroup.remove(this.cupGroup);
    this.cupGroup = cupGltf.scene.clone(true);
    this.cupGroup.visible = false;
    this._makeDoubleSided(this.cupGroup);
    this.worldGroup.add(this.cupGroup);

    this._positionCamera();
    this._redrawCheckers();
  }

  // The world group gets mirrored on z for Black's view (see constructor
  // comment); a negative-scale transform flips triangle winding, which
  // would make front faces get back-face-culled and look inverted/missing
  // without this.
  _makeDoubleSided(root) {
    root.traverse((obj) => {
      if (obj.material) obj.material.side = THREE.DoubleSide;
    });
  }

  // Bear-off trays have no dedicated geometry in the asset set — built as
  // simple markers just past the board's edge, aligned with each color's
  // home row (both home boards sit on the same x side, split by z; SPEC §4.1).
  _setupOffTrays() {
    if (this.offTrayGroup) this.worldGroup.remove(this.offTrayGroup);
    this.offTrayGroup = new THREE.Group();
    this.worldGroup.add(this.offTrayGroup);

    const makeTray = (colorKey, z, glowHex) => {
      const geo = new THREE.BoxGeometry(0.05, 0.01, 0.09);
      const mat = new THREE.MeshStandardMaterial({
        color: 0x161624,
        emissive: new THREE.Color(0, 0, 0),
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(0.36, 0.036, z);
      mesh.userData.isOff = true;
      mesh.userData.offColor = colorKey;
      mesh.userData.baseEmissive = new THREE.Color(0, 0, 0);
      mesh.userData.glow = new THREE.Color(glowHex);
      this.offTrayGroup.add(mesh);

      const label = this._makeLabelSprite("0");
      label.position.set(0.36, 0.06, z);
      this.offTrayGroup.add(label);

      return { mesh, label };
    };

    this.offTrays = {
      light: makeTray("light", 0.15, 0x2ee6ff),
      dark: makeTray("dark", -0.15, 0xff3ec8),
    };
  }

  _updateOffLabels() {
    if (!this.offTrays || !this.state) return;
    const whiteLabel = this._makeLabelSprite(String(this.state.off_white));
    whiteLabel.position.copy(this.offTrays.light.label.position);
    this.offTrayGroup.remove(this.offTrays.light.label);
    this.offTrayGroup.add(whiteLabel);
    this.offTrays.light.label = whiteLabel;

    const blackLabel = this._makeLabelSprite(String(this.state.off_black));
    blackLabel.position.copy(this.offTrays.dark.label.position);
    this.offTrayGroup.remove(this.offTrays.dark.label);
    this.offTrayGroup.add(blackLabel);
    this.offTrays.dark.label = blackLabel;
  }

  // Board corners that must stay on-screen, checked at both +z/-z (the
  // world mirror only flips which is which, not the set of x/z combos, so
  // fitting is correct regardless of _applyPerspectiveMirror's state).
  static _FIT_CORNERS = [
    new THREE.Vector3(0.37, 0.05, 0.26),
    new THREE.Vector3(-0.37, 0.05, 0.26),
    new THREE.Vector3(0.37, 0.05, -0.26),
    new THREE.Vector3(-0.37, 0.05, -0.26),
  ];

  _positionCamera() {
    // The camera is FIXED and identical for both players — it never moves
    // to "the other side of the table." Both home boards in this asset sit
    // on the same physical x-side (split by z only, not a diagonal seating
    // layout), so relocating the camera would flip left/right along with
    // front/back, landing Black's home bottom-LEFT instead of bottom-right.
    // Instead, _applyPerspectiveMirror() mirrors the world's z axis for
    // Black's view: that flips only near/far (front/back), leaving which
    // side is "right" unchanged for both players.
    //
    // The camera's viewing ANGLE is fixed (this ratio of y:z), but its
    // DISTANCE adapts to the container's current aspect ratio so the board
    // fills the frame as much as possible without clipping on any window
    // size — a fixed distance tuned for one aspect ratio clipped the wide
    // bottom corners on narrower windows (e.g. moving to a laptop screen).
    const elevation = new THREE.Vector3(0, 0.46, 0.5).normalize();
    const MARGIN = 0.88; // keep corners within +-0.88 NDC as a safety margin
    let distance = 0.68;

    for (let iter = 0; iter < 5; iter++) {
      this.camera.position.copy(elevation).multiplyScalar(distance);
      this.camera.up.set(0, 1, 0);
      this.camera.lookAt(0, 0, 0);
      this.camera.updateMatrixWorld(true);

      let maxAbs = 0;
      for (const corner of Board3D._FIT_CORNERS) {
        const ndc = corner.clone().project(this.camera);
        maxAbs = Math.max(maxAbs, Math.abs(ndc.x), Math.abs(ndc.y));
      }
      if (!isFinite(maxAbs) || maxAbs <= MARGIN) break;
      distance = THREE.MathUtils.clamp(distance * (maxAbs / MARGIN), 0.35, 1.6);
    }

    this._applyPerspectiveMirror();
  }

  _applyPerspectiveMirror() {
    this.worldGroup.scale.set(1, 1, this.yourColor === -1 ? -1 : 1);
  }

  // -- game state rendering ------------------------------------------------

  render(gameState, legalMoves, yourColor, yourTurn) {
    this.state = gameState;
    this.legalMoves = legalMoves || [];
    this.yourColor = yourColor;
    this.yourTurn = yourTurn;
    this.prefix = [];
    this.selectedFrom = null;
    this._positionCamera();
    this._redrawCheckers();
    this._updateHighlights();
  }

  _updateHighlights() {
    if (!this.pointMeshes) return;
    const CYAN = new THREE.Color(0x2ee6ff);
    const MAGENTA = new THREE.Color(0xff3ec8);

    const reset = (mesh) => {
      if (mesh.material && mesh.userData.baseEmissive) {
        mesh.material.emissive.copy(mesh.userData.baseEmissive);
        mesh.material.emissiveIntensity = 0;
      }
    };
    for (const mesh of this.pointMeshes.values()) reset(mesh);
    if (this.barMesh) reset(this.barMesh);
    if (this.offTrays) {
      reset(this.offTrays.light.mesh);
      reset(this.offTrays.dark.mesh);
    }

    if (!this.yourTurn || this.legalMoves.length === 0) return;

    const interactive = this.selectedFrom === null;
    const fromTargets = interactive ? this._fromTargets() : new Set();
    const toTargets = !interactive ? this._toTargetsFor(this.selectedFrom) : [];
    const toIndexSet = new Set(toTargets.map((mv) => mv[1]));

    const tint = (key, color) => {
      if (key === "bar") {
        if (this.barMesh) {
          this.barMesh.material.emissive.copy(color);
          this.barMesh.material.emissiveIntensity = 0.9;
        }
        return;
      }
      if (key === "off") {
        if (!this.offTrays) return;
        // Only the mover's own tray is a legal bear-off destination.
        const own = this.yourColor === 1 ? this.offTrays.light.mesh : this.offTrays.dark.mesh;
        own.material.emissive.copy(own.userData.glow);
        own.material.emissiveIntensity = 1.1;
        return;
      }
      const mesh = this.pointMeshes.get(key + 1); // pointMeshes keyed 1-24, targets are 0-23
      if (mesh) {
        mesh.material.emissive.copy(color);
        mesh.material.emissiveIntensity = 0.9;
      }
    };
    for (const key of fromTargets) tint(key, CYAN);
    for (const key of toIndexSet) tint(key, MAGENTA);
  }

  _candidates() {
    return this.legalMoves.filter((seq) =>
      this.prefix.every(
        (mv, i) => seq[i] && seq[i][0] === mv[0] && seq[i][1] === mv[1] && seq[i][2] === mv[2]
      )
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
    this._applyLocal(match, this.yourColor);

    const remaining = this._candidates();
    const done = remaining.every((seq) => seq.length === this.prefix.length);
    this.onMoveChosen([match], done);
    this._redrawCheckers();
    this._updateHighlights();
  }

  applyRemote(move) {
    if (!this.state) return;
    this._applyLocal(move, -this.yourColor);
    this._redrawCheckers();
  }

  // Same atomic-move math as the 2D board (SPEC §4.5 apply_move), applied to
  // this.state directly since 3D checker meshes are rebuilt from it wholesale
  // on every change rather than tracked incrementally.
  _applyLocal(move, color) {
    const [frm, to] = move;
    const s = this.state;
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

  _redrawCheckers() {
    while (this.checkerGroup.children.length) {
      this.checkerGroup.remove(this.checkerGroup.children[0]);
    }
    if (!this.state || !this.checkerTemplates) return;

    for (let idx = 0; idx < 24; idx++) {
      const count = this.state.points[idx];
      if (count === 0) continue;
      const pointNum = idx + 1;
      const pos = this.pointWorldPos.get(pointNum);
      if (!pos) continue;
      const color = count > 0 ? "light" : "dark";
      const total = Math.abs(count);
      const n = Math.min(total, MAX_STACKED);
      const dir = pos.z >= 0 ? -1 : 1; // stack inward, toward board center
      for (let i = 0; i < n; i++) {
        const layer = Math.floor(i / LAYER_SIZE);
        const posInLayer = i % LAYER_SIZE;
        const mesh = this.checkerTemplates[color].clone();
        const z = pos.z + dir * (CHECKER_STACK_FIRST + posInLayer * CHECKER_STACK_STEP);
        const y = pos.y + CHECKER_HALF_HEIGHT + layer * CHECKER_LAYER_HEIGHT;
        mesh.position.set(pos.x, y, z);
        mesh.userData.pointIndex = idx;
        this.checkerGroup.add(mesh);
      }
      if (total > MAX_STACKED) {
        const topLayer = Math.floor((MAX_STACKED - 1) / LAYER_SIZE);
        const label = this._makeLabelSprite(`+${total - MAX_STACKED}`);
        const z = pos.z + dir * (CHECKER_STACK_FIRST + (LAYER_SIZE - 1) * CHECKER_STACK_STEP);
        const y = pos.y + CHECKER_HALF_HEIGHT + (topLayer + 1) * CHECKER_LAYER_HEIGHT + 0.012;
        label.position.set(pos.x, y, z);
        this.checkerGroup.add(label);
      }
    }

    this._drawBarCheckers("white", this.state.bar_white, 1);
    this._drawBarCheckers("black", this.state.bar_black, -1);
    this._updateOffLabels();
  }

  _drawBarCheckers(colorKey, count, dirSign) {
    const templateKey = colorKey === "white" ? "light" : "dark";
    const total = Math.min(count, MAX_STACKED);
    const barTop = this.barTopY ?? this.barWorldPos.y + CHECKER_HALF_HEIGHT;
    for (let i = 0; i < total; i++) {
      const layer = Math.floor(i / LAYER_SIZE);
      const posInLayer = i % LAYER_SIZE;
      const mesh = this.checkerTemplates[templateKey].clone();
      mesh.position.set(
        this.barWorldPos.x,
        barTop + CHECKER_HALF_HEIGHT + layer * CHECKER_LAYER_HEIGHT,
        dirSign * (0.03 + posInLayer * CHECKER_STACK_STEP)
      );
      mesh.userData.isBar = true;
      this.checkerGroup.add(mesh);
    }
    if (count > MAX_STACKED) {
      const topLayer = Math.floor((MAX_STACKED - 1) / LAYER_SIZE);
      const label = this._makeLabelSprite(`+${count - MAX_STACKED}`);
      label.position.set(
        this.barWorldPos.x,
        barTop + CHECKER_HALF_HEIGHT + (topLayer + 1) * CHECKER_LAYER_HEIGHT + 0.012,
        dirSign * (0.03 + (LAYER_SIZE - 1) * CHECKER_STACK_STEP)
      );
      this.checkerGroup.add(label);
    }
  }

  _makeLabelSprite(text) {
    const canvas = document.createElement("canvas");
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "rgba(10,10,18,0.85)";
    ctx.beginPath();
    ctx.arc(32, 32, 30, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#2ee6ff";
    ctx.font = "bold 26px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 32, 34);
    const tex = new THREE.CanvasTexture(canvas);
    const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(0.03, 0.03, 1);
    return sprite;
  }

  // -- interaction ---------------------------------------------------------

  _onCanvasClick(event) {
    if (!this.yourTurn || this.legalMoves.length === 0) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1
    );
    this._raycaster.setFromCamera(ndc, this.camera);

    const offMeshes = this.offTrays ? [this.offTrays.light.mesh, this.offTrays.dark.mesh] : [];
    const targets = [
      ...this.checkerGroup.children,
      ...this._pointHitMeshes(),
      this._barHitMesh(),
      ...offMeshes,
    ].filter(Boolean);
    const hits = this._raycaster.intersectObjects(targets, true);
    if (hits.length === 0) return;

    const pointIndex = this._resolvePointIndex(hits[0].object);
    if (pointIndex === null) return;
    this._handlePointClick(pointIndex);
  }

  _resolvePointIndex(obj) {
    let o = obj;
    while (o) {
      if (o.userData && o.userData.pointIndex !== undefined) return o.userData.pointIndex;
      if (o.userData && o.userData.isBar) return "bar";
      if (o.userData && o.userData.isOff) return "off";
      if (o.name && o.name.startsWith("point_")) return Number(o.name.split("_")[1]) - 1;
      if (o.name === "bar") return "bar";
      o = o.parent;
    }
    return null;
  }

  _pointHitMeshes() {
    return this.boardGroup ? findAllByPrefix(this.boardGroup, "point_") : [];
  }

  _barHitMesh() {
    return this.boardGroup ? findByName(this.boardGroup, "bar") : null;
  }

  _handlePointClick(idx) {
    if (this.selectedFrom === null) {
      if (this._fromTargets().has(idx)) {
        const options = this._toTargetsFor(idx);
        if (options.length === 1) {
          this._pick(idx, options[0][1]);
          return;
        }
        this.selectedFrom = idx;
      }
    } else if (this._toTargetsFor(this.selectedFrom).some((mv) => mv[1] === idx)) {
      this._pick(this.selectedFrom, idx);
      return;
    } else if (idx === this.selectedFrom) {
      this.selectedFrom = null;
    }
    this._updateHighlights();
  }

  // -- dice throw animation --------------------------------------------

  async playDiceRoll(d1, d2) {
    if (!this.cupGroup || !this.dieTemplate || this._animating) return;
    this._animating = true;

    while (this.diceGroup.children.length) this.diceGroup.remove(this.diceGroup.children[0]);

    this.cupGroup.visible = true;
    // Land in the mover's own home board (positive x = "right" for both
    // players, per the fixed-camera/world-mirror scheme) and within the
    // board's actual footprint (z up to ~0.24) — the old z=0.3 was past the
    // board's near edge entirely, so the throw visibly landed off the board.
    // cupGroup is a child of worldGroup, so Black's world-mirror already
    // relocates this to the correct near/bottom side; no per-color sign needed.
    this.cupGroup.position.set(DICE_LAND_X, 0.05, DICE_LAND_Z);
    this.cupGroup.scale.setScalar(0.6);

    await this._animate(500, (t) => {
      this.cupGroup.rotation.z = Math.sin(t * Math.PI * 6) * 0.35;
    });
    this.cupGroup.rotation.z = 0;
    this.cupGroup.visible = false;

    const dieA = this._makeDieMesh(d1, -0.02);
    const dieB = this._makeDieMesh(d2, 0.02);
    this.diceGroup.add(dieA, dieB);

    // Tumble from a random start orientation into the correct resting face
    // (already computed as each die's userData.targetQuaternion) rather
    // than popping in already-settled — reads as an actual roll landing.
    const dieAModel = dieA.children[0];
    const dieBModel = dieB.children[0];
    const startA = dieAModel.quaternion.clone();
    const startB = dieBModel.quaternion.clone();

    await this._animate(450, (t) => {
      const bounce = Math.abs(Math.sin(t * Math.PI * 2)) * (1 - t) * 0.03;
      dieA.position.y = 0.04 + bounce;
      dieB.position.y = 0.04 + bounce;
      const settle = Math.min(1, t * 1.6); // finish rotating slightly before the bounce ends
      dieAModel.quaternion.slerpQuaternions(startA, dieAModel.userData.targetQuaternion, settle);
      dieBModel.quaternion.slerpQuaternions(startB, dieBModel.userData.targetQuaternion, settle);
    });

    this._animating = false;
  }

  _makeDieMesh(value, xOffset) {
    const group = new THREE.Group();
    const die = this.dieTemplate.clone();
    die.scale.setScalar(1.8);

    // Rotate the face that carries this value's real pips to point up, per
    // DIE_FACE_LOCAL_AXIS (decoded from the asset itself, not guessed) —
    // plus a random spin around the vertical axis purely for visual
    // variety, which doesn't change which face is up.
    const alignUp = new THREE.Quaternion().setFromUnitVectors(DIE_FACE_LOCAL_AXIS[value], WORLD_UP);
    const spin = new THREE.Quaternion().setFromAxisAngle(WORLD_UP, Math.random() * Math.PI * 2);
    const target = spin.clone().multiply(alignUp);
    die.userData.targetQuaternion = target;

    // Starts at a random tumble orientation; playDiceRoll slerps it to
    // `target` over the landing animation instead of popping in pre-settled.
    die.quaternion.set(
      Math.random() * 2 - 1,
      Math.random() * 2 - 1,
      Math.random() * 2 - 1,
      Math.random() * 2 - 1
    ).normalize();

    group.add(die);
    // fixed landing spot (see playDiceRoll); worldGroup mirror handles per-viewer side
    group.position.set(DICE_LAND_X + xOffset, 0.04, DICE_LAND_Z);
    return group;
  }

  _animate(durationMs, onFrame) {
    return new Promise((resolve) => {
      const start = performance.now();
      const step = (now) => {
        const t = Math.min(1, (now - start) / durationMs);
        onFrame(t);
        if (t < 1) requestAnimationFrame(step);
        else resolve();
      };
      requestAnimationFrame(step);
    });
  }
}
