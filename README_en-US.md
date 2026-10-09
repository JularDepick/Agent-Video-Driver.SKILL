<div align="center">

# Agent-Video-Driver.SKILL

[![Version](https://img.shields.io/badge/Version-0.1.0-green)](https://github.com/JularDepick/Agent-Video-Driver.SKILL/tree/main)
[![Copyright](https://img.shields.io/badge/Copyright-JularDepick-0066AA)](./COPYRIGHT)
[![License](https://img.shields.io/badge/License-Apache--2.0-yellow)](./LICENSE)
[![Website](https://img.shields.io/badge/Website-online-38BDF8)](https://julardepick.github.io/Agent-Video-Driver.SKILL/)

[English] |
[简体中文](./README.md)

</div>

---

## What's this?

A SKILL that enables your Agent to generate videos using script-based tools, without the need for video models.

It uses no stock library and no editing software. The picture is computed frame by frame in code, the score is synthesized in code, and FFmpeg does the final encoding. The look comes from motion design, so every frame is reproducible and every beat cut is verifiable.

It covers general content: explainers, product promos, data animations, intros and outros, year-in-review pieces.

The core artifact is [`skills/agent-video-driver`](./skills/agent-video-driver), a SKILL bundle you can drop into your skills directory.

## Showcase

<https://julardepick.github.io/Agent-Video-Driver.SKILL/>

This 108-second explainer was made from scratch by the skill: the picture is computed frame by frame in code, the score is synthesized in code, and FFmpeg does the final encoding, with no video model involved. The video sits in the showcase section of the site; open the address above to play it.

## What it does

| Capability | Description |
|:---:|:---|
| Prompt scaffolding | One shared brief plus a seven-module prompt per stage (role / context / task / specs / style / avoid / check). Subagents receive only the brief and the current stage prompt, so their context stays clean |
| Content and compliance floor | Every fact traces to a source and is dropped otherwise, every asset license is checked by hand and credited, no AI-drawn faces and AI content is labelled, and the picture depends only on time with seeded randomness. Brand colours are measured rather than guessed, and every number on screen is reconciled against the code |
| Copy and pacing | Opening grammar, a quantified reading-speed model for on-screen text, narrative through-lines, and key lines landing on the bar where the music changes energy |
| Beat sync | Three layers of alignment (structure, events, sound effects), a per-beat duty table inside each segment, and two complementary verification methods: whole-film motion peaks and per-anchor frame pairs |
| Picture engine | Supersampled anti-aliased canvas, easing and beat primitives, font size solved from a target width, cap-height alignment, tracking and per-glyph stagger, landing impact, glow and additive bloom, reusable UI components |
| 3D and print | Pure-Python 3D point-cloud rendering with hidden-line engraving; a print and riso route with paper stock, halftone screens, separations, multiply overprint and misregistration |
| Look deck | 17 ready-to-apply looks drawn at random by default, with an exclude list for the previous film, and the drawn card written into the project as `STYLE.md` |
| Score engine | Orchestral and electronic voice libraries, a ten-section orchestration table against monotony, and a warm mastering chain that includes oversampled true-peak limiting |
| User-supplied music | Beat-grid detection, seamless-loop search, bar-accurate cutting with the grid preserved, and a re-measure of the grid afterwards |
| Vision-free verification | Character-map composition checks, before/after frame comparison, contact sheets, GIF motion previews, brightness calibration against a reference, glyph inspection, frame differencing, PSNR, and true peak measured back from the delivered file |
| Encoding | Frame encoding, mixdown, loudness normalisation, true-peak acceptance, stream and quality checks, in one command |
| Process safety gates | One consent gate before starting, then a separate one before the full render and before the final assembly; heavy steps probe cores, load, memory and disk first and run within the recommended limits instead of claiming every core |
| Project scaffolding | One command to start a project: create the tree, copy the scripts in as a self-contained set, generate four skeletons and fill in the top-level constants |

## Workflow

```
0 probe -> 1 brief and prompts -> 2 content and copy -> 3 look and storyboard
  -> 4 score first -> 5 segmented render -> 6 encode -> 7 objective acceptance
```

Each stage lands an inspectable artifact before the next one starts. The first three stages involve the user, either step by step or in a single confirmation pass.

Two delivery checkpoints are never skipped: the look is drawn from the deck by default and the drawn card is rendered on the first screen for the user to confirm, and a roughly ten-second opening preview is reviewed before the full render.

## Quick start

Open your agent in an empty directory and say:

```
Use the agent-video-driver skill to turn <your topic> into a <duration> video
```

The agent will first report the cost (tokens, intermediate frames, render time, machine load, exclusive use of the session) and ask for consent before probing the environment and writing the storyboard.
Before the full render, and again before the final assembly, it asks a second time and shows you the resource probe together with the limits it intends to use.

To walk through it by hand, run these from inside the skill directory:

```
python scripts/new_project.py ../my-video --bpm 100 --dur 108 --prefix proj
cd ../my-video
python scripts/style_lottery.py --write . --tone light
python scripts/check_env.py
python scripts/timing.py script.md --bpm 100 --bars 45
python scripts/orchestra.py 108 100 score.wav "7.2,16.8,26.4,36,50.4,64.8,79.2,91.2,103.2"
python scene_module.py probe
python scene_module.py plan
python scripts/resources.py --for render --frames 3240
python scene_module.py render 0 810
python scripts/resources.py --for encode --frames 3240 --out-dir out
pwsh -File scripts/assemble.ps1 -Frames temp\frames_proj -Audio audio\score.wav -Out out\final.mp4 -ProbeOnly
pwsh -File scripts/assemble.ps1 -Frames temp\frames_proj -Audio audio\score.wav -Out out\final.mp4 -ConfirmAssembly
python scripts/qa.py out/final.mp4 --plan temp/plan.json
```

`new_project.py` copies the scripts in as a self-contained set and generates four skeletons, so the rest runs from inside the project directory. When starting a project by hand, copy `script.md` and `scene_module.py` out of `templates/` before filling them in, as described in `templates/screen-script.md` and `templates/scene_module.py`.
On machines with only Windows PowerShell 5.1, replace `pwsh` with `powershell`; the script runs under both.

## Requirements

| Dependency | Used for | If missing |
|:---:|:---|:---|
| Python 3 | All scripts | Nothing runs |
| numpy | Background rendering, score synthesis, acceptance metrics | No rendering or synthesis |
| Pillow | Drawing and frame export | No rendering |
| FFmpeg and FFprobe | Encoding, mixdown, frame extraction, quality checks | No video output |
| CJK fonts | On-screen text | CJK glyphs render as tofu boxes |
| zstandard | Optional, token stats only | No cost caption in the end card |

The default route needs no browser, no Node.js and no stock library. `python scripts/check_env.py` reports item by item whether the current environment can run.

## Installation

Copy the whole [`skills/agent-video-driver`](./skills/agent-video-driver) directory into your skills directory. Discovery depth is one level.

You can also download `Agent-Video-Driver.SKILL.zip` from [Releases](https://github.com/JularDepick/Agent-Video-Driver.SKILL/releases); the `agent-video-driver/` it unpacks to is ready to use as is.

Or hand this line to any coding agent:

```
Install the agent-video-driver skill from https://github.com/JularDepick/Agent-Video-Driver.SKILL
```

## Repository layout

```
Agent-Video-Driver.SKILL/
├── .github/                    # GitHub Actions workflows
├── site/                       # Project site, see site/README.md
├── skills/
│   └── agent-video-driver/     # Core artifact, the skill bundle
├── COPYRIGHT                   # Copyright file
├── LICENSE                     # License file
├── README.md                   # Chinese README
└── README_en-US.md             # English README
```

Inside the skill:

```
agent-video-driver/
├── SKILL.md                    # Entry: consent gates, eight stages, content floor, engineering rules, acceptance
├── references/                 # Deeper documents, read on demand
├── scripts/                    # Scripts to reuse or copy
└── templates/                  # Skeletons and templates
```

Section ten of `SKILL.md` carries the reading order for the reference documents. Only that table defines the order, so no file name carries a number.

## Design tradeoffs

- **Code-rendered rather than generative**: the picture and the score are computed, so the same frame renders identically every time, beat cuts are quantifiable, and a change is a parameter change. The cost is a bounded visual range, unsuited to live-action footage or on-camera people
- **Score first**: fixing the music fixes the timeline, so picture cuts follow score cuts and no post-hoc alignment is needed
- **The look is drawn, not repeated**: the engine can make very different films but left to itself keeps making its loudest one, so the default is a draw from a deck with the previous card excluded, and more than half the deck is quiet
- **Verification without vision**: most agents cannot see what they rendered, so acceptance rests on quantifiable substitutes, and the agent states plainly that the look still needs human review
- **No external dependencies**: Python standard library plus numpy plus Pillow plus FFmpeg. Offline, version-controlled, no surprises

## Copyright

Copyright &copy; 2026 JularDepick

See [COPYRIGHT](./COPYRIGHT) for details.

## License

This repository uses the [Apache-2.0](./LICENSE) license.

## Links

- Open-source local-first conversational AI video editor with a multi-track timeline: https://github.com/0xsline/OpenChatCut/
- Agent skill that renders motion-graphic films from pure code: https://github.com/HRuiCcc/RuiC-motion-reel/
- Agent skill that turns one topic into a knowledge explainer video: https://github.com/Win-Hao/knowledge-video/
