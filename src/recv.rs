use pyo3::exceptions::{PyBlockingIOError, PyRuntimeError, PyStopIteration};
use pyo3::prelude::*;
use pyo3::types::PyAny;
use pyo3::{PyTraverseError, PyVisit};

enum State {
    Start {
        socket: Py<PyAny>,
        args: Py<PyAny>,
        checkpoint: Py<PyAny>,
    },
    Resume(Result<Py<PyAny>, Py<PyAny>>),
    Done,
}

#[pyclass]
pub(crate) struct RecvAttempt {
    state: State,
}

#[pymethods]
impl RecvAttempt {
    #[new]
    fn new(socket: Py<PyAny>, args: Py<PyAny>, checkpoint: Py<PyAny>) -> Self {
        Self {
            state: State::Start {
                socket,
                args,
                checkpoint,
            },
        }
    }

    fn __await__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.advance(py, &py.None().into_bound(py))
    }

    fn send(&mut self, py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        self.advance(py, value)
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        match &self.state {
            State::Start { socket, args, checkpoint } => {
                visit.call(socket)?;
                visit.call(args)?;
                visit.call(checkpoint)?;
            }
            State::Resume(Ok(value) | Err(value)) => visit.call(value)?,
            State::Done => {}
        }
        Ok(())
    }

    fn __clear__(&mut self) {
        self.state = State::Done;
    }
}

impl RecvAttempt {
    fn advance(&mut self, py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        match std::mem::replace(&mut self.state, State::Done) {
            State::Start { socket, args, checkpoint } => {
                let result = match socket.bind(py).call_method1(
                    pyo3::intern!(py, "recv"),
                    args.bind(py).cast::<pyo3::types::PyTuple>()?,
                ) {
                    Ok(data) => Ok(data.unbind()),
                    Err(err) if err.is_instance_of::<PyBlockingIOError>(py) => {
                        return Err(PyStopIteration::new_err(()));
                    }
                    Err(err) => Err(err.into_value(py).into_any()),
                };
                self.state = State::Resume(result);
                Ok(checkpoint)
            }
            State::Resume(result) => {
                value.call_method0(pyo3::intern!(py, "unwrap"))?;
                match result {
                    Ok(data) => Err(PyStopIteration::new_err((data,))),
                    Err(error) => {
                        let error = PyErr::from_value(error.into_bound(py));
                        // An iterator's StopIteration would otherwise look
                        // like successful completion to the outer coroutine.
                        if error.is_instance_of::<PyStopIteration>(py) {
                            let wrapped = PyRuntimeError::new_err("coroutine raised StopIteration");
                            wrapped.set_cause(py, Some(error));
                            Err(wrapped)
                        } else {
                            Err(error)
                        }
                    }
                }
            }
            State::Done => Err(PyRuntimeError::new_err("receive attempt already completed")),
        }
    }
}
