/**
 * AudioLoader - Load Audio with the pack's player on it.
 *
 * Core's Load Audio gives a pack node no transport: ComfyUI attaches its own player, waveform
 * and download to a fixed list of its own classes, and everything else gets a bare file box.
 * So this node draws the pack's player instead - the same one in audio_player.js that the save
 * nodes use - and the file it shows is the one the field points at, not the one a run wrote.
 *
 * The dropdown lists the folder as it was when the page loaded, so Upload... is how a file that
 * arrived since then gets in: it puts the file in input/ and selects it.
 */
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { PLAYER_HEIGHT, clearWaveform, loadPlayer, makePlayer } from "./audio_player.js";

const NODE = "AudioLoader";
const FIELD = "audio";

const fieldOf = (node) => node.widgets?.find((w) => w.name === FIELD);

app.registerExtension({
    name: "StemSplitter.AudioLoader",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            this.ossPlayer = makePlayer();
            const widget = this.addDOMWidget(
                "ossPlayer", "player", this.ossPlayer.box, { serialize: false }
            );
            widget.computeSize = (width) => [width, PLAYER_HEIGHT];

            // One picker for the life of the node. A picker made inside the click is referenced
            // by nothing, and a chosen file can go nowhere with it - a click that does nothing
            // at all. ComfyUI's own file input is held this way too, and its value is cleared so
            // that picking the same file a second time still counts as a change.
            const picker = document.createElement("input");
            picker.type = "file";
            picker.accept = "audio/*";
            picker.onchange = () => {
                const file = picker.files?.[0];
                picker.value = "";
                if (file) this.ossSelect(file);
            };
            this.ossPicker = picker;
            this.addWidget("button", "Upload...", null, () => picker.click());

            // The player follows the field, so picking another file redraws without a run.
            const field = fieldOf(this);
            if (field) {
                const chosen = field.callback;
                field.callback = (...args) => {
                    chosen?.apply(field, args);
                    this.ossShow(field.value);
                };
            }
            this.ossShow(field?.value);
        };

        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            if (this.ossPicker) {
                this.ossPicker.onchange = null;
                this.ossPicker = null;
            }
            onRemoved?.apply(this, arguments);
        };

        // A loaded workflow sets the fields directly, which fires no callback of its own.
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            this.ossShow(fieldOf(this)?.value);
        };

        /** Point the player at whatever the file field holds. */
        nodeType.prototype.ossShow = function (name) {
            const player = this.ossPlayer;
            if (!player) return;
            if (!name) {
                player.audio.pause();
                player.audio.removeAttribute("src");
                player.title.textContent = "";
                clearWaveform(player.canvas);
                return;
            }
            loadPlayer(player, { filename: name, subfolder: "", type: "input" }, null);
        };

        /** Put a file into ComfyUI's input folder, then select it. */
        nodeType.prototype.ossSelect = async function (file) {
            // The route and the field name ComfyUI's own upload widgets use. It takes any
            // file type and files land in input/, which is the folder this node lists.
            const body = new FormData();
            body.append("image", file);
            body.append("type", "input");

            let response;
            try {
                response = await api.fetchApi("/upload/image", { method: "POST", body });
            } catch (error) {
                alert(`Upload failed: ${error}`);
                return;
            }
            if (response.status !== 200) {
                alert(`Upload failed: ${response.status} ${response.statusText}`);
                return;
            }

            const saved = await response.json();
            const name = saved.subfolder ? `${saved.subfolder}/${saved.name}` : saved.name;
            const field = fieldOf(this);
            if (!field) return;

            // The dropdown was built when the page loaded, so a name uploaded since then is
            // not in it yet. Sorted, because the server lists the folder sorted.
            const values = field.options?.values;
            if (Array.isArray(values) && !values.includes(name)) {
                values.push(name);
                values.sort();
            }

            // Setting the value alone is not enough: ComfyUI's own upload does these two as
            // well, and the Vue node renderer and anything else watching the widget need them.
            // The callback the constructor put on the field also redraws the player.
            const previous = field.value;
            field.value = name;
            field.callback?.(name);
            this.onWidgetChanged?.(FIELD, name, previous, field);
        };
    },
});
