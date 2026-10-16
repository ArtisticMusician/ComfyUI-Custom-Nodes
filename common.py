# Shared helpers for the whole pack.

"""
UVR5 Audio Suite — ComfyUI nodes for audio source separation and restoration.

Engine: the ``audio-separator`` package (the UVR5 model ecosystem). It is a
dependency of this environment; models are downloaded on first use into
``<ComfyUI>/models/audio_separator/`` and cached for the lifetime of the process.

Nodes
-----
UVR5 Audio Separator        two-stem separation (vocals/instrumental, lead/backing, ...)
UVR5 Multi-Stem Separator   one-pass 4/6-stem Demucs separation
UVR5 Audio Restoration      denoise / dereverb / de-echo using UVR restoration models
"""

import os
import re
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager

import comfy.audio
import comfy.utils
import soundfile as sf
import torch

import folder_paths

try:
    from audio_separator.separator import Separator
    from audio_separator.separator.ensembler import Ensembler
except Exception as exc:  # keep ComfyUI loading even when the backend is missing
    Separator = Ensembler = None
    _BACKEND_ERROR = exc
else:
    _BACKEND_ERROR = None


BRAND = "One Solo Studios"
CATEGORY = f"{BRAND}/Audio/StemSplitter"
AUDIO_CATEGORY = f"{BRAND}/Audio"
IO_CATEGORY = f"{BRAND}/Audio/IO"
TOOLS_CATEGORY = f"{BRAND}/Audio/Tools"
UTIL_CATEGORY = f"{BRAND}/Utils"

# Demucs splits into 4 or 6 stems in a single pass. Each node below offers only the
# models that produce the stems it has outputs for, so no output can ever be dead.
_STEMS4 = ("vocals", "drums", "bass", "other")
_STEMS6 = ("vocals", "drums", "bass", "guitar", "piano", "other")

# The drum model splits the kit itself. Its six stems are named the way the model declares
# them, which stem_1..stem_6 come back in, and the sockets are labelled readably on top.
_DRUMS = ("kick", "snare", "toms", "hh", "ride", "crash")
_DRUM_SOCKETS = ("kick", "snare", "toms", "hi_hat", "ride", "crash")

# The models offered in the dropdowns: the best two the library has for each of the
# twelve processes in BuildGuide.md, so every stage has a choice.
#
# Ranked by audio-separator's own published SDR where it publishes one. The rest of the
# catalogue (169 separator models: legacy checkpoints and community fine-tunes of the
# same few bases) is deliberately not offered.
#
# The guide names commercial tools that have no headless build — Waves Clarity,
# Accentize DeRoom2 and DX Revive, iZotope RX, Acon DeVerberate, LALAL.AI — and
# DeepFilterNet, which is not installed. The open-source models below stand in for them.
#
# Every entry is (guide process, why this model, exact catalogue name). The dropdowns and
# the cheat-sheet node both read these, so they cannot disagree.


_CLEAN_STEM_NAMES = ("dry", "noreverb")
_ARTIFACT_STEM_NAMES = ("noise", "reverb", "echo", "wet")


def _model_dir() -> str:
    """This pack's models, under the brand folder."""
    path = os.path.join(folder_paths.models_dir, "One Solo Studios", "audio_separator")
    os.makedirs(path, exist_ok=True)
    return path


def _run_dir() -> str:
    """Stable working directory for stems.

    audio-separator captures its output directory when the model is loaded, so a
    loaded engine cannot be pointed at a fresh temp dir per run; the directory is
    therefore fixed and emptied before each separation.
    """
    path = os.path.join(tempfile.gettempdir(), "uvr5_audiosuite")
    os.makedirs(path, exist_ok=True)
    return path


def _clear_dir(path: str) -> None:
    for entry in os.listdir(path):
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            shutil.rmtree(full, ignore_errors=True)
        else:
            try:
                os.remove(full)
            except OSError:
                pass


def _require_backend() -> None:
    if Separator is None or Ensembler is None:
        raise RuntimeError(
            "audio-separator is required by this pack's separation nodes but could not be "
            f"imported ({_BACKEND_ERROR}). Install it into the ComfyUI environment with: "
            "pip install audio-separator"
        )


# --------------------------------------------------------------------------- #
# Model catalogue — single source of truth is audio-separator's own model list
# --------------------------------------------------------------------------- #
# Used only when the catalogue cannot be loaded (e.g. first run with no network).
_FALLBACK_CATALOG = {
    "VR": {
        "VR Arch Single Model v5: 1_HP-UVR":
            {"filename": "1_HP-UVR.pth", "stems": ["instrumental", "vocals"]},
        "VR Arch Single Model v5: UVR-DeNoise by FoxJoy":
            {"filename": "UVR-DeNoise.pth", "stems": ["noise", "no noise"]},
        "VR Arch Single Model v4: UVR-De-Reverb by aufr33-jarredou":
            {"filename": "UVR-De-Reverb-aufr33-jarredou.pth", "stems": ["dry", "no dry"]},
    },
    "MDX": {
        "MDX-Net Model: Kim Vocal 2":
            {"filename": "Kim_Vocal_2.onnx", "stems": ["vocals", "instrumental"]},
    },
    "MDXC": {
        "Roformer Model: BS-Roformer-Viperx-1297":
            {"filename": "model_bs_roformer_ep_317_sdr_12.9755.ckpt", "stems": ["vocals", "instrumental"]},
        "MDX23C Model: MDX23C-InstVoc HQ":
            {"filename": "MDX23C-8KFFT-InstVoc_HQ.ckpt", "stems": ["vocals", "instrumental"]},
    },
    "Demucs": {
        "Demucs v4: htdemucs":
            {"filename": "htdemucs.yaml", "stems": ["vocals", "drums", "bass", "other"]},
        "Demucs v4: htdemucs_6s":
            {"filename": "htdemucs_6s.yaml", "stems": ["vocals", "drums", "bass", "guitar", "piano", "other"]},
    },
}

_catalog = None


def _catalog_models():
    """{arch: {label: {"filename": str, "stems": [str]}}}, built once."""
    global _catalog
    if _catalog is not None:
        return _catalog
    try:
        _require_backend()
        probe = Separator(
            model_file_dir=_model_dir(),
            output_dir=_run_dir(),
            output_format="wav",
            log_level=50,
        )
        raw = probe.list_supported_model_files()
        _catalog = {
            arch: {
                label: {"filename": info["filename"], "stems": list(info.get("stems") or [])}
                for label, info in models.items()
            }
            for arch, models in raw.items()
        }
    except Exception as exc:
        print(f"[UVR5] Could not read the model catalogue from audio-separator ({exc}); "
              f"falling back to the built-in model list.")
        _catalog = _FALLBACK_CATALOG
    return _catalog


def _choices(entries):
    """The guide's model list, filtered to what the installed catalogue actually has."""
    names = [name for _, _, name in entries]
    available = {label for models in _catalog_models().values() for label in models}
    chosen = [name for name in names if name in available]
    missing = [name for name in names if name not in available]
    if missing:
        print(f"[UVR5] Not in the audio-separator catalogue: {missing}")
    # Never hand ComfyUI an empty dropdown.
    return chosen or sorted(available)


def _resolve(label):
    """label -> model info dict."""
    for models in _catalog_models().values():
        if label in models:
            return models[label]
    raise ValueError(
        f"Model '{label}' is not in the audio-separator catalogue. "
        "Press R to refresh the node, then pick another model."
    )


# --------------------------------------------------------------------------- #
# Engine + inference
# --------------------------------------------------------------------------- #
# One loaded Separator per model filename: loading is expensive, inference is not.
_ENGINES = {}


def _engine(filename: str) -> "Separator":
    engine = _ENGINES.get(filename)
    if engine is None:
        _require_backend()
        engine = Separator(
            model_file_dir=_model_dir(),
            output_dir=_run_dir(),
            output_format="wav",
            sample_rate=44100,
            log_level=30,
            # Write stems through soundfile, at the depth of the mix it was handed. The
            # library's default writer runs every stem through pydub, which casts it to
            # 16-bit PCM no matter how deep its input was.
            use_soundfile=True,
        )
        engine.load_model(filename)  # downloads the weights on first use
        _ENGINES[filename] = engine
    return engine


_STEM_TAG = re.compile(r"_\(([^()]+)\)")


def _float32_input():
    """The WAV depth switch the two save nodes share.

    One definition, so the label, the default and the tooltip cannot drift apart between
    them. On is 32-bit float - the precision the models hand over, no round trip through
    16-bit on the way to disk. Off is 16-bit PCM, what these nodes wrote before the switch
    existed.
    """
    return ("BOOLEAN", {
        "default": True,
        "tooltip": "Write 32-bit float WAV instead of 16-bit: full precision out of the "
                   "models, about twice the size, and some players will not open it.",
    })


def _write_wav(path, waveform, sample_rate, float32=False):
    """Write one clip as WAV: 32-bit float, or 16-bit PCM when ``float32`` is off.

    Nothing is reshaped here beyond a 1-D clip becoming one channel, so a mono clip stays
    mono. Anything a separation model needs on top of that belongs to the call that feeds
    the engine.
    """
    wav = waveform.detach().cpu().float()
    if wav.dim() == 1:
        wav = wav.unsqueeze(0)
    sf.write(path, wav.numpy().T, int(sample_rate),
             subtype="FLOAT" if float32 else "PCM_16")


def _to_comfy_audio(path):
    data, sample_rate = sf.read(path, dtype="float32", always_2d=True)  # [samples, channels]
    waveform = torch.from_numpy(data.T).contiguous()
    return {"waveform": waveform.unsqueeze(0), "sample_rate": int(sample_rate)}


def _file_entry(path, folder, kind="output"):
    """A file entry for the frontend: where one file sits inside its own folder."""
    rel = os.path.relpath(os.path.dirname(path), folder).replace(os.sep, "/")
    return {
        "filename": os.path.basename(path),
        "subfolder": "" if rel == "." else rel,
        "type": kind,
    }


def _saved_file(path):
    """A file entry for the frontend's Save as button, relative to the output folder."""
    return _file_entry(path, folder_paths.get_output_directory(), "output")


# Opus only accepts these sample rates, so other rates are moved to the next one up.
_OPUS_RATES = (8000, 12000, 16000, 24000, 48000)

# Container and encoder PyAV uses for the two formats only it can write - the same encoders
# ComfyUI's own audio nodes pick. WAV and FLAC are not here: soundfile writes both, and it
# is the one that can write FLAC at 24-bit.
_AV_CONTAINERS = {"mp3": "mp3", "opus": "opus"}
_AV_ENCODERS = {"mp3": "libmp3lame", "opus": "libopus"}


def _write_compressed(wav, sample_rate, path, fmt, quality):
    """Write one clip as flac, mp3 or opus.

    FLAC is written by soundfile at 24-bit: lossless, the ceiling every player opens. PyAV's
    own flac encoder offers only 16- and 32-bit, and a 32-bit FLAC is refused by most
    players. MP3 and Opus go through PyAV, the library ComfyUI's own audio nodes save
    through, with the same encoders they pick - soundfile cannot write either. Opus only
    accepts a few sample rates, so anything else is moved to the next one up first.
    """
    samples = wav.detach().cpu().float()
    if fmt == "flac":
        sf.write(path, samples.numpy().T, int(sample_rate),
                 format="FLAC", subtype="PCM_24")
        return

    import av

    rate = sample_rate
    if fmt == "opus":
        if rate > 48000:
            rate = 48000
        elif rate not in _OPUS_RATES:
            rate = next((r for r in _OPUS_RATES if r > rate), 48000)

    if rate != sample_rate:
        samples = comfy.audio.resample(samples, sample_rate, rate)

    layout = "mono" if samples.shape[0] == 1 else "stereo"
    container = av.open(path, mode="w", format=_AV_CONTAINERS[fmt])
    stream = container.add_stream(_AV_ENCODERS[fmt], rate=rate, layout=layout)
    if fmt in ("mp3", "opus"):  # the lossy two; flac is lossless
        stream.bit_rate = int(str(quality).rstrip("k")) * 1000

    frame = av.AudioFrame.from_ndarray(
        samples.movedim(0, 1).reshape(1, -1).numpy(),
        format="flt",
        layout=layout,
    )
    frame.sample_rate = rate
    frame.pts = 0
    container.mux(stream.encode(frame))
    container.mux(stream.encode(None))
    container.close()


def _output_path(filename_prefix, ext, stamp=None, index=None):
    """Where a node writes, always inside ComfyUI's output folder.

    ComfyUI's own resolver does the work: it applies the ``%year%``-style variables,
    allows subfolders in the prefix ("stems/song/vocals"), creates the folder, and
    refuses anything that points outside the output directory.

    ``stamp`` set  -> name_<stamp>.ext: a new file per run, which is what you want while
                      iterating, and it never overwrites anything.
    ``stamp`` None -> ComfyUI's own counter: name_00001.ext, so a re-run adds a file
                      instead of replacing one.
    """
    folder = folder_paths.get_output_directory()
    out, name, counter, _, _ = folder_paths.get_save_image_path(filename_prefix, folder)
    if stamp is None:
        return os.path.join(out, f"{name}_{counter + (index or 0):05}.{ext}")

    name = f"{name}_{stamp}" + (f"_{index:02}" if index is not None else "")
    path = os.path.join(out, f"{name}.{ext}")
    bump = 2
    while os.path.exists(path):  # two runs inside the same second
        path = os.path.join(out, f"{name}-{bump}.{ext}")
        bump += 1
    return path


def _input_waveform(audio):
    waveform = audio["waveform"]
    if waveform.dim() == 3:
        if waveform.shape[0] > 1:
            print(f"[UVR5] Audio batch has {waveform.shape[0]} items; processing the first only.")
        waveform = waveform[0]
    return waveform, int(audio["sample_rate"])


# ComfyUI draws a node's progress bar from the updates that node sends. The separation
# engine reports no percentage of its own, so we send the phases we know, and refine the
# middle of the bar from the progress the engine prints while it works.
_PCT = re.compile(r"(\d{1,3})%\|")


class _StderrWatcher:
    """Lets stderr through untouched, while watching it for the engine's own progress."""

    def __init__(self, underlying, report):
        self._underlying = underlying
        self._report = report
        self._tail = ""

    def write(self, text):
        self._tail = (self._tail + text)[-160:]
        found = _PCT.findall(self._tail)
        if found:  # the newest percentage in the buffer, not every one still in it
            self._report(min(int(found[-1]), 100))
        return self._underlying.write(text)

    def flush(self):
        return self._underlying.flush()

    def __getattr__(self, name):
        return getattr(self._underlying, name)


@contextmanager
def _separation(filename: str, waveform, sample_rate, pbar=None):
    """Run ``filename`` over the waveform; yields [(stem_name, output_path), ...]."""
    sent = {"value": -1}

    def report(value):
        # The bar only ever moves forward; the engine's own output can arrive out of order.
        if pbar is None or value <= sent["value"]:
            return
        sent["value"] = value
        pbar.update_absolute(value)

    # Where the engine's own progress lands on the bar. Downloading a model for the first
    # time is by far the longest wait there is, so its window gets real room; a model
    # already on disk loads in a moment, so its window stays small.
    downloading = not os.path.exists(os.path.join(_model_dir(), filename))
    window = {"lo": 2, "hi": 60 if downloading else 10}

    def refine(pct):
        report(window["lo"] + pct * (window["hi"] - window["lo"]) // 100)

    report(2)
    workdir = _run_dir()
    _clear_dir(workdir)
    # The engine prints its own progress to stderr; watch it without swallowing it.
    real_stderr, sys.stderr = sys.stderr, _StderrWatcher(sys.stderr, refine)
    try:
        engine = _engine(filename)
        ready = window["hi"]
        report(ready)
        window["lo"], window["hi"] = ready, 95
        source = os.path.join(workdir, "input.wav")
        mix = waveform.detach().cpu().float()
        if mix.dim() == 1:
            mix = mix.unsqueeze(0)
        if mix.shape[0] == 1:  # separation models expect stereo
            mix = mix.repeat(2, 1)
        # 32-bit float, so the engine's own writer has full precision to put into the
        # stems it hands back, and nothing downstream starts from 16 bits.
        _write_wav(source, mix, sample_rate, float32=True)
        produced = engine.separate(source)
        report(96)
        stems = []
        for path in produced:
            # audio-separator returns bare filenames for single-model runs.
            if not os.path.isabs(path):
                path = os.path.join(workdir, path)
            if not os.path.exists(path):
                raise RuntimeError(f"audio-separator reported a missing output file: {path}")
            tag = _STEM_TAG.search(os.path.basename(path))
            name = tag.group(1) if tag else os.path.splitext(os.path.basename(path))[0]
            stems.append((name, path))
        report(100)
        yield stems
    finally:
        sys.stderr = real_stderr
        _clear_dir(workdir)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _ordered_stems(stems, declared):
    """Order stems as the model declares them (primary stem first).

    audio-separator returns output files in an arbitrary order, so the catalogue's
    declared stem order is used to make ``stem_1`` deterministic and meaningful.
    Stems the model does not declare keep their relative position at the end.
    """
    if not declared:
        return stems
    index = {_norm(name): i for i, name in enumerate(declared)}
    return sorted(stems, key=lambda item: index.get(_norm(item[0]), len(declared)))


def _clean_stem(stems):
    """Pick the cleaned stem produced by a restoration model."""
    for name, path in stems:
        lowered = name.strip().lower()
        if lowered.startswith("no ") or lowered in _CLEAN_STEM_NAMES:
            return name, path
    for name, path in stems:
        if name.strip().lower() not in _ARTIFACT_STEM_NAMES:
            return name, path
    return stems[0]


def _removed_stem(stems, clean_path):
    """The artifact stem: whatever the model took out of the signal."""
    for name, path in stems:
        if path != clean_path:
            return name, path
    raise RuntimeError(f"only one stem came back ({stems[0][0]}); nothing was removed.")


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #






# Everything above is this module's surface, private helpers included: the split-out
# modules pull from here with `import *`, which otherwise skips underscore names.
__all__ = [name for name in dir() if not name.startswith("__")]
