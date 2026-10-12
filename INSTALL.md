# Installation

This pack has **two** dependencies, both installed into the same Python environment
ComfyUI runs in. No Pixi and no second environment are needed.

- `audio-separator` — the UVR5 model ecosystem, used by `StemSplitter`, `StemSplitter6`
  and `StemSplitterFX`.
- `basic-pitch` — Spotify's audio-to-MIDI model, used by `Audio2MIDI`.

## Check whether it is already installed

```bash
# use ComfyUI's own python (the one that starts main.py)
python -c "import audio_separator, soundfile; print('ok')"
python -c "import basic_pitch, pretty_midi; print('ok')"   # only needed for Audio2MIDI
```

If those print `ok`, the pack is ready — drop the folder into
`ComfyUI/custom_nodes/`, restart ComfyUI, and the nodes appear under **StemSplitter**:
`StemSplitter`, `StemSplitter4`, `StemSplitter6`, `StemSplitterFX`, `StemSplitter Cheatsheet`
and `Audio2MIDI`.

## Install the dependency

```bash
# inside ComfyUI's python environment:
pip install audio-separator
pip install --no-deps basic-pitch pretty_midi resampy mir_eval   # Audio2MIDI only
```

`audio-separator` pulls in `soundfile`, `librosa`, `onnxruntime` and the rest of its
requirements automatically.

`--no-deps` on the second line is deliberate. Basic Pitch's metadata pins
`tensorflow<2.15.1`, which does not exist for Python 3.13 — and TensorFlow is not needed:
the pack runs Basic Pitch's bundled **ONNX** model on the `onnxruntime` that
`audio-separator` already installed. `--no-deps` also guarantees pip cannot touch your
existing `torch` or `numpy`.

- **GPU note:** `pip install audio-separator` installs CPU ONNX Runtime. PyTorch models
  (Roformer / VR / Demucs) still use CUDA; to speed up MDX (`*.onnx`) models install the
  GPU build with `pip install onnxruntime-gpu` (it must match your CUDA version).
- **ffmpeg** must be on `PATH` (ComfyUI standalone bundles one).

## Models

Nothing to download by hand. Pick a model in a node and run it — the weights are fetched
on first use into:

```
ComfyUI/models/OneSoloStudio/audio_separator/
```

To see or manage what is cached, delete files from that folder; they will be re-fetched
as needed.

## Troubleshooting

**`RuntimeError: audio-separator is required … could not be imported`**
The package is missing from ComfyUI's environment, or `pip` installed it into a different
Python. Verify with the `python -c "import audio_separator"` check above, using ComfyUI's
interpreter.

**`RuntimeError: Basic Pitch is not installed …`**
Only `Audio2MIDI` needs it; the other nodes work without it. Install the four packages
with ComfyUI's own interpreter (`pip install --no-deps basic-pitch pretty_midi resampy mir_eval`).

**The model dropdown is short / missing models**
The catalogue could not be read from `audio-separator` (usually no network on first run);
the node falls back to a small built-in list. Check the ComfyUI console for a `[UVR5]`
message, restore connectivity, and press **R** to refresh the node definitions.
