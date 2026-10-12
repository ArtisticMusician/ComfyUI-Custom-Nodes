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


_BASIC_PITCH = {}


def _basic_pitch():
    """Basic Pitch's predict function and model, loaded once per process."""
    if "model" not in _BASIC_PITCH:
        try:
            from basic_pitch import ICASSP_2022_MODEL_PATH
            from basic_pitch.inference import Model, predict
        except ImportError as exc:
            raise RuntimeError(
                "Basic Pitch is not installed in this ComfyUI's Python. Install it with:\n"
                "  pip install --no-deps basic-pitch pretty_midi resampy mir_eval"
            ) from exc
        _BASIC_PITCH["predict"] = predict
        _BASIC_PITCH["model"] = Model(ICASSP_2022_MODEL_PATH)
    return _BASIC_PITCH["predict"], _BASIC_PITCH["model"]


class Audio2MIDI:
    """Transcribes an audio clip to MIDI with Spotify's Basic Pitch."""

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
                "onset_threshold": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "How sure the model must be that a note starts here.",
                }),
                "frame_threshold": ("FLOAT", {
                    "default": 0.3, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "How sure the model must be that a note is still sounding.",
                }),
                "minimum_note_length": ("FLOAT", {
                    "default": 127.7, "min": 0.0, "max": 5000.0, "step": 1.0,
                    "tooltip": "Shortest note to keep, in milliseconds.",
                }),
            }
        }

    RETURN_TYPES = ("MIDI", "STRING")
    RETURN_NAMES = ("midi", "midi_path")
    FUNCTION = "transcribe"
    CATEGORY = AUDIO_CATEGORY
    DESCRIPTION = "Audio to MIDI with Spotify's Basic Pitch. Writes a .mid file and returns it."

    def transcribe(self, audio, filename_prefix, timestamp, onset_threshold, frame_threshold,
                   minimum_note_length):
        # Loaded first, so a missing dependency fails with a message that says how to fix it.
        predict, model = _basic_pitch()

        waveform, sample_rate = _input_waveform(audio)
        workdir = _run_dir()
        _clear_dir(workdir)

        sent = {"value": -1}
        pbar = comfy.utils.ProgressBar(100)

        def report(value):
            if value > sent["value"]:
                sent["value"] = value
                pbar.update_absolute(value)

        report(2)
        source = os.path.join(workdir, "input.wav")
        _write_wav(source, waveform, sample_rate)

        report(10)
        # Basic Pitch reports no progress of its own, so this bar moves by phase only.
        _unused, midi_data, notes = predict(
            source,
            model,
            onset_threshold=onset_threshold,
            frame_threshold=frame_threshold,
            minimum_note_length=minimum_note_length,
        )
        report(96)

        out_path = _output_path(
            filename_prefix, "mid", time.strftime("%Y%m%d-%H%M%S") if timestamp else None
        )
        midi_data.write(out_path)
        report(100)
        print(f"[UVR5] Basic Pitch: {len(notes)} notes -> {out_path}")
        # mido.MidiFile is the MIDI type other ComfyUI audio packs use.
        import mido

        return {
            "ui": {"stem_splitter_files": [_saved_file(out_path)],
                   "stem_splitter_prefix": [filename_prefix]},
            "result": (mido.MidiFile(out_path), out_path),
        }


# --------------------------------------------------------------------------- #
# AudioSave
# --------------------------------------------------------------------------- #
