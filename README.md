# StemSplitter

ComfyUI nodes for **audio source separation** and **audio restoration**, powered by the
[`audio-separator`](https://github.com/nomadkaraoke/python-audio-separator) package — the
same engine behind Ultimate Vocal Remover (UVR5).

No Pixi, no subprocess, no separate environment: the nodes run in ComfyUI's own Python
environment and reuse `audio-separator` plus the UVR5 model catalogue it maintains.

## Requirements

- ComfyUI with **`audio-separator`** installed in the *same* Python environment
  (see [INSTALL.md](INSTALL.md)).
- `soundfile` (installed with `audio-separator`).

## Nodes

### 🎧 StemSplitter — two-stem split

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown) |
| Outputs | `stem_1`, `stem_2` (AUDIO) |

Splits a clip into two stems (Vocals / Instrumental, Lead / Backing, Drums / All
Instruments, …). `stem_1` is the model's **primary** stem and `stem_2` the complement,
using the order the model itself declares — so for a vocals model `stem_1` is the vocals.

### StemSplitter4 — one-pass 4-stem split

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown, Demucs v4 models) |
| Outputs | `vocals`, `drums`, `bass`, `other` (AUDIO) |

Demucs in one pass, four stems. The dropdown holds only the models that make four —
nothing here can ask for a stem that doesn't exist.

### StemSplitter6 — one-pass 6-stem split

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown) |
| Outputs | `vocals`, `drums`, `bass`, `guitar`, `piano`, `other` (AUDIO) |

The six-stem version. Only `htdemucs_6s` is offered, because it is the only model in
the library that produces guitar and piano — so every output on this node always carries
audio. For guitar and piano, use this node; for everything else the four-stem one is
faster.

### StemSplitterFX — denoise / dereverb / de-echo

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown) |
| Outputs | `processed`, `removed` (AUDIO) |

Applies a UVR restoration model. `processed` is the cleaned signal (the model's "no
reverb" / "no noise" / "dry" output) and `removed` is what was taken out of the signal —
the reverb, noise or echo itself. Leave `removed` unwired if you don't want it; the node
runs the same either way.

### StemSplitter Cheatsheet — the model list, pre-filled

No inputs, no outputs, nothing to wire. Drag it onto the canvas and the text is already
on it: which model for which of the twelve processes, which node to use for each, where
the library has no second option, and which models named by the guide cannot run here.

It is **generated from the same lists the dropdowns use**, at the top of
`audio_suite_nodes.py`, so it cannot fall out of step with them. The text is a normal
editable widget — add your own notes to it, or copy it into the graph as a reference.

### Audio2MIDI — audio to MIDI

| | |
|---|---|
| Inputs | `audio` (AUDIO), `onset_threshold`, `frame_threshold`, `minimum_note_length` |
| Outputs | `midi` (MIDI), `midi_path` (STRING) |

Spotify's **Basic Pitch** transcribes pitched audio into notes. No UVR5 model is
involved — it just lives here with the other audio nodes.

- `midi` is a `mido.MidiFile`, the same MIDI type the other ComfyUI audio packs use, so
  it wires straight into MIDI nodes.
- `midi_path` is the `.mid` file, written into ComfyUI's `output/` folder. Use the
  **Save as...** button on the node to put a copy anywhere you like.
- The three knobs are Basic Pitch's own: raise `onset_threshold` to drop tentative note
  starts, raise `frame_threshold` to drop notes that fade out, raise
  `minimum_note_length` (milliseconds) to drop very short notes.

Works best on one instrument at a time. On a full mix it finds whichever pitched content
is loudest, so splitting first and transcribing a stem gives better results.

### AudioSave — save anything

| | |
|---|---|
| Inputs | `audio` (AUDIO), `filename_prefix` (STRING) |
| Outputs | `audio` (AUDIO) — passes straight through |

Terminal node: takes any AUDIO, writes it as WAV into ComfyUI's `output/` folder under
`filename_prefix` (default `audio/StemSplitter`), and passes the audio through so it can
still feed other nodes.

**Save as...** — the button on this node and on Audio2MIDI downloads the file that run
just wrote, so you can put it wherever you want. It exists because ComfyUI only hands its
built-in player/download to a fixed list of its own node classes (`PreviewAudio`,
`SaveAudio`, `SaveAudioMP3`, `SaveAudioOpus`, `SaveAudioAdvanced`); nodes from a pack get
no download at all unless the pack adds one. That button is `web/stemsplitter_save.js`.

## Models

The dropdowns offer **the best two models the library has for each of the twelve
processes in `BuildGuide.md`**, so every stage has a choice — not the library's whole
catalogue of 145 separator models. Where `audio-separator` publishes SDR scores, the
ranking comes from those.

**StemSplitter — the two-stem stages**

1. Vocals / Instrumentals — `BS-Roformer-Viperx-1297` (best instrumental score),
   `MelBand Roformer | Vocals by Kimberley Jensen` (best vocals score)
2. Lead / Backing vocals — `Mel-Roformer-Karaoke-Aufr33-Viperx`, `5_HP-Karaoke-UVR`
3. Drums / Instrumentals — `kuielab_a_drums`, `kuielab_b_drums`
4. Bass / Instrumentals — `kuielab_a_bass`, `kuielab_b_bass`
8. Brass / wind — `17_HP-Wind_Inst-UVR` (the only wind model in the library)
9. Other / Instrumentals — `kuielab_a_other`, `kuielab_b_other`

**StemSplitter4 — four stems in one pass**

`htdemucs` (the standard one) and `htdemucs_ft` (fine-tuned, best quality, slower).
These cover drums, bass and other as independent tracks and generally beat the kuielab
MDX models above for all three.

**StemSplitter6 — six stems in one pass**

`htdemucs_6s`, the only model that also produces guitar and piano.

**StemSplitterFX — the cleanup stages**

10. Dereverb — `MelBand Roformer | De-Reverb by anvuew`,
    `MelBand Roformer | De-Reverb Less Aggressive by anvuew`
11. Denoise — `Mel-Roformer-Denoise-Aufr33`, `Mel-Roformer-Denoise-Aufr33-Aggr`
12. De-echo — `UVR-De-Echo-Normal`, `UVR-De-Echo-Aggressive`

**Processes with no two-model choice, because the library has nothing to offer**

- 5. Guitar and 6. Piano exist *only* inside `htdemucs_6s`.
- 7. Strings — no model in the library targets strings at all.
- 8. Brass — only the woodwind model above; nothing brass-specific exists.

The guide also names Waves Clarity, Accentize DeRoom2 and DX Revive, iZotope RX, Acon
DeVerberate and LALAL.AI — all commercial, with no headless build — and DeepFilterNet,
which is not installed.

Weights are downloaded on first use into `ComfyUI/models/OneSoloStudio/audio_separator/` and cached
there. A model is loaded once per ComfyUI session and reused.

To offer a different model, add its exact catalogue name to the matching list at the top
of `audio_suite_nodes.py`.

> Models run on CUDA through PyTorch. MDX (`*.onnx`) models use ONNX Runtime instead; if
> the GPU build (`onnxruntime-gpu`) is not installed they fall back to CPU and are slower.

## Example workflow

[`example_workflow.json`](example_workflow.json): Load Audio → BS-Roformer splitter →
preview the vocals → denoise them with UVR DeNoise → preview, plus the instrumental saved
to `output/audio/`. Pick or upload your own clip in the **Load Audio** node first.

## Output format

Every stem is returned as a standard ComfyUI `AUDIO` (`{"waveform": [1, C, S], "sample_rate"}`
float32). Models run at 44.1 kHz, so stems come back at 44.1 kHz regardless of the input
rate.

## Notes

- Batched AUDIO inputs are processed as the first item of the batch (logged when trimmed).
- Mono inputs are duplicated to stereo, as the separation models expect stereo.
- For stereo/multi-channel input, each stem keeps the model's channel layout.
