"""Convert the recorded Playwright video of the first E2E test into docs/assets/demo.gif.

Usage: LETRANIX_VIDEO=1 LETRANIX_SCREENSHOTS=1 npx playwright test, then
python scripts/make_demo_gif.py. Requires ffmpeg on PATH. The GIF is a speed-up
of a real recorded run, not a mock-up.
"""

import shutil
import subprocess  # nosec B404 - fixed ffmpeg invocation on local files
import sys
from pathlib import Path

videos = sorted(Path("test-results").glob("*import-OCR*/video.webm"))
if not videos:
    sys.exit("No recorded video found; run Playwright with LETRANIX_VIDEO=1 first")
ffmpeg = shutil.which("ffmpeg")
if not ffmpeg:
    sys.exit("ffmpeg not found")
out = Path("docs/assets/demo.gif")
filters = "setpts=0.4*PTS,fps=6,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(videos[-1]), "-vf", filters, str(out)], check=True)  # nosec B603
print(f"{out} {out.stat().st_size / 1e6:.1f} MB")
