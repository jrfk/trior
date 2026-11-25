use pyo3::prelude::*;
use pyo3::exceptions::{PyAssertionError, PyStopIteration, PyTypeError};
use pyo3::types::{PyList, PyModule};
use super::{NativeRunQueue, NativeTaskState, reschedule_native};
#[cfg(feature = "probe")]
use super::probe;
#[cfg(feature = "probe")]
use std::time::Instant;
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

fn run_batch_optimized<'py>(
    py: Python<'py>,
    runner: &Bound<'py, PyAny>,
    batch: &mut Vec<Py<PyAny>>,
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

    while let Some(owned_task) = batch.pop() {
        #[cfg(feature = "probe")]
        let step_start = Instant::now();
        let task = owned_task.bind(py);
        run_context.setattr(pyo3::intern!(py, "task"), &task)?;
        instrument_opt(py, runner, pyo3::intern!(py, "before_task_step"), &task)?;

        let state = task.cast::<NativeTaskState>()?;
        let (next_send_fn, next_send) = {
            let mut state = state.borrow_mut();
            (std::mem::replace(&mut state._next_send_fn, py.None()),
             std::mem::replace(&mut state._next_send, py.None()))
        };
        let next_send_fn = next_send_fn.bind(py);
        let next_send = next_send.bind(py);
        if next_send_fn.is_none() {
            return Err(PyAssertionError::new_err("next_send_fn must not be None"));
        }

        #[cfg(feature = "probe")]
        let context_start = Instant::now();
        let step = task.getattr(pyo3::intern!(py, "context"))
            .and_then(|context| context.call_method1(pyo3::intern!(py, "run"), (&next_send_fn, &next_send)));
        #[cfg(feature = "probe")]
        let dispatch_start = Instant::now();

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
                    #[cfg(feature = "probe")]
                    let shield_start = Instant::now();
                    if fast_reschedule {
                        reschedule_native(py, runner, &task, &value_type.call1((py.None(),))?)?;
                    } else {
                        runner.call_method1(pyo3::intern!(py, "reschedule"), (&task,))?;
                    }
                    #[cfg(feature = "probe")]
                    if probe::enabled() { probe::record_shield(shield_start.elapsed().as_nanos() as u64); }
                } else if msg.get_type().is(&wait_type) {
                    increment_opt(&task, pyo3::intern!(py, "_cancel_points"))?;
                    state.borrow_mut()._abort_func = msg.getattr(pyo3::intern!(py, "abort_func"))?.unbind();
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
                    state.borrow_mut()._next_send_fn = task.getattr(pyo3::intern!(py, "coro"))?.getattr(pyo3::intern!(py, "throw"))?.unbind();
                }
            }
        }

        #[cfg(feature = "probe")]
        let finish_start = Instant::now();
        instrument_opt(py, runner, pyo3::intern!(py, "after_task_step"), &task)?;
        run_context.delattr(pyo3::intern!(py, "task"))?;
        #[cfg(feature = "probe")]
        if probe::enabled() {
            let finish_end = Instant::now();
            probe::record(context_start.duration_since(step_start).as_nanos() as u64,
                          dispatch_start.duration_since(context_start).as_nanos() as u64,
                          finish_start.duration_since(dispatch_start).as_nanos() as u64,
                          finish_end.duration_since(finish_start).as_nanos() as u64);
        }
        // Bounds (task, result, arguments) are dropped every iteration;
        // Python-owned references never persist in a Rust global/cache.
    }
    Ok(())
}

#[pyfunction]
fn run_batch_opt<'py>(py: Python<'py>, runner: &Bound<'py, PyAny>, batch: &Bound<'py, PyList>, run_module: &Bound<'py, PyModule>) -> PyResult<()> {
    let mut tasks = batch.iter().map(Bound::unbind).collect();
    batch.call_method0("clear")?;
    run_batch_optimized(py, runner, &mut tasks, run_module, false)
}

#[pyfunction]
pub(super) fn run_batch_fast<'py>(py: Python<'py>, runner: &Bound<'py, PyAny>, batch: &Bound<'py, PyList>, run_module: &Bound<'py, PyModule>) -> PyResult<()> {
    let mut tasks = batch.iter().map(Bound::unbind).collect();
    batch.call_method0("clear")?;
    run_batch_optimized(py, runner, &mut tasks, run_module, true)
}

#[pyfunction]
pub(super) fn run_queue_fast<'py>(py: Python<'py>, runner: &Bound<'py, PyAny>, batch: &Bound<'py, NativeRunQueue>, run_module: &Bound<'py, PyModule>, reverse: bool) -> PyResult<()> {
    let mut tasks: Vec<_> = std::mem::take(&mut batch.borrow_mut().items).into_iter().collect();
    if reverse { tasks.reverse(); }
    run_batch_optimized(py, runner, &mut tasks, run_module, true)
}
