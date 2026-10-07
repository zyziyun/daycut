#!/usr/bin/env python3
"""Launch kit entry point for the recipe and the skill: the same CLI as ``python -m vstudio.launch``.

  python3 $VSTUDIO/workflows/launch-kit/scripts/launch_kit.py <step> launch.config.yaml [options]
  steps: features | capture | build | render | stills | copy | schedule | check | all   (see vstudio.launch)
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

from vstudio.launch.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
