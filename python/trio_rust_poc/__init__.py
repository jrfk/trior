"""Experimental, process-wide Trio 0.35.0 scheduler adapter.

This is an experiment, not a supported Trio backend. It changes only the
runnable-batch loop; Python remains responsible for I/O, timers, Task objects,
Nursery, CancelScope, and the outer scheduler. Activate once before trio.run.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import pathlib
import sys

import trio
from trio._core import _run

_EXPECTED_RUN_SHA256 = "0354771966e15f5549a6d6b3cfaba8b666a429712c54af367c368c27c8edcb7b"
_active: str | None = None
_original = _run.unrolled_run


def activate(mode: str = "rust") -> None:
    """Select python, python-batch, rust, rust-opt, or rust-fast."""
    global _active
    if mode not in ("python", "python-batch", "rust", "rust-opt", "rust-fast"):
        raise ValueError(f"unknown backend {mode!r}")
    if _active is not None:
        if _active != mode:
            raise RuntimeError("Use a fresh process to select a different backend")
        return
    if trio.__version__ != "0.35.0":
        raise RuntimeError("This experiment requires Trio 0.35.0 exactly")
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("This prototype is limited to CPython 3.12")
    if trio.lowlevel.in_trio_run():
        raise RuntimeError("Activate before entering Trio")
    source_path = pathlib.Path(_run.__file__)
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if digest != _EXPECTED_RUN_SHA256:
        raise RuntimeError(f"Unexpected Trio source hash: {digest}")
    if mode == "python":
        _active = mode
        return

    source, start_line = inspect.getsourcelines(_original)
    tree = ast.parse("".join(source))
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    loops = [n for n in ast.walk(fn)
             if isinstance(n, ast.While) and isinstance(n.test, ast.Name)
             and n.test.id == "batch"]
    if len(loops) != 1:
        raise RuntimeError("Expected one runnable batch loop")
    batch_loop = loops[0]

    # Compile the identical body as a Python control for the extra call boundary.
    helper = ast.parse("@enable_ki_protection\ndef _poc_python_batch(runner, batch):\n    pass\n").body[0]
    helper.body = [copy.deepcopy(batch_loop)]
    helper_tree = ast.Module(body=[helper], type_ignores=[])
    ast.fix_missing_locations(helper_tree)
    ast.increment_lineno(helper_tree, start_line - 1)
    exec(compile(helper_tree, str(source_path), "exec"), _run.__dict__)

    if mode == "python-batch":
        _run._poc_run_batch = _run._poc_python_batch
    else:
        from . import _native
        # Bind the original module as a third argument with a C-implemented
        # partial, avoiding an extra Python frame around every Rust call.
        from functools import partial
        native_fn = {"rust": _native.run_batch, "rust-opt": _native.run_batch_opt,
                     "rust-fast": _native.run_batch_fast}[mode]
        _run._poc_run_batch = partial(native_fn, run_module=_run)

    class ReplaceBatch(ast.NodeTransformer):
        def visit_While(self, node: ast.While):
            if node is batch_loop:
                call = ast.Expr(value=ast.Call(
                    func=ast.Name(id="_poc_run_batch", ctx=ast.Load()),
                    args=[ast.Name(id="runner", ctx=ast.Load()),
                          ast.Name(id="batch", ctx=ast.Load())],
                    keywords=[],
                ))
                return ast.copy_location(call, node)
            return self.generic_visit(node)

    ReplaceBatch().visit(tree)
    ast.fix_missing_locations(tree)
    ast.increment_lineno(tree, start_line - 1)
    exec(compile(tree, str(source_path), "exec"), _run.__dict__)
    _active = mode


def backend() -> str | None:
    return _active

