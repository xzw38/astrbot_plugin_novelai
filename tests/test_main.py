import io
import json
import sys
import types
import unittest
import zipfile

try:
    import httpx
except ModuleNotFoundError:
    httpx = types.ModuleType("httpx")

    class Response:
        def __init__(self, status_code, content=b""):
            self.status_code = status_code
            self.content = content

        def json(self):
            return json.loads(self.content.decode("utf-8"))

        @property
        def text(self):
            return self.content.decode("utf-8", errors="replace")

    class HTTPError(Exception):
        pass

    class TimeoutException(HTTPError):
        pass

    httpx.Response = Response
    httpx.HTTPError = HTTPError
    httpx.TimeoutException = TimeoutException
    sys.modules["httpx"] = httpx

from main import (
    COMMAND_YUEGAO,
    DEFAULT_BASE_PROMPT,
    DEFAULT_NEGATIVE_PROMPT,
    GenerationConfig,
    NovelAIPluginError,
    build_novelai_payload,
    call_astrbot_llm,
    clean_translated_prompt,
    contains_cjk,
    extract_first_png,
    extract_images_from_zip,
    format_output_text,
    format_novelai_error,
    load_generation_config,
    parse_generation_request,
    resize_input_size,
    strip_nai_command,
    strip_yuegao_command,
)


class NovelAIPluginTests(unittest.TestCase):
    def test_parse_generation_request_with_options(self):
        request = parse_generation_request(
            '1girl, Cat_Ears --negative "bad hands" --width 1024 --height 1024 '
            "--steps 32 --scale 5.5 --seed 123 --sampler k_euler --model nai-test",
            GenerationConfig(),
        )

        self.assertEqual(request.prompt, f"1girl, cat ears, {DEFAULT_BASE_PROMPT}")
        self.assertEqual(request.negative_prompt, f"bad hands, {DEFAULT_NEGATIVE_PROMPT}")
        self.assertEqual(request.width, 1024)
        self.assertEqual(request.height, 1024)
        self.assertEqual(request.steps, 32)
        self.assertEqual(request.scale, 5.5)
        self.assertEqual(request.seed, 123)
        self.assertEqual(request.sampler, "k_euler")
        self.assertEqual(request.model, "nai-test")

    def test_load_generation_config_applies_defaults(self):
        config = load_generation_config({"auth_token": " token ", "width": 768})

        self.assertEqual(config.auth_token, "token")
        self.assertEqual(config.width, 768)
        self.assertEqual(config.height, 1216)
        self.assertEqual(config.model, "nai-diffusion-3")

    def test_invalid_size_is_rejected(self):
        with self.assertRaisesRegex(NovelAIPluginError, "64"):
            parse_generation_request("1girl --width 1000", GenerationConfig())

    def test_invalid_steps_are_rejected(self):
        with self.assertRaisesRegex(NovelAIPluginError, "steps"):
            parse_generation_request("1girl --steps 51", GenerationConfig())

    def test_resolution_alias_and_model_alias(self):
        request = parse_generation_request("1girl -r square -m nai-v3 -s k_euler_ancestral", GenerationConfig())

        self.assertEqual(request.width, 1024)
        self.assertEqual(request.height, 1024)
        self.assertEqual(request.model, "nai-diffusion-3")
        self.assertEqual(request.sampler, "k_euler_ancestral")

    def test_payload_uses_nai3_shape(self):
        request = parse_generation_request("1girl -m nai-v3 -s k_euler_a -C karras", GenerationConfig())
        payload = build_novelai_payload(request)

        self.assertEqual(payload["parameters"]["params_version"], 3)
        self.assertEqual(payload["parameters"]["noise_schedule"], "karras")
        self.assertEqual(payload["parameters"]["sampler"], "k_euler_ancestral")
        self.assertEqual(payload["parameters"]["ucPreset"], 2)
        self.assertFalse(payload["parameters"]["qualityToggle"])

    def test_payload_uses_nai4_shape(self):
        request = parse_generation_request("1girl -m nai-v4-full", GenerationConfig())
        payload = build_novelai_payload(request)

        self.assertEqual(payload["model"], "nai-diffusion-4-full")
        self.assertIn("v4_prompt", payload["parameters"])
        self.assertIn("v4_negative_prompt", payload["parameters"])

    def test_no_translator_option(self):
        request = parse_generation_request("1girl -T", GenerationConfig())

        self.assertTrue(request.no_translator)

    def test_img2img_payload_fields(self):
        request = parse_generation_request("1girl -N 0.6 -n 0.1", GenerationConfig())
        request.image_base64 = "abc"
        payload = build_novelai_payload(request)

        self.assertEqual(payload["parameters"]["image"], "abc")
        self.assertEqual(payload["parameters"]["strength"], 0.6)
        self.assertEqual(payload["parameters"]["noise"], 0.1)

    def test_iterations_batch_and_output(self):
        request = parse_generation_request("1girl -i 2 -b 3 -o verbose", GenerationConfig())
        payload = build_novelai_payload(request)

        self.assertEqual(request.iterations, 2)
        self.assertEqual(request.batch, 3)
        self.assertEqual(request.output_mode, "verbose")
        self.assertEqual(payload["parameters"]["n_samples"], 3)

    def test_total_images_limit(self):
        with self.assertRaisesRegex(NovelAIPluginError, "total images"):
            parse_generation_request("1girl -i 4 -b 4", GenerationConfig(max_total_images=8))

    def test_enhance_option(self):
        request = parse_generation_request("1girl -e", GenerationConfig())

        self.assertTrue(request.enhance)

    def test_resize_input_size(self):
        self.assertEqual(resize_input_size(1000, 1000), (512, 512))

    def test_contains_cjk(self):
        self.assertTrue(contains_cjk("一个女孩, cat ears"))
        self.assertFalse(contains_cjk("1girl, cat ears"))

    def test_clean_translated_prompt(self):
        self.assertEqual(clean_translated_prompt('Prompt: "1girl, cat ears"\n'), "1girl, cat ears")

    def test_call_astrbot_llm_uses_unified_msg_origin(self):
        calls = {}

        class Provider:
            async def text_chat(self, **kwargs):
                calls["kwargs"] = kwargs
                return types.SimpleNamespace(completion_text="1girl, cat ears")

        class Context:
            def get_using_provider(self, umo=None):
                calls["umo"] = umo
                return Provider()

        event = types.SimpleNamespace(unified_msg_origin="aiocqhttp:group:123")
        result = run_async(call_astrbot_llm(Context(), event, "translate"))

        self.assertEqual(result, "1girl, cat ears")
        self.assertEqual(calls["umo"], "aiocqhttp:group:123")
        self.assertEqual(calls["kwargs"]["prompt"], "translate")
        self.assertFalse(calls["kwargs"]["persist"])

    def test_extract_first_png_from_zip(self):
        image_bytes = b"\x89PNG\r\n\x1a\nfake"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("image_0.png", image_bytes)

        self.assertEqual(extract_first_png(buffer.getvalue()), image_bytes)
        self.assertEqual(extract_images_from_zip(buffer.getvalue()), [image_bytes])

    def test_extract_first_png_rejects_bad_zip(self):
        with self.assertRaisesRegex(NovelAIPluginError, "zip"):
            extract_first_png(b"not a zip")

    def test_format_auth_error(self):
        response = httpx.Response(401, content=b'{"message":"bad token"}')

        self.assertIn("auth failed", format_novelai_error(response))

    def test_format_rate_limit_error(self):
        response = httpx.Response(429, content=b"")

        self.assertIn("rate limit", format_novelai_error(response))

    def test_strip_commands(self):
        self.assertEqual(strip_nai_command("/nai draw 1girl"), "1girl")
        self.assertEqual(strip_nai_command("/nai img 1girl"), "1girl")
        self.assertEqual(strip_nai_command("/nai enhance 1girl"), "--enhance 1girl")
        self.assertEqual(strip_nai_command("nai draw 1girl"), "1girl")
        self.assertEqual(strip_nai_command("imagine 1girl"), "1girl")
        self.assertEqual(strip_yuegao_command(f"{COMMAND_YUEGAO} 1girl"), "1girl")

    def test_format_output_text(self):
        request = parse_generation_request("1girl -o verbose -x 1", GenerationConfig())

        text = format_output_text(request, 1, 2)

        self.assertIn("seed = 1", text)
        self.assertIn("model =", text)
        self.assertIn("prompt =", text)


if __name__ == "__main__":
    unittest.main()


def run_async(coro):
    import asyncio

    return asyncio.run(coro)
