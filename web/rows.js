/**
 * The row trimmer, shared by every node in this pack whose rows follow its wiring.
 *
 * ComfyUI fixes a node's OUTPUTS when the class is written and will not grow them at run time.
 * Inputs are the other way round: the executor hands a node whatever the prompt gives it, so a
 * node takes inputs its class never declared, and the front end can keep adding rows. That
 * leaves two shapes here:
 *
 *   - a bank the class declares, with a cap (StemSave: one output per row, so the row count is
 *     fixed by the outputs), and
 *   - rows that simply keep coming (TextMerge: one output, so the row count is free).
 *
 * Either way the node shows the rows in use plus one spare - only as tall as the work, with the
 * next row already there to wire - and only ever an unwired row is removed.
 *
 * A "spec" says where a node's rows live:
 *
 *   inputs   (row) => the input names that make up that row
 *   output   (row) => the output name for that row, or null when the node has none
 *   widgets  (row) => the widget names that belong to that row, hidden when the row goes
 *   defs     (name) => {type, opts} to build a row input from, for rows past what the class
 *            declared
 *   rows     the number of rows the class declared; omit for as many as get wired
 */
const wired = (slot) => slot != null && slot.link != null;
const connected = (slot) => slot != null && (slot.links ?? []).length > 0;

// A widget is hidden by its type: the frontend draws none whose type says "hidden", while a
// hidden widget's value is still saved and still reaches the node. Removing the input is not
// enough - that takes the socket away and leaves the field behind, which is why a row bank
// used to show every field it declares next to only the rows in use.
const SHOWN_TYPE = "ossShownType";

// A DOM widget draws its own element, and hiding it by type does not take the element's height
// away: the frontend keeps the space it last measured, so a bank down to two rows still stood as
// tall as twenty. The element and the size it reports go away with the row, and come back with it.
const SHOWN_DOM = "ossShownDom";

function setVisible(widget, visible) {
    if (!widget) return;
    const element = widget.element;
    if (visible) {
        if (widget[SHOWN_TYPE] !== undefined) {
            widget.type = widget[SHOWN_TYPE];
            delete widget[SHOWN_TYPE];
        }
        if (widget[SHOWN_DOM]) {
            const { display, computeSize } = widget[SHOWN_DOM];
            element.style.display = display;
            widget.computeSize = computeSize;
            delete widget[SHOWN_DOM];
        }
        return;
    }
    if (widget[SHOWN_TYPE] === undefined) {
        widget[SHOWN_TYPE] = widget.type;
        widget.type = "hidden";
    }
    if (element && !widget[SHOWN_DOM]) {
        widget[SHOWN_DOM] = { display: element.style.display, computeSize: widget.computeSize };
        element.style.display = "none";
        widget.computeSize = () => [0, 0];
    }
}

/** What a declared bank rebuilds a row from: the live node, before anything is removed. */
function remember(node, spec) {
    if (node.ossRowDefs) return node.ossRowDefs;
    const defs = { inputs: {}, outputs: {} };
    for (let row = 1; row <= spec.rows; row++) {
        for (const name of spec.inputs(row)) {
            const found = node.inputs?.find((i) => i.name === name);
            if (found) defs.inputs[name] = { type: found.type, opts: { ...found } };
        }
        const out = spec.output?.(row);
        const found = out && node.outputs?.find((o) => o.name === out);
        if (found) defs.outputs[out] = found.type;
    }
    node.ossRowDefs = defs;
    return defs;
}

/** The definition to build a row input from: the spec's own rule, or the declared bank. */
function inputDef(node, spec, name) {
    if (spec.defs) return spec.defs(name);
    return remember(node, spec).inputs[name] ?? null;
}

/** The highest row the node carries. Rows are added and removed in order, so this is a walk. */
function rowsOnNode(node, spec) {
    let highest = 0;
    for (let row = 1; spec.rows === undefined || row <= spec.rows; row++) {
        const present = spec.inputs(row).some((name) => node.inputs?.some((i) => i.name === name));
        if (!present) break;
        highest = row;
    }
    return highest;
}

/**
 * Size the node to what is showing.
 *
 * Height follows the rows, both ways: it is not something the user sets, and keeping it left a
 * bank that had dropped to two rows standing as tall as the twenty it declared. Width is the
 * user's - it only ever grows, so a node the user widened to read long names keeps that width.
 */
export function fit(node) {
    const size = node.computeSize();
    node.setSize([Math.max(node.size?.[0] ?? 0, size[0]), size[1]]);
    node.setDirtyCanvas(true, true);
}

/**
 * Put the node back to the rows in use plus one spare: drop the unwired rows past that, put
 * back any that an earlier pass took away, and add the next row when the wiring has reached it.
 *
 * Exported so the rule can be driven without a browser, with a stand-in node object.
 */
export function reconcile(node, spec) {
    // A declared bank is remembered before anything is removed, or the rows that are about to go
    // are forgotten along with them.
    if (!spec.defs) remember(node, spec);

    let lastUsed = 0;
    for (let row = 1; row <= rowsOnNode(node, spec); row++) {
        if (spec.inputs(row).some((name) => wired(node.inputs?.find((i) => i.name === name)))) {
            lastUsed = row;
        }
    }
    const keep = lastUsed + 1; // the rows in use, plus one spare

    for (let row = rowsOnNode(node, spec); row > keep; row--) {
        for (const name of spec.inputs(row)) {
            const index = node.inputs?.findIndex((i) => i.name === name) ?? -1;
            if (index >= 0 && !wired(node.inputs[index])) node.removeInput(index);
        }
        const out = spec.output?.(row);
        if (out) {
            const index = node.outputs?.findIndex((o) => o.name === out) ?? -1;
            if (index >= 0 && !connected(node.outputs[index])) node.removeOutput(index);
        }
    }

    for (let row = 1; row <= keep; row++) {
        for (const name of spec.inputs(row)) {
            if (node.inputs?.some((i) => i.name === name)) continue;
            const def = inputDef(node, spec, name);
            if (def) node.addInput(name, def.type, def.opts);
        }
        const out = spec.output?.(row);
        if (out && !node.outputs?.some((o) => o.name === out)) {
            const type = spec.defs ? null : remember(node, spec).outputs[out];
            if (type) node.addOutput(out, type);
        }
    }

    // The fields that belong to a row follow it: past the rows in use they are hidden, never
    // removed, so their values stay with the node.
    if (spec.widgets) {
        for (let row = 1; row <= spec.rows; row++) {
            for (const name of spec.widgets(row)) {
                setVisible(node.widgets?.find((w) => w.name === name), row <= keep);
            }
        }
    }

    fit(node);
}

/**
 * Keep a node type's rows down to the rows in use. Covers the three events that change them:
 * the node appearing, a workflow being loaded, and a wire being made.
 */
export function trimRows(nodeType, spec) {
    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
        onNodeCreated?.apply(this, arguments);
        reconcile(this, spec);
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
        onConfigure?.apply(this, arguments);
        reconcile(this, spec);
    };

    const onConnectionsChange = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function () {
        onConnectionsChange?.apply(this, arguments);
        reconcile(this, spec);
    };
}
