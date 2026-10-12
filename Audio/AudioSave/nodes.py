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
