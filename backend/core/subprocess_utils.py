"""Windowed Windows apps must not inherit invalid console handles or flash a console."""
import os
import subprocess


def hidden_process_options():
    return {"stdin": subprocess.DEVNULL,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})}
