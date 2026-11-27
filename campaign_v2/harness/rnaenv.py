"""统一折叠环境（ViennaRNA 2.8.0 + Turner 2004 + 37 °C + Vienna 默认 dangles=2）。

所有验证都必须经过 `pin_env()`，并把 `provenance()` 写进结果文件。
不这样做，表里的数字就不可比 —— 见 baseline_plan.md §1。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys

import RNA

KT_37C = 0.6163207755023825  # kcal/mol, ViennaRNA 在 37 °C 的 kT

_PINNED = False


def pin_env(temperature: float = 37.0, dangles: int = 2, no_lonely_pairs: bool = False) -> None:
    """锁定能量模型。Turner 2004 是 ViennaRNA 2.x 的默认参数，这里显式加载以留痕。"""
    global _PINNED
    RNA.cvar.temperature = temperature
    RNA.cvar.dangles = dangles
    RNA.cvar.noLonelyPairs = 1 if no_lonely_pairs else 0
    load = getattr(RNA, "params_load_RNA_Turner2004", None)
    if load is not None:
        load()
    _PINNED = True


def model_details(temperature: float = 37.0, dangles: int = 2, no_lonely_pairs: bool = False):
    md = RNA.md()
    md.temperature = temperature
    md.dangles = dangles
    md.noLP = 1 if no_lonely_pairs else 0
    return md


def _git_head(path: str) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", path, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or None
    except Exception:
        return None


def provenance(extra: dict | None = None) -> dict:
    rec = {
        "rna_version": RNA.__version__,
        "energy_params": "Turner2004 (ViennaRNA 2.x default, 显式 params_load_RNA_Turner2004)",
        "temperature_C": float(RNA.cvar.temperature),
        "dangles": int(RNA.cvar.dangles),
        "noLonelyPairs": int(RNA.cvar.noLonelyPairs),
        "kT_kcal_per_mol": KT_37C,
        "pinned": _PINNED,
        "python": sys.version.split()[0],
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV"),
        "slurm_job": os.environ.get("SLURM_JOB_ID"),
        "harness_git": _git_head(os.path.dirname(os.path.abspath(__file__))),
    }
    if extra:
        rec.update(extra)
    return rec


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_provenance(path: str, extra: dict | None = None) -> dict:
    rec = provenance(extra)
    with open(path, "w") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
    return rec
