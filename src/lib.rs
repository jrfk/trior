//! Trior's native runtime module.
mod reactor;
mod runtime;

use pyo3::prelude::*;
use pyo3::types::PyModule;

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<runtime::Runtime>()?;
    m.add_class::<runtime::Trap>()?;
    m.add_class::<runtime::WaitQueue>()?;
    Ok(())
}
