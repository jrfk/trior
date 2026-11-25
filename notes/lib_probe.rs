//! Experimental translation of Trio v0.35.0's `while batch` scheduler body.
//!
//! Algorithm and semantics derived from python-trio/trio, MIT licensed; see
//! LICENSE.Trio. This version intentionally keeps Python-owned Task state.
//! No mutable Rust borrow or lock survives a callback into Python.

use pyo3::exceptions::{PyAssertionError, PyStopIteration, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyList, PyModule};
use std::sync::{atomic::{AtomicBool, Ordering}, Mutex};
use std::time::Instant;

// Diagnostic only. Disabled for normal benchmarks; wall intervals approximate
// CPU intervals when the benchmark is pinned and does not block in a task.
static PROBE_ENABLED: AtomicBool = AtomicBool::new(false);
static PROBE: Mutex<[u128; 7]> = Mutex::new([0; 7]);

#[pyfunction]
fn set_probe_enabled(enabled: bool) {
    PROBE_ENABLED.store(enabled, Ordering::Relaxed);
}

#[pyfunction]
fn take_probe() -> PyResult<(u128, u128, u128, u128, u128, u128, u128)> {
    let mut values = PROBE.lock().map_err(|_| PyAssertionError::new_err("probe lock poisoned"))?;
    let current = *values;
    *values = [0; 7];
    Ok((current[0], current[1], current[2], current[3], current[4], current[5], current[6]))
}

fn increment(task: &Bound<'_, PyAny>, name: &str) -> PyResult<()> {
    // Preserve arbitrary-sized Python counters rather than truncating to u64.
    task.setattr(name, task.getattr(name)?.add(1)?)
}

fn instrument(runner: &Bound<'_, PyAny>, name: &str, task: &Bound<'_, PyAny>) -> PyResult<()> {
    let instruments = runner.getattr("instruments")?;
    // Re-check at each hook: user hooks may add or remove instruments.
    if instruments.contains(name)? {
        instruments.call_method1("call", (name, task))?;
    }
    Ok(())
}

#[pyfunction]
fn run_batch<'py>(
    py: Python<'py>,
    runner: &Bound<'py, PyAny>,
    batch: &Bound<'py, PyList>,
    run_module: &Bound<'py, PyModule>,
) -> PyResult<()> {
    let run_context = run_module.getattr("GLOBAL_RUN_CONTEXT")?;
    let shield_checkpoint = run_module.getattr("CancelShieldedCheckpoint")?;
    let wait_type = run_module.getattr("WaitTaskRescheduled")?;
    let detach_type = run_module.getattr("PermanentlyDetachCoroutineObject")?;
    let value_type = run_module.getattr("Value")?;
    let error_type = run_module.getattr("Error")?;
    let context_tb_frames: usize = run_module.getattr("CONTEXT_RUN_TB_FRAMES")?.extract()?;

    while !batch.is_empty() {
        let index = batch.len() - 1;
        let task = batch.get_item(index)?;
        batch.del_item(index)?;
        run_context.setattr("task", &task)?;
        instrument(runner, "before_task_step", &task)?;

        let next_send_fn = task.getattr("_next_send_fn")?;
        let next_send = task.getattr("_next_send")?;
        task.setattr("_next_send_fn", py.None())?;
        task.setattr("_next_send", py.None())?;
        if next_send_fn.is_none() {
            return Err(PyAssertionError::new_err("next_send_fn must not be None"));
        }

        let step = task.getattr("context")
            .and_then(|context| context.call_method1("run", (&next_send_fn, &next_send)));

        // Normalize the exception outside Python's handled-exception state,
        // so task_exited does not attach the caught exception as context.
        match step {
            Err(err) => {
                let final_outcome = if err.is_instance_of::<PyStopIteration>(py) {
                    value_type.call1((err.value(py).getattr("value")?,))?
                } else {
                    let exc = err.value(py);
                    let mut tb = exc.getattr("__traceback__")?;
                    // Rust introduces no Python frame. The Python loop trims
                    // 1 + context_tb_frames; here trim only context's frames.
                    for _ in 0..context_tb_frames {
                        if !tb.is_none() {
                            tb = tb.getattr("tb_next")?;
                        }
                    }
                    error_type.call1((exc.call_method1("with_traceback", (tb,))?,))?
                };
                runner.call_method1("task_exited", (&task, final_outcome))?;
            }
            Ok(msg) => {
                increment(&task, "_schedule_points")?;
                if msg.is(&shield_checkpoint) {
                    runner.call_method1("reschedule", (&task,))?;
                } else if msg.get_type().is(&wait_type) {
                    increment(&task, "_cancel_points")?;
                    task.setattr("_abort_func", msg.getattr("abort_func")?)?;
                    if runner.getattr("ki_pending")?.is_truthy()?
                        && task.is(&runner.getattr("main_task")?)
                    {
                        task.call_method0("_attempt_delivery_of_pending_ki")?;
                    }
                    task.call_method0("_attempt_delivery_of_any_pending_cancel")?;
                } else if msg.get_type().is(&detach_type) {
                    runner.call_method1("task_exited", (&task, msg.getattr("final_outcome")?))?;
                } else {
                    let repr = msg.repr()?;
                    let exc = PyTypeError::new_err(format!(
                        "trio.run received unrecognized yield message {}. \
                         Are you trying to use a library written for some \
                         other framework like asyncio? That won't work \
                         without some kind of compatibility shim.",
                        repr.to_str()?
                    ));
                    runner.call_method1("reschedule", (&task, exc.value(py)))?;
                    task.setattr("_next_send_fn", task.getattr("coro")?.getattr("throw")?)?;
                }
            }
        }

        instrument(runner, "after_task_step", &task)?;
        run_context.delattr("task")?;
        // Bounds (task, result, arguments) are dropped every iteration;
        // Python-owned references never persist in a Rust global/cache.
    }
    Ok(())
}

// Controlled variant: only attribute/method name construction is changed.
// Python-owned state and callback order remain identical to run_batch.
fn increment_opt(task: &Bound<'_, PyAny>, name: &Bound<'_, pyo3::types::PyString>) -> PyResult<()> {
    task.setattr(name, task.getattr(name)?.add(1)?)
}

fn instrument_opt(
    py: Python<'_>,
    runner: &Bound<'_, PyAny>,
    name: &Bound<'_, pyo3::types::PyString>,
    task: &Bound<'_, PyAny>,
) -> PyResult<()> {
    let instruments = runner.getattr(pyo3::intern!(py, "instruments"))?;
    if instruments.contains(name)? {
        instruments.call_method1(pyo3::intern!(py, "call"), (name, task))?;
    }
    Ok(())
}

#[pyfunction]
fn run_batch_opt<'py>(
    py: Python<'py>,
    runner: &Bound<'py, PyAny>,
    batch: &Bound<'py, PyList>,
    run_module: &Bound<'py, PyModule>,
) -> PyResult<()> {
    let profiling = PROBE_ENABLED.load(Ordering::Relaxed);
    let mut local = [0u128; 7];
    let run_context = run_module.getattr(pyo3::intern!(py, "GLOBAL_RUN_CONTEXT"))?;
    let shield_checkpoint = run_module.getattr(pyo3::intern!(py, "CancelShieldedCheckpoint"))?;
    let wait_type = run_module.getattr(pyo3::intern!(py, "WaitTaskRescheduled"))?;
    let detach_type = run_module.getattr(pyo3::intern!(py, "PermanentlyDetachCoroutineObject"))?;
    let value_type = run_module.getattr(pyo3::intern!(py, "Value"))?;
    let error_type = run_module.getattr(pyo3::intern!(py, "Error"))?;
    let context_tb_frames: usize = run_module.getattr(pyo3::intern!(py, "CONTEXT_RUN_TB_FRAMES"))?.extract()?;

    while !batch.is_empty() {
        let t0 = profiling.then(Instant::now);
        let index = batch.len() - 1;
        let task = batch.get_item(index)?;
        batch.del_item(index)?;
        run_context.setattr(pyo3::intern!(py, "task"), &task)?;
        instrument_opt(py, runner, pyo3::intern!(py, "before_task_step"), &task)?;

        let next_send_fn = task.getattr(pyo3::intern!(py, "_next_send_fn"))?;
        let next_send = task.getattr(pyo3::intern!(py, "_next_send"))?;
        task.setattr(pyo3::intern!(py, "_next_send_fn"), py.None())?;
        task.setattr(pyo3::intern!(py, "_next_send"), py.None())?;
        if next_send_fn.is_none() {
            return Err(PyAssertionError::new_err("next_send_fn must not be None"));
        }

        let t1 = profiling.then(Instant::now);

        let step = task.getattr(pyo3::intern!(py, "context"))
            .and_then(|context| context.call_method1(pyo3::intern!(py, "run"), (&next_send_fn, &next_send)));

        let t2 = profiling.then(Instant::now);

        // Normalize the exception outside Python's handled-exception state,
        // so task_exited does not attach the caught exception as context.
        match step {
            Err(err) => {
                let final_outcome = if err.is_instance_of::<PyStopIteration>(py) {
                    value_type.call1((err.value(py).getattr(pyo3::intern!(py, "value"))?,))?
                } else {
                    let exc = err.value(py);
                    let mut tb = exc.getattr(pyo3::intern!(py, "__traceback__"))?;
                    // Rust introduces no Python frame. The Python loop trims
                    // 1 + context_tb_frames; here trim only context's frames.
                    for _ in 0..context_tb_frames {
                        if !tb.is_none() {
                            tb = tb.getattr(pyo3::intern!(py, "tb_next"))?;
                        }
                    }
                    error_type.call1((exc.call_method1(pyo3::intern!(py, "with_traceback"), (tb,))?,))?
                };
                runner.call_method1(pyo3::intern!(py, "task_exited"), (&task, final_outcome))?;
            }
            Ok(msg) => {
                increment_opt(&task, pyo3::intern!(py, "_schedule_points"))?;
                if msg.is(&shield_checkpoint) {
                    let call_started = profiling.then(Instant::now);
                    runner.call_method1(pyo3::intern!(py, "reschedule"), (&task,))?;
                    if let Some(started) = call_started {
                        local[5] += started.elapsed().as_nanos();
                        local[6] += 1;
                    }
                } else if msg.get_type().is(&wait_type) {
                    increment_opt(&task, pyo3::intern!(py, "_cancel_points"))?;
                    task.setattr(pyo3::intern!(py, "_abort_func"), msg.getattr(pyo3::intern!(py, "abort_func"))?)?;
                    if runner.getattr(pyo3::intern!(py, "ki_pending"))?.is_truthy()?
                        && task.is(&runner.getattr(pyo3::intern!(py, "main_task"))?)
                    {
                        task.call_method0(pyo3::intern!(py, "_attempt_delivery_of_pending_ki"))?;
                    }
                    task.call_method0(pyo3::intern!(py, "_attempt_delivery_of_any_pending_cancel"))?;
                } else if msg.get_type().is(&detach_type) {
                    runner.call_method1(pyo3::intern!(py, "task_exited"), (&task, msg.getattr(pyo3::intern!(py, "final_outcome"))?))?;
                } else {
                    let repr = msg.repr()?;
                    let exc = PyTypeError::new_err(format!(
                        "trio.run received unrecognized yield message {}. \
                         Are you trying to use a library written for some \
                         other framework like asyncio? That won't work \
                         without some kind of compatibility shim.",
                        repr.to_str()?
                    ));
                    runner.call_method1(pyo3::intern!(py, "reschedule"), (&task, exc.value(py)))?;
                    task.setattr(pyo3::intern!(py, "_next_send_fn"), task.getattr(pyo3::intern!(py, "coro"))?.getattr(pyo3::intern!(py, "throw"))?)?;
                }
            }
        }

        let t3 = profiling.then(Instant::now);

        instrument_opt(py, runner, pyo3::intern!(py, "after_task_step"), &task)?;
        run_context.delattr(pyo3::intern!(py, "task"))?;
        if let (Some(a), Some(b), Some(c), Some(d)) = (t0, t1, t2, t3) {
            let e = Instant::now();
            local[0] += b.duration_since(a).as_nanos();
            local[1] += c.duration_since(b).as_nanos();
            local[2] += d.duration_since(c).as_nanos();
            local[3] += e.duration_since(d).as_nanos();
            local[4] += 1;
        }
        // Bounds (task, result, arguments) are dropped every iteration;
        // Python-owned references never persist in a Rust global/cache.
    }
    if profiling {
        let mut totals = PROBE.lock().map_err(|_| PyAssertionError::new_err("probe lock poisoned"))?;
        for i in 0..7 { totals[i] += local[i]; }
    }
    Ok(())
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_batch, m)?)?;
    m.add_function(wrap_pyfunction!(run_batch_opt, m)?)?;
    m.add_function(wrap_pyfunction!(set_probe_enabled, m)?)?;
    m.add_function(wrap_pyfunction!(take_probe, m)?)?;
    m.add("IMPLEMENTATION", "trio-0.35.0-python-owned-state-batch-v1")?;
    Ok(())
}
