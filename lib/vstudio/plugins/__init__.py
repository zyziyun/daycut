"""vstudio.plugins - Reelfold's plugin system: the batch orchestrator for video work, tools and agents plug in.

Three kinds (contract.py, API_VERSION 1): importers (external boards / projects -> Create shots), shot providers
(anything that makes a shot: Kling, MiniMax, Veo, Seedance, local runtimes, HyperFrames renders ...) and agent
runners (hand a job folder to Claude Code, Codex or any command; jobfolder.py is the protocol). Discovery, manifests
and on / off state: registry.py. Boards: board.py, importing.py. Parallel lanes: lanes.py.

    python -m vstudio.create plugins [list | enable KEY | disable KEY | set KEY --settings-json J]   KEY = <kind>:<id>
    python -m vstudio.create import PATH [--into EID] [--sniff]        python -m vstudio.create make EID [--lanes N]
Docs: docs/PLUGINS.md.
"""
from .contract import API_VERSION, KINDS  # noqa: F401
