/**
 * StemSplitter - the single-file save nodes' player and Save as button.
 *
 * The player itself lives in audio_player.js, because StemSave draws one per stem.
 *
 * The nodes put their written files in the ui payload as `audio` (the key ComfyUI's own
 * audio nodes use) and `stem_splitter_files` ([{filename, subfolder, type}]).
 */
import { app } from "../../scripts/app.js";
import { PLAYER_HEIGHT, fileURL, loadPlayer, makePlayer } from "./audio_player.js";

const SAVE_NODES = ["AudioSave", "AudioConvert", "Audio2MIDI", "StemSave"];
const PLAYER_NODES = ["AudioSave", "AudioConvert"]; // Audio2MIDI writes MIDI, so it has no audio to play

app.registerExtension({
    name: "StemSplitter.SaveAs",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!SAVE_NODES.includes(nodeData.name)) return;
        const hasPlayer = PLAYER_NODES.includes(nodeData.name);

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            this.stemSplitterFiles = message?.stem_splitter_files ?? null;

            // Show the name the run actually used. ComfyUI ignores the field's own value
            // once an input is wired into it, so without this the field keeps showing
            // whatever it held before. Written only while an input is wired in, which is
            // exactly when the field cannot affect the run - so this is display only.
            const used = message?.stem_splitter_prefix?.[0];
            const wired = this.inputs?.find((i) => i.name === "filename_prefix");
            const field = this.widgets?.find((w) => w.name === "filename_prefix");
            if (used && field && wired && wired.link != null) {
                field.value = used;
            }

            const first = message?.audio?.[0];
            if (!hasPlayer || !first || !this.stemSplitterPlayer) return;
            loadPlayer(this.stemSplitterPlayer, first, null);
        };

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            this.stemSplitterFiles = null;

            if (hasPlayer) {
                this.stemSplitterPlayer = makePlayer();
                const widget = this.addDOMWidget(
                    "stemSplitterPlayer", "player", this.stemSplitterPlayer.box,
                    { serialize: false }
                );
                widget.computeSize = (width) => [width, PLAYER_HEIGHT];
            }

            this.addWidget("button", "Save as...", null, () => {
                const files = this.stemSplitterFiles;
                if (!files || !files.length) {
                    alert("Nothing saved yet - run the node first.");
                    return;
                }
                for (const f of files) {
                    const link = document.createElement("a");
                    link.href = fileURL(f);
                    link.download = f.filename;
                    document.body.appendChild(link);
                    link.click();
                    link.remove();
                }
            });
        };
    },
});
