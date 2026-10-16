"""One Solo Studios node pack: audio separation, and whatever else earns a place.

The folders mirror the node menu, so a node's category and its home on disk agree:

    Audio/StemSplitter/   the splitter family, and their cheat sheet
    Audio/Audio2MIDI/     audio to MIDI
    Audio/AudioLoad/      loading audio, with the pack's player on it
    Audio/AudioSave/      saving audio, and converting it to other formats
    Utils/Increment/      counting, for numbering files

Shared helpers live in common.py. Front end scripts live in web/.
"""

from .Audio.Audio2MIDI.nodes import Audio2MIDI
from .Audio.AudioLoad.nodes import AudioLoader
from .Audio.AudioSave.nodes import AudioConvert, AudioSave, StemSave
from .Audio.PhaseInvert.nodes import PhaseInvert
from .Audio.StemSplitter.cheatsheet import StemSplitterCheatsheet
from .Audio.StemSplitter.nodes import (
    StemEnsemble,
    StemSplitter,
    StemSplitter4,
    StemSplitter6,
    StemSplitterDrums,
    StemSplitterFX,
)
from .Audio.StemSplitter.sam_audio_nodes import StemSplitterSAM
from .Utils.Increment.nodes import Increment
from .Utils.TextMerge.nodes import TextMerge

NODE_CLASS_MAPPINGS = {
    "StemSplitter": StemSplitter,
    "StemSplitter4": StemSplitter4,
    "StemSplitter6": StemSplitter6,
    "StemSplitterDrums": StemSplitterDrums,
    "StemSplitterFX": StemSplitterFX,
    "StemSplitterSAM": StemSplitterSAM,
    "StemEnsemble": StemEnsemble,
    "Audio2MIDI": Audio2MIDI,
    "AudioLoader": AudioLoader,
    "AudioSave": AudioSave,
    "AudioConvert": AudioConvert,
    "StemSave": StemSave,
    "PhaseInvert": PhaseInvert,
    "Increment": Increment,
    "TextMerge": TextMerge,
    # Registered last, so it comes last in its folder.
    "StemSplitterCheatsheet": StemSplitterCheatsheet,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    name: ("StemSplitter Cheatsheet" if name == "StemSplitterCheatsheet" else name)
    for name in NODE_CLASS_MAPPINGS
}

__all__ = list(NODE_CLASS_MAPPINGS)

# Extra words the node search matches besides the node name, so "oss" finds every node.
SEARCH_ALIASES = ["oss", "one solo studios"]
for _node in NODE_CLASS_MAPPINGS.values():
    _node.SEARCH_ALIASES = SEARCH_ALIASES

WEB_DIRECTORY = "./web"
