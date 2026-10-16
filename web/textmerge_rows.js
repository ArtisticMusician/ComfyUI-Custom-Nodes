/**
 * TextMerge's front end: wire a text into the last row and another row appears, for as long as
 * you keep going. There is no fixed number of rows and never a row to add by hand - the class
 * declares the first one, and every row past it is built here from the same rule.
 *
 * The row bookkeeping itself is rows.js, which StemSave and StemEnsemble use too.
 */
import { app } from "../../scripts/app.js";
import { trimRows } from "./rows.js";

const ROW_INPUTS = (row) => [`text_${row}`];
const ROW_DEF = () => ({ type: "STRING", opts: { forceInput: true } });
const ROWS_SPEC = { inputs: ROW_INPUTS, output: () => null, defs: ROW_DEF };

app.registerExtension({
    name: "StemSplitter.TextMergeRows",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "TextMerge") return;
        trimRows(nodeType, ROWS_SPEC);
    },
});
