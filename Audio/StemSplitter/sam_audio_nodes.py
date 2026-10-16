"""SAM-Audio separation, without needing any other node pack installed.

The model and its inference library are Meta's (facebookresearch/sam-audio). The
sam_support package beside this file is ComfyUI-SAM-Audio by ethanfel, MIT licensed,
vendored here because Meta's package imports xformers, audiotools and torchcodec at import
time - none of which inference needs - and because its chunked inference is what keeps
long audio inside the window the model was trained on.

The checkpoint is loaded once per model name and kept, and ComfyUI tracks it through a
patcher so it can be offloaded when something else needs the memory.
"""

import comfy.model_management as model_management
import comfy.model_patcher as model_patcher
import comfy.utils as comfy_utils
import folder_paths
import torch

from .sam_support.attention import attention_backend_context
from .sam_support.audio import (
    crossfade_audio_chunks,
    plan_audio_chunks,
    prepare_audio,
    result_to_audio,
)
from .sam_support.runtime import (
    PRECISIONS,
    load_pipeline,
    model_choices,
    model_folder_display,
    ode_options,
    register_model_folder,
    seeded_inference,
)

# Declaring the models folder is this pack's job now that it stands alone: without it
# folder_paths has no "sam_audio" entry, and the checkpoint list cannot be built.
register_model_folder(folder_paths)

CATEGORY = "One Solo Studios/Audio/StemSplitter"
ATTENTION_BACKEND = "pytorch"  # the accurate path; the alternatives are quantized kernels

_PIPELINES = {}


def _pipeline(name, precision):
    """One loaded checkpoint per name, kept between runs."""
    if name not in _PIPELINES:
        _PIPELINES[name] = load_pipeline(
            name, folder_paths, model_management, model_patcher,
            ATTENTION_BACKEND, precision, "cpu",
        )
    return _PIPELINES[name]


def _as_result_list(value):
    """The model returns a tensor or a list per batch item; normalise to a list."""
    if isinstance(value, torch.Tensor):
        return [value] if value.ndim == 1 else list(value)
    return list(value)


class StemSplitterSAM:
    """Pulls the sound a text description names out of audio.

    The second output is the model's own estimate of everything else. It is generated alongside
    the target from the same sampling pass, not the input minus the target: Meta's model decodes
    two streams from one latent. The two are trained to add back up to the mixture, but nothing
    enforces it, so treat the residual as the model's idea of the rest - and take the mix minus
    the target (PhaseInvert, or any subtract) when the complement has to be exact.

    SAM-Audio is driven by the description: short lowercase noun or verb phrases such as
    "man speaking" or "dog barking" match its training best. Long audio is processed in
    chunks with a crossfade between them, because the model works on short windows.
    """

    @classmethod
    def INPUT_TYPES(cls):
        choices = model_choices(folder_paths)
        default = "sam-audio-small" if "sam-audio-small" in choices else choices[0]
        return {
            "required": {
                "audio": ("AUDIO",),
                "model_name": (choices, {
                    "default": default,
                    "tooltip": f"Meta's checkpoints by name, plus anything already downloaded into {model_folder_display()}.",
                }),
                "description": ("STRING", {
                    "default": "man speaking",
                    "tooltip": "A short, lowercase description of the sound to pull out.",
                }),
                "precision": (list(PRECISIONS), {
                    "default": "auto",
                    "tooltip": "Auto uses BF16 where the GPU supports it. BF16 roughly halves model memory.",
                }),
                "predict_spans": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Ask the model to locate the sound first. Uses more memory and time.",
                }),
                "seed": ("INT", {
                    "default": 0, "min": 0, "max": 2 ** 64 - 1,
                    "control_after_generate": True,
                    "tooltip": "Controls the model's initial noise, for repeatable results.",
                }),
                "inference_steps": ("INT", {
                    "default": 32, "min": 2, "max": 128, "step": 2,
                    "tooltip": "Higher is slower and may be better. Must be even.",
                }),
                "chunk_duration": ("FLOAT", {
                    "default": 10.0, "min": 0.0, "max": 3600.0, "step": 0.5,
                    "tooltip": "Seconds processed per pass. 0 processes the whole clip at once.",
                }),
                "chunk_overlap": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 60.0, "step": 0.1,
                    "tooltip": "Seconds shared between adjacent chunks, for a smooth join.",
                }),
            },
            "optional": {
                # No tooltip, on purpose: there is nothing to promise. The Judge that would
                # rank the candidates is never attached (ensure_judge_ranker has no caller), so
                # anything above 1 samples extra candidates and hands back the first one.
                "reranking_candidates": ("INT", {
                    "default": 1, "min": 1, "max": 8, "step": 1,
                }),
            },
        }

    RETURN_TYPES = ("AUDIO", "AUDIO")
    RETURN_NAMES = ("target", "residual")
    FUNCTION = "separate"
    CATEGORY = CATEGORY
    DESCRIPTION = "Separates a described sound from audio with SAM-Audio, Meta's model. Target and residual are both generated. Self-contained."

    def separate(self, audio, model_name, description, precision, predict_spans, seed,
                 inference_steps, chunk_duration, chunk_overlap, reranking_candidates=1):
        description = (description or "").strip()
        if not description:
            raise ValueError(
                "description cannot be empty: it is what tells SAM-Audio which sound to pull out."
            )

        pipeline = _pipeline(model_name, precision)
        sample_rate = pipeline.processor.audio_sampling_rate
        waveforms, target_length = prepare_audio(audio, sample_rate)
        batch_size = len(waveforms)
        chunks = plan_audio_chunks(target_length, sample_rate, chunk_duration, chunk_overlap)
        options = ode_options(inference_steps)

        pipeline.load(model_management)
        progress = comfy_utils.ProgressBar(len(chunks) * inference_steps)

        targets, residuals = [], []
        for index, chunk in enumerate(chunks):
            model_management.throw_exception_if_processing_interrupted()
            batch = pipeline.processor(
                audios=[piece[..., chunk.start:chunk.end] for piece in waveforms],
                descriptions=[description] * batch_size,
            ).to(pipeline.device)
            with (
                seeded_inference((seed + index) % (2 ** 64), pipeline.device),
                attention_backend_context(pipeline.attention_backend),
                torch.autocast(
                    device_type=pipeline.device.type,
                    dtype=pipeline.dtype,
                    enabled=pipeline.dtype != torch.float32,
                ),
                torch.inference_mode(),
            ):
                result = pipeline.model.separate(
                    batch,
                    ode_opt=options,
                    reranking_candidates=reranking_candidates,
                    predict_spans=predict_spans,
                )
            for collected, part in ((targets, result.target), (residuals, result.residual)):
                clip = result_to_audio(_as_result_list(part), sample_rate, chunk.length)
                collected.append((chunk, clip["waveform"]))
            progress.update(inference_steps)

        print(f"[UVR5] SAM-Audio '{description}': target, residual")
        return (
            {"waveform": crossfade_audio_chunks(targets, target_length).contiguous(),
             "sample_rate": sample_rate},
            {"waveform": crossfade_audio_chunks(residuals, target_length).contiguous(),
             "sample_rate": sample_rate},
        )
