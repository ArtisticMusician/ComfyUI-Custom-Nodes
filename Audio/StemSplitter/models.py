"""Part of the pack, split out of the single module it used to live in."""

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

from ...common import *  # noqa: F403 - the pack's shared helpers and constants


GUIDE_SPLITTER_MODELS = (
    ("1 Vocals / Instrumental", "best instrumental score", "Roformer Model: BS-Roformer-Viperx-1297"),
    ("1 Vocals / Instrumental", "best vocals score", "Roformer Model: MelBand Roformer | Vocals by Kimberley Jensen"),
    ("1 Vocals / Instrumental", "MDX23C checkpoint", "MDX23C Model: MDX23C-InstVoc HQ"),
    ("1 Vocals / Instrumental", "MDX-Net, instrumental listed first", "MDX-Net Model: UVR-MDX-NET Inst HQ 4"),
    ("1 Vocals / Instrumental", "MDX-Net, Kim Inst weights", "MDX-Net Model: Kim Inst"),
    ("2 Lead / Backing", "newest karaoke model", "Roformer Model: Mel-Roformer-Karaoke-Aufr33-Viperx"),
    ("2 Lead / Backing", "classic karaoke, VR arch", "VR Arch Single Model v5: 5_HP-Karaoke-UVR"),
    ("2 Lead / Backing", "the other karaoke model, VR arch", "VR Arch Single Model v5: 6_HP-Karaoke-UVR"),
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

# Drum kit pieces: the library's one drum-specific model, on its own node because its six
# stems are the kit, not the stems any other multi-stem node produces.
GUIDE_DRUM_MODELS = (
    ("3 Drums, kit pieces", "the only drum-specific model", "MDX23C Model: MDX23C DrumSep by aufr33-jarredou"),
)

GUIDE_FX_MODELS = (
    ("10 Dereverb", "highest scoring", "Roformer Model: MelBand Roformer | De-Reverb by anvuew"),
    ("10 Dereverb", "less aggressive", "Roformer Model: MelBand Roformer | De-Reverb Less Aggressive by anvuew"),
    ("11 Denoise", "highest scoring", "Roformer Model: Mel-Roformer-Denoise-Aufr33"),
    ("11 Denoise", "more aggressive", "Roformer Model: Mel-Roformer-Denoise-Aufr33-Aggr"),
    ("12 De-echo", "normal", "VR Arch Single Model v5: UVR-De-Echo-Normal by FoxJoy"),
    ("12 De-echo", "stronger", "VR Arch Single Model v5: UVR-De-Echo-Aggressive by FoxJoy"),
)

# Everything above is this module's surface, private helpers included: the split-out
# modules pull from here with `import *`, which otherwise skips underscore names.
__all__ = [name for name in dir() if not name.startswith("__")]
