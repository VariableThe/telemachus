# Telemachus Linux client

The Linux client for Telemachus. The Mac runs the host unchanged; this
receiver connects to it over the LAN, decodes the HEVC/H.264 stream with a
system `ffmpeg` subprocess, and presents it in an SDL2 window.

Target machine: Zorin OS 18.1 (Ubuntu 24.04 base), GNOME 46 on Wayland
(Mutter), Ryzen 9 4900H + Radeon Vega iGPU (VAAPI) and GTX 1660 Ti (NVDEC).
Target display: the external HP 22" 1920x1080@60.

## IMPORTANT: put the Mac in Wireless mode first

USB mode only accepts loopback connections (it is the `adb reverse` path for
Android). A Linux workstation on the LAN is a non-loopback client, so it is
rejected unless the Mac host is in **Wireless** mode with a matching token.

Mac-side steps:

1. Open Telemachus on the Mac.
2. Switch the transport/mode selector to **Wireless** (not USB).
3. Start streaming. The Mac shows a QR code containing
   `telemachus://HOST:PORT?t=TOKEN&name=NAME`.
4. On this machine, pair with `--qr` (below). Anyone holding that URI holds
   the credential until the token is reset on the Mac.

## Install

```bash
sudo apt update
sudo apt install ffmpeg libsdl2-2.0-0
pip install -r requirements.txt  # pysdl2; everything else is stdlib
```

VAAPI needs access to the render nodes:

```bash
ls -l /dev/dri/renderD*
sudo usermod -aG video,render "$USER"
# log out and back in, then verify:
groups | tr ' ' '\n' | grep -E '^(video|render)$'
```

`ffmpeg` must come from apt (not pip). If pysdl2 cannot find `libSDL2.so`,
install `libsdl2-2.0-0` (above); `pysdl2-dll` is only relevant outside Linux
distro packaging.

## Pairing

One-shot pairing from the Mac QR code:

```bash
./telemachus-linux --qr 'telemachus://192.168.1.50:54321?t=...&name=mac'
```

The token is saved to the config file at `~/.config/telemachus/client.conf`
(token file mode `0600`). Later runs reuse it:

```bash
./telemachus-linux
./telemachus-linux --host 192.168.1.50 --port 54321 --name zorin
```

Precedence: CLI flags > config file > defaults. `--qr` fills any of
host/port/token/name the CLI did not set explicitly.

## Running

```bash
./telemachus-linux --qr 'telemachus://...'      # first run (pairs + connects)
./telemachus-linux                              # later runs (uses saved config)
./telemachus-linux --display HP                 # force the external HP panel
./telemachus-linux --display 1920x1080@60      # same, by mode
./telemachus-linux --display 1                  # same, by SDL index
./telemachus-linux --windowed                   # window instead of fullscreen
./telemachus-linux --decoder vaapi|cuda|sw      # override auto (vaapi -> cuda -> sw)
./telemachus-linux --no-input                   # disable mouse forwarding
./telemachus-linux --hud                        # fps / Mbps / RTT overlay
./telemachus-linux --fake-payload               # synthetic frames, no Mac needed
./telemachus-linux --selftest                   # loopback mock-server pipeline test
```

Display selection: integer index, case-insensitive name substring, or
`WxH@Hz`. With no `--display` the client picks the 1920x1080@60 display,
which disambiguates the external HP (60 Hz) from the internal 144 Hz panel
without hardcoding Wayland connector names.

## HUD

`--hud` (or `F1` at runtime) shows fps / Mbps / RTT in the window title and
logs them about once a second. HUD rendering is deliberately title+log only
so no SDL_ttf dependency is needed.

## Input behavior

- The workstation mouse forwards as a type-2 touch **only while the SDL
  window has focus**.
- Left button: press = DOWN (action 0), drag = MOTION (action 1, throttled
  to ~120 Hz / 8 ms minimum interval), release = UP (action 2).
- Shift+left-drag (or right-drag) synthesises a two-finger gesture
  (`count=2` with `x2,y2` mirrored through the content-rect centre).
- Coordinates are normalised through the same letterbox content-rect math as
  Android's TouchMapper and clamped to 0..1; black-bar areas map to the
  edges, never outside.
- `--no-input` (or `input_enabled=false` in the config) disables forwarding.
- **No keyboard forwarding exists.** The wire protocol defines no keyboard
  message, and this client does not invent one.

## Troubleshooting

- **VAAPI missing -> CUDA -> software.** The client enumerates
  `/dev/dri/renderD*` and tries VAAPI, then NVDEC/CUDA, then software. Check
  which backend won in the log line `decoder backend=...`. Missing groups
  (`video`/`render`) is the usual VAAPI failure; a dead ffmpeg process
  triggers a forced keyframe request plus re-init automatically.
- **Wayland monitor selection.** If fullscreen lands on the wrong panel,
  pass `--display HP`, `--display 1920x1080@60`, or the SDL index explicitly.
  The default rule exists precisely because both panels are 1080p and only
  the refresh rate differs.
- **Token rejected.** Re-pair: put the Mac back in Wireless mode, start
  streaming for a fresh QR, reset the token on the Mac if one is stale, and
  re-run with the new `--qr` URI.
- **No display config.** The client waits ~15 s for the first display-config
  message; firewall rules or connecting while the Mac streams over USB
  (loopback-only) are the common causes.
- **Plaintext.** The token and the video travel unencrypted; use a trusted
  LAN or a direct Ethernet cable, never port-forward the listener.

## Explicit limitations (v1)

- No keyboard forwarding (no wire message for it).
- No audio forwarding.
- Plaintext token + video: trusted LAN / direct Ethernet only.
- `rotation != 0` is best-effort (ffmpeg transpose + a warning in the log).
- Single active client: connecting a second client evicts the first.
