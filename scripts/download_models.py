#!/usr/bin/env python3
"""Download the audio models used by the pipeline.

Run in the pipeline environment after accepting the pyannote model terms.
Supply a Hugging Face read token through HF_TOKEN. MEDISCRIBE_MODEL_CACHE
selects a shared cache directory.
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--whisper-model", default="turbo", help="openai-whisper model name (default: turbo)")
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "0")

    print(f"[1/5] whisper {args.whisper_model}", flush=True)
    import whisper

    whisper.load_model(args.whisper_model, device="cpu")

    print("[2/5] pyannote speaker-diarization-community-1", flush=True)
    from pyannote.audio import Pipeline

    last: Exception | None = None
    for repo in ("pyannote/speaker-diarization-community-1",
                 "pyannote-community/speaker-diarization-community-1"):
        try:
            Pipeline.from_pretrained(repo)
            last = None
            break
        except Exception as exc:  # noqa: BLE001 — try the mirror, then report
            last = exc
    if last is not None:
        print(f"pyannote download failed: {last}\n"
              "Accept the model terms on huggingface.co and set HF_TOKEN.", file=sys.stderr)
        return 1

    print("[3/5] MMS forced aligner (torchaudio)", flush=True)
    from torchaudio.pipelines import MMS_FA

    MMS_FA.get_model(with_star=False)

    print("[4/5] silero-vad", flush=True)
    from silero_vad import load_silero_vad

    load_silero_vad()

    print("[5/5] parakeet-tdt-0.6b-v3 (onnx)", flush=True)
    import onnx_asr

    onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3")

    print("All audio models are cached.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
