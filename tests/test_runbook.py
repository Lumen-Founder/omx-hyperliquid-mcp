"""The command lines in the public docs (README.md, docs/*.md) must match the real CLI and policy."""
import re
import shlex
from pathlib import Path

from omx import cli as cli_mod
from omx.audit import AuditLog
from omx.engine import Engine
from omx.policy import PolicyConfig
from omx.types import Algo, Intent, Side
from omx.venue.sim import SimConfig, SimVenue

from test_daemon import quiet

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md"))


def _command_lines():
    """Code lines that run the CLI: they start with `python -m omx.cli` (prose mentions are skipped)."""
    return [ln.strip() for p in DOCS for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith("python -m omx.cli ")]


def _argv(line):
    rest = re.search(r"omx\.cli\s+(.*)$", line).group(1).split("#")[0]
    rest = re.sub(r"<[^>]*>", "1", rest)
    return shlex.split(rest.replace("\\", "/"))


def test_docs_are_english_only():
    assert not [p.name for p in DOCS if p.stem.upper().endswith("_KO")]
    hangul = re.compile("[" + chr(0xAC00) + "-" + chr(0xD7A3) + "]")         # Hangul syllables
    assert not [p.name for p in DOCS if hangul.search(p.read_text(encoding="utf-8"))]


def test_every_documented_command_parses():
    lines = _command_lines()
    assert len(lines) >= 5, lines
    bad = []
    for line in lines:
        try:
            cli_mod._parser().parse_args(_argv(line))
        except SystemExit:
            bad.append(line)
    assert not bad, bad


def test_every_command_names_the_config_and_the_docs_cover_the_daemon_and_unkill():
    lines = _command_lines()
    assert lines and all("--config" in ln for ln in lines), lines
    assert any(_argv(ln)[-1] == "daemon" for ln in lines)
    assert any(_argv(ln)[-1] == "unkill" for ln in lines)
    assert any("I UNDERSTAND" in p.read_text(encoding="utf-8") for p in DOCS)


def test_resting_limit_at_99_3_pct_of_mid_passes_the_default_band(tmp_path):
    sim = SimVenue(SimConfig(seed=1), coins=quiet())
    eng = Engine(sim, PolicyConfig(min_day_ntl_usd=0.0, min_depth_usd=0.0), AuditLog(tmp_path / "a.jsonl"),
                 state_dir=tmp_path / "s")
    sim.advance(100)
    eng.step()
    mid = sim.snapshot("ETH").mid
    rep = eng.submit(Intent("hu-rb", "ETH", Side.BUY, 0.005, algo=Algo.LIMIT, limit_px=round(0.993 * mid, 1),
                            post_only=True))
    assert rep.state == "working", (rep.state, rep.block_reasons)
