/**
 * Increment - keeps the count where you can see it.
 *
 * The number lives in the node's own "starting number" field, and the node moves that
 * field on after every run. Nothing is stored anywhere else, so the count travels with the
 * workflow.
 */
import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "StemSplitter.Increment",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "Increment") return;

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            const next = message?.stem_splitter_next?.[0];
            const field = this.widgets?.find((w) => w.name === "starting_number");
            if (typeof next === "number" && field) field.value = next;
        };
    },
});
