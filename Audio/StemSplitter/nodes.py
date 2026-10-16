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

import logging
import os
import re
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager

import comfy.audio
import comfy.utils
import numpy as np
import soundfile as sf
import torch

import folder_paths
from comfy_execution.graph import ExecutionBlocker

from ...common import *  # noqa: F403 - the pack's shared helpers and constants
from .models import *  # noqa: F403 - the model lists this folder owns
from . import band_max


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


class _MultiStemNode:
    """Shared behaviour for the nodes whose stems are fixed by the model they run.

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


class StemSplitter4(_MultiStemNode):
    """Four stems in one pass: vocals, drums, bass, other."""

    STEMS = _STEMS4
    MODELS = GUIDE_SPLITTER4_MODELS
    RETURN_TYPES = ("AUDIO",) * len(_STEMS4)
    RETURN_NAMES = _STEMS4
    DESCRIPTION = "Four stems in one pass: vocals, drums, bass, other."


class StemSplitter6(_MultiStemNode):
    """Six stems in one pass, guitar and piano included."""

    STEMS = _STEMS6
    MODELS = GUIDE_SPLITTER6_MODELS
    RETURN_TYPES = ("AUDIO",) * len(_STEMS6)
    RETURN_NAMES = _STEMS6
    DESCRIPTION = "Six stems in one pass: vocals, drums, bass, guitar, piano, other."


class StemSplitterDrums(_MultiStemNode):
    """The pieces of a drum kit in one pass: kick, snare, toms, hi-hat, ride, crash.

    The one drum-specific model in the library. It is not on the other multi-stem nodes,
    whose sockets are named for the stems Demucs produces, and this model produces the
    pieces of the kit instead. Feed it a drum track or a drums stem; it is looking for
    nothing but drums.
    """

    # The model declares "hh" for the hi-hat; the socket says what it is.
    STEMS = _DRUMS
    MODELS = GUIDE_DRUM_MODELS
    RETURN_TYPES = ("AUDIO",) * len(_DRUMS)
    RETURN_NAMES = _DRUM_SOCKETS
    DESCRIPTION = "Splits drums into kick, snare, toms, hi-hat, ride and crash."


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


# --------------------------------------------------------------------------- #
# Blending: a stem from several splitter runs, and its opposite, side by side
# --------------------------------------------------------------------------- #
# audio-separator blends them itself. Its Ensembler takes waveforms as (channels, samples)
# arrays, which is what a wired AUDIO already is, so nothing about the mixing is written
# here. The order and the wording below are this pack's; a rule the library adds later is
# appended to the menu rather than dropped, so nothing it gains goes missing.
#
# Three families, named the same way throughout, so the menu reads as one scheme rather than
# a pile of library names:
#
#   by Waveform   one decision for the whole clip: the input that is loudest or quietest overall
#   by Sample     a decision per sample            (the library's *_wave rules)
#   by Frequency  a decision per bin, or per band  (the library's *_fft rules, and ours)
#
# The menu: what the dropdown shows, in order, and the name the blend code knows it by. One
# table, so the wording and the order cannot drift apart.
#
# The naming runs in three families, so the list reads as one scheme rather than a pile of
# library names:
#
#   by Waveform   one decision for the whole clip: the input that is loudest or quietest overall
#   by Sample     a decision per sample            (the library's *_wave rules)
#   by Frequency  a decision per bin, or per band  (the library's *_fft rules, and ours)
#
# Two pairs name the same underlying rule twice, on purpose, for that symmetry: averaging
# waveforms IS averaging samples, and so is the median. Both spellings work and both send the
# same algorithm name.
_ENSEMBLE_MENU = (
    ("Average the Waveforms", "avg_wave"),
    ("Average By Sample", "avg_wave"),
    ("Average by Frequency", "avg_fft"),
    ("Median of the Waveforms", "median_wave"),
    ("Median of the Sample", "median_wave"),
    ("Median of the Frequency", "median_fft"),
    ("Loudest Wins per Band, per Frame", "band_max"),
    ("Loudest Wins by Waveform", "loudest_input"),
    ("Loudest Wins by Sample", "max_wave"),
    ("Loudest Wins by Frequency", "max_fft"),
    ("Quietest Wins per Band, per Frame", "band_min"),
    ("Quietest Wins by Waveform", "quietest_input"),
    ("Quietest Wins by Sample", "min_wave"),
    ("Quietest Wins by Frequency", "min_fft"),
)

# This pack's own rules: the two band-level picks (band_max.py) and the two whole-clip picks.
# The band picks are not something the library offers. The whole-clip picks decide once for the
# clip by its own level, where every library rule decides per sample, per bin or per band.
_OWN_ALGORITHMS = ("band_max", "band_min", "loudest_input", "quietest_input")

# Names this node does not offer, each for a measured reason rather than a guess:
#
#   'ensemble_wav'  splits a waveform along its first axis, so handed the (channels, samples)
#                   a stem arrives as it returns one of its inputs unchanged.
#   'uvr_max_spec'  the same rule as 'max_fft' - biggest magnitude wins each time-frequency
#   'uvr_min_spec'  cell - built on UVR's own transform instead of librosa's, and it hands
#                   back a SHORTER file: measured 743 samples (16.85 ms) short on a real
#                   stereo pair, where the 'max_fft' path returned the input's length exactly.
#                   Two names for one result, and one of them costs the tail of the audio.
#                   Its equivalent, which does return the full length, is 'loudest wins,
#                   frequency by frequency' (and 'quietest ...' for the min side).
_ENSEMBLE_SKIP = ("ensemble_wav", "uvr_max_spec", "uvr_min_spec")


def _ensemble_choices():
    """[(what the dropdown shows, the name the blend code knows it by), ...].

    Straight from _ENSEMBLE_MENU, so the menu is one list with one order. Anything the library
    offers that the menu does not name is appended under its raw name, so a rule it adds later
    still shows up instead of going missing.
    """
    try:
        _require_backend()
        library = [name for name in Separator.VALID_ENSEMBLE_ALGORITHMS
                   if name not in _ENSEMBLE_SKIP]
    except Exception as exc:
        print(f"[UVR5] Could not read the ensemble algorithms from audio-separator ({exc}); "
              f"using the ones this pack was written against.")
        library = [name for _, name in _ENSEMBLE_MENU if name not in _ENSEMBLE_SKIP]
    known = {name for _, name in _ENSEMBLE_MENU}
    offered = [(shown, name) for shown, name in _ENSEMBLE_MENU
               if name in _OWN_ALGORITHMS or name in library]
    offered += [(name, name) for name in library if name not in known]
    return offered


def _ensemble_algorithm(label):
    """The dropdown's wording -> the name the blend code knows the algorithm by."""
    for shown, name in _ensemble_choices():
        if shown == label:
            return name
    return label  # an algorithm no label covers: its own name is what the dropdown shows


def _blend_side(algorithm, stems, rate):
    """One side, blended: this pack's own rules where it has them, else the library's."""
    if algorithm in ("band_max", "band_min"):
        return band_max.blend(stems, rate, loudest=algorithm == "band_max")
    if algorithm in ("loudest_input", "quietest_input"):
        return _pick_waveform(stems, loudest=algorithm == "loudest_input")
    return Ensembler(logging.getLogger(__name__), algorithm).ensemble(stems)


def _pick_waveform(stems, loudest=True):
    """The whole-clip pick: whichever input is loudest (or quietest) overall, passed through.

    Every other rule here decides per sample, per bin or per band. This one decides once for the
    clip, so the output is one of the inputs, untouched, and never a mixture of two.
    """
    if len(stems) == 1:
        return stems[0]
    levels = [float(np.sqrt((wave ** 2).mean())) for wave in stems]
    return stems[levels.index(max(levels) if loudest else min(levels))]


# The two sides a split comes in: what you are pulling out, and its opposite. What goes on
# each row's first socket blends into the first output, the second socket into the second.
_ENSEMBLE_SIDES = ("audio_1", "audio_2")


class StemEnsemble:
    """Blends the stems wired in, one clip per side: the stem you want, and its opposite.

    A row is one splitter's pair. Wire both of its outputs into a row, and everything on the
    rows' first sockets is blended into ``audio_1`` while everything on their second sockets
    is blended into ``audio_2``. Wire only one side and the other output is blocked, rather
    than filled with audio that was never there.
    """

    # Rows, for the same reason StemSave declares twenty: ComfyUI fixes a node's inputs when
    # the class is written and will not grow them at run time. Rows nobody wires do nothing,
    # and the front end drops the empty ones past the last row in use.
    ROWS = 8

    @classmethod
    def INPUT_TYPES(cls):
        optional = {}
        for row in range(1, cls.ROWS + 1):
            optional[f"audio_{row}"] = ("AUDIO", {
                "tooltip": f"Row {row}: the stem you are pulling out. Every one of these "
                           f"blends into {_ENSEMBLE_SIDES[0]}.",
            })
            optional[f"opposite_{row}"] = ("AUDIO", {
                "tooltip": f"Row {row}: the opposite of that stem. Every one of these blends "
                           f"into {_ENSEMBLE_SIDES[1]}.",
            })
        return {
            "required": {
                "algorithm": ([shown for shown, _ in _ensemble_choices()], {
                    "tooltip": "How each side is combined. 'average the waveforms' is the "
                               "plain blend; the rest are audio-separator's own algorithms.",
                }),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("AUDIO",) * len(_ENSEMBLE_SIDES)
    RETURN_NAMES = _ENSEMBLE_SIDES
    FUNCTION = "blend"
    CATEGORY = CATEGORY
    DESCRIPTION = ("Blends the stems wired in: audio_1 is everything on the rows' first "
                   "sockets, audio_2 everything on their second.")

    def blend(self, algorithm, **streams):
        _require_backend()
        # Rows arrive by name, and a row nobody wired does not arrive at all. Walk them in
        # row order, so the result does not depend on the order things were wired in.
        wired = [(row, streams.get(f"audio_{row}"), streams.get(f"opposite_{row}"))
                 for row in range(1, self.ROWS + 1)]
        wired = [(row, first, second) for row, first, second in wired if first or second]
        if not wired:
            raise RuntimeError(
                "StemEnsemble: nothing is wired in. Connect a splitter output to at least "
                "one row."
            )

        pbar = comfy.utils.ProgressBar(100)
        pbar.update_absolute(5)

        # Everything moves to the highest rate and the widest channel count wired in, so both
        # outputs come back the same shape. A single run is unaffected by this.
        rate = max(int(audio["sample_rate"]) for _, first, second in wired
                   for audio in (first, second) if audio)
        channels = 0
        waves = {}
        for done, (row, first, second) in enumerate(wired):
            waves[row] = []
            for audio in (first, second):
                if audio is None:
                    waves[row].append(None)
                    continue
                waveform, sample_rate = _input_waveform(audio)
                if sample_rate != rate:
                    waveform = comfy.audio.resample(waveform, sample_rate, rate)
                if waveform.dim() == 1:
                    waveform = waveform.unsqueeze(0)
                channels = max(channels, waveform.shape[0])
                waves[row].append(waveform)
            pbar.update_absolute(5 + 45 * (done + 1) // len(wired))

        lengths = {waveform.shape[-1] for pair in waves.values()
                   for waveform in pair if waveform is not None}
        if len(lengths) > 1:
            print("[UVR5] StemEnsemble: the wired stems are not the same length. "
                  "audio-separator pads the shorter ones with silence, and the min and "
                  "median algorithms can then pick that silence.")

        sides = [[], []]  # index 0 -> audio_1, index 1 -> audio_2
        for row, pair in waves.items():
            for index, waveform in enumerate(pair):
                if waveform is None:
                    continue
                if waveform.shape[0] == 1 and channels > 1:
                    waveform = waveform.repeat(channels, 1)  # what the models do with mono
                if waveform.shape[0] != channels:
                    which = "first" if index == 0 else "second"
                    raise RuntimeError(
                        f"StemEnsemble: row {row}'s {which} socket carries "
                        f"{waveform.shape[0]} channels and the others carry {channels}; "
                        f"waveforms have to match to be blended."
                    )
                sides[index].append(waveform.float().numpy())
        pbar.update_absolute(60)

        algorithm_name = _ensemble_algorithm(algorithm)
        outputs = []
        for name, stems in zip(_ENSEMBLE_SIDES, sides):
            if not stems:
                # Nothing is wired to this side, so there is nothing to blend and nothing to
                # invent: blocked, and whatever was fed from it is skipped with it.
                print(f"[UVR5] StemEnsemble: nothing wired for {name}; it is blocked.")
                outputs.append(ExecutionBlocker(None))
                continue
            blended = _blend_side(algorithm_name, stems, rate)
            if blended.ndim == 1:  # the AUDIO contract is [batch, channels, samples]
                blended = blended[None, :]
            outputs.append({
                "waveform": torch.from_numpy(np.ascontiguousarray(blended, dtype=np.float32)).unsqueeze(0),
                "sample_rate": int(rate),
            })
        pbar.update_absolute(100)

        counts = ", ".join(f"{name}: {len(stems)}" for name, stems in zip(_ENSEMBLE_SIDES, sides))
        print(f"[UVR5] StemEnsemble: {counts}, blended with '{algorithm_name}' at {rate} Hz")
        return tuple(outputs)
