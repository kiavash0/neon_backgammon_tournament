// Per-player visual preferences (board / checkers / dice) — purely local,
// never sent to the server. Persisted in localStorage so choices survive
// reloads. Backed by assets/manifest.json so the theme list stays in sync
// with whatever art actually exists on disk.

const STORAGE_KEY = "nbt_theme_prefs";
const MANIFEST_URL = "/assets/manifest.json";
const ASSET_ROOT = "/assets/";

let manifest = null;

export async function loadManifest() {
  if (manifest) return manifest;
  const resp = await fetch(MANIFEST_URL);
  manifest = await resp.json();
  return manifest;
}

function defaults(m) {
  return {
    board: m.default_theme,
    checkers: Object.keys(m.checkers_sets)[0],
    dice: Object.keys(m.dice_sets)[0],
  };
}

export function getPrefs(m) {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (stored && stored.board && stored.checkers && stored.dice) return stored;
  } catch {
    /* fall through to defaults */
  }
  return defaults(m);
}

export function setPrefs(prefs) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
}

export function assetUrl(relativePath) {
  return ASSET_ROOT + relativePath;
}

export function boardUrl(m, themeName) {
  return assetUrl(m.themes[themeName].board);
}

export function checkersUrl(m, setName) {
  return assetUrl(m.checkers_sets[setName]);
}

export function diceUrl(m, colorName) {
  return assetUrl(m.dice_sets[colorName]);
}

export function diceCupUrl(m) {
  // Only one dice-cup model exists in the asset set (not one per board
  // theme) — every theme shares it rather than faking a per-theme thrower.
  return assetUrl(m.accessories.dice_cup);
}

export function populateThemeSelectors() {
  return loadManifest().then((m) => {
    const prefs = getPrefs(m);

    const boardSel = document.getElementById("theme-board");
    boardSel.innerHTML = Object.keys(m.themes)
      .map((name) => `<option value="${name}">${capitalize(name)}</option>`)
      .join("");
    boardSel.value = prefs.board;

    const checkersSel = document.getElementById("theme-checkers");
    checkersSel.innerHTML = Object.keys(m.checkers_sets)
      .map((name) => `<option value="${name}">${capitalize(name)}</option>`)
      .join("");
    checkersSel.value = prefs.checkers;

    const diceSel = document.getElementById("theme-dice");
    diceSel.innerHTML = Object.keys(m.dice_sets)
      .map((name) => `<option value="${name}">${capitalize(name)}</option>`)
      .join("");
    diceSel.value = prefs.dice;

    return { manifest: m, prefs };
  });
}

// Standard starting position (SPEC §4.1 / engine initial_state), used only
// to give the lobby theme preview something real to display.
export const STARTING_STATE = {
  points: [-2, 0, 0, 0, 0, 5, 0, 3, 0, 0, 0, -5, 5, 0, 0, 0, -3, 0, -5, 0, 0, 0, 0, 2],
  bar_white: 0,
  bar_black: 0,
  off_white: 0,
  off_black: 0,
  turn: 1,
};

function capitalize(s) {
  return s.replace(/([A-Z])/g, " $1").replace(/^./, (c) => c.toUpperCase());
}
