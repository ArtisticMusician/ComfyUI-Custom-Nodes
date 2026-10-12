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
