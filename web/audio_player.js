/**
 * The pack's audio preview: a waveform canvas over a real audio element.
 *
 * ComfyUI hands its built-in player and its download only to a hardcoded list of its own
 * node classes (PreviewAudio, SaveAudio, SaveAudioMP3, SaveAudioOpus, SaveAudioAdvanced),
 * so a pack's nodes get neither. Both are built here, once, and used by every node that
 * needs them - the single-file savers and each row of StemSave.
 */
import { api } from "../../scripts/api.js";

export const WAVE_HEIGHT = 36;
export const PLAYER_HEIGHT = WAVE_HEIGHT + 42; // waveform plus the audio controls under it
const WAVE_COLOR = "#7ab0ff";

export const fileURL = (f) =>
    api.apiURL(
        `/view?filename=${encodeURIComponent(f.filename)}` +
        `&subfolder=${encodeURIComponent(f.subfolder ?? "")}` +
        `&type=${encodeURIComponent(f.type ?? "output")}`
    );

export function makePlayer() {
    const box = document.createElement("div");
    box.style.cssText = "display:flex;flex-direction:column;gap:4px;padding:2px 6px 4px;";

    const title = document.createElement("div");
    title.style.cssText = "font-size:12px;opacity:0.8;";

    const canvas = document.createElement("canvas");
    canvas.width = 512;
    canvas.height = WAVE_HEIGHT;
    canvas.style.cssText = `width:100%;height:${WAVE_HEIGHT}px;display:block;`;

    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.style.cssText = "width:100%;display:block;";

    box.append(title, canvas, audio);
    return { box, title, canvas, audio };
}

/** Draw a file's waveform. Width comes from the node, so a gap in the audio is a gap here. */
export async function drawWaveform(canvas, url) {
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

/** Point a player at a written file and label it. */
export function loadPlayer(player, file, name) {
    player.title.textContent = name || file.filename;
    const url = fileURL(file);
    player.audio.src = url;
    drawWaveform(player.canvas, url);
}
