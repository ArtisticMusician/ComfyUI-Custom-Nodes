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
from .models import *  # noqa: F403 - the model lists this folder owns


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
