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
