from .audio_suite_nodes import (
    StemSplitter,
    StemSplitter4,
    StemSplitter6,
    StemSplitterFX,
    StemSplitterCheatsheet,
    Audio2MIDI,
    AudioSave,
    AudioConvert,
    Increment,
)

# SAM-Audio lives in its own module, with the vendored support package beside it.
from .sam_audio_nodes import StemSplitterSAM

NODE_CLASS_MAPPINGS = {
    "StemSplitter": StemSplitter,
    "StemSplitter4": StemSplitter4,
    "StemSplitter6": StemSplitter6,
    "StemSplitterFX": StemSplitterFX,
    "StemSplitterSAM": StemSplitterSAM,
    "Audio2MIDI": Audio2MIDI,
    "AudioSave": AudioSave,
    "AudioConvert": AudioConvert,
    "Increment": Increment,
    # Registered last so it comes last in its folder: the node list keeps registration
    # order unless the library's alphabetical sort is on.
    "StemSplitterCheatsheet": StemSplitterCheatsheet,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "StemSplitter": "StemSplitter",
    "StemSplitter4": "StemSplitter4",
    "StemSplitter6": "StemSplitter6",
    "StemSplitterFX": "StemSplitterFX",
    "StemSplitterSAM": "StemSplitterSAM",
    "Audio2MIDI": "Audio2MIDI",
    "AudioSave": "AudioSave",
    "AudioConvert": "AudioConvert",
    "Increment": "Increment",
    "StemSplitterCheatsheet": "StemSplitter Cheatsheet",
}

__all__ = list(NODE_CLASS_MAPPINGS)

# Extra words ComfyUI's node search matches besides the node name, so "oss" finds every
# node here. Set on the classes below rather than written into each one, so a node added
# later cannot miss it.
SEARCH_ALIASES = ["oss", "one solo studios"]
for _node in NODE_CLASS_MAPPINGS.values():
    _node.SEARCH_ALIASES = SEARCH_ALIASES

WEB_DIRECTORY = "./web"
