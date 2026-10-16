"""Part of the pack, split out of the single module it used to live in."""

import os
import re
import time

from ...common import *  # noqa: F403 - the pack's shared helpers and constants


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
                    "default": False,
                    "tooltip": "Put the time in the name so every run writes a new file.",
                }),
                "float32": _float32_input(),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = f"{IO_CATEGORY}/AudioSave"
    DESCRIPTION = "Saves any audio to ComfyUI's output folder, with playback and waveform."

    def save(self, audio, filename_prefix, timestamp, float32=False):
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
            _write_wav(path, wav, sample_rate, float32=float32)
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
    CATEGORY = f"{IO_CATEGORY}/AudioConvert"
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


class StemSave:
    """Saves each named input as its own WAV, and passes every one of them back out.

    Twenty rows are declared up front, because ComfyUI fixes a node's inputs and outputs
    when the class is written and will not grow them afterwards. Rows you leave unwired do
    nothing at all; the front end drops the empty ones past the last row in use so the node
    stays small.

    Put a name on a row ("drums", "bass" - whatever it is), wire audio into it, and this
    node writes that stem to <filename_prefix>/<name>.wav in ComfyUI's output folder.
    """

    ROWS = 20

    @classmethod
    def INPUT_TYPES(cls):
        optional = {}
        for row in range(1, cls.ROWS + 1):
            optional[f"audio_{row}"] = ("AUDIO", {
                "tooltip": f"Stem {row}. Leave it unwired to skip this row.",
            })
            optional[f"name_{row}"] = ("STRING", {
                "default": f"stem_{row}",
                "tooltip": "What this stem is: it becomes the file name.",
            })
        # Last, after the rows rather than among the required inputs: widgets_values in a
        # saved workflow is a positional array, so a widget in front of name_1 would load
        # every stem's name into the wrong field on every workflow saved before this.
        optional["float32"] = _float32_input()
        return {
            "required": {
                "filename_prefix": ("STRING", {
                    "default": "audio/StemSplitter",
                    "tooltip": "Folder, inside ComfyUI's output folder, that the stems go in.",
                }),
                "timestamp": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Put the time in the name so every run writes a new file.",
                }),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("AUDIO",) * 20
    RETURN_NAMES = tuple(f"stem_{row}" for row in range(1, 21))
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = f"{IO_CATEGORY}/StemSave"
    DESCRIPTION = "Saves any number of named stems as WAV, and passes each one on."

    def save(self, filename_prefix, timestamp, float32=False, **stems):
        # Every wired row arrives here as audio_<n>, with its own name_<n> beside it; the
        # rows that are not wired are simply absent.
        stamp = time.strftime("%Y%m%d-%H%M%S") if timestamp else None
        saved, returned, written = [], [], []

        for row in range(1, self.ROWS + 1):
            audio = stems.get(f"audio_{row}")
            if not audio:
                returned.append(None)
                continue

            name = (stems.get(f"name_{row}") or "").strip() or f"stem_{row}"
            # The name becomes a file name, so keep it to one folder below the prefix and
            # clear of the characters Windows refuses.
            parts = [p for p in name.replace("\\", "/").split("/")
                     if p not in ("", ".", "..")]
            name = ("/".join(re.sub(r'[<>:"|?*\x00-\x1f]', "_", part) for part in parts)
                    or f"stem_{row}")

            waveform = audio["waveform"].detach().cpu().float()
            sample_rate = int(audio["sample_rate"])
            batch = waveform.shape[0] if waveform.dim() == 3 else 1
            row_files = []
            for batch_number, wav in enumerate(waveform if waveform.dim() == 3 else [waveform]):
                if wav.dim() == 1:
                    wav = wav.unsqueeze(0)
                path = _output_path(f"{filename_prefix.rstrip('/')}/{name}", "wav", stamp,
                                    index=batch_number if batch > 1 else None)
                _write_wav(path, wav, sample_rate, float32=float32)
                entry = _saved_file(path)
                row_files.append(entry)
                saved.append(entry)

            written.append({"name": name, "files": row_files})
            returned.append(audio)

        if saved:
            print("[UVR5] saved stems " + ", ".join(f["filename"] for f in saved))
        else:
            print("[UVR5] StemSave: nothing wired, nothing written")

        # stem_save_stems pairs each row with the files it wrote, so the node can draw one
        # waveform and player per stem instead of guessing which file belongs to which row.
        return {"ui": {"stem_splitter_files": saved,
                       "stem_splitter_prefix": [filename_prefix],
                       "stem_save_stems": written},
                "result": tuple(returned)}


