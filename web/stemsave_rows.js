/**
 * StemSave - keep the node down to the rows you are actually using.
 *
 * The node declares twenty inputs and twenty outputs up front, because ComfyUI fixes both
 * when the class is written and will not grow them at run time. Twenty empty sockets is a
 * useless tower, so the trailing ones are dropped, never a connected one, leaving a single
 * spare row to wire. Connecting the spare brings the next pair into view; disconnecting
 * takes them away again.
 *
 * Only rows that are unused are ever removed, so the ones that remain are always the first
 * N - which means re-adding appends in the right order.
 */
import { app } from "../../scripts/app.js";

const ROWS = 20;
const ROW_INPUTS = (row) => [`audio_${row}`, `name_${row}`];
const ROW_OUTPUT = (row) => `stem_${row}`;

/** The definitions to rebuild a row from, captured before anything is removed. */
function remember(node) {
    if (node.stemsaveRowDefs) return node.stemsaveRowDefs;
    const defs = { inputs: {}, outputs: {} };
    for (let row = 1; row <= ROWS; row++) {
        for (const name of ROW_INPUTS(row)) {
            const found = node.inputs?.find((i) => i.name === name);
            if (found) defs.inputs[name] = { type: found.type, opts: { ...found } };
        }
        const out = node.outputs?.find((o) => o.name === ROW_OUTPUT(row));
        if (out) defs.outputs[ROW_OUTPUT(row)] = out.type;
    }
    node.stemsaveRowDefs = defs;
    return defs;
}

const wired = (slot) => slot != null && slot.link != null;
const connected = (slot) => slot != null && (slot.links ?? []).length > 0;

function reconcile(node) {
    const defs = remember(node);

    let lastUsed = 0;
    for (let row = 1; row <= ROWS; row++) {
        if (wired(node.inputs?.find((i) => i.name === `audio_${row}`))) lastUsed = row;
    }
    const keep = Math.min(ROWS, lastUsed + 1); // the rows in use, plus one spare

    for (let row = ROWS; row > keep; row--) {
        for (const name of ROW_INPUTS(row)) {
            const index = node.inputs?.findIndex((i) => i.name === name) ?? -1;
            if (index >= 0 && !wired(node.inputs[index])) node.removeInput(index);
        }
        const index = node.outputs?.findIndex((o) => o.name === ROW_OUTPUT(row)) ?? -1;
        if (index >= 0 && !connected(node.outputs[index])) node.removeOutput(index);
    }

    // Put back anything the trim above took away in an earlier pass, in row order.
    for (let row = 1; row <= keep; row++) {
        for (const name of ROW_INPUTS(row)) {
            if (node.inputs?.some((i) => i.name === name)) continue;
            const def = defs.inputs[name];
            if (def) node.addInput(name, def.type, def.opts);
        }
        if (!node.outputs?.some((o) => o.name === ROW_OUTPUT(row)) && defs.outputs[ROW_OUTPUT(row)]) {
            node.addOutput(ROW_OUTPUT(row), defs.outputs[ROW_OUTPUT(row)]);
        }
    }

    const size = node.computeSize();
    node.setSize([Math.max(node.size[0], size[0]), Math.max(node.size[1], size[1])]);
}

app.registerExtension({
    name: "StemSplitter.StemSaveRows",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "StemSave") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            reconcile(this);
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            reconcile(this);
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            onConnectionsChange?.apply(this, arguments);
            reconcile(this);
        };
    },
});
