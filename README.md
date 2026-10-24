![One Solo Studios](https://raw.githubusercontent.com/ArtisticMusician/assets/main/OneSoloStudios/OneSoloStudios_banner.png)

# One Solo Studios — ComfyUI nodes

ComfyUI nodes from One Solo Studios: stem separation, waveform loading and saving,
audio-to-MIDI conversion, and a few utilities.

The heavy lifting is three libraries. [`audio-separator`](https://github.com/nomadkaraoke/python-audio-separator),
the engine behind Ultimate Vocal Remover (UVR5), runs the Roformer, MDX and VR separation models;
SAM-Audio, Meta's text-prompted separator, pulls out a sound you describe in words; Spotify's
Basic Pitch does audio-to-MIDI. Everything else is plain audio handling.

Requirements and install steps: [INSTALL.md](INSTALL.md). In short, ComfyUI plus
`audio-separator` in the same Python ComfyUI runs in, and `basic-pitch` as well if you want
`Audio2MIDI`.

## Where the nodes appear

```
One Solo Studios/Audio/IO                 AudioLoader, AudioSave, StemSave, AudioConvert
One Solo Studios/Audio/Utilities          PhaseInvert, Audio2MIDI
One Solo Studios/Audio/StemSplitter        StemSplitter, StemSplitter4, StemSplitter6,
                                           StemSplitterFX, StemSplitterSAM, StemSplitterDrums,
                                           StemEnsemble
One Solo Studios/Utils                     Increment, TextMerge
```

The search box matches "oss" and "one solo studios" as well as the node name.

## Nodes

### StemSplitter — two stems out

<img width="355" alt="StemSplitter node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/StemSplitter/StemSplitter.png">

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown) |
| Outputs | `stem_1`, `stem_2` (AUDIO) |

Splits a clip into two stems (Vocals / Instrumental, Lead / Backing, Drums / All Instruments,
…). `stem_1` is the model's **primary** stem and `stem_2` the complement, taken from the
order the model itself declares — so for a vocals model, `stem_1` is the vocals.

**Models** — everything in the dropdown, in dropdown order (the prefix in each name is the
architecture it comes from):

- Vocals / Instrumentals — `Roformer Model: BS-Roformer-Viperx-1297` (best instrumental
  score), `Roformer Model: MelBand Roformer | Vocals by Kimberley Jensen` (best vocals score),
  `MDX23C Model: MDX23C-InstVoc HQ`, `MDX-Net Model: UVR-MDX-NET Inst HQ 4`,
  `MDX-Net Model: Kim Inst`
- Lead / Backing vocals — `Roformer Model: Mel-Roformer-Karaoke-Aufr33-Viperx`,
  `VR Arch Single Model v5: 5_HP-Karaoke-UVR`, `VR Arch Single Model v5: 6_HP-Karaoke-UVR`
- Drums / Instrumentals — `MDX-Net Model: kuielab_a_drums`, `MDX-Net Model: kuielab_b_drums`
- Bass / Instrumentals — `MDX-Net Model: kuielab_a_bass`, `MDX-Net Model: kuielab_b_bass`
- Brass / wind — `VR Arch Single Model v5: 17_HP-Wind_Inst-UVR` (the only wind model in the
  library; `stem_2` comes back as the woodwinds)
- Other / Instrumentals — `MDX-Net Model: kuielab_a_other`, `MDX-Net Model: kuielab_b_other`

### StemSplitter4 — four stems in one pass

<img width="355" alt="StemSplitter4 node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/StemSplitter/StemSplitter4.png">

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown) |
| Outputs | `vocals`, `drums`, `bass`, `other` (AUDIO) |

Demucs in a single pass, four stems. The dropdown holds only the models that produce four,
so nothing here can ask for a stem that doesn't exist.

**Models**

- `Demucs v4: htdemucs` — the standard one
- `Demucs v4: htdemucs_ft` — fine-tuned, best quality, slower

### StemSplitter6 — six stems in one pass

<img width="355" alt="StemSplitter6 node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/StemSplitter/StemSplitter6.png">

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown) |
| Outputs | `vocals`, `drums`, `bass`, `guitar`, `piano`, `other` (AUDIO) |

Only `htdemucs_6s` is offered, because it is the only model in the library that produces
guitar and piano — every output always carries audio. Use this one when you need guitar or
piano; the four-stem node is faster for everything else.

**Models**

- `Demucs v4: htdemucs_6s` — guitar and piano exist in no other model

### StemSplitterDrums — the kit, piece by piece

<img width="346" alt="StemSplitterDrums node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/StemSplitter/StemSplitterDrums.png">

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown) |
| Outputs | `kick`, `snare`, `toms`, `hi_hat`, `ride`, `crash` (AUDIO) |

`MDX23C DrumSep` is the one drum-specific model in the library, and it splits the kit itself
rather than the mix: feed it a drum track or a drums stem from a splitter, not a full song. It
is on its own node because its six stems are the pieces of the kit — the six sockets on
StemSplitter6 belong to Demucs, which produces nothing like them.

**Models**

- `MDX23C Model: MDX23C DrumSep by aufr33-jarredou` — kick, snare, toms, hi-hat, ride, crash.
  The library publishes no SDR score for it.

### StemSplitterFX — denoise / dereverb / de-echo

<img width="346" alt="StemSplitterFX node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/StemSplitter/StemSplitterFX.png">

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model` (dropdown) |
| Outputs | `processed`, `removed` (AUDIO) |

Applies a UVR cleanup model. `processed` is the cleaned signal (the model's "no reverb" /
"no noise" / "dry" output) and `removed` is what was taken out of the signal — the reverb,
noise or echo itself. Leave `removed` unwired if you don't want it; the node runs the same
either way.

**Models**

- Dereverb — `Roformer Model: MelBand Roformer | De-Reverb by anvuew` (highest scoring),
  `Roformer Model: MelBand Roformer | De-Reverb Less Aggressive by anvuew`
- Denoise — `Roformer Model: Mel-Roformer-Denoise-Aufr33` (highest scoring),
  `Roformer Model: Mel-Roformer-Denoise-Aufr33-Aggr`
- De-echo — `VR Arch Single Model v5: UVR-De-Echo-Normal by FoxJoy`,
  `VR Arch Single Model v5: UVR-De-Echo-Aggressive by FoxJoy`

### StemSplitterSAM — separate a sound you describe in words

<img width="372" alt="StemSplitterSAM node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/StemSplitter/StemSsplitterSam.png">

| | |
|---|---|
| Inputs | `audio` (AUDIO), `model_name` (dropdown), `description` (STRING), `precision`, `predict_spans`, `seed`, `inference_steps`, `chunk_duration`, `chunk_overlap` |
| Optional | `reranking_candidates` |
| Outputs | `target`, `residual` (AUDIO) |

SAM-Audio, Meta's text-prompted separator: type what you want pulled out — "a tone",
"applause", "the singer" — and this node returns it as `target`, with everything else as
`residual`. It is a different engine from the UVR5 models above and does not use
`audio-separator`.

**Models** — Meta's checkpoints, by name:

- `sam-audio-small` (the default), `sam-audio-base`, `sam-audio-large`
- `sam-audio-small-tv`, `sam-audio-base-tv`, `sam-audio-large-tv`

The dropdown also lists any checkpoint already downloaded into
`models/One Solo Studios/sam_audio/`, so a local copy is offered alongside Meta's.

Its code is vendored in `Audio/StemSplitter/sam_support/` (MIT, licence included) rather than
imported from another node pack, so this pack works on its own. Weights live in
`models/One Solo Studios/sam_audio/`.

### StemEnsemble — blend a stem, and its opposite, side by side

<img width="347" alt="StemEnsemble node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/StemSplitter/StemEnsemble.png">

| | | |
|---|---|---|
| Inputs | `algorithm` (dropdown), then 8 rows of `audio` + `opposite` (AUDIO) |
| Outputs | `audio_1`, `audio_2` (AUDIO) |

A row is one splitter's pair. Wire a splitter's two outputs into a row — the stem you are
pulling out on `audio`, its opposite on `opposite` — and the blend runs once per side: every
`audio` socket feeds `audio_1`, every `opposite` socket feeds `audio_2`. So three models'
vocals come out as one blended vocal, with their three instrumentals blended into the other
output alongside it.

`algorithm` is how each side is combined, from `audio-separator`'s own blend algorithms:
`average the waveforms` (the default), per-sample or per-frequency `loudest` / `quietest wins`,
median of the waveforms or the spectra, and UVR's max- and min-spectrum blends. The library's
`ensemble_wav` is **not** offered: it splits a waveform on the wrong axis for the shape a stem
arrives as, and hands back one of its inputs unchanged.

Wire only one side and the other output is **blocked** rather than filled with audio that was
never there — nothing downstream of it runs, and the log says so. Stems at different sample
rates are resampled to the highest one wired in, and a mono stem among stereo ones is
duplicated to match, so both outputs always come back the same shape. Stems of different
lengths are padded with silence by the library, as in its own Separator; a note is printed
when that happens, because the `min` and `median` algorithms can then pick that silence.

Eight rows are declared up front for the same reason StemSave declares twenty — ComfyUI fixes
a node's inputs when the class is written. Rows you leave unwired do nothing, and the front end
drops the empty ones past the last row in use.

### Audio2MIDI — audio to MIDI

<img width="355" alt="Audio2MIDI node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/Utility/Audio2MIDI.png">

| | |
|---|---|
| Inputs | `audio` (AUDIO), `filename_prefix` (STRING), `timestamp` (BOOLEAN), `onset_threshold`, `frame_threshold`, `minimum_note_length` |
| Outputs | `midi` (MIDI), `midi_path` (STRING) |

Spotify's **Basic Pitch** converts pitched audio into notes. No UVR5 model is involved.

- `midi` is a `mido.MidiFile`, the same MIDI type other ComfyUI audio packs use, so it wires
  straight into MIDI nodes.
- `midi_path` is the `.mid` file, written under `filename_prefix` in ComfyUI's `output/`
  folder. **Save as...** on the node puts a copy anywhere you like.
- The three knobs are Basic Pitch's own: raise `onset_threshold` to drop tentative note
  starts, raise `frame_threshold` to drop notes that fade out, raise `minimum_note_length`
  (milliseconds) to drop very short notes.

Works best on one instrument at a time. On a full mix it picks out whichever pitched content
is loudest, so splitting first and converting a stem gives better results.

### AudioLoader — load audio, and hear it

<img width="355" alt="AudioLoader node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/IO/AudioLoader.png">

| | |
|---|---|
| Inputs | `audio` (dropdown: the audio files in ComfyUI's `input/` folder, with nothing chosen until you pick one) |
| Outputs | `audio` (AUDIO) |

Loads one audio file out of ComfyUI's `input/` folder. The dropdown starts with nothing
chosen, so a new node never loads whichever file happens to sort first — pick a file and
the player fills in. Unlike core's Load Audio it draws the pack's player — the same waveform, playhead and play button the save nodes use — so a file can
be checked before anything is run. **Upload...** puts a file into `input/` and selects it, since
the dropdown can only list what was there when the app started.

The waveform is the point of drawing it here: it spans the whole file, so silence is visible at
a glance. That matters on stems, where a long flat stretch is normal — the instrument simply is
not playing — and a stem that reads as silence end to end shows a split that went wrong without
playing a second of it.

Replacing a file with a new take under the same name re-runs whatever is downstream: the node
keys its cache on the file's size and modification time, not on its name alone.

### AudioSave — write audio to disk

<img width="355" alt="AudioSave node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/IO/AudioSave.png">

| | |
|---|---|
| Inputs | `audio` (AUDIO), `filename_prefix` (STRING), `timestamp` (BOOLEAN), `float32` (BOOLEAN) |
| Outputs | `audio` (AUDIO) — passes straight through |

Writes any AUDIO to ComfyUI's `output/` folder as WAV under `filename_prefix` (default
`audio/StemSplitter`), and passes the audio through so it can still feed other nodes.
`timestamp` appends the date and time to the file name.

It draws the waveform of the file it just wrote, and the waveform is what makes a stem review
quick: stems are silent wherever their instrument is, so the picture shows exactly where each
one has audio and where it has gaps — check that a split found something, and see how much of
the clip it actually covers, without listening through the whole file.

`float32` writes 32-bit float WAV instead of 16-bit PCM. Stems come out of the separation
models in 32 bits, so this is the setting that keeps every sample of what the model
produced; the file is about twice the size, and some players will not open it. Off is what
this node has always written.

**Save as...** — the button on this node and on Audio2MIDI downloads the file that run just
wrote. It exists because ComfyUI only hands its built-in player and download to a fixed list
of its own node classes (`PreviewAudio`, `SaveAudio`, `SaveAudioMP3`, `SaveAudioOpus`,
`SaveAudioAdvanced`); nodes from a pack get no download at all unless the pack adds one. That
button, and the waveform player on these nodes, are `web/stemsplitter_save.js`.

### AudioConvert — write audio in another format

<img width="351" alt="AudioConvert node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/IO/AudioConvert.png">

| | |
|---|---|
| Inputs | `audio` (AUDIO), `filename_prefix` (STRING), `timestamp`, `format`, `quality` |
| Outputs | `audio` (AUDIO) — passes straight through |

Same as AudioSave, but for people who want something other than WAV: **flac** (default),
**mp3** or **opus**, with `quality` from 64k to 320k (default 192k). FLAC is the default
because it is the one lossless option in the list, and it is written at 24-bit — compressed,
lossless, and small enough to hand off. MP3 and Opus are lossy: 160–192 kbps stereo is where
they stop being audible, and the data they drop never comes back.

It draws the same waveform player as AudioSave, so the converted file can be checked in place.

### StemSave — many named stems, one node

<img width="351" alt="StemSave node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/IO/StemSave.png">

| | |
|---|---|
| Inputs | `filename_prefix` (STRING), `timestamp`, then 20 rows of `audio` + `name`, and `float32` |
| Outputs | `stem_1` … `stem_20` (AUDIO) |

Twenty rows up front, because ComfyUI fixes a node's inputs and outputs when the class is
written and will not grow them at run time. Name a row ("drums", "bass", "vocals" — whatever
it is), wire audio into it, and that row is written to `<filename_prefix>/<name>.wav`.
Rows you don't wire are skipped, and the front end drops the empty ones past the last row in
use, so the node stays only as tall as the work you are doing.

Every written row gets its own waveform player, one under the other. On a page of stems that
is the fastest review there is: silent gaps stack up as flat lines, so a stem that came back
empty or a mix with no low end is visible without soloing anything.

`float32` is one switch for the whole node: on, every stem is written as 32-bit float WAV
instead of 16-bit PCM. It sits after the rows rather than among the fields at the top so
workflows saved before it existed still line up.

Each wired row also passes its audio back out on `stem_1` … `stem_20`, so you can keep
routing any stem onward. **Save as...** downloads everything the run wrote.

The name becomes a file name, so it is kept to the folder you put under `filename_prefix` —
a name containing `../` cannot walk out of the output folder.

### PhaseInvert — flip the polarity

<img width="370" alt="PhaseInvert node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Audio/Utility/Phaseinvert.png">

| | | |
|---|---|---|
| Inputs | `audio` (AUDIO) |
| Outputs | `inverted` (AUDIO) |

Every sample times −1: the same clip, upside down. Sample rate, channels and length come back
unchanged.

Its use is cancellation. Wire an inverted stem into StemEnsemble alongside the one it came from
and the two subtract rather than add — which is how you take the difference of two models, or
of a model and the original. The result sits at whatever level the chosen algorithm works at:
an average is divided by the number of stems wired in, so two stems give the difference at half
level.

### Increment — counting, for numbering files

<img width="363" alt="Increment node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Utility/Increment.png">

| | |
|---|---|
| Inputs | `mode`, `starting_number`, `padding`, `step` |
| Outputs | `value` (STRING) |

Returns its number as text and moves on, so a queue of runs numbers its own files: 1, 2, 3…
`mode` counts up or down, `padding` sets the width (`1` gives `01`, `2` gives `001`), and
`step` sets how far each run moves. Wire `value` into a `filename_prefix` to use it.

### TextMerge — join any number of texts

<img width="363" alt="TextMerge node" src="https://raw.githubusercontent.com/ArtisticMusician/assets/main/comfyUI_custom_nodes/Utility/TextMerge.png">

| | | |
|---|---|---|
| Inputs | `delimiter` (STRING), then a `text` row per text you wire (STRING) |
| Outputs | `text` (STRING) |

Everything wired in, joined in row order, with `delimiter` between each pair — the same idea as
ComfyUI's own Concatenate Text, except the inputs keep coming: wire a text node into the last row
and another row appears, for as long as you keep going. There is no fixed number of rows to run
into, and never a row to add by hand. Unwired rows do nothing, and the front end drops the empty
ones past the last row in use.

`delimiter` is taken literally — a space, a comma, or a line you type. Leave it empty to run the
texts together with nothing between. Numbers arriving from `Increment` are joined as the text
they came in as.

(The class itself declares one row; ComfyUI's executor hands a node whatever the prompt has, so
rows past that one are real inputs, not decoration. `StemSave` is the other case — it declares
twenty because it must return one output per row, and outputs cannot grow.)

## Models

The dropdowns offer **the models the guide names for each of the twelve processes**, filtered to
the ones `audio-separator` actually lists — a choice at every stage where the library has a
second model for it — rather than its whole catalogue of 169 separator models. Where
`audio-separator` publishes SDR scores, the ranking comes from those. Each node's section above
lists what is in its own dropdown.

**Processes with no two-model choice, because the library has nothing to offer**

- 5. Guitar and 6. Piano exist *only* inside `htdemucs_6s`.
- 7. Strings — no model in the library targets strings at all.
- 8. Brass — only the woodwind model on StemSplitter; nothing brass-specific exists.

The guide also names Waves Clarity, Accentize DeRoom2 and DX Revive, iZotope RX, Acon
DeVerberate and LALAL.AI — all commercial, with no headless build — and DeepFilterNet, which
this pack does not use.

Weights are downloaded on first use into `models/One Solo Studios/audio_separator/` and cached
there; a model is loaded once per ComfyUI session and reused. To offer a different model, add
its exact catalogue name to the matching list in `Audio/StemSplitter/models.py`.

> Models run on CUDA through PyTorch. MDX (`*.onnx`) models use ONNX Runtime instead; without
> the GPU build (`onnxruntime-gpu`) they fall back to CPU and are slower.

## Example workflows

Five workflows in [`Examples/`](Examples/). Open one with **Workflow → Open** in ComfyUI; each
one's **AudioLoader** still points at the file it was saved with, so pick or upload your own
clip there first.

| Workflow | What it does |
|---|---|
| [`StemSplitter_Vox-Inst.json`](Examples/StemSplitter_Vox-Inst.json) | The smallest real chain. Two StemSplitter models — BS-Roformer for the instrumental, the Kimberley Jensen vocals model — blended by StemEnsemble at `Average by Frequency`, and that blend dereverbed by two StemSplitterFX nodes recombined at `Loudest Wins by Frequency`. Three AudioSave nodes take Vox, Inst and Removed Reverb. |
| [`OneSoloStudios-FastlyMessy_stem_separator.json`](Examples/OneSoloStudios-FastlyMessy_stem_separator.json) | The same job with every node left on the canvas: the two vocals models, `htdemucs_6s`, `MDX23C DrumSep`, dereverb, two StemEnsembles, everything landing in one StemSave bank (Vox, drums, kick, snare, toms, hi-hat, ride…). |
| [`OneSoloStudios-Fastly-Neat_stem_separator.json`](Examples/OneSoloStudios-Fastly-Neat_stem_separator.json) | Those same eight separation nodes wrapped in one subgraph, so the canvas reads AudioLoader → subgraph → StemSave. |
| [`SimpleStemSplitAndMidi.json`](Examples/SimpleStemSplitAndMidi.json) | Stems and MIDI in one run: BS-Roformer, the Kimberley vocals model, `htdemucs_6s`, drum sep and dereverb, saved as named stems, then seven Audio2MIDI nodes writing a `.mid` per stem. Folder names are built from Primitive String, TextMerge and Increment, so each run gets its own numbered folder. |
| [`SimpleStemSplitAndMidi_Neat.json`](Examples/SimpleStemSplitAndMidi_Neat.json) | The same thirty-two nodes inside a `Split Stems And MIDI` subgraph, with an `Iteration` counter and a note on where the files land. |

## Output format

Every stem comes back as a standard ComfyUI `AUDIO` (`{"waveform": [1, C, S], "sample_rate"}`)
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
web/                   front end scripts: the badge, the player, the row trimmer,
                       the counting widget
Audio/StemSplitter/    the splitter family, and vendored SAM support
Audio/Audio2MIDI/      audio to MIDI
Audio/AudioSave/       saving, and converting to other formats
Audio/PhaseInvert/     polarity
Utils/Increment/       counting
Utils/TextMerge/       joining text
```
