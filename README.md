# astrbot_plugin_novelai

AstrBot 的 NovelAI 图片生成插件，支持文生图、改图、增强、批量生成和中文 prompt 自动翻译。

## 安装

推荐从 AstrBot WebUI 添加插件源后安装：

```text
https://raw.githubusercontent.com/xzw38/astrbot_plugin_novelai/master/plugins.json
```

手动安装时，把本仓库放到：

```text
data/plugins/astrbot_plugin_novelai
```

然后在 AstrBot WebUI 重载插件，并在插件设置里填写 `auth_token`。Token 只填本体，不要带 `Bearer ` 前缀。`endpoint` 建议保持默认：

```text
https://image.novelai.net
```

依赖会在插件加载时自动安装。如果自动安装失败，再手动执行：

```bash
pip install -r data/plugins/astrbot_plugin_novelai/requirements.txt
```

## 常用命令

```text
/nai help
/nai draw 1girl, cat ears, blue eyes
/nai 1girl, cat ears, blue eyes
/novelai 1girl, cat ears, blue eyes
imagine 1girl, cat ears, blue eyes
约稿 1girl, cat ears, blue eyes
```

## 参数示例

```text
/nai draw 1girl -r square -m nai-v3 -s k_euler_a -C native
/nai draw 1girl --width 1024 --height 1024 -t 32 -c 5.5 -x 123
/nai draw 1girl -u "bad hands, extra fingers"
/nai draw 1girl -O
/nai draw 1girl -S -d -D
/nai draw "一个女孩，猫耳，蓝眼睛"
/nai draw "一个女孩，猫耳" -T
/nai draw 1girl -i 2 -b 3 -o verbose
```

- `-r` / `--resolution`：尺寸，支持 `portrait`、`landscape`、`square` 或 `1024x1024`。
- `--width` / `--height`：自定义宽高，必须是 64 的倍数。
- `-t` / `--steps`：生成步数。
- `-c` / `--scale`：提示词引导强度。
- `-x` / `--seed`：随机种子。
- `-s` / `--sampler`：采样器。
- `-m` / `--model`：模型或别名，例如 `nai-v3`、`nai-v4-full`。
- `-C` / `--scheduler`：调度器。
- `-u` / `--negative` / `--undesired`：负面提示词。
- `-O` / `--override`：本次不追加默认正向质量词和默认 UC。
- `-T` / `--no-translator`：本次跳过自动翻译。
- `-N` / `--strength`：改图幅度。
- `-n` / `--noise`：改图噪声。
- `-e` / `--enhance`：增强模式。
- `-i` / `--iterations`：生成轮数。
- `-b` / `--batch`：每轮张数。
- `-o` / `--output`：输出模式，支持 `minimal`、`default`、`verbose`。
- `-S`、`-d`、`-D`：SMEA、SMEA DYN、Decrisper。

## 质量词和 UC

默认会追加两类词：

- `base_prompt`：默认正向质量词，会追加到 prompt 末尾。
- `negative_prompt`：默认 UC / 负面词，会追加到负面提示词里。

这部分参考 `koishijs/novelai-bot`：API payload 保持 `qualityToggle=false`、`ucPreset=2`，再由插件自己追加可配置的质量词和 UC，避免 NovelAI API 隐藏重复追加。

设置里对应：

- `quality_tags_enabled`：类似 NovelAI Web 的 `Quality Tags Enabled`。
- `uc_preset_enabled`：类似 NovelAI Web 的 `UC Preset Enabled`。

单次完全自己控制 prompt 和 UC 时使用：

```text
/nai draw 1girl -u "bad hands" -O
```

## 批量和输出

```text
/nai draw 1girl -i 3
/nai draw 1girl -b 4
/nai draw 1girl -i 2 -b 3 -o verbose
```

`iterations * batch` 会受到设置里的 `max_total_images` 限制。

输出模式：

- `minimal`：只发图片。
- `default`：发送 seed 和图片。
- `verbose`：发送 seed、模型、采样器、步数、scale、尺寸、prompt、负面词和图片。

## 改图

发送或回复一张图片，再附带命令：

```text
/nai draw 1girl, new clothes -N 0.7 -n 0.2
/nai img 1girl, different hairstyle
```

消息里带图片时，插件会自动走 NovelAI img2img。

## 增强

发送 NovelAI 生成图并附带：

```text
/nai enhance masterpiece
/nai draw masterpiece -e
```

增强模式参考 `koishijs/novelai-bot`：适合宽高之和为 `1280` 的 NovelAI 生成图，输出约 1.5 倍尺寸。

## 自动翻译

开启 `auto_translate_prompt` 后，包含中文的 prompt 会先交给 AstrBot 当前接入的 LLM 翻译成英文标签，再发给 NovelAI。

默认翻译模板：

```text
Translate the following NovelAI image prompt tags into concise English tags. Keep existing English tags, weights, brackets, braces, commas, and tag order. Return only the translated prompt, with no explanation:
{prompt}
```

可以修改模板，但必须保留 `{prompt}`。

如需单次跳过翻译：

```text
/nai draw "一个女孩，猫耳" -T
```

用 `-o verbose` 可以确认是否翻译成功；成功时会出现：

```text
translated = yes
original prompt = ...
prompt = ...
```

## 与 koishijs/novelai-bot 的关系

本插件不是直接依赖 Koishi 插件，而是参考并移植其成熟行为：

- 模型别名；
- 横竖图尺寸；
- 短参数；
- 默认正向词和 UC；
- NovelAI v3/v4 payload；
- zip 图片解析；
- img2img 和 enhance。

## English Short Guide

This is a NovelAI image generation plugin for AstrBot. Configure `auth_token`, keep `endpoint` as `https://image.novelai.net`, then use `/nai draw <prompt>`.

Common commands:

```text
/nai help
/nai draw 1girl, cat ears
/nai draw 1girl -u "bad hands"
/nai draw 1girl -i 2 -b 3 -o verbose
```

## 测试

```bash
python -m unittest discover -s tests
python -m py_compile main.py
```
