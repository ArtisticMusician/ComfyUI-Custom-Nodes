"""Polarity: flipping a clip so it cancels against another.

Arithmetic, not separation: every sample multiplied by -1. Nothing here comes from the
separation library, and there is no model and no setting.
"""

from ...common import *  # noqa: F403 - the pack's shared helpers and constants


class PhaseInvert:
    """Flips the polarity of a clip: every sample times -1.

    Its use is cancellation. Blend an inverted stem against the clip it came from and the two
    subtract; through StemEnsemble that is the difference of two models rather than their
    sum - at the level the chosen algorithm works at, since an average is divided by how many
    stems are wired in.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {
                    "tooltip": "The clip to flip. Sample rate, channels and length come back "
                               "unchanged.",
                }),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("inverted",)
    FUNCTION = "invert"
    CATEGORY = TOOLS_CATEGORY
    DESCRIPTION = "Flips the polarity of a clip, so it cancels against the original when mixed."

    def invert(self, audio):
        return ({"waveform": -audio["waveform"].detach().float(),
                 "sample_rate": int(audio["sample_rate"])},)
