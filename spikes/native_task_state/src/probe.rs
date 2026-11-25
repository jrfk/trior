use std::cell::Cell;
use std::sync::atomic::{AtomicBool, Ordering};

static ENABLED: AtomicBool = AtomicBool::new(false);
thread_local! { static TOTAL: Cell<[u64; 7]> = const { Cell::new([0; 7]) }; }

pub(super) fn enabled() -> bool { ENABLED.load(Ordering::Relaxed) }

pub(super) fn record(prepare: u64, context: u64, dispatch: u64, finish: u64) {
    TOTAL.with(|cell| {
        let mut values = cell.get();
        values[0] += prepare;
        values[1] += context;
        values[2] += dispatch;
        values[3] += finish;
        values[4] += 1;
        cell.set(values);
    });
}

pub(super) fn record_shield(ns: u64) {
    TOTAL.with(|cell| {
        let mut values = cell.get();
        values[5] += ns;
        values[6] += 1;
        cell.set(values);
    });
}

#[pyo3::pyfunction]
pub(super) fn set_probe_enabled(enabled: bool) { ENABLED.store(enabled, Ordering::Relaxed); }

#[pyo3::pyfunction]
pub(super) fn take_probe() -> [u64; 7] {
    TOTAL.with(|cell| cell.replace([0; 7]))
}
