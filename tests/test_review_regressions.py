"""Regressions for open review items re-checked for v0.1.9.

F5b (concurrent submits exceed a coin cap): the Engine is single-threaded by contract. The daemon
enforces that (OwnedEngine, tests/test_daemon.py), and the in-process paths (demo, paper, tests)
reach the engine only through AgentGateway, whose lock serialises every call. Here two agent
submits race through one gateway while the venue is slow to place, and the coin cap still holds.
"""
import threading
import time

from omx.approvals import AgentBudget, ApprovalQueue
from omx.audit import AuditLog
from omx.engine import Engine
from omx.mcp_server import AgentGateway
from omx.venue.sim import SimConfig, SimVenue

from test_daemon import quiet
from test_mcp import call, make_cfg, make_eligible


class SlowPlaceSim(SimVenue):
    """A venue whose place() takes 0.3 s (signing + HTTP round trip) and says when it is inside."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.in_place = threading.Event()

    def place(self, child):
        self.in_place.set()
        time.sleep(0.3)
        return super().place(child)


def test_F5b_concurrent_agent_submits_through_the_gateway_keep_the_coin_cap(tmp_path):
    cfg = make_cfg(tmp_path, **{"default_coin_notional_usd = 10000.0": "default_coin_notional_usd = 5000.0",
                                "approval_above_usd = 1000.0": "approval_above_usd = 10000.0",
                                "daily_budget_usd = 5000.0": "daily_budget_usd = 50000.0"})
    assert cfg.policy.default_coin_notional_usd == 5000.0
    make_eligible(cfg.state_dir)
    audit = AuditLog(cfg.audit_path)
    sim = SlowPlaceSim(SimConfig(seed=1, start_equity_usd=1e5), coins=quiet())
    eng = Engine(sim, cfg.policy, audit, state_dir=cfg.state_dir)
    sim.advance(100)
    eng.step()
    gw = AgentGateway(eng, cfg, ApprovalQueue(cfg.state_dir, audit), AgentBudget(cfg.state_dir, 50000.0), audit)
    results, errs = [], []

    def sub():
        try:
            results.append(call(gw, "submit_order", {"coin": "ETH", "side": "buy", "size": 1.0, "algo": "market"}))
        except Exception as e:  # noqa: BLE001
            errs.append(repr(e))

    a = threading.Thread(target=sub)
    a.start()
    assert sim.in_place.wait(5)                       # the first submit is inside place() now
    b = threading.Thread(target=sub)
    b.start()
    a.join(10)
    b.join(10)
    for _ in range(10):
        sim.advance(100)
        eng.step()
    pos = sim.account().position("ETH")
    assert not errs and len(results) == 2, (errs, results)
    assert pos * 3000 <= 5000 + 1e-6, f"coin cap 5000 USD, position {pos} ETH; {results}"
