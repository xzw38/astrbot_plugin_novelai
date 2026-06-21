# astrbot_plugin_novelai

NovelAI image generation plugin for AstrBot.

## Install

1. Put this repository at `data/plugins/astrbot_plugin_novelai`.
2. Reload plugins in AstrBot WebUI.
3. Configure `auth_token`. Paste only the token value, without `Bearer `.
4. Keep `endpoint` as `https://image.novelai.net` unless you know you need a custom endpoint.
5. Open plugin Pages -> `usage` for the built-in Chinese guide.
6. Dependencies are installed automatically on plugin load. If pip is unavailable, run:

```bash
pip install -r data/plugins/astrbot_plugin_novelai/requirements.txt
```

## Commands

```text
/nai help
/nai draw 1girl, cat ears, blue eyes
/nai 1girl, cat ears, blue eyes
/novelai 1girl, cat ears, blue eyes
imagine 1girl, cat ears, blue eyes
约稿 1girl, cat ears, blue eyes
```

## Options

```text
/nai draw 1girl -r square -m nai-v3 -s k_euler_a -C native
/nai draw 1girl --width 1024 --height 1024 -t 32 -c 5.5 -x 123
/nai draw 1girl -u "bad hands, extra fingers"
/nai draw 1girl -O
/nai draw 1girl -S -d -D
/nai draw 一个女孩，猫耳，蓝眼睛
/nai draw 一个女孩，猫耳 -T
/nai draw 1girl -i 2 -b 3 -o verbose
```

- `--resolution` / `-r`: `portrait`, `landscape`, `square`, or `1024x1024`.
- `--width` / `--height`: custom size, both must be multiples of 64.
- `--steps` / `-t`: generation steps.
- `--scale` / `-c`: prompt guidance.
- `--seed` / `-x`: random seed.
- `--sampler` / `-s`: NovelAI sampler.
- `--model` / `-m`: model or alias such as `nai-v3`, `nai-v4-full`.
- `--scheduler` / `-C`: NovelAI scheduler.
- `--negative`, `--undesired`, `-u`: negative prompt.
- `--override` / `-O`: do not append configured base and negative prompts.
- `--no-translator` / `-T`: skip LLM prompt translation once.
- `--strength` / `-N`: img2img strength.
- `--noise` / `-n`: img2img noise.
- `--enhance` / `-e`: enable enhance mode when an image is attached.
- `--iterations` / `-i`: generation rounds.
- `--batch` / `-b`: images per round.
- `--output` / `-o`: `minimal`, `default`, or `verbose`.
- `--smea` / `-S`, `--smea-dyn` / `-d`, `--decrisper` / `-D`: NovelAI advanced toggles.

## Batch and Output Mode

```text
/nai draw 1girl -i 3
/nai draw 1girl -b 4
/nai draw 1girl -i 2 -b 3 -o verbose
```

`iterations * batch` is limited by `max_total_images` in plugin settings.

Output modes:

- `minimal`: image only.
- `default`: seed and image.
- `verbose`: seed, model, sampler, steps, scale, size, prompt, negative prompt, and image.

## Image-to-Image

Attach or reply with an image, then send:

```text
/nai draw 1girl, new clothes -N 0.7 -n 0.2
/nai img 1girl, different hairstyle
```

When an image is present, the plugin sends it as NovelAI img2img input.

## Enhance

Attach a NovelAI-generated image and use:

```text
/nai enhance masterpiece
/nai draw masterpiece -e
```

Like `koishijs/novelai-bot`, enhance expects a generated image whose width plus height is `1280`, then outputs at `1.5x` size.

## Auto Translation

Set `auto_translate_prompt` to `true` to let the configured AstrBot LLM translate prompts containing Chinese characters before sending them to NovelAI.

Default template:

```text
Translate the following NovelAI image prompt tags into concise English tags. Keep existing English tags, weights, brackets, braces, commas, and tag order. Return only the translated prompt, with no explanation:
{prompt}
```

You can edit this template in plugin settings, but keep `{prompt}`.

Use `-T` when one request should keep the original prompt:

```text
/nai draw 一个女孩，猫耳 -T
```

## Koishi Reference

This plugin reuses the mature behavior of `koishijs/novelai-bot` where it fits AstrBot:

- model aliases;
- orientation sizes;
- short option names;
- default base and undesired prompts;
- NovelAI v3/v4 payload shape;
- zip response handling;
- img2img and enhance behavior.

## Test

```bash
python -m unittest discover -s tests
python -m py_compile main.py
```
