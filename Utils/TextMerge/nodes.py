"""Text handling: joining what other nodes produce, for prompts and file names."""

from ...common import *  # noqa: F403 - the pack's shared helpers and constants


class TextMerge:
    """Joins every text wired in, in row order, with a delimiter between them.

    Wire a text output into the last row and another row appears, for as long as you keep going:
    there is no fixed number of rows, and never a row to add by hand. Unwired rows do nothing,
    and the front end drops the empty ones past the last row in use, so the node stays only as
    tall as the work.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "delimiter": ("STRING", {
                    "default": "",
                    "tooltip": "What goes between the texts: a space, a comma, a newline. "
                               "Empty joins them with nothing between.",
                }),
            },
            "optional": {
                # Only the first row is declared. ComfyUI fixes a node's inputs when the class is
                # written, but the executor hands this node whatever the prompt has, so the front
                # end grows the rows and there is no ceiling to hit.
                "text_1": ("STRING", {
                    "forceInput": True,
                    "tooltip": "Text 1. Wire a text output here; the next row appears by itself.",
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "merge"
    CATEGORY = UTIL_CATEGORY
    DESCRIPTION = "Joins every text wired in, in row order, with a delimiter between them."

    def merge(self, delimiter, **texts):
        # Whatever rows arrived, in row order. A row nobody wired is simply not here.
        rows = sorted(int(name.split("_")[1]) for name in texts if name.startswith("text_"))
        parts = [texts[f"text_{row}"] for row in rows if texts.get(f"text_{row}") is not None]
        return (delimiter.join(parts),)
