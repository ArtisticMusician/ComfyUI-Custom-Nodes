/**
 * StemSave's front end: one row per input, with its name field ON the socket row and its
 * waveform underneath.
 *
 * Why the fields are positioned by measurement: ComfyUI draws a node's sockets in their own
 * band and every widget in a band beneath it, so a widget can never land on a socket's row.
 * A widget can however render an element, and from that element the node's own DOM can be
 * reached (`div.lg-node[data-node-id]`). So each row's field is an absolutely positioned
 * input inside a layer covering the node, placed over its socket row by measuring the row the
 * frontend drew - the label text `audio_<n>` for the left, `stem_<n>` for the right, so the
 * field sits between them the way a name field should.
 *
 * If those labels cannot be measured (a frontend that names things differently, a node whose
 * DOM is not up yet), every field goes back into its own row block under the sockets. The
 * node is then laid out the way it was before this file existed rather than left with no
 * fields at all.
 *
 * The native field for each row stays on the node behind it - hidden, never removed - so the
 * value still travels in the workflow exactly as it did, and a workflow saved earlier still
 * opens with its names in place.
 */
import { app } from "../../scripts/app.js";
import { PLAYER_HEIGHT, loadPlayer, makePlayer } from "./audio_player.js";
import { reconcile, trimRows } from "./rows.js";

const NODE = "StemSave";
const ROWS = 20;
const ROW_INPUTS = (row) => [`audio_${row}`, `name_${row}`];
const ROW_OUTPUT = (row) => `stem_${row}`;
const ROW_WIDGET = (row) => `stemsave_row_${row}`;
const FIELD_LAYER = "stemsave_field_layer";
const FIELD_HEIGHT = 24;
const GAP = 6;          // clear of the socket's own label and of the output's
const MIN_WIDTH = 70;   // narrower than this and the field would cover something

// Air above each stem's waveform, so a stack of stems reads as stems rather than as one block.
// It rides on the player, which is the part that exists exactly when the row has audio: a row
// with nothing to write takes none of it and collapses instead of leaving a stem-sized hole.
const ROW_SPACING = 10;

const hidden = (box) => box.style.display === "none";
const nameWidget = (node, row) => node.widgets?.find((w) => w.name === `name_${row}`);

/** Hide the native field behind each row for good: the row draws its own. */
function hideNativeFields(node) {
    for (let row = 1; row <= ROWS; row++) {
        const widget = nameWidget(node, row);
        if (widget && widget.type !== "hidden") widget.type = "hidden";
    }
}

function makeField(node, row) {
    const field = document.createElement("input");
    field.type = "text";
    field.spellcheck = false;
    field.placeholder = `stem_${row}`;
    field.title = `Name for stem ${row}. It becomes the file name.`;
    field.setAttribute("aria-label", `Name for stem ${row}`);
    field.className = `stemsave-field stemsave-field-${row}`;
    field.style.cssText = `box-sizing:border-box;padding:1px 6px;font-size:12px;height:${FIELD_HEIGHT}px;` +
                          `color:inherit;background:rgba(255,255,255,0.06);` +
                          `border:1px solid rgba(255,255,255,0.16);border-radius:4px;`;
    // The value belongs to the hidden native field: that is what the workflow saves and what
    // the node is handed when it runs.
    field.addEventListener("input", () => {
        const widget = nameWidget(node, row);
        if (widget) widget.value = field.value;
    });
    return field;
}

/** Every row, built once: its field, and its player waiting to be shown. */
function rowsFor(node) {
    if (node.stemsaveRows) return node.stemsaveRows;

    const rows = [];
    for (let row = 1; row <= ROWS; row++) {
        const box = document.createElement("div");
        box.style.cssText = "display:flex;flex-direction:column;gap:4px;";

        const field = makeField(node, row);
        const player = makePlayer();
        player.box.style.display = "none";
        player.box.style.marginTop = `${ROW_SPACING}px`;

        box.append(field, player.box);

        const widget = node.addDOMWidget(ROW_WIDGET(row), "stem", box, { serialize: false });
        // The field only takes room while it is in here. While it is placed on the socket
        // row above, only the player's height counts, plus the air above it.
        widget.computeSize = (width) => [width, (node.ossFieldsPlaced ? 0 : FIELD_HEIGHT) +
                                                (hidden(player.box) ? 0 : PLAYER_HEIGHT + ROW_SPACING)];

        rows.push({ box, field, player });
    }
    node.stemsaveRows = rows;
    return rows;
}

/** Put the saved names back into the fields: the native widgets hold them, the rows show them. */
function syncFields(node) {
    rowsFor(node).forEach((entry, index) => {
        const value = nameWidget(node, index + 1)?.value ?? "";
        if (entry.field.value !== value) entry.field.value = value;
    });
}

// ---------------------------------------------------------------- placing a field on a row

function nodeElement(node) {
    return document.querySelector(`[data-node-id="${node.id}"]`);
}

/** The frontend's own label for a socket: an element whose whole text is that name. */
function labelFor(root, text) {
    if (!root) return null;
    for (const el of root.querySelectorAll("div,span,p,button,label")) {
        if (el.children.length === 0 && el.textContent.trim() === text) return el;
    }
    return null;
}

function fieldLayer(nodeEl) {
    if (!nodeEl) return null;
    let layer = nodeEl.querySelector(`:scope > .${FIELD_LAYER}`);
    if (!layer) {
        layer = document.createElement("div");
        layer.className = FIELD_LAYER;
        // Covers the node, takes no input of its own, sits above the sockets.
        layer.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;" +
                              "pointer-events:none;z-index:2;";
        nodeEl.appendChild(layer);
    }
    return layer;
}

/** Where a row's field should sit, in the layer's own coordinates, or null if not measurable.
 *
 * The frontend draws a node's DOM inside a container scaled by the canvas zoom, so a rect in
 * page pixels is not a length in the node's own pixels. Everything measured comes back through
 * this: without it the fields are out by the zoom (10% at 90%, 50% at 50%) and a height taken
 * from the row covers the row below.
 */
function layerScale(layer) {
    const box = layer.getBoundingClientRect();
    return {
        x: layer.offsetWidth ? box.width / layer.offsetWidth : 1,
        y: layer.offsetHeight ? box.height / layer.offsetHeight : 1,
    };
}

// Room above and below the field inside its row. Two fields as tall as the row touch, and a
// column of touching boxes reads as one list rather than as one name on one row.
const FIELD_INSET = 2;

/** The row's own band: where it starts and how tall a row is, from the labels beside it. */
function rowBand(nodeEl, row) {
    const here = labelFor(nodeEl, `audio_${row}`);
    if (!here) return null;
    const box = here.getBoundingClientRect();
    if (!box.height) return null;
    const neighbour = labelFor(nodeEl, `audio_${row + 1}`) || labelFor(nodeEl, `audio_${row - 1}`);
    return {
        top: box.top,
        right: box.right,
        pitch: neighbour
            ? Math.abs(neighbour.getBoundingClientRect().top - box.top)
            : box.height,
    };
}

export function fieldPlacement(nodeEl, layer, row) {
    const band = rowBand(nodeEl, row);
    if (!band) return null;
    const out = labelFor(nodeEl, `stem_${row}`);
    const node = layer.getBoundingClientRect();
    if (!node.width || !node.height) return null;

    const scale = layerScale(layer);
    const limit = out ? out.getBoundingClientRect().left : node.right;
    const left = (band.right - node.left) / scale.x + GAP;
    const width = (limit - node.left) / scale.x - GAP - left;
    // One row's height, less the air: FIELD_HEIGHT is only the ceiling, for a frontend whose
    // rows are taller than a text field needs.
    const height = Math.min(FIELD_HEIGHT, band.pitch / scale.y) - 2 * FIELD_INSET;
    if (!(width >= MIN_WIDTH) || height < 8) return null;
    return { left, top: (band.top - node.top) / scale.y + FIELD_INSET, width, height };
}

/** Put every shown row's field over its socket row. False = could not be done, so use the rows. */
export function placeFields(node) {
    const nodeEl = nodeElement(node);
    const layer = fieldLayer(nodeEl);
    const rows = rowsFor(node);
    if (!nodeEl || !layer) return false;

    const shown = shownRows(node);
    const spots = [];
    for (let row = 1; row <= shown; row++) {
        const entry = rows[row - 1];
        const spot = fieldPlacement(nodeEl, layer, row);
        if (!spot) return false;       // one unmeasurable row means the whole band goes back
        spots.push([entry, spot]);
    }
    if (!spots.length) return false;

    for (const [entry, spot] of spots) {
        const f = entry.field.style;
        f.position = "absolute";
        f.left = `${spot.left}px`;
        f.top = `${spot.top}px`;
        f.width = `${spot.width}px`;
        f.height = `${spot.height}px`;
        f.pointerEvents = "auto";
        if (entry.field.parentElement !== layer) layer.appendChild(entry.field);
    }
    node.ossFieldsPlaced = true;
    return true;
}

/** How many rows the trimmer is showing: the wired ones plus the spare. */
function shownRows(node) {
    let last = 0;
    for (let row = 1; row <= ROWS; row++) {
        if (node.inputs?.some((i) => i.name === `audio_${row}`)) last = row;
        else break;
    }
    return last || 1;
}

/** Back to field-in-its-own-block, for when the socket rows cannot be measured. */
function stackFields(node) {
    for (const entry of rowsFor(node)) {
        if (entry.field.parentElement === entry.box) continue;
        const f = entry.field.style;
        f.position = "";
        f.left = f.top = f.width = "";
        f.height = `${FIELD_HEIGHT}px`;
        entry.box.insertBefore(entry.field, entry.player.box);
    }
    node.ossFieldsPlaced = false;
}

function layout(node) {
    syncFields(node);
    const placed = placeFields(node);
    if (!placed) stackFields(node);
    node.setDirtyCanvas?.(true, true);
    return placed;
}

// A node's element appears a frame or two after the node does, and a programmatically added
// node can take longer. Without a retry the fields stay stacked for good, because nothing else
// fires on a node nobody has touched yet.
const RETRY_MS = 50;
const RETRY_LIMIT = 40;

/** The frontend re-lays a node out after it hides widgets, resizes or reconnects. */
function relayout(node) {
    cancelAnimationFrame(node.ossLayoutFrame);
    clearTimeout(node.ossLayoutTimer);
    node.ossLayoutTimer = null;
    node.ossLayoutFrame = requestAnimationFrame(() => {
        const placed = layout(node);
        // One more pass after the band settles, then watch the node's own size.
        requestAnimationFrame(() => layout(node));
        if (!placed && (node.ossLayoutTries = (node.ossLayoutTries ?? 0) + 1) <= RETRY_LIMIT) {
            node.ossLayoutTimer = setTimeout(() => relayout(node), RETRY_MS);
        } else if (placed) {
            node.ossLayoutTries = 0;
        }
        if (!node.ossResizeWatch && typeof ResizeObserver !== "undefined") {
            node.ossResizeWatch = new ResizeObserver(() => layout(node));
        }
        const nodeEl = nodeElement(node);
        if (node.ossResizeWatch && nodeEl && node.ossResizeTarget !== nodeEl) {
            node.ossResizeWatch.disconnect();
            node.ossResizeWatch.observe(nodeEl);
            node.ossResizeTarget = nodeEl;
        }
    });
}

function showStems(node, stems) {
    rowsFor(node).forEach((entry, index) => {
        const stem = stems?.[index];
        if (!stem?.files?.length) {
            if (!hidden(entry.player.box)) {
                entry.player.box.style.display = "none";
                entry.player.audio.removeAttribute("src");
            }
            return;
        }
        // Shown before the waveform is drawn, so the canvas is measured at its real width.
        entry.player.box.style.display = "flex";
        loadPlayer(entry.player, stem.files[0], stem.name);
    });
    relayout(node);
}

app.registerExtension({
    name: "StemSplitter.StemSaveRows",

    // Built here, not in onNodeCreated: the node's fields and the Save as button are already on
    // it by now, so the rows land under them instead of pushing them down.
    nodeCreated(node) {
        if (node.comfyClass !== NODE && node.type !== NODE) return;
        hideNativeFields(node);
        rowsFor(node);
        // The rows were built after the trimmer's own pass over this node, so run it again to
        // hide the rows past the ones in use and size the node to what is left.
        reconcile(node, ROWS_SPEC);
        relayout(node);
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE) return;

        trimRows(nodeType, ROWS_SPEC);

        // A loaded workflow sets the native fields directly, which fires nothing of its own.
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            hideNativeFields(this);
            relayout(this);
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            onConnectionsChange?.apply(this, arguments);
            relayout(this);
        };

        const onResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function () {
            onResize?.apply(this, arguments);
            relayout(this);
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            showStems(this, message?.stem_save_stems);
        };
    },

    async setup() {
        // Nodes already on the canvas when this extension loads never saw nodeCreated.
        for (const node of app.graph?._nodes ?? []) {
            if (node.type !== NODE && node.comfyClass !== NODE) continue;
            hideNativeFields(node);
            rowsFor(node);
            relayout(node);
        }
    },
});

// The row block is what the trimmer shows and hides. The native fields behind the rows are
// hidden for good, so they are not in this list.
const ROWS_SPEC = {
    rows: ROWS,
    inputs: ROW_INPUTS,
    output: ROW_OUTPUT,
    widgets: (row) => [ROW_WIDGET(row)],
};
