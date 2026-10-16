/**
 * StemEnsemble's front end: its eight rows kept down to the rows in use, so the node is only
 * as tall as the blending you are doing. The trimming itself is rows.js.
 */
import { app } from "../../scripts/app.js";
import { trimRows } from "./rows.js";

const ROWS = 8;
const ROW_INPUTS = (row) => [`audio_${row}`, `opposite_${row}`];
const ROWS_SPEC = { rows: ROWS, inputs: ROW_INPUTS, output: () => null };

app.registerExtension({
    name: "StemSplitter.StemEnsembleRows",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "StemEnsemble") return;
        trimRows(nodeType, ROWS_SPEC);
    },
});
