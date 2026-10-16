/**
 * The pack's audio player: a waveform you play from.
 *
 * ComfyUI hands its own player and download only to a fixed list of its own node classes, so a
 * pack gets neither and builds both. This is the player, used by the single-file savers and by
 * every row of StemSave.
 *
 * The wave IS the timeline here. The browser's own controls cannot serve that: its scrub track
 * lives inside the element's shadow DOM, which JavaScript cannot reach, so a full-width waveform
 * could never line up with it - the two timelines had different beginnings and ends and playing
 * what you saw was guesswork. In this player the picture, the playhead and the thing you drag are
 * one element, so they line up by construction.
 */
import { api } from "../../scripts/api.js";

export const WAVE_HEIGHT = 36;
const TITLE_HEIGHT = 16;
const ROW_GAP = 6;
const BOX_PADDING = 6;
// The whole widget: the name line, the gap, the control row, the box's own padding.
export const PLAYER_HEIGHT = TITLE_HEIGHT + ROW_GAP + WAVE_HEIGHT + BOX_PADDING;

const WAVE_COLOR = "#7ab0ff";
const HEAD_COLOR = "#ff9a6a";
const SEEK_SECONDS = 5; // one arrow-key press
const PEAKS_PER_SECOND = 500; // the cache the drawing keeps, ~600 KB for five minutes

export const fileURL = (f) =>
    api.apiURL(
        `/view?filename=${encodeURIComponent(f.filename)}` +
        `&subfolder=${encodeURIComponent(f.subfolder ?? "")}` +
        `&type=${encodeURIComponent(f.type ?? "output")}`
    );

const PLAYING = "\u275A\u275A"; // two bars, text presentation
const PAUSED = "\u25B6\uFE0E";

const clock = (seconds) => {
    if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
    const total = Math.floor(seconds);
    const s = String(total % 60).padStart(2, "0");
    const m = Math.floor(total / 60) % 60;
    const h = Math.floor(total / 3600);
    return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
};

/**
 * Everything the controls show comes from here, so the button, the playhead and the clock cannot
 * drift apart: the audio element is the only state there is.
 */
function refresh(player) {
    const { audio, button, head, wave, time } = player;
    const duration = audio.duration;
    const ratio = duration ? Math.min(1, audio.currentTime / duration) : 0;

    button.textContent = audio.paused ? PAUSED : PLAYING;
    button.title = audio.paused ? "Play" : "Pause";
    button.setAttribute("aria-label", button.title);

    head.style.display = duration ? "block" : "none";
    head.style.left = `${ratio * 100}%`;
    wave.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
    wave.setAttribute("aria-valuetext", `${clock(audio.currentTime)} of ${clock(duration)}`);

    time.textContent = `${clock(audio.currentTime)} / ${clock(duration)}`;
}

/** The playhead follows the clock while it runs; `timeupdate` alone fires about four times a second. */
function tick(player) {
    if (player.audio.paused) {
        player.ticking = false;
        return;
    }
    refresh(player);
    player.ticking = requestAnimationFrame(() => tick(player));
}

function startTicking(player) {
    if (player.ticking) return;
    player.ticking = true;
    tick(player);
}

function seekTo(player, clientX) {
    const { audio, wave } = player;
    if (!audio.duration) return;
    const rect = wave.getBoundingClientRect();
    if (!rect.width) return;
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    audio.currentTime = ratio * audio.duration;
    refresh(player);
}

function wireTransport(player) {
    const { audio, button, wave } = player;

    button.addEventListener("click", () => {
        if (audio.paused) {
            // At the end there is nowhere left to play, so the button starts it over; a pause
            // half way through keeps its place.
            if (audio.ended || (audio.duration && audio.currentTime >= audio.duration - 0.01)) {
                audio.currentTime = 0;
            }
            audio.play();
        } else {
            audio.pause();
        }
    });

    audio.addEventListener("play", () => { refresh(player); startTicking(player); });
    audio.addEventListener("pause", () => { refresh(player); });
    audio.addEventListener("ended", () => { refresh(player); });
    audio.addEventListener("loadedmetadata", () => { refresh(player); });
    audio.addEventListener("timeupdate", () => { if (!player.ticking) refresh(player); });

    let dragging = false;
    wave.addEventListener("pointerdown", (event) => {
        dragging = true;
        // Seek first: capturing the pointer is a nicety, and if it ever throws it must not be
        // able to swallow the seek with it.
        seekTo(player, event.clientX);
        try {
            wave.setPointerCapture(event.pointerId);
        } catch (error) {
            // no pointer to capture (a synthetic event, or one already released)
        }
        event.preventDefault();
    });
    wave.addEventListener("pointermove", (event) => {
        if (dragging) seekTo(player, event.clientX);
    });
    const release = (event) => {
        dragging = false;
        try {
            wave.releasePointerCapture(event.pointerId);
        } catch (error) {
            // nothing captured
        }
    };
    wave.addEventListener("pointerup", release);
    wave.addEventListener("pointercancel", release);

    // The browser's own track was the only keyboard seek, and it is gone with the rest of its
    // controls, so the wave answers the arrows itself.
    wave.addEventListener("keydown", (event) => {
        if (!audio.duration) return;
        const steps = { ArrowLeft: -SEEK_SECONDS, ArrowRight: SEEK_SECONDS };
        if (event.key in steps) {
            audio.currentTime = Math.min(audio.duration,
                                         Math.max(0, audio.currentTime + steps[event.key]));
        } else if (event.key === "Home") {
            audio.currentTime = 0;
        } else if (event.key === "End") {
            audio.currentTime = audio.duration;
        } else {
            return;
        }
        refresh(player);
        event.preventDefault();
    });
}

export function makePlayer() {
    const box = document.createElement("div");
    box.style.cssText = `display:flex;flex-direction:column;gap:${ROW_GAP}px;padding:3px 6px;`;

    const title = document.createElement("div");
    title.style.cssText = "font-size:12px;line-height:1;opacity:0.8;white-space:nowrap;" +
                          "overflow:hidden;text-overflow:ellipsis;";

    const row = document.createElement("div");
    row.style.cssText = `display:flex;align-items:center;gap:6px;height:${WAVE_HEIGHT}px;`;

    const button = document.createElement("button");
    button.type = "button";
    button.textContent = PAUSED;
    button.title = "Play";
    button.setAttribute("aria-label", "Play");
    button.style.cssText = "flex:0 0 auto;width:22px;height:22px;padding:0;line-height:1;" +
                           "font-size:10px;cursor:pointer;";

    const wave = document.createElement("div");
    wave.style.cssText = `position:relative;flex:1 1 auto;height:${WAVE_HEIGHT}px;cursor:pointer;`;
    wave.tabIndex = 0;
    wave.setAttribute("role", "slider");
    wave.setAttribute("aria-label", "Playback position");
    wave.setAttribute("aria-valuemin", "0");
    wave.setAttribute("aria-valuemax", "100");

    const canvas = document.createElement("canvas");
    canvas.height = WAVE_HEIGHT;
    canvas.style.cssText = `width:100%;height:${WAVE_HEIGHT}px;display:block;`;

    const head = document.createElement("div");
    head.style.cssText = `position:absolute;top:0;bottom:0;width:2px;margin-left:-1px;` +
                         `background:${HEAD_COLOR};pointer-events:none;display:none;`;

    wave.append(canvas, head);

    const time = document.createElement("div");
    time.textContent = "0:00 / 0:00";
    time.style.cssText = "flex:0 0 auto;font-size:11px;opacity:0.75;text-align:right;" +
                         "font-variant-numeric:tabular-nums;min-width:74px;";

    row.append(button, wave, time);

    const audio = document.createElement("audio");
    audio.preload = "metadata";
    // Not display:none: Chromium never loads metadata for a media element it does not render, and
    // the clock and the playhead both come from that metadata. Rendered, but one transparent pixel.
    audio.style.cssText = "position:absolute;width:1px;height:1px;opacity:0;pointer-events:none;";

    box.append(title, row, audio);

    const player = { box, title, row, button, wave, canvas, head, time, audio };
    wireTransport(player);
    refresh(player);
    return player;
}

/** Peaks at a fixed rate, so the picture can be redrawn at any width without decoding again. */
function peaksOf(decoded) {
    const step = Math.max(1, Math.round(decoded.sampleRate / PEAKS_PER_SECOND));
    const count = Math.max(1, Math.ceil(decoded.length / step));
    const peaks = new Float32Array(count);

    // Every channel, not just the first: a stem panned to one side would otherwise draw as silence.
    const channels = [];
    for (let c = 0; c < decoded.numberOfChannels; c++) channels.push(decoded.getChannelData(c));

    for (let p = 0; p < count; p++) {
        const start = p * step;
        const end = Math.min(start + step, decoded.length);
        let peak = 0;
        for (const samples of channels) {
            for (let i = start; i < end; i++) {
                const value = Math.abs(samples[i]);
                if (value > peak) peak = value;
            }
        }
        peaks[p] = peak;
    }
    return peaks;
}

/** Draw the cached peaks at the node's real pixel width, so a gap in the audio is a gap here. */
function paint(canvas) {
    const width = Math.max(160, Math.round(canvas.clientWidth || 512));
    if (canvas.width !== width) canvas.width = width;

    const ctx = canvas.getContext("2d");
    const { height } = canvas;
    ctx.clearRect(0, 0, width, height);

    const peaks = canvas.ossPeaks;
    if (!peaks || !peaks.length) return; // left blank on purpose: a failed decode must not look like silence

    const bars = Math.max(40, Math.min(400, Math.round(width / 4)));
    const barWidth = width / bars;
    const perBar = peaks.length / bars;

    ctx.fillStyle = WAVE_COLOR;
    for (let bar = 0; bar < bars; bar++) {
        const start = Math.floor(bar * perBar);
        const end = Math.max(start + 1, Math.floor((bar + 1) * perBar));
        let peak = 0;
        for (let p = start; p < end && p < peaks.length; p++) {
            if (peaks[p] > peak) peak = peaks[p];
        }
        const barHeight = Math.max(2, peak * (height - 6)); // a silent bar keeps 2px
        ctx.fillRect(bar * barWidth + 1, (height - barHeight) / 2, Math.max(1, barWidth - 2), barHeight);
    }
}

/** A resized node gets a redraw, not a stretched bitmap. */
function observeWidth(canvas) {
    if (canvas.ossObserver) return;
    const measure = () => paint(canvas);
    canvas.ossObserver = new ResizeObserver(measure);
    canvas.ossObserver.observe(canvas);
}

/** Blank the picture, for when there is nothing to draw. */
export function clearWaveform(canvas) {
    canvas.ossPeaks = null;
    paint(canvas);
}

/** Draw a file's waveform. */
export async function drawWaveform(canvas, url) {
    clearWaveform(canvas);
    try {
        const bytes = await (await fetch(url)).arrayBuffer();
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        const decoded = await new AudioCtx().decodeAudioData(bytes);
        canvas.ossPeaks = peaksOf(decoded);
    } catch (error) {
        console.warn("[StemSplitter] could not draw the waveform", error);
        return;
    }
    paint(canvas);
    observeWidth(canvas);
}

/** Point a player at a written file and label it. */
export function loadPlayer(player, file, name) {
    player.title.textContent = name || file.filename;
    const url = fileURL(file);
    player.audio.pause();
    player.audio.src = url; // a new source starts at zero, so there is nothing to rewind
    refresh(player);
    drawWaveform(player.canvas, url);
}
