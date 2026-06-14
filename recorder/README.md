# Meeting Ghost — Local Recorder

Records system audio (Teams call) on macOS via BlackHole + ffmpeg, then uploads the audio to the deployed agent and saves the generated report.

## One-time macOS setup

### 1. Install BlackHole 2ch and ffmpeg

```bash
brew install ffmpeg
brew install --cask blackhole-2ch
```

After installing BlackHole, log out and back in (or restart) so macOS registers the new audio device.

### 2. Create a Multi-Output Device (so you still hear the call)

1. Open **Audio MIDI Setup** (`/Applications/Utilities/Audio MIDI Setup.app`).
2. Click **+** at the bottom left → **Create Multi-Output Device**.
3. Tick both **BlackHole 2ch** and your speakers/headphones.
4. Right-click the new device → **Use This Device For Sound Output**.

Your speakers continue to play audio normally; BlackHole simultaneously captures everything for ffmpeg.

### 3. List available audio devices

Run this to find the exact device index/name recognised by ffmpeg:

```bash
ffmpeg -f avfoundation -list_devices true -i "" 2>&1 | grep -A 20 "AVFoundation audio"
```

Look for a line like `[0] BlackHole 2ch` or similar. The default argument `:BlackHole 2ch` (colon = audio-only, no video) usually works without the index.

## Running the recorder

Start the recorder before (or during) a Teams call:

```bash
python -m recorder.record \
  --agent-url https://<your-agent-endpoint>/invocations \
  --format docx \
  --title "Weekly sync" \
  --date "2026-06-14" \
  --token "<bearer-token-if-required>"
```

Press **Ctrl-C** to stop recording. The recorder will:
1. Terminate ffmpeg cleanly.
2. Read the captured `.wav` file.
3. Base64-encode the audio and POST it to the agent.
4. Save the returned report file (`.docx` or `.pdf`) in the current directory.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--device` | `:BlackHole 2ch` | avfoundation audio device string |
| `--agent-url` | *(required)* | Full URL of the agent `/invocations` endpoint |
| `--format` | `docx` | Output report format: `docx` or `pdf` |
| `--title` | *(optional)* | Meeting title embedded in the report |
| `--date` | *(optional)* | Meeting date (YYYY-MM-DD) embedded in the report |
| `--token` | *(optional)* | Bearer token for the agent endpoint |

## Troubleshooting

- **No audio captured / silent file** — confirm BlackHole is set as the system output device in System Settings → Sound → Output.
- **Teams audio not captured** — some versions of Teams use its own audio engine. Try setting BlackHole as the default output in System Settings before joining the call.
- **ffmpeg not found** — ensure `/usr/local/bin` or `/opt/homebrew/bin` is in your `PATH`.
