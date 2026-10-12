# One Solo Studios — ComfyUI nodes

Audio nodes for ComfyUI. Separation runs on [`audio-separator`](https://github.com/nomadkaraoke/python-audio-separator),
the engine behind Ultimate Vocal Remover (UVR5); transcription runs on Spotify's Basic Pitch;
everything else is plain audio handling.

Requirements and install steps: [INSTALL.md](INSTALL.md). In short, ComfyUI plus
`audio-separator` in the same Python ComfyUI runs in, and `basic-pitch` as well if you want
`Audio2MIDI`.

## Where the nodes appear

```
One Solo Studios/Audio/StemSplitter    StemSplitter, StemSplitter4, StemSplitter6,
                                       StemSplitterFX, StemSplitterSAM,
                                       StemSplitter Cheatsheet
One Solo Studios/Audio                 Audio2MIDI, AudioSave, AudioConvert, StemSave
One Solo Studios/Utils                 Increment
```

The search box matches "oss" and "one solo studios" as well as the node name.

## Nodes

### StemSplitter — two stems out

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown) |
| Outputs | `stem_1`, `stem_2` (AUDIO) |

Splits a clip into two stems (Vocals / Instrumental, Lead / Backing, Drums / All Instruments,
…). `stem_1` is the model's **primary** stem and `stem_2` the complement, taken from the
order the model itself declares — so for a vocals model, `stem_1` is the vocals.

### StemSplitter4 — four stems in one pass

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown, Demucs v4 models) |
| Outputs | `vocals`, `drums`, `bass`, `other` (AUDIO) |

Demucs in a single pass, four stems. The dropdown holds only the models that produce four,
so nothing here can ask for a stem that doesn't exist.

### StemSplitter6 — six stems in one pass

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown) |
| Outputs | `vocals`, `drums`, `bass`, `guitar`, `piano`, `other` (AUDIO) |

Only `htdemucs_6s` is offered, because it is the only model in the library that produces
guitar and piano — every output always carries audio. Use this one when you need guitar or
piano; the four-stem node is faster for everything else.

### StemSplitterFX — denoise / dereverb / de-echo

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown) |
| Outputs | `processed`, `removed` (AUDIO) |

Applies a UVR cleanup model. `processed` is the cleaned signal (the model's "no reverb" /
"no noise" / "dry" output) and `removed` is what was taken out of the signal — the reverb,
noise or echo itself. Leave `removed` unwired if you don't want it; the node runs the same
either way.

### StemSplitterSAM — separate a sound you describe in words

| | |
|---|---|
| Inputs | `audio` (AUDIO), `description` (STRING), `model` (dropdown), `predict_spans`, `reranking` |
| Outputs | `target`, `residual` (AUDIO) |

SAM-Audio, Meta's text-prompted separator: type what you want pulled out — "a tone",
"applause", "the singer" — and this node returns it as `target`, with everything else as
`residual`. It is a different engine from the UVR5 models above and does not use
`audio-separator`.

Its code is vendored in `Audio/StemSplitter/sam_support/` (MIT, licence included) rather than
imported from another node pack, so this pack works on its own. Weights live in
`models/OneSoloStudio/sam_audio/`.

### StemSplitter Cheatsheet — the model list, pre-filled

No inputs, no outputs, nothing to wire. Drag it onto the canvas and the text is already on
it: which model for which of the twelve processes, which node to use for each, where the
library has no second option, and which models named by the guide cannot run here.

It is **generated from the same lists the dropdowns use** — `Audio/StemSplitter/models.py` —
so the sheet cannot fall out of step with them. The text is a normal editable widget: add
your own notes, or copy it into the graph as a reference.

### Audio2MIDI — audio to MIDI

| | |
|---|---|
| Inputs | `audio` (AUDIO), `onset_threshold`, `frame_threshold`, `minimum_note_length` |
| Outputs | `midi` (MIDI), `midi_path` (STRING) |

Spotify's **Basic Pitch** transcribes pitched audio into notes. No UVR5 model is involved.

- `midi` is a `mido.MidiFile`, the same MIDI type other ComfyUI audio packs use, so it wires
  straight into MIDI nodes.
- `midi_path` is the `.mid` file, written into ComfyUI's `output/` folder. **Save as...** on
  the node puts a copy anywhere you like.
- The three knobs are Basic Pitch's own: raise `onset_threshold` to drop tentative note
  starts, raise `frame_threshold` to drop notes that fade out, raise `minimum_note_length`
  (milliseconds) to drop very short notes.

Works best on one instrument at a time. On a full mix it picks out whichever pitched content
is loudest, so splitting first and transcribing a stem gives better results.

### AudioSave — write audio to disk

| | |
|---|---|
| Inputs | `audio` (AUDIO), `filename_prefix` (STRING), `timestamp` (BOOLEAN) |
| Outputs | `audio` (AUDIO) — passes straight through |

Writes any AUDIO to ComfyUI's `output/` folder as WAV under `filename_prefix` (default
`audio/StemSplitter`), and passes the audio through so it can still feed other nodes.
`timestamp` appends the date and time to the file name.

**Save as...** — the button on this node and on Audio2MIDI downloads the file that run just
wrote. It exists because ComfyUI only hands its built-in player and download to a fixed list
of its own node classes (`PreviewAudio`, `SaveAudio`, `SaveAudioMP3`, `SaveAudioOpus`,
`SaveAudioAdvanced`); nodes from a pack get no download at all unless the pack adds one. That
button, and the waveform player on these nodes, are `web/stemsplitter_save.js`.

### AudioConvert — write audio in another format

| | |
|---|---|
| Inputs | `audio` (AUDIO), `filename_prefix` (STRING), `timestamp`, `format`, `quality` |
| Outputs | `audio` (AUDIO) — passes straight through |

Same as AudioSave, but for people who want something other than WAV: **flac** (default),
**mp3** or **opus**, with `quality` from 64k to 320k (default 192k). FLAC is the default
because it is the one lossless option in the list.

### StemSave — many named stems, one node

| | |
|---|---|
| Inputs | `filename_prefix` (STRING), `timestamp`, then 20 rows of `audio` + `name` |
| Outputs | `stem_1` … `stem_20` (AUDIO) |

Twenty rows up front, because ComfyUI fixes a node's inputs and outputs when the class is
written and will not grow them at run time. Name a row ("drums", "bass", "vocals" — whatever
it is), wire audio into it, and that row is written to `<filename_prefix>/<name>.wav`.
Rows you don't wire are skipped, and the front end drops the empty ones past the last row in
use, so the node stays only as tall as the work you are doing.

Each wired row also passes its audio back out on `stem_1` … `stem_20`, so you can keep
routing any stem onward. **Save as...** downloads everything the run wrote.

The name becomes a file name, so it is kept to the folder you put under `filename_prefix` —
a name containing `../` cannot walk out of the output folder.

### Increment — counting, for numbering files

| | |
|---|---|
| Inputs | `mode`, `number`, `pad_zeros`, `step` |
| Outputs | `value` (STRING) |

Returns its number as text and moves on, so a queue of runs numbers its own files: 1, 2, 3…
`mode` counts up or down, `pad_zeros` sets the width (`1` gives `01`, `2` gives `001`), and
`step` sets how far each run moves. Wire `value` into a `filename_prefix` to use it.

## Models

The dropdowns offer **the best two models the library has for each of the twelve processes**,
so every stage has a choice — not the library's whole catalogue of 145 separator models.
Where `audio-separator` publishes SDR scores, the ranking comes from those.

**StemSplitter — the two-stem stages**

1. Vocals / Instrumentals — `BS-Roformer-Viperx-1297` (best instrumental score),
   `MelBand Roformer | Vocals by Kimberley Jensen` (best vocals score)
2. Lead / Backing vocals — `Mel-Roformer-Karaoke-Aufr33-Viperx`, `5_HP-Karaoke-UVR`
3. Drums / Instrumentals — `kuielab_a_drums`, `kuielab_b_drums`
4. Bass / Instrumentals — `kuielab_a_bass`, `kuielab_b_bass`
8. Brass / wind — `17_HP-Wind_Inst-UVR` (the only wind model in the library)
9. Other / Instrumentals — `kuielab_a_other`, `kuielab_b_other`

**StemSplitter4 — four stems in one pass**

`htdemucs` (the standard one) and `htdemucs_ft` (fine-tuned, best quality, slower). These
cover drums, bass and other as independent tracks and generally beat the kuielab MDX models
above for all three.

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
DeVerberate and LALAL.AI — all commercial, with no headless build — and DeepFilterNet, which
this pack does not use.

Weights are downloaded on first use into `models/OneSoloStudio/audio_separator/` and cached
there; a model is loaded once per ComfyUI session and reused. To offer a different model, add
its exact catalogue name to the matching list in `Audio/StemSplitter/models.py`.

> Models run on CUDA through PyTorch. MDX (`*.onnx`) models use ONNX Runtime instead; without
> the GPU build (`onnxruntime-gpu`) they fall back to CPU and are slower.

## Example workflow

[`example_workflow.json`](example_workflow.json): Load Audio → BS-Roformer splitter → preview
the vocals → denoise them with UVR DeNoise → preview, plus the instrumental saved to
`output/audio/`. Pick or upload your own clip in the **Load Audio** node first.

## Output format

Every stem comes back as a standard ComfyUI `AUDIO` (`{"waveform": [1, C, S], "sample_rate"}`
float32). The separation models run at 44.1 kHz, so stems come back at 44.1 kHz regardless of
the input rate.

## Notes

- Batched AUDIO inputs are processed as the first item of the batch (logged when trimmed).
- Mono inputs are duplicated to stereo, as the separation models expect stereo.
- For stereo or multi-channel input, each stem keeps the model's channel layout.

## Layout

```
__init__.py            registers every node, in the order they appear in the menu
common.py              shared helpers: reading audio, writing files, running a model
web/                   front end scripts: the badge, the player, the counting widget
Audio/StemSplitter/    the splitter family, the cheat sheet, and vendored SAM support
Audio/Audio2MIDI/      audio to MIDI
Audio/AudioSave/       saving, and converting to other formats
Utils/Increment/       counting
```
