use pyo3::prelude::*;
use pyo3::exceptions::PyAssertionError;
use pyo3::pyclass::{PyTraverseError, PyVisit};
use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
mod batch;
#[cfg(feature = "probe")]
mod probe;

static NATIVE_EMPTY_CHECK: AtomicBool = AtomicBool::new(false);

#[pyfunction]
fn set_native_empty_check(enabled: bool) {
    NATIVE_EMPTY_CHECK.store(enabled, Ordering::Relaxed);
}

#[pyclass]
struct NativeRunQueue {
    items: VecDeque<Py<PyAny>>,
}

#[pymethods]
impl NativeRunQueue {
    #[new]
    fn new() -> Self { Self { items: VecDeque::new() } }

    fn __len__(&self) -> usize { self.items.len() }

    fn append(&mut self, task: Py<PyAny>) { self.items.push_back(task); }

    fn clear(&mut self) { self.items.clear(); }

    fn take_batch(&mut self) -> Vec<Py<PyAny>> {
        self.items.drain(..).collect()
    }

    fn take_batch_queue(&mut self) -> Self {
        Self { items: std::mem::take(&mut self.items) }
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        for task in &self.items { visit.call(task)?; }
        Ok(())
    }

    fn __clear__(&mut self) { self.items.clear(); }
}

#[pyclass(subclass)]
struct NativeTaskState {
    #[pyo3(get, set)]
    _next_send_fn: Py<PyAny>,
    #[pyo3(get, set)]
    _next_send: Py<PyAny>,
    #[pyo3(get, set)]
    _abort_func: Py<PyAny>,
    #[pyo3(get, set)]
    custom_sleep_data: Py<PyAny>,
}

#[pymethods]
impl NativeTaskState {
    #[new]
    fn new(py: Python<'_>) -> Self {
        Self { _next_send_fn: py.None(), _next_send: py.None(),
               _abort_func: py.None(), custom_sleep_data: py.None() }
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self._next_send_fn)?;
        visit.call(&self._next_send)?;
        visit.call(&self._abort_func)?;
        visit.call(&self.custom_sleep_data)?;
        Ok(())
    }

    fn __clear__(&mut self) {
        Python::attach(|py| {
            self._next_send_fn = py.None();
            self._next_send = py.None();
            self._abort_func = py.None();
            self.custom_sleep_data = py.None();
        });
    }
}

#[pyfunction]
fn reschedule_native(py: Python<'_>, runner: &Bound<'_, PyAny>, task: &Bound<'_, PyAny>, next_send: &Bound<'_, PyAny>) -> PyResult<()> {
    if !task.getattr(pyo3::intern!(py, "_runner"))?.is(runner) {
        return Err(PyAssertionError::new_err("task belongs to a different runner"));
    }
    let state = task.cast::<NativeTaskState>()?;
    if !state.borrow()._next_send_fn.is_none(py) {
        return Err(PyAssertionError::new_err("task already scheduled"));
    }
    let send = task.getattr(pyo3::intern!(py, "coro"))?.getattr(pyo3::intern!(py, "send"))?.unbind();
    {
        let mut state = state.borrow_mut();
        state._next_send_fn = send;
        state._next_send = next_send.clone().unbind();
        state._abort_func = py.None();
        state.custom_sleep_data = py.None();
    }
    let runq = runner.getattr(pyo3::intern!(py, "runq"))?;
    let queue_empty = if NATIVE_EMPTY_CHECK.load(Ordering::Relaxed) {
        if let Ok(queue) = runq.cast::<NativeRunQueue>() {
            queue.borrow().items.is_empty()
        } else {
            !runq.is_truthy()?
        }
    } else {
        !runq.is_truthy()?
    };
    if queue_empty && runner.getattr(pyo3::intern!(py, "is_guest"))?.is_truthy()? {
        runner.call_method0(pyo3::intern!(py, "force_guest_tick_asap"))?;
    }
    if let Ok(queue) = runq.cast::<NativeRunQueue>() {
        queue.borrow_mut().items.push_back(task.clone().unbind());
    } else {
        runq.call_method1(pyo3::intern!(py, "append"), (task,))?;
    }
    let instruments = runner.getattr(pyo3::intern!(py, "instruments"))?;
    let hook = pyo3::intern!(py, "task_scheduled");
    if instruments.contains(hook)? {
        instruments.call_method1(pyo3::intern!(py, "call"), (hook, task))?;
    }
    Ok(())
}

#[pymodule]
fn _native_task_state(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<NativeRunQueue>()?;
    m.add_class::<NativeTaskState>()?;
    m.add_function(wrap_pyfunction!(reschedule_native, m)?)?;
    m.add_function(wrap_pyfunction!(set_native_empty_check, m)?)?;
    m.add_function(wrap_pyfunction!(batch::run_batch_fast, m)?)?;
    m.add_function(wrap_pyfunction!(batch::run_queue_fast, m)?)?;
    #[cfg(feature = "probe")]
    {
        m.add_function(wrap_pyfunction!(probe::set_probe_enabled, m)?)?;
        m.add_function(wrap_pyfunction!(probe::take_probe, m)?)?;
    }
    Ok(())
}
