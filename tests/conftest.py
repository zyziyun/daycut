"""Run every test against persona.example.yaml defaults, never the creator's private persona.local.yaml."""
import os

os.environ["VSTUDIO_DEFAULT_PERSONA"] = "1"
