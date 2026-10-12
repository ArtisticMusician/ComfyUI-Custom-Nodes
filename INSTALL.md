# Installation

ComfyUI does the work; this pack runs in the Python ComfyUI already uses. Two packages
have to be in that environment:

| Package | Needed by |
|---|---|
| `audio-separator` | `StemSplitter`, `StemSplitter4`, `StemSplitter6`, `StemSplitterFX` |
| `basic-pitch` | `Audio2MIDI` |

`StemSplitterSAM`, the cheat sheet, `AudioSave`, `AudioConvert` and `Increment` need nothing
beyond ComfyUI itself.

## Check what is already there

Use the same Python that starts ComfyUI. For the Desktop app that is its own embedded
interpreter, not your system Python.

```bash
python -c "import audio_separator, soundfile; print('ok')"
python -c "import basic_pitch, pretty_midi; print('ok')"        # Audio2MIDI only
```

## Install

```bash
pip install audio-separator
pip install --no-deps basic-pitch pretty_midi resampy mir_eval   # Audio2MIDI only
```

`audio-separator` brings `soundfile`, `librosa`, `onnxruntime` and the rest with it.

The `--no-deps` is deliberate: Basic Pitch's metadata pins `tensorflow<2.15.1`, which does
not exist for Python 3.13, and TensorFlow is not used — the pack runs Basic Pitch's bundled
**ONNX** model on the `onnxruntime` already present. It also keeps pip out of your `torch`
and `numpy`.

Then put the pack in `ComfyUI/custom_nodes/` and restart ComfyUI.

## Where the nodes appear

```
One Solo Studios/Audio/StemSplitter    StemSplitter, StemSplitter4, StemSplitter6,
                                       StemSplitterFX, StemSplitterSAM,
                                       StemSplitter Cheatsheet
One Solo Studios/Audio                 Audio2MIDI, AudioSave, AudioConvert
One Solo Studios/Utils                 Increment
```

The search box matches "oss" and "one solo studios" as well as the node name.

## Models

Weights are fetched on first use — nothing to download by hand:

```
ComfyUI/models/OneSoloStudio/audio_separator/   UVR5 / Roformer / MDX checkpoints
ComfyUI/models/OneSoloStudio/sam_audio/         SAM-Audio checkpoints
```

Deleting a file from those folders is safe; it comes back the next time that model is picked.

## Notes

- **GPU:** `pip install audio-separator` gives you CPU ONNX Runtime. The PyTorch models
  (Roformer, VR, Demucs) still use CUDA. For MDX (`*.onnx`) models install the GPU build,
  `pip install onnxruntime-gpu`, matching your CUDA version.
- **ffmpeg** on `PATH` handles some input formats; ComfyUI's installer already bundles one.

## Troubleshooting

**`audio-separator is required … could not be imported`**
It is not in ComfyUI's Python, or pip installed it into a different one. Re-run the check
above with ComfyUI's own interpreter.

**`Basic Pitch is not installed …`**
Only `Audio2MIDI` needs it; every other node works without it.

**The model dropdown is short / missing models**
The catalogue could not be read from `audio-separator` (usually no network on a first run),
so the node falls back to a short built-in list. Check the console for a `[UVR5]` line,
restore connectivity, and press **R** to refresh the node definitions.
