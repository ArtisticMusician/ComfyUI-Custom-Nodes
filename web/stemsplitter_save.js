/**
 * StemSplitter - the save nodes' browser affordances: a player and a Save as button.
 *
 * A pack's nodes get neither from ComfyUI. The built-in player and waveform go to a
 * hardcoded list of node classes (PreviewAudio, SaveAudio, SaveAudioMP3, SaveAudioOpus,
 * SaveAudioAdvanced), and the download goes with it. Both are built here instead.
 *
 * The player is a DOM widget holding a waveform canvas and a real audio element - the same
 * thing ComfyUI's own audio nodes use - so nothing here depends on frontend internals.
 *
 * The nodes put their written files in the ui payload as `audio` (the key ComfyUI's own
 * audio nodes use) and `stem_splitter_files` ([{filename, subfolder, type}]).
 */
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const SAVE_NODES = ["AudioSave", "AudioConvert", "Audio2MIDI", "StemSave"];
const PLAYER_NODES = ["AudioSave", "AudioConvert"]; // Audio2MIDI writes MIDI, so it has no audio to play

const WAVE_HEIGHT = 36;
const WAVE_COLOR = "#7ab0ff";

const fileURL = (f) =>
    api.apiURL(
        `/view?filename=${encodeURIComponent(f.filename)}` +
        `&subfolder=${encodeURIComponent(f.subfolder ?? "")}` +
        `&type=${encodeURIComponent(f.type ?? "output")}`
    );

function makePlayer() {
    const box = document.createElement("div");
    box.style.cssText = "display:flex;flex-direction:column;gap:4px;padding:2px 6px 4px;";

    const canvas = document.createElement("canvas");
    canvas.width = 512;
    canvas.height = WAVE_HEIGHT;
    canvas.style.cssText = `width:100%;height:${WAVE_HEIGHT}px;display:block;`;

    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.style.cssText = "width:100%;display:block;";

    box.append(canvas, audio);
    return { box, canvas, audio };
}

async function drawWaveform(canvas, url) {
    // Drawn at the node's real pixel width so a gap in the audio is a gap in the drawing,
    // and one bar per few pixels so short hits between long silences stay separate.
    canvas.width = Math.max(160, Math.round(canvas.clientWidth || 512));
    const ctx = canvas.getContext("2d");
    const { width, height } = canvas;
    ctx.clearRect(0, 0, width, height);
    try {
        const bytes = await (await fetch(url)).arrayBuffer();
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        const decoded = await new AudioCtx().decodeAudioData(bytes);

        // Every channel, not just the first: a stem panned to one side would otherwise
        // draw as silence.
        const channels = [];
        for (let c = 0; c < decoded.numberOfChannels; c++) {
            channels.push(decoded.getChannelData(c));
        }

        const total = decoded.length;
        const bars = Math.max(40, Math.min(400, Math.round(width / 4)));
        const perBar = Math.max(1, Math.floor(total / bars));
        const barWidth = width / bars;
        ctx.fillStyle = WAVE_COLOR;
        for (let bar = 0; bar < bars; bar++) {
            const start = bar * perBar;
            const end = Math.min(start + perBar, total);
            let peak = 0;
            for (const samples of channels) {
                for (let i = start; i < end; i++) {
                    const value = Math.abs(samples[i]);
                    if (value > peak) peak = value;
                }
            }
            const barHeight = Math.max(2, peak * (height - 6));
            ctx.fillRect(bar * barWidth + 1, (height - barHeight) / 2,
                         Math.max(1, barWidth - 2), barHeight);
        }
    } catch (error) {
        // Left blank on purpose: a failed decode must not look like a silent file.
        console.warn("[StemSplitter] could not draw the waveform", error);
    }
}

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
            const url = fileURL(first);
            this.stemSplitterPlayer.audio.src = url;
            drawWaveform(this.stemSplitterPlayer.canvas, url);
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
                widget.computeSize = (width) => [width, WAVE_HEIGHT + 42];
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
