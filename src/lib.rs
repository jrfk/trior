//! Experimental translation of Trio v0.35.0's `while batch` scheduler body.
//!
//! Algorithm and semantics derived from python-trio/trio, MIT licensed; see
//! LICENSE.Trio. This version intentionally keeps Python-owned Task state.
//! No mutable Rust borrow or lock survives a callback into Python.

mod recv;
mod runtime;
use pyo3::exceptions::{PyAssertionError, PyStopIteration, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyList, PyModule};

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

// Reproduce Runner.reschedule's default path inside the already-native batch.
// This remains a private, version-pinned experiment, not a general replacement
// for external lowlevel.reschedule calls.
fn reschedule_fast<'py>(
    py: Python<'py>, runner: &Bound<'py, PyAny>, task: &Bound<'py, PyAny>,
    value_type: &Bound<'py, PyAny>,
) -> PyResult<()> {
    let outcome = value_type.call1((py.None(),))?;
    if !task.getattr(pyo3::intern!(py, "_runner"))?.is(runner) {
        return Err(PyAssertionError::new_err("task._runner is not runner"));
    }
    if !task.getattr(pyo3::intern!(py, "_next_send_fn"))?.is_none() {
        return Err(PyAssertionError::new_err("task._next_send_fn is not None"));
    }
    let send = task.getattr(pyo3::intern!(py, "coro"))?.getattr(pyo3::intern!(py, "send"))?;
    task.setattr(pyo3::intern!(py, "_next_send_fn"), send)?;
    task.setattr(pyo3::intern!(py, "_next_send"), outcome)?;
    task.setattr(pyo3::intern!(py, "_abort_func"), py.None())?;
    task.setattr(pyo3::intern!(py, "custom_sleep_data"), py.None())?;
    let runq = runner.getattr(pyo3::intern!(py, "runq"))?;
    if !runq.is_truthy()? && runner.getattr(pyo3::intern!(py, "is_guest"))?.is_truthy()? {
        runner.call_method0(pyo3::intern!(py, "force_guest_tick_asap"))?;
    }
    runq.call_method1(pyo3::intern!(py, "append"), (task,))?;
    instrument_opt(py, runner, pyo3::intern!(py, "task_scheduled"), task)
}

fn run_batch_optimized<'py>(
    py: Python<'py>,
    runner: &Bound<'py, PyAny>,
    batch: &Bound<'py, PyList>,
    run_module: &Bound<'py, PyModule>,
    fast_reschedule: bool,
) -> PyResult<()> {
    let run_context = run_module.getattr(pyo3::intern!(py, "GLOBAL_RUN_CONTEXT"))?;
    let shield_checkpoint = run_module.getattr(pyo3::intern!(py, "CancelShieldedCheckpoint"))?;
    let wait_type = run_module.getattr(pyo3::intern!(py, "WaitTaskRescheduled"))?;
    let detach_type = run_module.getattr(pyo3::intern!(py, "PermanentlyDetachCoroutineObject"))?;
    let value_type = run_module.getattr(pyo3::intern!(py, "Value"))?;
    let error_type = run_module.getattr(pyo3::intern!(py, "Error"))?;
    let context_tb_frames: usize = run_module.getattr(pyo3::intern!(py, "CONTEXT_RUN_TB_FRAMES"))?.extract()?;

    while !batch.is_empty() {
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

        let step = task.getattr(pyo3::intern!(py, "context"))
            .and_then(|context| context.call_method1(pyo3::intern!(py, "run"), (&next_send_fn, &next_send)));

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
                    if fast_reschedule {
                        reschedule_fast(py, runner, &task, &value_type)?;
                    } else {
                        runner.call_method1(pyo3::intern!(py, "reschedule"), (&task,))?;
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

        instrument_opt(py, runner, pyo3::intern!(py, "after_task_step"), &task)?;
        run_context.delattr(pyo3::intern!(py, "task"))?;
        // Bounds (task, result, arguments) are dropped every iteration;
        // Python-owned references never persist in a Rust global/cache.
    }
    Ok(())
}

#[pyfunction]
fn run_batch_opt<'py>(py: Python<'py>, runner: &Bound<'py, PyAny>, batch: &Bound<'py, PyList>, run_module: &Bound<'py, PyModule>) -> PyResult<()> {
    run_batch_optimized(py, runner, batch, run_module, false)
}

#[pyfunction]
fn run_batch_fast<'py>(py: Python<'py>, runner: &Bound<'py, PyAny>, batch: &Bound<'py, PyList>, run_module: &Bound<'py, PyModule>) -> PyResult<()> {
    run_batch_optimized(py, runner, batch, run_module, true)
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<runtime::Runtime>()?;
    m.add_class::<runtime::Trap>()?;
    m.add_class::<runtime::WaitQueue>()?;
    m.add_class::<recv::RecvAttempt>()?;
    m.add_function(wrap_pyfunction!(run_batch, m)?)?;
    m.add_function(wrap_pyfunction!(run_batch_opt, m)?)?;
    m.add_function(wrap_pyfunction!(run_batch_fast, m)?)?;
    m.add("IMPLEMENTATION", "trio-0.35.0-python-owned-state-batch-v1")?;
    Ok(())
}
