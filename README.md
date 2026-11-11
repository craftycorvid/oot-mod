# Ultrawide Mod for The Legend of Zelda: Ocarina of Time (Nintendo Switch 2)

Play the Ocarina of Time remake in 21:9 or 32:9, or 16:10 (Steam Deck), on an emulator. The game renders a picture of your screen's shape, the 3D view gets a genuinely wider field of view on ultrawide screens, and the HUD and pre-rendered videos stay at their original 16:9 proportions, centred on screen.

Distributed as small IPS patches only. No game files are included.

## Versions

| Download | For screens | Target aspect | Game renders at |
| --- | --- | --- | --- |
| [`oot-ultrawide-21x9-3440x1440.zip`](releases/oot-ultrawide-21x9-3440x1440.zip) | 3440×1440 | 2.389 (43:18) | 3440×1440 |
| [`oot-ultrawide-21x9-2560x1080.zip`](releases/oot-ultrawide-21x9-2560x1080.zip) | 2560×1080 | 2.370 (64:27) | 2560×1080 |
| [`oot-ultrawide-21x9-5120x2160.zip`](releases/oot-ultrawide-21x9-5120x2160.zip) | 5120×2160 | 2.370 (64:27) | 3416×1440 |
| [`oot-super-ultrawide-32x9.zip`](releases/oot-super-ultrawide-32x9.zip) | 5120×1440, 3840×1080 | 3.556 (32:9) | 4096×1152 |
| [`oot-16x10.zip`](releases/oot-16x10.zip) | Steam Deck (1280×800), 1920×1200, 2560×1600 | 1.6 (16:10) | 2304×1440 |

Enable **only one** at a time, since they all patch the same code.

## Compatibility

- **Game:** The Legend of Zelda: Ocarina of Time, title ID `0400486024DEC000`
- **Executable:** `main` build ID `E0F3CCFAF50065AE4EA01EB5AEB13B1A45DA3348`. Other builds are not supported.
- **Tested on:** [Lichii](https://github.com/zortos293/Lichii) `nx2-build-88`. Works alongside Lichii's built-in "Max Resolution" and "Dynamic FPS" patches.

## Installation

1. Download the zip for your screen from [`releases/`](releases/).
2. In Lichii, right-click the game → **Properties → Add-Ons → Import Mod from ZIP**, select the zip and accept the suggested mod name. If you installed another version before, untick or delete it in the same list.
3. In the same Properties window, set **Graphics → Aspect Ratio → Stretch to Window** and play fullscreen.
   The game renders a picture of your screen's shape, so the emulator scales it without distorting it.
4. Restart the game. The emulator log should show `Applying IPS patch from mod "<mod name>"`.

For other emulators, or to install by hand, extract the zip into the emulator's `load/` directory. It contains `0400486024DEC000/<mod name>/exefs/E0F3CCFAF50065AE4EA01EB5AEB13B1A45DA3348.ips`.

## What it changes

- **Resolution:** the picture the game renders (2560×1440, and the 1920×1080 scene its upscaler takes in, 3/4 of it) takes your screen's shape, so the 3D and the HUD are not stretched. 3440×1440, 3416×1440 and 4096×1152 cost a bit more GPU time than the game's own picture; 2560×1080 and 2304×1440 (16:10) cost less. 5120×2160 screens get 3416×1440, which the emulator scales up. 32:9 renders 4096×1152 because a 5120×1440 picture ran out of the game's render-target memory and crashed.
- **3D:** every 16:9 camera projection is switched to the target aspect, so you see more to the sides instead of a stretched image. On a 16:10 screen the view keeps its height and is a little narrower than 16:9. The new aspect is written back to the camera, so other systems that read it (e.g. culling) see the wider view too. Non-16:9 views such as cubemaps are left alone.
- **HUD and menus:** full-screen 2D is drawn into the centre 16:9 area (a band across the middle of a 16:10 screen). Edge-anchored elements (hearts, buttons, minimap) sit at the edges of that area. Markers that track the 3D world, such as the Z-target reticle and NPC speech bubbles, stay in the right place. Menu backgrounds and fade transitions still cover the whole screen.
- **Pre-rendered videos:** drawn in the centre 16:9 area instead of being stretched.

## Known limitations

- Only the build ID above is supported. A game update will need new offsets.

## How it works

The patch places small ARM64 routines in unused executable padding after `.text` (`main+0x3C46800`, after the space Lichii's built-in patches use) and branches to them from nine hook sites. Each hook reruns the instruction it replaced and jumps back.

Six more words set the size of the picture: `main+0x1202EE0` and `main+0x31F39F4` build the picture's size (`mov x8, #2560`, then `movk x8, #1440, lsl #32` for the height) and `main+0x31F3A00` the scene's (`#1920`, `#1080`), which is 3/4 of the picture. These are the same constants NX2navi (`wide_out` / `wide_scene`) and Hookshot patch.

| Hook (`main+`) | Purpose |
| --- | --- |
| `0x3485CC0` | `sead::PerspectiveProjection::doUpdateMatrix`: if the aspect is within 0.01 of 16:9, use the target aspect and write it back to `mAspect` |
| `0x004F1E8`, `0x023B9A8`, `0x033B82C` | Inlined copies of the same matrix builder (the game mostly uses these) |
| `0x025D76C` | Render-view setup: the width/height aspect passed to shaders gets the same mapping |
| `0x0774368` | 2D canvas setup: if the projection is the full-screen 3840×2160 layout ortho, scale x by `(16/9) / target` (on 16:10, y by `target / (16/9)`). The backgrounds of the L/R item menu, pause menu and system menu are skipped, because they redraw a capture of the whole frame. So are the loading and cutscene fades, so they cover the whole screen |
| `0x3B5C758` | Movie layer draw: shrink the full-target viewport to the centre `(16/9) / target` of the width (on 16:10, the centre `target / (16/9)` of the height) |
| `0x020C2B0` | NPC speech bubble anchor: the layout x of the speaker (`ndc.x × 1920`) is divided by the HUD squeeze, so the bubble sits over the speaker. On 16:10 the hook is at `0x020C2B8` and divides the layout y (`ndc.y × 1080`) instead |
| `0x0C2A36C` | Graphics allocator setup: the render-target pool's initial size is doubled, as Lichii's "Texture Pool x2" fix (PR #976) does. The wider picture's render targets ran the stock pool out when an item was collected, and the game froze |

Offsets are module offsets. In the IPS32 files they are shifted by the `0x100`-byte NSO header. All routines only use registers that the original code overwrites immediately afterwards, or that are dead at that point.

## Building

`build.py` generates the three zips in `releases/` using only the Python 3 standard library. The zips are reproducible: rebuilding gives byte-identical files.

```sh
python3 build.py
```

To add another aspect ratio, add an entry to `VARIANTS` in `build.py`: mod name, zip file name, target aspect and the picture size to render, normally of the same shape.

If you have a decompressed image of the `main` module (module offset 0 = file offset 0), you can check every replaced instruction against it:

```sh
python3 build.py --verify-main /path/to/main.bin
```

## Disclaimer

This is an unofficial fan modification and is not affiliated with or endorsed by Nintendo. It contains no Nintendo code, assets, keys or executables. Use it with a legally obtained copy of the game, and back up your saves.
