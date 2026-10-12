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
except Exception as exc:  # keep ComfyUI loading even when the backend is missing
    Separator = None
    _BACKEND_ERROR = exc
else:
    _BACKEND_ERROR = None


# Node menu, i.e. the folders shown in ComfyUI's node search:
#     One Solo Studios
#       Audio                 <- AudioSave, Audio2MIDI, AudioConvert
#         StemSplitter        <- the splitter family, including the cheat sheet
#       Utils                 <- Increment
BRAND = "One Solo Studios"
CATEGORY = f"{BRAND}/Audio/StemSplitter"
AUDIO_CATEGORY = f"{BRAND}/Audio"
UTIL_CATEGORY = f"{BRAND}/Utils"

# Demucs splits into 4 or 6 stems in a single pass. Each node below offers only the
# models that produce the stems it has outputs for, so no output can ever be dead.
_STEMS4 = ("vocals", "drums", "bass", "other")
_STEMS6 = ("vocals", "drums", "bass", "guitar", "piano", "other")

# The models offered in the dropdowns: the best two the library has for each of the
# twelve processes in BuildGuide.md, so every stage has a choice.
#
# Ranked by audio-separator's own published SDR where it publishes one. The rest of the
# catalogue (145 separator models: legacy checkpoints and community fine-tunes of the
# same few bases) is deliberately not offered.
#
# The guide names commercial tools that have no headless build — Waves Clarity,
# Accentize DeRoom2 and DX Revive, iZotope RX, Acon DeVerberate, LALAL.AI — and
# DeepFilterNet, which is not installed. The open-source models below stand in for them.
#
# Every entry is (guide process, why this model, exact catalogue name). The dropdowns and
# the cheat-sheet node both read these, so they cannot disagree.
GUIDE_SPLITTER_MODELS = (
    ("1 Vocals / Instrumental", "best instrumental score", "Roformer Model: BS-Roformer-Viperx-1297"),
    ("1 Vocals / Instrumental", "best vocals score", "Roformer Model: MelBand Roformer | Vocals by Kimberley Jensen"),
    ("2 Lead / Backing", "newest karaoke model", "Roformer Model: Mel-Roformer-Karaoke-Aufr33-Viperx"),
    ("2 Lead / Backing", "classic karaoke, VR arch", "VR Arch Single Model v5: 5_HP-Karaoke-UVR"),
    ("3 Drums", "Demucs is better", "MDX-Net Model: kuielab_a_drums"),
    ("3 Drums", "Demucs is better", "MDX-Net Model: kuielab_b_drums"),
    ("4 Bass", "Demucs is better", "MDX-Net Model: kuielab_a_bass"),
    ("4 Bass", "Demucs is better", "MDX-Net Model: kuielab_b_bass"),
    ("8 Brass / wind", "only wind model; stem_2 = woodwinds", "VR Arch Single Model v5: 17_HP-Wind_Inst-UVR"),
    ("9 Other", "Demucs is better", "MDX-Net Model: kuielab_a_other"),
    ("9 Other", "Demucs is better", "MDX-Net Model: kuielab_b_other"),
)

GUIDE_SPLITTER4_MODELS = (
    ("3-9 separate stems", "the standard one", "Demucs v4: htdemucs"),
    ("3-9 separate stems", "fine-tuned, best quality, slower", "Demucs v4: htdemucs_ft"),
)

GUIDE_SPLITTER6_MODELS = (
    ("5 Guitar / 6 Piano", "the only model that gives guitar and piano", "Demucs v4: htdemucs_6s"),
)

GUIDE_FX_MODELS = (
    ("10 Dereverb", "highest scoring", "Roformer Model: MelBand Roformer | De-Reverb by anvuew"),
    ("10 Dereverb", "less aggressive", "Roformer Model: MelBand Roformer | De-Reverb Less Aggressive by anvuew"),
    ("11 Denoise", "highest scoring", "Roformer Model: Mel-Roformer-Denoise-Aufr33"),
    ("11 Denoise", "more aggressive", "Roformer Model: Mel-Roformer-Denoise-Aufr33-Aggr"),
    ("12 De-echo", "normal", "VR Arch Single Model v5: UVR-De-Echo-Normal by FoxJoy"),
    ("12 De-echo", "stronger", "VR Arch Single Model v5: UVR-De-Echo-Aggressive by FoxJoy"),
)

_CHEATSHEET_TAIL = """
Which node for which process
----------------------------
  1 Vocals / Instrumental    StemSplitter
  2 Lead / Backing vocals    StemSplitter    (the karaoke models)
  3 Drums                    StemSplitter4   Demucs beats the kuielab models
  4 Bass                     StemSplitter4
  5 Guitar                   StemSplitter6   only htdemucs_6s does this
  6 Piano                    StemSplitter6   only htdemucs_6s does this
  7 Strings                  nothing in the library does this
  8 Brass / wind             StemSplitter    woodwinds only; no brass model exists
  9 Other                    StemSplitter4
 10 Dereverb                 StemSplitterFX
 11 Denoise                  StemSplitterFX
 12 De-echo                  StemSplitterFX
 13 A sound you describe     StemSplitterSAM SAM-Audio, not the UVR5 library

Where there is no choice, because the library has nothing to give
  5 Guitar, 6 Piano   htdemucs_6s is the only model that produces them
  7 Strings           nothing at all
  8 Brass             only a woodwind model; nothing brass-specific

Named by the guide but not usable here
  Waves Clarity, Accentize DeRoom2, DX Revive, iZotope RX,
  Acon DeVerberate, LALAL.AI  - commercial, no headless build
  DeepFilterNet               - not installed

Model weights are downloaded into  ComfyUI/models/OneSoloStudio/audio_separator/
SAM-Audio checkpoints go in       ComfyUI/models/OneSoloStudio/sam_audio/
"""


def _grouped(entries):
    """Collapse consecutive entries that share a process, so it is named once."""
    groups = []
    for process, why, name in entries:
        if groups and groups[-1][0] == process:
            groups[-1][1].append((why, name))
        else:
            groups.append((process, [(why, name)]))
    return groups


def _sam_lines():
    """The SAM-Audio section, read from that node so it cannot drift from the node itself."""
    try:
        from .sam_audio_nodes import StemSplitterSAM

        options = StemSplitterSAM.INPUT_TYPES()["required"]
        models = [name.rsplit("/", 1)[-1] for name in options["model_name"][0]]
    except Exception as error:  # vendored support, or Meta's library, is not usable
        return ["", "StemSplitterSAM - not usable in this install",
                f"      {type(error).__name__}: {error}"]

    return [
        "",
        "StemSplitterSAM - 1 description in, target + residual out",
        "  A different kind of tool: rather than picking a model for a process, you name the",
        "  sound, and Meta's SAM-Audio pulls it out.",
        "  description      short and lowercase: man speaking, dog barking, car honking",
        "  target           the sound you named",
        "  residual         everything else",
        "  chunk_duration   seconds per pass; long files are chunked, so they take a while",
        "  model_name       " + ", ".join(models),
        "                   the -tv checkpoints take visual prompts and are not used here",
    ]


def _cheatsheet_text():
    lines = ["StemSplitter - which model for which job", "=" * 40]
    for heading, entries in (("StemSplitter   -  1 model in, 2 stems out", GUIDE_SPLITTER_MODELS),
                             ("StemSplitter4  -  1 model in, 4 stems out", GUIDE_SPLITTER4_MODELS),
                             ("StemSplitter6  -  1 model in, 6 stems out", GUIDE_SPLITTER6_MODELS),
                             ("StemSplitterFX -  1 model in, cleaned + removed out", GUIDE_FX_MODELS)):
        lines += ["", heading]
        for process, group in _grouped(entries):
            lines.append(f"  {process}")
            for why, name in group:
                lines.append(f"      {name.split(': ', 1)[-1]}  -  {why}")
    lines += _sam_lines()
    return "\n".join(lines) + _CHEATSHEET_TAIL


CHEATSHEET = _cheatsheet_text()

# Stem names that carry the *cleaned* signal produced by a restoration model.
_CLEAN_STEM_NAMES = ("dry", "noreverb")
_ARTIFACT_STEM_NAMES = ("noise", "reverb", "echo", "wet")


# --------------------------------------------------------------------------- #
# Backend / model directory
# --------------------------------------------------------------------------- #
def _model_dir() -> str:
    """This pack's models, under the brand folder."""
    path = os.path.join(folder_paths.models_dir, "OneSoloStudio", "audio_separator")
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
    if Separator is None:
        raise RuntimeError(
            "audio-separator is required by StemSplitter but could not be "
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
        )
        engine.load_model(filename)  # downloads the weights on first use
        _ENGINES[filename] = engine
    return engine


_STEM_TAG = re.compile(r"_\(([^()]+)\)")


def _write_wav(path, waveform, sample_rate):
    wav = waveform.detach().cpu().float()
    if wav.dim() == 1:
        wav = wav.unsqueeze(0)
    if wav.shape[0] == 1:  # separation models expect stereo
        wav = wav.repeat(2, 1)
    sf.write(path, wav.numpy().T, int(sample_rate))


def _to_comfy_audio(path):
    data, sample_rate = sf.read(path, dtype="float32", always_2d=True)  # [samples, channels]
    waveform = torch.from_numpy(data.T).contiguous()
    return {"waveform": waveform.unsqueeze(0), "sample_rate": int(sample_rate)}


def _saved_file(path):
    """A file entry for the frontend's Save as button, relative to the output folder."""
    folder = folder_paths.get_output_directory()
    rel = os.path.relpath(os.path.dirname(path), folder).replace(os.sep, "/")
    return {
        "filename": os.path.basename(path),
        "subfolder": "" if rel == "." else rel,
        "type": "output",
    }


# Opus only accepts these sample rates, so other rates are moved to the next one up.
_OPUS_RATES = (8000, 12000, 16000, 24000, 48000)

# Container and encoder PyAV uses per format - the same choices ComfyUI's own audio nodes
# make. WAV is not here: it is written directly by soundfile, which is what the save node
# and this pack work in.
_AV_CONTAINERS = {"flac": "flac", "mp3": "mp3", "opus": "opus"}
_AV_ENCODERS = {"flac": "flac", "mp3": "libmp3lame", "opus": "libopus"}


def _write_compressed(wav, sample_rate, path, fmt, quality):
    """Write one clip as flac, mp3 or opus.

    Encoding goes through PyAV, the library ComfyUI's own audio nodes save through, with
    the same encoders they pick - soundfile cannot write any of these three. Opus only
    accepts a few sample rates, so anything else is moved to the next one up first.
    """
    import av

    rate = sample_rate
    if fmt == "opus":
        if rate > 48000:
            rate = 48000
        elif rate not in _OPUS_RATES:
            rate = next((r for r in _OPUS_RATES if r > rate), 48000)

    samples = wav.float()
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
        _write_wav(source, waveform, sample_rate)
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
class StemSplitter:
    """Two-stem split with any UVR5 model (Roformer / MDX / VR)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "model": (_choices(GUIDE_SPLITTER_MODELS),),
            }
        }

    RETURN_TYPES = ("AUDIO", "AUDIO")
    RETURN_NAMES = ("stem_1", "stem_2")
    FUNCTION = "split"
    CATEGORY = CATEGORY
    DESCRIPTION = ("Splits an audio clip into two stems (e.g. Vocals / Instrumental) "
                   "with a UVR5 model. stem_1 is the model's primary stem.")

    def split(self, audio, model):
        info = _resolve(model)
        waveform, sample_rate = _input_waveform(audio)
        with _separation(info["filename"], waveform, sample_rate, comfy.utils.ProgressBar(100)) as stems:
            stems = _ordered_stems(stems, info["stems"])
            if len(stems) < 2:
                raise RuntimeError(
                    f"'{model}' produced {len(stems)} stem(s); at least 2 were expected."
                )
            print(f"[UVR5] {model}: " + ", ".join(f"{n}={os.path.basename(p)}" for n, p in stems))
            return (_to_comfy_audio(stems[0][1]), _to_comfy_audio(stems[1][1]))


class _DemucsNode:
    """Shared behaviour for the Demucs nodes.

    A subclass fixes its stems and the models that produce them, so the outputs on the
    node always match what the model actually gives you - no dead sockets.
    """

    STEMS = ()
    MODELS = ()

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio": ("AUDIO",), "model": (_choices(cls.MODELS),)}}

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ()
    FUNCTION = "split"
    CATEGORY = CATEGORY

    def split(self, audio, model):
        info = _resolve(model)
        waveform, sample_rate = _input_waveform(audio)
        with _separation(info["filename"], waveform, sample_rate, comfy.utils.ProgressBar(100)) as stems:
            by_name = {_norm(name): path for name, path in stems}
            print(f"[UVR5] {model}: " + ", ".join(sorted(by_name)))
            absent = [name for name in self.STEMS if _norm(name) not in by_name]
            if absent:
                raise RuntimeError(
                    f"'{model}' did not produce {', '.join(absent)}; "
                    f"it produced {', '.join(sorted(by_name))}."
                )
            return tuple(_to_comfy_audio(by_name[_norm(name)]) for name in self.STEMS)


class StemSplitter4(_DemucsNode):
    """Four stems in one pass: vocals, drums, bass, other."""

    STEMS = _STEMS4
    MODELS = GUIDE_SPLITTER4_MODELS
    RETURN_TYPES = ("AUDIO",) * len(_STEMS4)
    RETURN_NAMES = _STEMS4
    DESCRIPTION = "Four stems in one pass: vocals, drums, bass, other."


class StemSplitter6(_DemucsNode):
    """Six stems in one pass, guitar and piano included."""

    STEMS = _STEMS6
    MODELS = GUIDE_SPLITTER6_MODELS
    RETURN_TYPES = ("AUDIO",) * len(_STEMS6)
    RETURN_NAMES = _STEMS6
    DESCRIPTION = "Six stems in one pass: vocals, drums, bass, guitar, piano, other."


class StemSplitterFX:
    """Denoise / dereverb / de-echo with the UVR restoration models."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "model": (_choices(GUIDE_FX_MODELS),),
            }
        }

    RETURN_TYPES = ("AUDIO", "AUDIO")
    RETURN_NAMES = ("processed", "removed")
    FUNCTION = "restore"
    CATEGORY = CATEGORY
    DESCRIPTION = ("Removes noise, reverb or echo. 'processed' is the cleaned signal, "
                   "'removed' is what was taken out of it. Leave 'removed' unwired if "
                   "you don't want it.")

    def restore(self, audio, model):
        info = _resolve(model)
        waveform, sample_rate = _input_waveform(audio)
        with _separation(info["filename"], waveform, sample_rate, comfy.utils.ProgressBar(100)) as stems:
            name, path = _clean_stem(stems)
            removed_name, removed_path = _removed_stem(stems, path)
            print(f"[UVR5] {model}: processed '{name}', removed '{removed_name}'")
            return (_to_comfy_audio(path), _to_comfy_audio(removed_path))


class StemSplitterCheatsheet:
    """Which model for which job. Drop it on the canvas and the text is already there."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "cheat_sheet": ("STRING", {"multiline": True, "default": CHEATSHEET}),
            }
        }

    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "show"
    CATEGORY = CATEGORY
    DESCRIPTION = "The StemSplitter model cheat sheet, filled in for you. Nothing to wire up."

    def show(self, cheat_sheet):
        return ()


# --------------------------------------------------------------------------- #
# Audio2MIDI — Spotify's Basic Pitch
# --------------------------------------------------------------------------- #
# Not a UVR5 model, it just lives here with the other audio nodes. The library is
# imported on demand so this pack still loads in instances that do not have it.
_BASIC_PITCH = {}


def _basic_pitch():
    """Basic Pitch's predict function and model, loaded once per process."""
    if "model" not in _BASIC_PITCH:
        try:
            from basic_pitch import ICASSP_2022_MODEL_PATH
            from basic_pitch.inference import Model, predict
        except ImportError as exc:
            raise RuntimeError(
                "Basic Pitch is not installed in this ComfyUI's Python. Install it with:\n"
                "  pip install --no-deps basic-pitch pretty_midi resampy mir_eval"
            ) from exc
        _BASIC_PITCH["predict"] = predict
        _BASIC_PITCH["model"] = Model(ICASSP_2022_MODEL_PATH)
    return _BASIC_PITCH["predict"], _BASIC_PITCH["model"]


class Audio2MIDI:
    """Transcribes an audio clip to MIDI with Spotify's Basic Pitch."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "filename_prefix": ("STRING", {
                    "default": "audio2midi",
                    "tooltip": "Name, and optionally a subfolder, inside ComfyUI's output folder.",
                }),
                "timestamp": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Put the time in the name so every run writes a new file.",
                }),
                "onset_threshold": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "How sure the model must be that a note starts here.",
                }),
                "frame_threshold": ("FLOAT", {
                    "default": 0.3, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "How sure the model must be that a note is still sounding.",
                }),
                "minimum_note_length": ("FLOAT", {
                    "default": 127.7, "min": 0.0, "max": 5000.0, "step": 1.0,
                    "tooltip": "Shortest note to keep, in milliseconds.",
                }),
            }
        }

    RETURN_TYPES = ("MIDI", "STRING")
    RETURN_NAMES = ("midi", "midi_path")
    FUNCTION = "transcribe"
    CATEGORY = AUDIO_CATEGORY
    DESCRIPTION = "Audio to MIDI with Spotify's Basic Pitch. Writes a .mid file and returns it."

    def transcribe(self, audio, filename_prefix, timestamp, onset_threshold, frame_threshold,
                   minimum_note_length):
        # Loaded first, so a missing dependency fails with a message that says how to fix it.
        predict, model = _basic_pitch()

        waveform, sample_rate = _input_waveform(audio)
        workdir = _run_dir()
        _clear_dir(workdir)

        sent = {"value": -1}
        pbar = comfy.utils.ProgressBar(100)

        def report(value):
            if value > sent["value"]:
                sent["value"] = value
                pbar.update_absolute(value)

        report(2)
        source = os.path.join(workdir, "input.wav")
        _write_wav(source, waveform, sample_rate)

        report(10)
        # Basic Pitch reports no progress of its own, so this bar moves by phase only.
        _unused, midi_data, notes = predict(
            source,
            model,
            onset_threshold=onset_threshold,
            frame_threshold=frame_threshold,
            minimum_note_length=minimum_note_length,
        )
        report(96)

        out_path = _output_path(
            filename_prefix, "mid", time.strftime("%Y%m%d-%H%M%S") if timestamp else None
        )
        midi_data.write(out_path)
        report(100)
        print(f"[UVR5] Basic Pitch: {len(notes)} notes -> {out_path}")
        # mido.MidiFile is the MIDI type other ComfyUI audio packs use.
        import mido

        return {
            "ui": {"stem_splitter_files": [_saved_file(out_path)],
                   "stem_splitter_prefix": [filename_prefix]},
            "result": (mido.MidiFile(out_path), out_path),
        }


# --------------------------------------------------------------------------- #
# AudioSave
# --------------------------------------------------------------------------- #


class AudioSave:
    """Saves any audio clip into ComfyUI's output folder, and shows it on the node.

    "audio" in the UI payload is what the frontend draws as a player with a waveform;
    it is the same shape ComfyUI's own Save Audio sends.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "filename_prefix": ("STRING", {
                    "default": "audio/StemSplitter",
                    "tooltip": "Name, and optionally a subfolder, inside ComfyUI's output folder.",
                }),
                "timestamp": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Put the time in the name so every run writes a new file.",
                }),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = AUDIO_CATEGORY
    DESCRIPTION = "Saves any audio to ComfyUI's output folder, with playback and waveform."

    def save(self, audio, filename_prefix, timestamp):
        waveform = audio["waveform"].detach().cpu().float()
        sample_rate = int(audio["sample_rate"])
        stamp = time.strftime("%Y%m%d-%H%M%S") if timestamp else None
        batch = waveform.shape[0] if waveform.dim() == 3 else 1
        saved = []
        for batch_number, wav in enumerate(waveform if waveform.dim() == 3 else [waveform]):
            if wav.dim() == 1:
                wav = wav.unsqueeze(0)
            path = _output_path(filename_prefix, "wav", stamp,
                                index=batch_number if batch > 1 else None)
            sf.write(path, wav.numpy().T, sample_rate)
            saved.append(_saved_file(path))
        print("[UVR5] saved " + ", ".join(f["filename"] for f in saved))
        # "audio" is the key ComfyUI's own audio nodes return, and it is what the frontend's
        # player and waveform read. "stem_splitter_files" is what drives the Save as button,
        # and "stem_splitter_prefix" is the name actually used, so a wired-in prefix can be
        # shown in the node's own field instead of the value it had before it was wired.
        return {"ui": {"audio": saved, "stem_splitter_files": saved,
                       "stem_splitter_prefix": [filename_prefix]}, "result": (audio,)}


class AudioConvert:
    """Saves audio as FLAC, MP3 or Opus and passes it straight on.

    The rest of the pack works in WAV, because that is the format you can process again
    without losing anything. This node is for handing a file off in something smaller or
    more portable, and it leaves the audio it was given untouched.
    """

    FORMATS = ["flac", "mp3", "opus"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "filename_prefix": ("STRING", {
                    "default": "audio/Converted",
                    "tooltip": "Name, and optionally a subfolder, inside ComfyUI's output folder.",
                }),
                "timestamp": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Put the time in the name so every run writes a new file.",
                }),
                "format": (cls.FORMATS, {
                    "default": "flac",
                    "tooltip": "FLAC is compressed but lossless, so the default cannot degrade anything. MP3 and Opus are lossy.",
                }),
                "quality": (["64k", "96k", "128k", "192k", "320k"], {
                    "default": "192k",
                    "tooltip": "Bit rate for MP3 and Opus. FLAC ignores it.",
                }),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    OUTPUT_NODE = True
    FUNCTION = "convert"
    CATEGORY = AUDIO_CATEGORY
    DESCRIPTION = "Saves audio as FLAC, MP3 or Opus and passes it on. AudioSave writes WAV."

    def convert(self, audio, filename_prefix, timestamp, format, quality):
        waveform = audio["waveform"].detach().cpu().float()
        sample_rate = int(audio["sample_rate"])
        stamp = time.strftime("%Y%m%d-%H%M%S") if timestamp else None
        batch = waveform.shape[0] if waveform.dim() == 3 else 1
        saved = []
        for batch_number, wav in enumerate(waveform if waveform.dim() == 3 else [waveform]):
            if wav.dim() == 1:
                wav = wav.unsqueeze(0)
            path = _output_path(filename_prefix, format, stamp,
                                index=batch_number if batch > 1 else None)
            _write_compressed(wav, sample_rate, path, format, quality)
            saved.append(_saved_file(path))
        print("[UVR5] converted " + ", ".join(f["filename"] for f in saved))
        return {"ui": {"audio": saved, "stem_splitter_files": saved,
                       "stem_splitter_prefix": [filename_prefix]}, "result": (audio,)}


def _padded(value, padding):
    """The number as text with `padding` extra zeros in front: 1 -> 01, 3 -> 0001."""
    sign = "-" if value < 0 else ""
    digits = str(abs(int(value)))
    return sign + digits.zfill(len(digits) + int(padding))


class Increment:
    """Counts up or down once per run, and pads the number with zeros.

    The count lives in the "starting number" field: this node moves that field on after
    each run, so nothing else has to remember where it got to, and you can see the current
    value on the node. Feed the output into a text chain to build a filename that changes
    every run.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["increment", "decrement"], {
                    "default": "increment",
                    "tooltip": "Which way the number moves after each run.",
                }),
                "starting_number": ("INT", {
                    "default": 1, "min": -1000000, "max": 1000000, "step": 1,
                    "tooltip": "Where the count starts. This field advances after every run, so it always shows where the count is now.",
                }),
                "padding": ("INT", {
                    "default": 0, "min": 0, "max": 12, "step": 1,
                    "tooltip": "Extra zeros in front: 1 gives 01, 2 gives 001, 3 gives 0001.",
                }),
                "step": ("INT", {
                    "default": 1, "min": 1, "max": 1000, "step": 1,
                    "tooltip": "How far the number moves each run.",
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("value",)
    FUNCTION = "count"
    CATEGORY = UTIL_CATEGORY
    DESCRIPTION = "Counts up or down once per run, with zero padding, for numbering files."

    def count(self, mode, starting_number, padding, step):
        value = int(starting_number)
        text = _padded(value, padding)
        moved = value + (step if mode == "increment" else -step)
        print(f"[UVR5] count {text} -> next {_padded(moved, padding)}")
        return {"ui": {"stem_splitter_next": [moved]}, "result": (text,)}

