"""Isolated faster-whisper word timestamp adapter for Vistora."""

from __future__ import annotations

import argparse
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--trim-in", type=float, required=True)
    parser.add_argument("--trim-out", type=float, required=True)
    parser.add_argument("--speed", type=float, required=True)
    args = parser.parse_args()
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model)
    segments, _ = model.transcribe(args.audio, language=args.language.split("-", 1)[0], word_timestamps=True)
    words = []
    for segment in segments:
        for word in segment.words or ():
            if word.start is None or word.end is None or word.end <= args.trim_in or word.start >= args.trim_out:
                continue
            start = max(args.trim_in, float(word.start))
            end = min(args.trim_out, float(word.end))
            words.append({
                "text": word.word.strip(),
                "start_seconds": (start - args.trim_in) / args.speed,
                "end_seconds": (end - args.trim_in) / args.speed,
                "confidence": float(word.probability or 0),
            })
    print(json.dumps({"words": words}, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
