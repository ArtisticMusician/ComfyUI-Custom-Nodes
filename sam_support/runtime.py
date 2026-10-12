from __future__ import annotations

import contextlib
import functools
import hashlib
import importlib
import json
import logging
import math
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal, NamedTuple

import torch

from . import torchcodec_compat
from .attention import validate_attention_backend
from .audiotools_compat import audiotools_import_compatibility
from .xformers_compat import xformers_import_compatibility

LOGGER = logging.getLogger(__name__)

OFFICIAL_MODELS = (
    "facebook/sam-audio-small",
    "facebook/sam-audio-base",
    "facebook/sam-audio-large",
    "facebook/sam-audio-small-tv",
    "facebook/sam-audio-base-tv",
    "facebook/sam-audio-large-tv",
)

MODEL_FOLDER = "sam_audio"
MODEL_FILES = ("config.json", "checkpoint.pt")
MIRROR_MARKER = ".verified-mirror-checkpoint"
PRECISIONS = ("auto", "bf16", "fp32")
INITIAL_DEVICES = ("cpu", "gpu")
CPU_DEVICE = torch.device("cpu")
_IMPORT_LOCK = threading.RLock()


@dataclass(frozen=True)
class MirrorSpec:
    repo_id: str
    revision: str
    checkpoint_size: int
    checkpoint_sha256: str


@dataclass(frozen=True)
class SupportModelSpec:
    repo_id: str
    revision: str
    allow_patterns: tuple[str, ...] | None = None


# Each mirror revision is immutable, includes Meta's SAM License, and was checked
# against the corresponding facebook checkpoint.pt LFS SHA-256 on 2026-08-23.
MIRROR_MODELS = {
    "facebook/sam-audio-small": MirrorSpec(
        "mrfakename/sam-audio-small",
        "682824171fd5cfec47b88687f583a11050c1bf1d",
        5_100_547_943,
        "8c44fda9821fd9f2ec8977304e3c0f55290d9eacb6bbf25b4b8fb1f69c2a8c06",
    ),
    "facebook/sam-audio-base": MirrorSpec(
        "mrfakename/sam-audio-base",
        "351f6666d46357edea2149a338a680fcd0d7afdd",
        7_725_405_659,
        "b5f3e29ea7a9e80e90a00da495a8aafe890571f371c4bfb88c052c65a5636839",
    ),
    "facebook/sam-audio-large": MirrorSpec(
        "mrfakename/sam-audio-large",
        "497809f191dd4f673a2c93557176387cf2a06cf2",
        14_861_356_211,
        "ca55418b1d23e8c8a4dcc55f259d9801c8f79da0131a66e525d862c1289e3c4f",
    ),
    "facebook/sam-audio-small-tv": MirrorSpec(
        "mrfakename/sam-audio-small-tv",
        "2fee00b2836ede05fce503726ac9f908b1fc4aa9",
        5_100_547_943,
        "1a9693b235efc3176986664dac349eb64022c7468cf8d4195954490a2457e6a9",
    ),
    "facebook/sam-audio-base-tv": MirrorSpec(
        "mrfakename/sam-audio-base-tv",
        "ed6a64b2d3c6151276d81783becb8881d75efe4f",
        7_725_405_659,
        "569e3fecdefe267047b02d117acb5a67c03d2f73c4943d3d8bd43df9e9b9148d",
    ),
    "facebook/sam-audio-large-tv": MirrorSpec(
        "mrfakename/sam-audio-large-tv",
        "30eea7c915f43349f3b3f5c7e33e8658a01d7253",
        14_861_356_211,
        "90e047269238c498c5abe0da6e6ba40859d152111d4a09f582a209027a33b72f",
    ),
}

# SAM-Audio constructs these support models while loading. Resolve immutable
# snapshots once, then pass local paths upstream to prevent repeated Hub checks.
SUPPORT_MODELS = {
    "t5-base": SupportModelSpec(
        "google-t5/t5-base",
        "a9723ea7f1b39c1eae772870f3b547bf6ef7e6c1",
        ("config.json", "model.safetensors", "spiece.model", "tokenizer.json"),
    ),
    "pe-a-frame-large": SupportModelSpec(
        "facebook/pe-a-frame-large",
        "40187271298f84e2966d4518c88dde698540c9ad",
    ),
    "sam-audio-judge": SupportModelSpec(
        "facebook/sam-audio-judge",
        "cd52eb977697cc0b25d4ecd309a88d4af46223ee",
        (
            "checkpoint.pt",
            "config.json",
            "preprocessor_config.json",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
        ),
    ),
}


class SpanPrompt(NamedTuple):
    token: Literal["+", "-"]
    start: float
    end: float


@dataclass
class SAMAudioPipeline:
    model: torch.nn.Module
    processor: Any
    patcher: Any
    device: torch.device
    source: str
    attention_backend: str = "pytorch"
    span_predictor_source: str | None = None
    dtype: torch.dtype = torch.float32

    def get_models(self) -> list[Any]:
        """Let ComfyUI track this model for the lifetime of the prompt."""
        return [self.patcher]

    def load(self, model_management: Any) -> None:
        started = time.perf_counter()
        model_management.load_models_gpu([self.patcher], force_full_load=True)
        self.model.eval()
        elapsed = time.perf_counter() - started
        if elapsed >= 1.0:
            LOGGER.info("Loaded SAM-Audio weights onto %s in %.1f seconds", self.device, elapsed)

    def ensure_span_predictor(self, model_management: Any) -> None:
        """Attach the optional PE span predictor only when it is requested."""
        if hasattr(self.model, "span_predictor"):
            return
        if self.span_predictor_source is None:
            raise RuntimeError(
                "This SAM-Audio checkpoint does not declare a span predictor"
            )

        self._unload_before_extension(model_management)

        started = time.perf_counter()
        predictor, transform = _load_span_predictor_assets(
            self.span_predictor_source
        )
        self.model.span_predictor = predictor.eval().to(device="cpu", dtype=self.dtype)
        self.model.span_predictor_transform = transform
        self._reset_patcher_size()
        LOGGER.info(
            "Loaded optional SAM-Audio span predictor in %.1f seconds",
            time.perf_counter() - started,
        )

    def ensure_judge_ranker(self, model_management: Any) -> None:
        """Attach Meta's Judge ranker only when multiple candidates are requested."""
        if getattr(self.model, "text_ranker", None) is not None:
            return
        self._unload_before_extension(model_management)
        started = time.perf_counter()
        self.model.text_ranker = _load_judge_ranker(self.dtype)
        self._reset_patcher_size()
        LOGGER.info(
            "Loaded optional SAM-Audio Judge reranker in %.1f seconds",
            time.perf_counter() - started,
        )

    def _unload_before_extension(self, model_management: Any) -> None:
        # Move an already-used model off the GPU before adding a submodule so
        # ComfyUI can recalculate its complete size and residency.
        unload = getattr(model_management, "unload_model_and_clones", None)
        if unload is None:
            return
        try:
            unload(self.patcher, all_devices=True)
        except TypeError:
            unload(self.patcher)

    def _reset_patcher_size(self) -> None:
        if hasattr(self.patcher, "size"):
            self.patcher.size = 0


def register_model_folder(folder_paths: Any) -> Path:
    # Changed from upstream: checkpoints live under this pack's brand folder. The folder
    # name itself is unchanged, so every other use of it here still applies.
    model_dir = Path(folder_paths.models_dir) / "OneSoloStudio" / MODEL_FOLDER
    try:
        folder_paths.add_model_folder_path(
            MODEL_FOLDER, str(model_dir), is_default=True
        )
    except TypeError:
        # ComfyUI versions before is_default support still accept the two-argument form.
        folder_paths.add_model_folder_path(MODEL_FOLDER, str(model_dir))
    return model_dir


def _is_model_directory(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_file() for name in MODEL_FILES)


def discover_local_models(folder_paths: Any) -> dict[str, Path]:
    """Return stable UI labels for valid model directories in every configured root."""
    discovered: list[tuple[str, Path]] = []
    official_directory_names = {name.rsplit("/", 1)[-1] for name in OFFICIAL_MODELS}
    for raw_root in folder_paths.get_folder_paths(MODEL_FOLDER):
        root = Path(raw_root)
        if not root.is_dir():
            continue
        for current, directories, files in os.walk(root):
            current_path = Path(current)
            if all(name in files for name in MODEL_FILES):
                if current_path.parent == root and current_path.name in official_directory_names:
                    directories[:] = []
                    continue
                relative = current_path.relative_to(root).as_posix()
                label = relative if relative != "." else current_path.name
                discovered.append((f"local/{label}", current_path))
                directories[:] = []
                continue
            directories[:] = [
                name
                for name in directories
                if not name.startswith(".") and name != "__pycache__"
            ]

    counts: dict[str, int] = {}
    result: dict[str, Path] = {}
    for label, path in sorted(discovered, key=lambda item: (item[0].lower(), str(item[1]))):
        counts[label] = counts.get(label, 0) + 1
        unique_label = label if counts[label] == 1 else f"{label} [{counts[label]}]"
        result[unique_label] = path
    return result


def model_choices(folder_paths: Any) -> list[str]:
    return [*OFFICIAL_MODELS, *discover_local_models(folder_paths).keys()]


def _is_gate_error(error: Exception) -> bool:
    """Recognize Hugging Face gated/authorization failures across hub versions."""
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if type(current).__name__ == "GatedRepoError":
            return True
        response = getattr(current, "response", None)
        if getattr(response, "status_code", None) in (401, 403):
            return True
        current = current.__cause__ or current.__context__
    return False


def _checkpoint_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as checkpoint:
        for chunk in iter(lambda: checkpoint.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_mirror_checkpoint(destination: Path, spec: MirrorSpec) -> None:
    checkpoint = destination / "checkpoint.pt"
    marker = destination / MIRROR_MARKER
    expected_marker = f"{spec.checkpoint_size} {spec.checkpoint_sha256}\n"

    if (
        marker.is_file()
        and marker.read_text(encoding="utf-8") == expected_marker
        and checkpoint.stat().st_size == spec.checkpoint_size
    ):
        return

    actual_size = checkpoint.stat().st_size
    if actual_size != spec.checkpoint_size:
        raise RuntimeError(
            f"Mirror checkpoint size mismatch for {spec.repo_id}: expected "
            f"{spec.checkpoint_size} bytes, received {actual_size}"
        )

    actual_hash = _checkpoint_sha256(checkpoint)
    if actual_hash != spec.checkpoint_sha256:
        raise RuntimeError(
            f"Mirror checkpoint checksum mismatch for {spec.repo_id}; refusing to load it"
        )
    marker.write_text(expected_marker, encoding="utf-8")


def _download_mirror_model(
    huggingface_hub: Any,
    destination: Path,
    spec: MirrorSpec,
) -> Path:
    marker = destination / MIRROR_MARKER
    marker.write_text(f"pending {spec.checkpoint_sha256}\n", encoding="utf-8")
    snapshot = huggingface_hub.snapshot_download(
        repo_id=spec.repo_id,
        revision=spec.revision,
        local_dir=str(destination),
        allow_patterns=[*MODEL_FILES, "LICENSE"],
    )
    path = Path(snapshot)
    if not _is_model_directory(path) or not (path / "LICENSE").is_file():
        raise RuntimeError(
            f"The mirror snapshot for {spec.repo_id} is incomplete; expected "
            "config.json, checkpoint.pt, and LICENSE"
        )
    _verify_mirror_checkpoint(path, spec)
    return path


def _download_official_model(repo_id: str, model_root: Path) -> Path:
    destination = model_root / repo_id.rsplit("/", 1)[-1]
    if _is_model_directory(destination):
        marker = destination / MIRROR_MARKER
        if marker.exists() and (destination / "LICENSE").is_file():
            _verify_mirror_checkpoint(destination, MIRROR_MODELS[repo_id])
            return destination
        if not marker.exists():
            return destination

    destination.mkdir(parents=True, exist_ok=True)
    try:
        huggingface_hub = importlib.import_module("huggingface_hub")
    except Exception as error:
        raise RuntimeError(
            "huggingface-hub is required to download SAM-Audio checkpoints; "
            "run this node's install.py and restart ComfyUI"
        ) from error

    try:
        snapshot = huggingface_hub.snapshot_download(
            repo_id=repo_id,
            local_dir=str(destination),
            allow_patterns=list(MODEL_FILES),
        )
    except Exception as error:
        if _is_gate_error(error):
            spec = MIRROR_MODELS[repo_id]
            LOGGER.warning(
                "Access to %s was gated; downloading checksum-verified mirror %s",
                repo_id,
                spec.repo_id,
            )
            try:
                return _download_mirror_model(huggingface_hub, destination, spec)
            except Exception as mirror_error:
                raise RuntimeError(
                    f"Access to {repo_id} was denied and its verified public mirror "
                    f"{spec.repo_id} could not be downloaded"
                ) from mirror_error
        raise RuntimeError(
            f"Could not download {repo_id}. Accept the model license at "
            f"https://huggingface.co/{repo_id}, run `hf auth login` in ComfyUI's "
            "Python environment, and retry."
        ) from error

    path = Path(snapshot)
    if not _is_model_directory(path):
        raise RuntimeError(
            f"The downloaded snapshot for {repo_id} is incomplete; expected "
            f"{', '.join(MODEL_FILES)} in {path}"
        )
    (path / MIRROR_MARKER).unlink(missing_ok=True)
    return path


def resolve_model(model_name: str, folder_paths: Any) -> Path:
    local_models = discover_local_models(folder_paths)
    if model_name in local_models:
        return local_models[model_name]
    if model_name not in OFFICIAL_MODELS:
        raise ValueError(
            f"Unknown SAM-Audio model {model_name!r}. Refresh the browser after adding local models."
        )
    model_root = register_model_folder(folder_paths)
    official_directory = model_name.rsplit("/", 1)[-1]
    for raw_root in folder_paths.get_folder_paths(MODEL_FOLDER):
        candidate = Path(raw_root) / official_directory
        if not _is_model_directory(candidate):
            continue
        marker = candidate / MIRROR_MARKER
        if marker.exists():
            if not (candidate / "LICENSE").is_file():
                # Never trust a partial mirror download. The primary destination's
                # downloader can resume or replace it after this search finishes.
                continue
            _verify_mirror_checkpoint(candidate, MIRROR_MODELS[model_name])
        return candidate
    return _download_official_model(model_name, model_root)


def import_sam_audio() -> tuple[Any, Any]:
    try:
        LOGGER.info(
            "Loading SAM-Audio through isolated inference-only compatibility layers"
        )
        # Serializing our temporary sys.modules entries prevents two simultaneous
        # loader executions from observing a half-installed compatibility surface.
        with _IMPORT_LOCK:
            with (
                xformers_import_compatibility(),
                audiotools_import_compatibility(),
                torchcodec_compat.torchcodec_import_compatibility(),
            ):
                module = importlib.import_module("sam_audio")
            _install_lazy_torchcodec_decoders()
        return module.SAMAudio, module.SAMAudioProcessor
    except Exception as error:
        raise RuntimeError(
            "SAM-Audio could not be imported. Install this node's requirements with "
            "ComfyUI's Python interpreter, then restart ComfyUI."
        ) from error


def _install_lazy_torchcodec_decoders() -> None:
    """Keep upstream file I/O usable without importing TorchCodec during node load."""
    for name, module in tuple(sys.modules.items()):
        if not (
            name == "sam_audio"
            or name.startswith("sam_audio.")
            or name == "core"
            or name.startswith("core.")
        ):
            continue
        if not hasattr(module, "__dict__"):
            continue
        for attribute, value in tuple(vars(module).items()):
            if value is torchcodec_compat.AudioDecoder:
                setattr(module, attribute, torchcodec_compat.LazyAudioDecoder)
            elif value is torchcodec_compat.VideoDecoder:
                setattr(module, attribute, torchcodec_compat.LazyVideoDecoder)


@functools.lru_cache(maxsize=None)
def _cached_support_snapshot(spec: SupportModelSpec) -> str:
    try:
        huggingface_hub = importlib.import_module("huggingface_hub")
    except Exception as error:
        raise RuntimeError(
            "huggingface-hub is required to resolve SAM-Audio support models"
        ) from error

    options: dict[str, Any] = {
        "repo_id": spec.repo_id,
        "revision": spec.revision,
    }
    if spec.allow_patterns is not None:
        options["allow_patterns"] = list(spec.allow_patterns)

    try:
        return huggingface_hub.snapshot_download(
            **options,
            local_files_only=True,
        )
    except Exception:
        LOGGER.info(
            "Downloading one-time SAM-Audio support model %s at %s",
            spec.repo_id,
            spec.revision,
        )
        return huggingface_hub.snapshot_download(**options)


def _sam_audio_model_kwargs(model_path: Path) -> dict[str, Any]:
    model_kwargs: dict[str, Any] = {
        "map_location": "cpu",
        # Upstream's override only calls torch.nn.Module.load_state_dict when this
        # is true. Passing false silently leaves the complete model uninitialized.
        "strict": True,
        "text_ranker": None,
        "visual_ranker": None,
    }
    config_path = model_path / "config.json"
    if not config_path.is_file():
        return model_kwargs

    config = json.loads(config_path.read_text(encoding="utf-8"))
    text_encoder = config.get("text_encoder")
    if isinstance(text_encoder, dict) and text_encoder.get("name") == "t5-base":
        text_encoder = dict(text_encoder)
        text_encoder["name"] = _cached_support_snapshot(SUPPORT_MODELS["t5-base"])
        model_kwargs["text_encoder"] = text_encoder

    # The PE span predictor is a separate 5.8 GiB model and is not required for
    # ordinary text, explicit-span, or visual separation. It is attached lazily
    # by SAMAudioPipeline.ensure_span_predictor when predict_spans is enabled.
    if config.get("span_predictor") is not None:
        model_kwargs["span_predictor"] = None
    return model_kwargs


def _configured_span_predictor(model_path: Path) -> str | None:
    config_path = model_path / "config.json"
    if not config_path.is_file():
        return None
    value = json.loads(config_path.read_text(encoding="utf-8")).get(
        "span_predictor"
    )
    return value if isinstance(value, str) and value else None


def _load_span_predictor_assets(source: str) -> tuple[torch.nn.Module, Any]:
    if source == "pe-a-frame-large":
        source = _cached_support_snapshot(SUPPORT_MODELS["pe-a-frame-large"])
    try:
        module = importlib.import_module("core.audio_visual_encoder")
        predictor = module.PEAudioFrame.from_config(source, pretrained=True)
        transform = module.PEAudioFrameTransform.from_config(source)
    except Exception as error:
        raise RuntimeError(
            f"Failed to load SAM-Audio's optional span predictor from {source}"
        ) from error
    return predictor, transform


def _load_local_checkpoint_efficient(
    model_class: Any,
    model_path: Path,
    *,
    config_overrides: dict[str, Any],
    target_device: torch.device,
    dtype: torch.dtype,
    ignored_missing_pattern: str | None = None,
    defer_text_encoder: bool = False,
    use_meta_device: bool = True,
) -> torch.nn.Module:
    """Materialize checkpoint tensors once, directly in their inference format."""
    config_path = model_path / "config.json"
    checkpoint_path = model_path / "checkpoint.pt"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for key, value in config_overrides.items():
        if key in config:
            config[key] = value
    state_dict = torch.load(
        checkpoint_path,
        weights_only=True,
        mmap=True,
        map_location="cpu",
    )

    model_config = model_class.config_cls(**config)
    if defer_text_encoder:
        # SAMAudio's constructor downloads and materializes T5 while also allocating
        # every much-larger checkpoint-backed module. Replace only T5 during the
        # meta-device construction, then restore and load the real pretrained encoder.
        constructor_globals = model_class.__init__.__globals__
        text_encoder_class = constructor_globals.get("T5TextEncoder")
        if text_encoder_class is None:
            raise RuntimeError("SAM-Audio's T5TextEncoder constructor was not found")
        with _IMPORT_LOCK:
            constructor_globals["T5TextEncoder"] = lambda _config: torch.nn.Identity()
            try:
                with torch.device("meta"):
                    model = model_class(model_config)
            finally:
                constructor_globals["T5TextEncoder"] = text_encoder_class
        model.text_encoder = text_encoder_class(model_config.text_encoder)
    elif not use_meta_device:
        with _IMPORT_LOCK:
            original_dtype = torch.get_default_dtype()
            torch.set_default_dtype(dtype)
            try:
                with torch.device(target_device):
                    model = model_class(model_config)
            finally:
                torch.set_default_dtype(original_dtype)
        # Preserve the small derived buffers which checkpoint.pt intentionally
        # omits, then release all random constructor parameters before materializing
        # the real state dict. This avoids holding two Judge-sized models in RAM.
        derived_buffers = {
            name: value.detach().clone()
            for name, value in model.named_buffers()
            if name not in state_dict
        }
        model.to_empty(device=torch.device("meta"))
        for name, value in derived_buffers.items():
            module_name, _, buffer_name = name.rpartition(".")
            module = model.get_submodule(module_name) if module_name else model
            module._buffers[buffer_name] = value
    else:
        with torch.device("meta"):
            model = model_class(model_config)
    for key in tuple(state_dict):
        value = state_dict[key]
        if not isinstance(value, torch.Tensor):
            continue
        destination_dtype = dtype if value.dtype.is_floating_point else value.dtype
        if value.device != target_device or value.dtype != destination_dtype:
            state_dict[key] = value.to(
                device=target_device,
                dtype=destination_dtype,
                non_blocking=False,
            )

    result = torch.nn.Module.load_state_dict(
        model,
        state_dict,
        strict=False,
        assign=True,
    )
    missing = list(result.missing_keys)
    if ignored_missing_pattern is not None:
        missing = [key for key in missing if not re.search(ignored_missing_pattern, key)]
    if missing or result.unexpected_keys:
        raise RuntimeError(
            f"Checkpoint keys do not match {model_class.__name__}: "
            f"missing={missing}, unexpected={list(result.unexpected_keys)}"
        )

    if defer_text_encoder:
        _materialize_sam_audio_buffers(model, target_device)

    meta_tensors = [
        name
        for name, tensor in (*model.named_parameters(), *model.named_buffers())
        if tensor.is_meta
    ]
    if meta_tensors:
        raise RuntimeError(
            "Checkpoint left meta tensors unmaterialized: " + ", ".join(meta_tensors)
        )

    # T5 and other assets loaded by the constructor are not part of checkpoint.pt.
    # Move/cast those remaining parameters after assigning the mmap-backed weights.
    return model.to(device=target_device, dtype=dtype)


def _materialize_sam_audio_buffers(
    model: torch.nn.Module, target_device: torch.device
) -> None:
    """Rebuild SAM-Audio's four derived, non-checkpoint buffers after meta init."""
    with torch.device(target_device):
        vision_model = model.vision_encoder.model
        if vision_model.attn_mask is not None and vision_model.attn_mask.is_meta:
            vision_model.attn_mask = vision_model.build_causal_mask()

        rope = model.transformer.rope_embeddings
        if rope is not None and rope.freqs_cis.is_meta:
            rope.reset_parameters()

        time_embedder = model.transformer.t_embedder
        if time_embedder.freqs.is_meta:
            half = time_embedder.frequency_embedding_size // 2
            time_embedder.freqs = torch.exp(
                -math.log(10_000)
                * torch.arange(start=0, end=half, dtype=torch.float32)
                / half
            )

        positional_embedding = model.timestep_emb
        if positional_embedding.inv_freq.is_meta:
            half = positional_embedding.inv_freq.numel()
            positional_embedding.inv_freq = torch.exp(
                -math.log(10_000) * torch.arange(half).float() / half
            )


def _load_sam_audio_checkpoint(
    SAMAudio: Any,
    model_path: Path,
    target_device: torch.device = CPU_DEVICE,
    dtype: torch.dtype = torch.float32,
) -> Any:
    """Load local weights efficiently, with a compatibility path for test doubles."""
    model_kwargs = _sam_audio_model_kwargs(model_path)
    if (
        (model_path / "config.json").is_file()
        and (model_path / "checkpoint.pt").is_file()
        and hasattr(SAMAudio, "config_cls")
    ):
        config_overrides = {
            key: value
            for key, value in model_kwargs.items()
            if key not in {"map_location", "strict"}
        }
        return _load_local_checkpoint_efficient(
            SAMAudio,
            model_path,
            config_overrides=config_overrides,
            target_device=target_device,
            dtype=dtype,
            ignored_missing_pattern=(
                r"(^text_encoder|^visual_ranker|^text_ranker|^span_predictor)"
            ),
            defer_text_encoder=True,
        )

    try:
        return SAMAudio.from_pretrained(str(model_path), **model_kwargs)
    except TypeError as error:
        message = str(error)
        if not (
            "_from_pretrained()" in message
            and "proxies" in message
            and "resume_download" in message
        ):
            raise

        LOGGER.info(
            "Using SAM-Audio's legacy local-checkpoint loader with the current "
            "huggingface_hub API"
        )
        return SAMAudio._from_pretrained(
            model_id=str(model_path),
            revision=None,
            cache_dir=None,
            force_download=False,
            proxies=None,
            resume_download=False,
            local_files_only=True,
            token=None,
            **model_kwargs,
        )


class _LocalJudgeRanker(torch.nn.Module):
    """Tensor-native wrapper around Meta's official SAM-Audio Judge."""

    def __init__(self, model: torch.nn.Module, processor: Any):
        super().__init__()
        self.model = model
        self.processor = processor

    @torch.inference_mode()
    def forward(
        self,
        input_audio: list[torch.Tensor],
        extracted_audio: list[torch.Tensor],
        descriptions: list[str],
        sample_rate: int = 48_000,
        **_kwargs: Any,
    ) -> torch.Tensor:
        batch_size, candidates = len(input_audio), len(input_audio[0])
        inputs = [sample[None] for group in input_audio for sample in group]
        outputs = [sample[None] for group in extracted_audio for sample in group]
        repeated_text = [text for text in descriptions for _ in range(candidates)]
        processed = self.processor(
            text=repeated_text,
            input_audio=inputs,
            separated_audio=outputs,
            return_tensors="pt",
            padding=True,
            sampling_rate=sample_rate,
        )
        device = next(self.model.parameters()).device
        result = self.model(**processed.to(device))
        return result.overall.view(batch_size, candidates)


def _load_judge_ranker(dtype: torch.dtype) -> torch.nn.Module:
    source = Path(_cached_support_snapshot(SUPPORT_MODELS["sam-audio-judge"]))
    try:
        judge_module = importlib.import_module("sam_audio.model.judge")
        processor_module = importlib.import_module("sam_audio.processor")
        judge = _load_local_checkpoint_efficient(
            judge_module.SAMAudioJudgeModel,
            source,
            config_overrides={},
            target_device=torch.device("cpu"),
            dtype=dtype,
            use_meta_device=False,
        )
        processor = processor_module.SAMAudioJudgeProcessor.from_pretrained(str(source))
    except Exception as error:
        raise RuntimeError(
            f"Failed to load Meta's optional SAM-Audio Judge from {source}: "
            f"{type(error).__name__}: {error}"
        ) from error
    return _LocalJudgeRanker(judge.eval(), processor).eval()


def resolve_precision(
    precision: str, load_device: torch.device, model_management: Any
) -> torch.dtype:
    if precision not in PRECISIONS:
        raise ValueError(f"Unknown precision {precision!r}; choose one of {PRECISIONS}")
    if precision == "fp32":
        return torch.float32
    if precision == "bf16":
        if load_device.type == "cpu":
            raise RuntimeError("BF16 SAM-Audio inference requires a supported GPU")
        supports_dtype = getattr(model_management, "supports_dtype", None)
        if callable(supports_dtype) and not supports_dtype(load_device, torch.bfloat16):
            raise RuntimeError(f"BF16 is not supported on {load_device}")
        return torch.bfloat16

    should_use_bf16 = getattr(model_management, "should_use_bf16", None)
    if load_device.type != "cpu" and callable(should_use_bf16):
        try:
            if should_use_bf16(load_device):
                return torch.bfloat16
        except Exception:
            pass
    return torch.float32


def load_pipeline(
    model_name: str,
    folder_paths: Any,
    model_management: Any,
    model_patcher: Any,
    attention_backend: str = "pytorch",
    precision: str = "auto",
    initial_device: str = "cpu",
) -> SAMAudioPipeline:
    load_device = model_management.get_torch_device()
    validate_attention_backend(attention_backend, load_device)
    if initial_device not in INITIAL_DEVICES:
        raise ValueError(
            f"Unknown initial device {initial_device!r}; choose one of {INITIAL_DEVICES}"
        )
    if initial_device == "gpu" and load_device.type == "cpu":
        raise RuntimeError("Initial device 'gpu' was selected, but ComfyUI has no GPU device")
    dtype = resolve_precision(precision, load_device, model_management)
    checkpoint_device = (
        load_device
        if initial_device == "gpu" and load_device.type != "cpu"
        else torch.device("cpu")
    )
    model_path = resolve_model(model_name, folder_paths)
    SAMAudio, SAMAudioProcessor = import_sam_audio()

    LOGGER.info(
        "Loading SAM-Audio model from %s as %s on %s",
        model_path,
        str(dtype).removeprefix("torch."),
        checkpoint_device,
    )
    started = time.perf_counter()
    try:
        model = _load_sam_audio_checkpoint(
            SAMAudio,
            model_path,
            target_device=checkpoint_device,
            dtype=dtype,
        )
        LOGGER.info(
            "Loaded SAM-Audio checkpoint and required text encoder on %s in %.1f seconds",
            checkpoint_device,
            time.perf_counter() - started,
        )
        processor = SAMAudioProcessor.from_pretrained(str(model_path))
    except Exception as error:
        raise RuntimeError(
            f"Failed to load SAM-Audio from {model_path}: "
            f"{type(error).__name__}: {error}"
        ) from error

    model = model.eval()
    # BaseModel exposes device() as a method, while ComfyUI's ModelPatcher tracks
    # residency through a mutable model.device attribute. Upstream does not call
    # that helper internally, so adopting ComfyUI's convention is safe here.
    model.device = checkpoint_device
    offload_device = model_management.unet_offload_device()
    patcher = model_patcher.ModelPatcher(
        model, load_device=load_device, offload_device=offload_device
    )
    pipeline = SAMAudioPipeline(
        model=model,
        processor=processor,
        patcher=patcher,
        device=load_device,
        source=model_name,
        attention_backend=attention_backend,
        span_predictor_source=_configured_span_predictor(model_path),
        dtype=dtype,
    )
    if checkpoint_device == load_device and load_device.type != "cpu":
        # Register direct-to-GPU loads immediately so ComfyUI's unload controls own
        # the allocation even if a downstream node fails before inference starts.
        pipeline.load(model_management)
    return pipeline


def ode_options(inference_steps: int) -> dict[str, Any]:
    if inference_steps < 2 or inference_steps % 2:
        raise ValueError("inference_steps must be an even integer of at least 2")
    return {"method": "midpoint", "options": {"step_size": 2.0 / inference_steps}}


@contextlib.contextmanager
def seeded_inference(seed: int, device: torch.device) -> Iterator[None]:
    cuda_devices: list[int] = []
    if device.type == "cuda" and torch.cuda.is_available():
        cuda_devices = [device.index if device.index is not None else torch.cuda.current_device()]
    with torch.random.fork_rng(devices=cuda_devices):
        torch.manual_seed(seed)
        if device.type == "cuda" and torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        yield


def validate_spans(
    spans: tuple[SpanPrompt, ...],
    duration: float,
    *,
    hop_length: int | None = None,
    sample_rate: int | None = None,
) -> None:
    if not spans:
        raise ValueError("At least one span prompt is required")
    if not any(span.token == "+" for span in spans):
        raise ValueError("At least one positive span is required")
    for span in spans:
        if span.start < 0 or span.end <= span.start:
            raise ValueError(
                f"Invalid span {span.start:g}-{span.end:g}: end must be after start"
            )
        if span.end > duration + 1e-6:
            raise ValueError(
                f"Span ends at {span.end:g}s but the input audio is only {duration:.3f}s"
            )
        if hop_length is not None and sample_rate is not None:
            start_step = math.ceil(span.start * sample_rate / hop_length)
            end_step = math.ceil(span.end * sample_rate / hop_length)
            if start_step == end_step:
                resolution = hop_length / sample_rate
                raise ValueError(
                    f"Span {span.start:g}-{span.end:g}s is shorter than SAM-Audio's "
                    f"effective {resolution:.3f}s anchor resolution at that position"
                )

    for index, first in enumerate(spans):
        for second in spans[index + 1 :]:
            if first.token == second.token:
                continue
            if max(first.start, second.start) < min(first.end, second.end):
                raise ValueError(
                    "Positive and negative span prompts cannot overlap: "
                    f"{first.start:g}-{first.end:g}s and "
                    f"{second.start:g}-{second.end:g}s"
                )
