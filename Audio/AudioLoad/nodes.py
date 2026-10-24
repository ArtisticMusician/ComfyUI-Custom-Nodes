"""Part of the pack, split out of the single module it used to live in."""

import hashlib
import os

import folder_paths
import soundfile as sf
import torch

from ...common import *  # noqa: F403 - the pack's shared helpers and constants


# The empty first entry, so a new node starts with nothing selected. ComfyUI takes the first
# item in a combo as its value, which without this is whichever file sorts first in input/.
_NO_FILE = ""


def _audio_files():
    """The audio files in ComfyUI's input folder, listed the way its own Load Audio lists them,
    behind an empty entry that leaves a new node with no file chosen."""
    folder = folder_paths.get_input_directory()
    os.makedirs(folder, exist_ok=True)
    files = folder_paths.filter_files_content_types(os.listdir(folder), ["audio"])
    return [_NO_FILE, *sorted(files)]


class AudioLoader:
    """Loads an audio file from ComfyUI's input folder, with a waveform you can play from.

    Core's Load Audio gives a pack node no player: ComfyUI attaches its own transport to a
    fixed list of its own classes. This node draws the pack's player instead - the same one
    the save nodes use - so a file can be checked before anything is run instead of after.

    The file list is read when ComfyUI asks for this node's inputs, which is at startup or on
    a refresh, so a file uploaded while the app is open shows up in the list either way: the
    frontend adds a name it just uploaded to the dropdown itself.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": (_audio_files(), {
                    "tooltip": "A file in ComfyUI's input folder. Nothing is chosen until you "
                               "pick one; Upload... puts a file there.",
                }),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "load"
    CATEGORY = IO_CATEGORY
    DESCRIPTION = "Loads an audio file from ComfyUI's input folder, with playback and waveform."

    @classmethod
    def IS_CHANGED(cls, audio):
        # Without this the graph is cached on the file NAME alone, so a new take dropped in
        # under a name that was used before would keep handing the old audio downstream.
        if not audio:
            # Nothing chosen: there is no file to watch, and the resolver would be handed the
            # folder itself.
            return _NO_FILE
        path = folder_paths.get_annotated_filepath(audio)
        info = os.stat(path)
        return hashlib.sha256(f"{path}:{info.st_mtime_ns}:{info.st_size}".encode()).hexdigest()

    def load(self, audio):
        if not audio:
            raise ValueError(
                "AudioLoader: no file chosen. Pick one from the dropdown, or use Upload... ."
            )
        # Core's own resolver, so a name cannot walk out of the input folder.
        path = folder_paths.get_annotated_filepath(audio)
        data, sample_rate = sf.read(path, dtype="float32", always_2d=True)  # [samples, channels]
        waveform = torch.from_numpy(data.T).contiguous().unsqueeze(0)
        entry = _file_entry(path, folder_paths.get_input_directory(), "input")
        print(f"[UVR5] loaded {entry['filename']} ({waveform.shape[1]}ch, {int(sample_rate)} Hz)")
        return {
            # No "audio" key: ComfyUI's own audio player is handed to a fixed list of its own
            # classes, and its handler assumes any node reporting one has that player as an
            # `audioUI` widget - it throws on this node, which has its own. This player follows
            # the field instead, so a run has nothing to tell it.
            "ui": {"stem_splitter_files": [entry]},
            "result": ({"waveform": waveform, "sample_rate": int(sample_rate)},),
        }


# Everything above is this module's surface, private helpers included: the split-out
# modules pull from here with `import *`, which otherwise skips underscore names.
__all__ = [name for name in dir() if not name.startswith("__")]
