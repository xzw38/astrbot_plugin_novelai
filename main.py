import argparse
import importlib
import io
import base64
import random
import shlex
import subprocess
import sys
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from astrbot.api import AstrBotConfig, logger
    from astrbot.api.event import AstrMessageEvent, filter
    from astrbot.api.star import Context, Star
except ImportError:  # Allows local tests without an AstrBot runtime.
    import logging

    AstrBotConfig = dict  # type: ignore
    AstrMessageEvent = Any  # type: ignore
    Context = Any  # type: ignore
    logger = logging.getLogger(__name__)

    class Star:  # type: ignore
        def __init__(self, context: Context):
            self.context = context

    class _Filter:  # type: ignore
        @staticmethod
        def command(_name: str):
            def decorator(func):
                return func

            return decorator

        @staticmethod
        def regex(_pattern: str):
            def decorator(func):
                return func

            return decorator

    filter = _Filter()


def ensure_httpx():
    try:
        return importlib.import_module("httpx")
    except ModuleNotFoundError:
        requirements = Path(__file__).with_name("requirements.txt")
        if not requirements.exists():
            raise
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-r", str(requirements)]
            )
        except Exception as exc:
            raise ModuleNotFoundError(
                "Missing dependency httpx and automatic installation failed. "
                "Run: pip install -r requirements.txt"
            ) from exc
        return importlib.import_module("httpx")


httpx = ensure_httpx()

try:
    from PIL import Image as PILImage
except ModuleNotFoundError:
    ensure_httpx()
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow>=10.0.0"])
    from PIL import Image as PILImage


COMMAND_YUEGAO = "\u7ea6\u7a3f"

DEFAULT_NEGATIVE_PROMPT = (
    "nsfw, lowres, {bad}, error, fewer, extra, missing, worst quality, "
    "jpeg artifacts, bad quality, watermark, unfinished, displeasing, "
    "chromatic aberration, signature, extra digits, artistic error, username, "
    "scan, [abstract]"
)
DEFAULT_BASE_PROMPT = "best quality, amazing quality, very aesthetic, absurdres"
DEFAULT_ENDPOINT = "https://image.novelai.net"
DEFAULT_MODEL = "nai-diffusion-3"
DEFAULT_SAMPLER = "k_euler_ancestral"
DEFAULT_SCHEDULER = "native"
MAX_STEPS = 50
MAX_RESOLUTION = 1920
OUTPUT_MODES = {"minimal", "default", "verbose"}


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}
    return bool(value)


def preview_text(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "..."

MODEL_MAP = {
    "safe": "safe-diffusion",
    "nai": "nai-diffusion",
    "furry": "nai-diffusion-furry",
    "nai-v3": "nai-diffusion-3",
    "nai-v4-curated-preview": "nai-diffusion-4-curated-preview",
    "nai-v4-full": "nai-diffusion-4-full",
}

ORIENT_MAP = {
    "landscape": {"width": 1216, "height": 832},
    "portrait": {"width": 832, "height": 1216},
    "square": {"width": 1024, "height": 1024},
}

NAI_SAMPLERS = {"k_euler_ancestral", "k_euler", "k_lms", "ddim", "plms"}
NAI3_SAMPLERS = {
    "k_euler",
    "k_euler_ancestral",
    "k_dpmpp_2s_ancestral",
    "k_dpmpp_2m",
    "k_dpmpp_sde",
    "ddim_v3",
}
NAI4_SAMPLERS = {
    "k_euler",
    "k_euler_ancestral",
    "k_dpmpp_2s_ancestral",
    "k_dpmpp_2m_sde",
    "k_dpmpp_2m",
    "k_dpmpp_sde",
}


class NovelAIPluginError(Exception):
    """User-facing error from local validation or NovelAI responses."""


@dataclass
class GenerationConfig:
    auth_token: str = ""
    endpoint: str = DEFAULT_ENDPOINT
    model: str = DEFAULT_MODEL
    sampler: str = DEFAULT_SAMPLER
    scheduler: str = DEFAULT_SCHEDULER
    width: int = 832
    height: int = 1216
    steps: int = 28
    scale: float = 5.0
    cfg_rescale: float = 0.0
    smea: bool = False
    smea_dyn: bool = False
    decrisper: bool = False
    auto_translate_prompt: bool = False
    translation_prompt: str = (
        "Translate the following NovelAI image prompt tags into concise English tags. "
        "Keep existing English tags, weights, brackets, braces, commas, and tag order. "
        "Return only the translated prompt, with no explanation:\n{prompt}"
    )
    quality_tags_enabled: bool = True
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    uc_preset_enabled: bool = True
    base_prompt: str = DEFAULT_BASE_PROMPT
    timeout_seconds: int = 120
    image_steps: int = 50
    strength: float = 0.7
    noise: float = 0.2
    output_mode: str = "default"
    max_iterations: int = 4
    max_batch: int = 4
    max_total_images: int = 8


@dataclass
class GenerationRequest:
    prompt: str
    negative_prompt: str
    model: str
    sampler: str
    scheduler: str
    width: int
    height: int
    steps: int
    scale: float
    seed: int
    cfg_rescale: float
    smea: bool
    smea_dyn: bool
    decrisper: bool
    no_translator: bool
    image_base64: str | None = None
    strength: float | None = None
    noise: float | None = None
    enhance: bool = False
    iterations: int = 1
    batch: int = 1
    output_mode: str = "default"
    translated_prompt: bool = False
    original_prompt: str | None = None


def load_generation_config(config: dict[str, Any] | None) -> GenerationConfig:
    config = config or {}
    return GenerationConfig(
        auth_token=str(config.get("auth_token", "")).strip(),
        endpoint=str(config.get("endpoint", DEFAULT_ENDPOINT)).strip().rstrip("/") or DEFAULT_ENDPOINT,
        model=str(config.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL,
        sampler=str(config.get("sampler", DEFAULT_SAMPLER)).strip() or DEFAULT_SAMPLER,
        scheduler=str(config.get("scheduler", DEFAULT_SCHEDULER)).strip() or DEFAULT_SCHEDULER,
        width=int(config.get("width", 832)),
        height=int(config.get("height", 1216)),
        steps=int(config.get("steps", 28)),
        scale=float(config.get("scale", 5.0)),
        cfg_rescale=float(config.get("cfg_rescale", 0.0)),
        smea=as_bool(config.get("smea", False)),
        smea_dyn=as_bool(config.get("smea_dyn", False)),
        decrisper=as_bool(config.get("decrisper", False)),
        auto_translate_prompt=as_bool(config.get("auto_translate_prompt", False)),
        translation_prompt=str(
            config.get(
                "translation_prompt",
                "Translate the following NovelAI image prompt tags into concise English tags. "
                "Keep existing English tags, weights, brackets, braces, commas, and tag order. "
                "Return only the translated prompt, with no explanation:\n{prompt}",
            )
        ),
        quality_tags_enabled=as_bool(config.get("quality_tags_enabled", True)),
        negative_prompt=str(config.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)).strip(),
        uc_preset_enabled=as_bool(config.get("uc_preset_enabled", True)),
        base_prompt=str(config.get("base_prompt", DEFAULT_BASE_PROMPT)).strip(),
        timeout_seconds=int(config.get("timeout_seconds", 120)),
        image_steps=int(config.get("image_steps", 50)),
        strength=float(config.get("strength", 0.7)),
        noise=float(config.get("noise", 0.2)),
        output_mode=str(config.get("output_mode", "default")).strip() or "default",
        max_iterations=int(config.get("max_iterations", 4)),
        max_batch=int(config.get("max_batch", 4)),
        max_total_images=int(config.get("max_total_images", 8)),
    )


def parse_generation_request(raw_args: str, config: GenerationConfig) -> GenerationRequest:
    parser = argparse.ArgumentParser(prog="nai draw", add_help=False)
    parser.add_argument("--negative", "--undesired", "-u", default="", dest="negative")
    parser.add_argument("--resolution", "-r", default=None)
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--steps", "-t", type=int, default=config.steps)
    parser.add_argument("--scale", "-c", type=float, default=config.scale)
    parser.add_argument("--seed", "-x", type=int, default=None)
    parser.add_argument("--sampler", "-s", default=config.sampler)
    parser.add_argument("--model", "-m", default=config.model)
    parser.add_argument("--scheduler", "-C", default=config.scheduler)
    parser.add_argument("--smea", "-S", action="store_true", default=config.smea)
    parser.add_argument("--smea-dyn", "-d", action="store_true", default=config.smea_dyn)
    parser.add_argument("--decrisper", "-D", action="store_true", default=config.decrisper)
    parser.add_argument("--enhance", "-e", action="store_true")
    parser.add_argument("--strength", "-N", type=float, default=None)
    parser.add_argument("--noise", "-n", type=float, default=None)
    parser.add_argument("--iterations", "-i", type=int, default=1)
    parser.add_argument("--batch", "-b", type=int, default=1)
    parser.add_argument("--output", "-o", default=config.output_mode)
    parser.add_argument("--no-translator", "-T", action="store_true")
    parser.add_argument("--override", "-O", action="store_true")
    parser.add_argument("prompt", nargs="*")

    try:
        namespace = parser.parse_args(shlex.split(raw_args))
    except ValueError as exc:
        raise NovelAIPluginError(f"Parameter parsing failed: {exc}") from exc
    except SystemExit as exc:
        raise NovelAIPluginError("Invalid parameters. Check width, height, steps, or option spelling.") from exc

    prompt = " ".join(namespace.prompt).strip()
    if not prompt:
        raise NovelAIPluginError("Please provide a prompt, for example: /nai draw 1girl, cat ears")

    width, height = resolve_size(namespace.resolution, namespace.width, namespace.height, config)
    steps = int(namespace.steps)
    scale = float(namespace.scale)
    model = resolve_model(namespace.model)
    sampler = sd2nai_sampler(str(namespace.sampler).strip(), model)

    validate_generation_options(width=width, height=height, steps=steps, scale=scale)
    iterations = int(namespace.iterations)
    batch = int(namespace.batch)
    output_mode = str(namespace.output).strip().lower() or config.output_mode
    validate_iteration_options(iterations, batch, output_mode, config)

    if namespace.override:
        prompt = normalize_prompt(prompt)
        negative_prompt = normalize_prompt(str(namespace.negative))
    else:
        base_prompt = normalize_prompt(config.base_prompt) if config.quality_tags_enabled else ""
        uc_preset = normalize_prompt(config.negative_prompt) if config.uc_preset_enabled else ""
        prompt = join_prompt(normalize_prompt(prompt), base_prompt)
        negative_prompt = join_prompt(normalize_prompt(str(namespace.negative)), uc_preset)

    seed = namespace.seed
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    if seed < 0 or seed > 2**32 - 1:
        raise NovelAIPluginError("seed must be between 0 and 4294967295.")

    return GenerationRequest(
        prompt=prompt,
        negative_prompt=negative_prompt,
        model=model,
        sampler=sampler,
        scheduler=str(namespace.scheduler).strip() or config.scheduler,
        width=width,
        height=height,
        steps=steps,
        scale=scale,
        seed=seed,
        cfg_rescale=config.cfg_rescale,
        smea=bool(namespace.smea),
        smea_dyn=bool(namespace.smea_dyn),
        decrisper=bool(namespace.decrisper),
        no_translator=bool(namespace.no_translator),
        strength=namespace.strength,
        noise=namespace.noise,
        enhance=bool(namespace.enhance),
        iterations=iterations,
        batch=batch,
        output_mode=output_mode,
    )


def resolve_size(
    resolution: str | None,
    width: int | None,
    height: int | None,
    config: GenerationConfig,
) -> tuple[int, int]:
    if resolution:
        source = resolution.strip().lower()
        if source in ORIENT_MAP:
            size = ORIENT_MAP[source]
            return size["width"], size["height"]
        delimiter = "x" if "x" in source else "\u00d7" if "\u00d7" in source else None
        if not delimiter:
            raise NovelAIPluginError("resolution must be portrait, landscape, square, or 1024x1024.")
        left, right = source.split(delimiter, 1)
        return closest_multiple(int(left)), closest_multiple(int(right))

    return int(width or config.width), int(height or config.height)


def closest_multiple(num: int, multiple: int = 64) -> int:
    floor = (num // multiple) * multiple
    ceil = ((num + multiple - 1) // multiple) * multiple
    closest = floor if num - floor < ceil - num else ceil
    return closest if closest > 0 else multiple


def resolve_model(model: str) -> str:
    model = str(model).strip() or DEFAULT_MODEL
    return MODEL_MAP.get(model, model)


def sd2nai_sampler(sampler: str, model: str) -> str:
    if sampler == "k_euler_a":
        return "k_euler_ancestral"
    if model == "nai-diffusion-3" and sampler in NAI3_SAMPLERS:
        return sampler
    if model in {"nai-diffusion-4-curated-preview", "nai-diffusion-4-full"} and sampler in NAI4_SAMPLERS:
        return sampler
    if sampler in NAI_SAMPLERS:
        return sampler
    return DEFAULT_SAMPLER


def normalize_prompt(prompt: str) -> str:
    return (
        prompt.strip()
        .replace("\uff0c", ",")
        .replace("\uff08", "(")
        .replace("\uff09", ")")
        .replace("\u300a", "<")
        .replace("\u300b", ">")
        .replace("_", " ")
        .lower()
    )


def contains_cjk(text: str) -> bool:
    return any(
        "\u3400" <= char <= "\u4dbf"
        or "\u4e00" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
        for char in text
    )


def clean_translated_prompt(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    for prefix in ("prompt:", "translated prompt:", "translation:"):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :].strip()
    return text.replace("\n", ", ").strip().strip('"')


async def call_astrbot_llm(context: Context, event: AstrMessageEvent, prompt: str) -> str:
    provider = None
    for getter_name in ("get_using_provider", "get_provider", "get_llm_provider"):
        getter = getattr(context, getter_name, None)
        if callable(getter):
            logger.debug("NovelAI auto-translate: trying provider getter %s", getter_name)
            maybe_provider = None
            if getter_name == "get_using_provider":
                umo = getattr(event, "unified_msg_origin", None)
                if umo:
                    try:
                        maybe_provider = getter(umo)
                    except TypeError:
                        try:
                            maybe_provider = getter(umo=umo)
                        except TypeError:
                            maybe_provider = getter()
                else:
                    maybe_provider = getter()
            else:
                maybe_provider = getter()
            provider = await maybe_provider if hasattr(maybe_provider, "__await__") else maybe_provider
            if provider:
                logger.debug(
                    "NovelAI auto-translate: provider selected via %s (%s)",
                    getter_name,
                    provider.__class__.__name__,
                )
                break
    if provider is None:
        raise NovelAIPluginError("Auto translation is enabled, but no AstrBot LLM provider is available.")

    for method_name in ("text_chat", "chat", "ask", "generate", "completion"):
        method = getattr(provider, method_name, None)
        if not callable(method):
            continue
        logger.debug("NovelAI auto-translate: calling provider.%s", method_name)
        try:
            if method_name == "text_chat":
                result = method(prompt=prompt, session_id=uuid.uuid4().hex, persist=False)
            else:
                result = method(prompt)
        except TypeError:
            try:
                result = method(prompt=prompt)
            except TypeError:
                continue
        result = await result if hasattr(result, "__await__") else result
        text = extract_llm_text(result)
        logger.debug("NovelAI auto-translate: raw LLM result preview=%s", preview_text(text))
        return text

    raise NovelAIPluginError("Auto translation is enabled, but this AstrBot provider has no supported text method.")


def extract_llm_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    for attr in ("completion_text", "result", "text", "content", "message"):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            return value
    if isinstance(result, dict):
        for key in ("completion_text", "result", "text", "content", "message"):
            value = result.get(key)
            if isinstance(value, str):
                return value
    return str(result)


async def maybe_translate_prompt(
    context: Context,
    event: AstrMessageEvent,
    request: GenerationRequest,
    config: GenerationConfig,
) -> GenerationRequest:
    has_cjk = contains_cjk(request.prompt)
    logger.debug(
        "NovelAI auto-translate check: enabled=%s no_translator=%s has_cjk=%s prompt=%s",
        config.auto_translate_prompt,
        request.no_translator,
        has_cjk,
        preview_text(request.prompt),
    )
    if not config.auto_translate_prompt:
        logger.debug("NovelAI auto-translate skipped: config disabled")
        return request
    if request.no_translator:
        logger.debug("NovelAI auto-translate skipped: command used -T/--no-translator")
        return request
    if not has_cjk:
        logger.debug("NovelAI auto-translate skipped: prompt has no CJK characters")
        return request

    translate_prompt = config.translation_prompt.replace("{prompt}", request.prompt)
    logger.info("NovelAI auto-translate: translating prompt via AstrBot LLM")
    logger.debug("NovelAI auto-translate prompt preview=%s", preview_text(translate_prompt))
    translated = clean_translated_prompt(await call_astrbot_llm(context, event, translate_prompt))
    if not translated:
        raise NovelAIPluginError("Auto translation returned an empty prompt.")

    logger.info("NovelAI auto-translate: prompt translated successfully")
    logger.debug("NovelAI auto-translate result preview=%s", preview_text(translated))
    request.original_prompt = request.prompt
    request.translated_prompt = True
    request.prompt = normalize_prompt(translated)
    return request


def validate_generation_options(width: int, height: int, steps: int, scale: float) -> None:
    for name, value in (("width", width), ("height", height)):
        if value <= 0 or value % 64 != 0:
            raise NovelAIPluginError(f"{name} must be a positive multiple of 64.")
        if value > MAX_RESOLUTION:
            raise NovelAIPluginError(f"{name} must not exceed {MAX_RESOLUTION}.")

    if steps <= 0 or steps > MAX_STEPS:
        raise NovelAIPluginError(f"steps must be between 1 and {MAX_STEPS}.")
    if scale <= 0:
        raise NovelAIPluginError("scale must be greater than 0.")


def validate_iteration_options(
    iterations: int,
    batch: int,
    output_mode: str,
    config: GenerationConfig,
) -> None:
    if iterations <= 0 or iterations > config.max_iterations:
        raise NovelAIPluginError(f"iterations must be between 1 and {config.max_iterations}.")
    if batch <= 0 or batch > config.max_batch:
        raise NovelAIPluginError(f"batch must be between 1 and {config.max_batch}.")
    if iterations * batch > config.max_total_images:
        raise NovelAIPluginError(f"total images must not exceed {config.max_total_images}.")
    if output_mode not in OUTPUT_MODES:
        raise NovelAIPluginError("output must be one of: minimal, default, verbose.")


def join_prompt(primary: str, secondary: str) -> str:
    parts = [part.strip() for part in (primary, secondary) if part and part.strip()]
    return ", ".join(parts)


def build_novelai_payload(request: GenerationRequest) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "params_version": 1,
        "width": request.width,
        "height": request.height,
        "scale": request.scale,
        "sampler": request.sampler,
        "steps": request.steps,
        "n_samples": request.batch,
        "ucPreset": 2,
        "qualityToggle": False,
        "seed": request.seed,
        "negative_prompt": request.negative_prompt,
        "dynamic_thresholding": request.decrisper,
    }
    if request.image_base64:
        parameters["image"] = request.image_base64
        parameters["strength"] = request.strength if request.strength is not None else 0.7
        parameters["noise"] = request.noise if request.noise is not None else 0.2

    is_nai3 = request.model == "nai-diffusion-3"
    is_nai4 = request.model in {"nai-diffusion-4-curated-preview", "nai-diffusion-4-full"}
    if is_nai3 or is_nai4:
        parameters.update(
            {
                "params_version": 3,
                "legacy": False,
                "legacy_v3_extend": False,
                "noise_schedule": request.scheduler,
            }
        )
        if parameters["scale"] > 10:
            parameters["scale"] = parameters["scale"] / 2

    if is_nai3:
        if request.sampler in {"k_euler_a", "k_dpmpp_2s_ancestral"} and parameters["noise_schedule"] == "karras":
            parameters["noise_schedule"] = "native"
        if request.sampler == "ddim_v3":
            parameters.pop("noise_schedule", None)
            parameters["sm"] = False
            parameters["sm_dyn"] = False
        else:
            parameters["sm_dyn"] = request.smea_dyn
            parameters["sm"] = request.smea or request.smea_dyn

    if is_nai4:
        parameters.update(
            {
                "add_original_image": True,
                "cfg_rescale": request.cfg_rescale,
                "characterPrompts": [],
                "controlnet_strength": 1,
                "deliberate_euler_ancestral_bug": False,
                "prefer_brownian": True,
                "reference_image_multiple": [],
                "reference_information_extracted_multiple": [],
                "reference_strength_multiple": [],
                "skip_cfg_above_sigma": None,
                "use_coords": False,
                "v4_prompt": {
                    "caption": {
                        "base_caption": request.prompt,
                        "char_captions": [],
                    },
                    "use_coords": False,
                    "use_order": True,
                },
                "v4_negative_prompt": {
                    "caption": {
                        "base_caption": request.negative_prompt,
                        "char_captions": [],
                    },
                },
            }
        )

    return {
        "input": request.prompt,
        "model": request.model,
        "action": "generate",
        "parameters": parameters,
    }


def extract_images_from_zip(zip_bytes: bytes) -> list[bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            image_names = [
                name
                for name in archive.namelist()
                if not name.endswith("/") and name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            ]
            if not image_names:
                raise NovelAIPluginError("NovelAI response did not contain an image file.")
            return [archive.read(name) for name in image_names]
    except zipfile.BadZipFile as exc:
        raise NovelAIPluginError("NovelAI response was not a valid image zip.") from exc


def extract_first_png(zip_bytes: bytes) -> bytes:
    return extract_images_from_zip(zip_bytes)[0]


class NovelAIClient:
    def __init__(self, config: GenerationConfig):
        self.config = config

    async def generate_images(self, request: GenerationRequest) -> list[bytes]:
        if not self.config.auth_token:
            raise NovelAIPluginError("Please configure NovelAI auth_token in AstrBot WebUI first.")

        headers = {
            "Authorization": f"Bearer {self.config.auth_token}",
            "Content-Type": "application/json",
            "Accept": "application/zip",
            "Referer": "https://novelai.net/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36"
            ),
        }
        payload = build_novelai_payload(request)
        logger.debug(
            "NovelAI request payload summary: endpoint=%s model=%s sampler=%s scheduler=%s size=%sx%s steps=%s scale=%s batch=%s img2img=%s enhance=%s",
            self.config.endpoint,
            request.model,
            request.sampler,
            request.scheduler,
            request.width,
            request.height,
            request.steps,
            request.scale,
            request.batch,
            bool(request.image_base64),
            request.enhance,
        )

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                logger.debug("NovelAI HTTP POST start: %s/ai/generate-image", self.config.endpoint)
                response = await client.post(
                    f"{self.config.endpoint}/ai/generate-image",
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise NovelAIPluginError("NovelAI request timed out. Try again later or increase timeout_seconds.") from exc
        except httpx.HTTPError as exc:
            raise NovelAIPluginError(f"NovelAI request failed: {exc.__class__.__name__}") from exc

        if response.status_code >= 400:
            logger.warning(
                "NovelAI HTTP error: status=%s content_type=%s body_preview=%s",
                response.status_code,
                response.headers.get("content-type", ""),
                preview_text(response.text[:500]),
            )
            raise NovelAIPluginError(format_novelai_error(response))

        images = extract_images_from_zip(response.content)
        logger.debug(
            "NovelAI HTTP success: status=%s zip_bytes=%s image_count=%s first_image_bytes=%s",
            response.status_code,
            len(response.content),
            len(images),
            len(images[0]) if images else 0,
        )
        return images

    async def generate_image(self, request: GenerationRequest) -> bytes:
        return (await self.generate_images(request))[0]


def format_novelai_error(response: httpx.Response) -> str:
    status_messages = {
        401: "NovelAI auth failed. Check auth_token.",
        402: "NovelAI token is unauthorized or may require an active subscription.",
        403: "NovelAI refused access. Check account permission or subscription status.",
        429: "NovelAI rate limit reached. Please try again later.",
    }
    if response.status_code in status_messages:
        return status_messages[response.status_code]
    if response.status_code >= 500:
        return f"NovelAI service is unavailable (HTTP {response.status_code}). Try again later."

    detail = ""
    try:
        data = response.json()
        detail = str(data.get("message") or data.get("error") or "")
    except ValueError:
        detail = response.text[:160].strip()
    suffix = f": {detail}" if detail else ""
    return f"NovelAI returned an error (HTTP {response.status_code}){suffix}"


def strip_nai_command(message: str) -> str:
    text = message.strip()
    for prefix in ("/nai", "nai", "/novelai", "novelai", "imagine"):
        if text == prefix:
            return ""
        if text.startswith(prefix + " "):
            text = text[len(prefix) :].strip()
            break
    if text.startswith("draw "):
        return text[len("draw ") :].strip()
    if text.startswith("img "):
        return text[len("img ") :].strip()
    if text.startswith("image "):
        return text[len("image ") :].strip()
    if text.startswith("enhance "):
        return "--enhance " + text[len("enhance ") :].strip()
    if text == "draw":
        return ""
    if text in {"img", "image"}:
        return ""
    if text == "enhance":
        return "--enhance"
    return text


def strip_yuegao_command(message: str) -> str:
    text = message.strip()
    if text.startswith(COMMAND_YUEGAO):
        return text[len(COMMAND_YUEGAO) :].strip()
    return text


async def write_temp_image(image_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(prefix="novelai_", suffix=".png", delete=False) as file:
        file.write(image_bytes)
        return file.name


def get_help_text() -> str:
    return (
        "NovelAI \u63d2\u4ef6\u5e2e\u52a9\n"
        "\n"
        "\u57fa\u7840\u753b\u56fe:\n"
        "/nai draw 1girl, cat ears\n"
        "/nai 1girl, cat ears\n"
        "\u7ea6\u7a3f \u4e00\u4e2a\u5973\u5b69, \u732b\u8033\n"
        "\n"
        "\u6539\u56fe/img2img: \u53d1\u9001\u56fe\u7247\u5e76\u9644\u5e26:\n"
        "/nai draw 1girl, cat ears -N 0.7 -n 0.2\n"
        "/nai img 1girl, different clothes\n"
        "\n"
        "\u589e\u5f3a/enhance: \u53d1\u9001 NovelAI \u751f\u6210\u56fe\u5e76\u9644\u5e26:\n"
        "/nai enhance masterpiece\n"
        "/nai draw masterpiece -e\n"
        "\n"
        "\u5e38\u7528\u53c2\u6570:\n"
        "-r \u5c3a\u5bf8 portrait/landscape/square/1024x1024\n"
        "-m \u6a21\u578b nai-v3/nai-v4-full\n"
        "-s \u91c7\u6837\u5668  -t \u6b65\u6570  -c scale  -x seed\n"
        "-u \u8d1f\u9762\u8bcd  -O \u4e0d\u8ffd\u52a0\u9ed8\u8ba4 prompt  -T \u8df3\u8fc7\u7ffb\u8bd1\n"
        "-N \u6539\u56fe\u5e45\u5ea6 strength  -n \u566a\u58f0 noise\n"
        "-i \u751f\u6210\u8f6e\u6570  -b \u6bcf\u8f6e\u5f20\u6570  -o minimal/default/verbose\n"
        "-S SMEA  -d SMEA DYN  -D Decrisper\n"
    )


def is_help_args(raw_args: str) -> bool:
    return raw_args.strip().lower() in {"help", "-h", "--help", "甯姪", "?"}


async def get_event_image_path(event: AstrMessageEvent) -> str | None:
    getter = getattr(event, "get_messages", None)
    messages = getter() if callable(getter) else getattr(getattr(event, "message_obj", None), "message", [])
    for comp in messages or []:
        if hasattr(comp, "convert_to_file_path") and (
            comp.__class__.__name__.lower() == "image" or getattr(comp, "type", None).__class__.__name__.lower() == "componenttype"
        ):
            try:
                return await comp.convert_to_file_path()
            except Exception:
                logger.exception("Failed to read input image from AstrBot event.")
                raise NovelAIPluginError("Failed to read the input image. Please make sure the platform image is accessible.")
    return None


def format_output_text(request: GenerationRequest, image_index: int, total_images: int) -> str:
    if request.output_mode == "minimal":
        return ""
    lines = [f"seed = {request.seed}"]
    if total_images > 1:
        lines.append(f"image = {image_index}/{total_images}")
    if request.output_mode == "verbose":
        lines.extend(
            [
                f"model = {request.model}",
                f"sampler = {request.sampler}",
                f"steps = {request.steps}",
                f"scale = {request.scale}",
                f"size = {request.width}x{request.height}",
            ]
        )
        if request.image_base64:
            lines.append(f"strength = {request.strength}")
            lines.append(f"noise = {request.noise}")
        if request.translated_prompt:
            lines.append("translated = yes")
            if request.original_prompt:
                lines.append(f"original prompt = {request.original_prompt}")
        lines.append(f"prompt = {request.prompt}")
        lines.append(f"negative = {request.negative_prompt}")
    return "\n".join(lines)


def prepare_input_image(path: str, request: GenerationRequest, config: GenerationConfig) -> None:
    with PILImage.open(path) as image:
        image = image.convert("RGB")
        width, height = image.size
        if request.enhance:
            if width + height != 1280:
                raise NovelAIPluginError("Enhance mode only supports NovelAI-generated images whose width plus height is 1280.")
            request.width = closest_multiple(int(width * 1.5))
            request.height = closest_multiple(int(height * 1.5))
            request.strength = request.strength if request.strength is not None else 0.2
            request.noise = request.noise if request.noise is not None else 0.0
        else:
            request.width, request.height = resize_input_size(width, height)
            request.strength = request.strength if request.strength is not None else config.strength
            request.noise = request.noise if request.noise is not None else config.noise
            request.steps = config.image_steps if request.steps == config.steps else request.steps
        validate_generation_options(request.width, request.height, request.steps, request.scale)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        request.image_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")


def resize_input_size(width: int, height: int) -> tuple[int, int]:
    max_area = 1048576
    if width % 64 == 0 and height % 64 == 0 and width * height <= max_area:
        return width, height
    aspect = width / height
    if aspect > 1:
        new_height = 512
        new_width = closest_multiple(int(new_height * aspect))
        if new_width * new_height <= max_area:
            return new_width, new_height
        new_width = 1024
        new_height = closest_multiple(int(new_width / aspect))
        return new_width, new_height
    new_width = 512
    new_height = closest_multiple(int(new_width / aspect))
    if new_width * new_height <= max_area:
        return new_width, new_height
    new_height = 1024
    new_width = closest_multiple(int(new_height * aspect))
    return new_width, new_height


class NovelAIPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = load_generation_config(dict(config or {}))
        logger.info(
            "NovelAI plugin loaded: endpoint=%s model=%s sampler=%s auto_translate=%s output=%s",
            self.config.endpoint,
            self.config.model,
            self.config.sampler,
            self.config.auto_translate_prompt,
            self.config.output_mode,
        )

    @filter.command("nai")
    async def nai(self, event: AstrMessageEvent):
        """NovelAI text-to-image: /nai draw <prompt>"""
        args = strip_nai_command(event.message_str)
        async for result in self._handle_draw(event, args):
            yield result

    @filter.command("novelai")
    async def novelai(self, event: AstrMessageEvent):
        """NovelAI text-to-image: /novelai <prompt>"""
        args = strip_nai_command(event.message_str)
        async for result in self._handle_draw(event, args):
            yield result

    @filter.command("imagine")
    async def imagine(self, event: AstrMessageEvent):
        """NovelAI text-to-image: imagine <prompt>"""
        args = strip_nai_command(event.message_str)
        async for result in self._handle_draw(event, args):
            yield result

    @filter.regex(r"^\u7ea6\u7a3f(\s+.+)?$")
    async def yuegao(self, event: AstrMessageEvent):
        """NovelAI text-to-image shortcut."""
        args = strip_yuegao_command(event.message_str)
        async for result in self._handle_draw(event, args):
            yield result

    async def _handle_draw(self, event: AstrMessageEvent, raw_args: str):
        image_path = ""
        try:
            logger.debug("NovelAI command received: raw_args=%s", preview_text(raw_args))
            if is_help_args(raw_args):
                logger.debug("NovelAI command handled as help")
                yield event.plain_result(get_help_text())
                return
            request = parse_generation_request(raw_args, self.config)
            logger.debug(
                "NovelAI command parsed: prompt=%s negative=%s model=%s sampler=%s output=%s iterations=%s batch=%s",
                preview_text(request.prompt),
                preview_text(request.negative_prompt),
                request.model,
                request.sampler,
                request.output_mode,
                request.iterations,
                request.batch,
            )
            request = await maybe_translate_prompt(self.context, event, request, self.config)
            logger.debug(
                "NovelAI prompt ready: translated=%s final_prompt=%s",
                request.translated_prompt,
                preview_text(request.prompt),
            )
            input_image_path = await get_event_image_path(event)
            if input_image_path:
                logger.debug("NovelAI input image detected: %s", input_image_path)
                prepare_input_image(input_image_path, request, self.config)
                logger.debug(
                    "NovelAI input image prepared: size=%sx%s strength=%s noise=%s",
                    request.width,
                    request.height,
                    request.strength,
                    request.noise,
                )
            elif request.enhance:
                raise NovelAIPluginError("Enhance mode requires one image in the message.")
            client = NovelAIClient(self.config)
            logger.info(
                "NovelAI image generation requested: model=%s size=%sx%s steps=%s seed=%s",
                request.model,
                request.width,
                request.height,
                request.steps,
                request.seed,
            )
            total_images = request.iterations * request.batch
            image_number = 1
            for iteration in range(1, request.iterations + 1):
                logger.debug("NovelAI generation iteration %s/%s seed=%s", iteration, request.iterations, request.seed)
                image_bytes_list = await client.generate_images(request)
                for image_bytes in image_bytes_list:
                    image_path = await write_temp_image(image_bytes)
                    output_text = format_output_text(request, image_number, total_images)
                    if output_text:
                        yield event.plain_result(output_text)
                    yield event.image_result(image_path)
                    try:
                        Path(image_path).unlink(missing_ok=True)
                    except OSError:
                        logger.warning("Failed to clean temporary image: %s", image_path)
                    image_path = ""
                    image_number += 1
                request.seed += request.batch
        except NovelAIPluginError as exc:
            yield event.plain_result(str(exc))
        except Exception as exc:
            logger.exception("NovelAI plugin failed to generate an image.")
            yield event.plain_result(f"Generation failed: {exc.__class__.__name__}")
        finally:
            if image_path:
                try:
                    Path(image_path).unlink(missing_ok=True)
                except OSError:
                    logger.warning("Failed to clean temporary image: %s", image_path)

    async def terminate(self):
        """AstrBot unload hook."""
