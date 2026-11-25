use pyo3::exceptions::{PyRuntimeError, PyStopIteration, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyList};
use std::cell::RefCell;
use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap, VecDeque};
use std::time::{Duration, Instant};

#[pyclass]
pub(crate) struct Trap {
    kind: u8,
    delay: f64,
    group: usize,
}

#[pymethods]
impl Trap {
    #[new]
    #[pyo3(signature = (kind, delay=0.0, group=0))]
    fn new(kind: u8, delay: f64, group: usize) -> Self {
        Self { kind, delay, group }
    }
}

#[pyclass]
#[derive(Default)]
pub(crate) struct WaitQueue {
    tasks: VecDeque<usize>,
}

#[pymethods]
impl WaitQueue {
    #[new]
    fn new() -> Self {
        Self::default()
    }

    fn push(&mut self, task: usize) {
        self.tasks.push_back(task);
    }

    fn pop(&mut self) -> Option<usize> {
        self.tasks.pop_front()
    }

    fn remove(&mut self, task: usize) {
        self.tasks.retain(|&id| id != task);
    }

    fn __len__(&self) -> usize {
        self.tasks.len()
    }
}

#[derive(Clone, Copy, PartialEq)]
enum Status {
    Ready,
    Running,
    Sleeping,
    Parked,
    Joining(usize),
}

struct Task {
    coro: Py<PyAny>,
    send: Py<PyAny>,
    context_run: Py<PyAny>,
    scopes: Vec<usize>,
    nursery: Option<usize>,
    status: Status,
    started: bool,
    generation: usize,
    join_group: Option<usize>,
    shield_next: bool,
    park_cancel: Option<usize>,
}

struct Scope {
    cancelled: bool,
    shield: bool,
    active: bool,
    deadline_generation: usize,
    children: usize,
    waiter: Option<usize>,
    errors: Vec<Py<PyAny>>,
}

#[derive(Default)]
struct State {
    tasks: HashMap<usize, Task>,
    next_task: usize,
    scopes: HashMap<usize, Scope>,
    next_scope: usize,
    ready: VecDeque<usize>,
    timers: BinaryHeap<Reverse<(Instant, usize, usize)>>,
    deadlines: BinaryHeap<Reverse<(Instant, usize, usize)>>,
    current: Option<usize>,
    root: Option<PyResult<Py<PyAny>>>,
}

impl State {
    fn compact_heaps(&mut self) {
        if self.timers.len() > self.tasks.len().saturating_mul(2) + 64 {
            self.timers.retain(|Reverse((_, id, generation))| {
                self.tasks.get(id).is_some_and(|task| {
                    task.status == Status::Sleeping && task.generation == *generation
                })
            });
        }
        if self.deadlines.len() > self.scopes.len().saturating_mul(2) + 64 {
            self.deadlines.retain(|Reverse((_, id, generation))| {
                self.scopes.get(id).is_some_and(|scope| {
                    !scope.cancelled && scope.deadline_generation == *generation
                })
            });
        }
    }

    fn task(&self, id: usize) -> &Task {
        self.tasks.get(&id).expect("task exists")
    }

    fn task_mut(&mut self, id: usize) -> &mut Task {
        self.tasks.get_mut(&id).expect("task exists")
    }

    fn current(&self) -> PyResult<usize> {
        self.current.ok_or_else(|| PyRuntimeError::new_err("outside running task"))
    }

    fn effective_cancel(&self, id: usize) -> Option<usize> {
        let mut selected = None;
        for &scope in self.task(id).scopes.iter().rev() {
            let entry = &self.scopes[&scope];
            if entry.cancelled {
                selected = Some(scope);
            }
            if entry.shield {
                break;
            }
        }
        selected
    }

    fn enqueue(&mut self, id: usize) {
        let task = self.task_mut(id);
        task.status = Status::Ready;
        task.generation += 1;
        self.ready.push_back(id);
    }

    fn cancel(&mut self, scope: usize) {
        self.scopes.get_mut(&scope).unwrap().cancelled = true;
        self.wake_cancelled();
    }

    fn wake_cancelled(&mut self) {
        let cancelled: Vec<_> = self.tasks.iter()
            .filter(|(_, task)| matches!(task.status, Status::Sleeping | Status::Parked))
            .filter_map(|(&id, _)| self.effective_cancel(id).map(|scope| (id, scope)))
            .collect();
        for (id, scope) in cancelled {
            if self.task(id).status == Status::Parked {
                self.task_mut(id).park_cancel = Some(scope);
            }
            self.enqueue(id);
        }
    }

    fn set_deadline(&mut self, scope: usize, deadline: Option<Instant>) {
        let entry = self.scopes.get_mut(&scope).unwrap();
        entry.deadline_generation += 1;
        if !entry.active || entry.cancelled {
            return;
        }
        if let Some(deadline) = deadline {
            if deadline <= Instant::now() {
                self.cancel(scope);
            } else {
                self.deadlines.push(Reverse((deadline, scope, entry.deadline_generation)));
            }
        }
        self.compact_heaps();
    }

    fn expire_deadlines(&mut self) {
        let now = Instant::now();
        let mut changed = false;
        while let Some(&Reverse((deadline, id, generation))) = self.deadlines.peek() {
            let valid = self.scopes.get(&id).is_some_and(|scope| {
                scope.active && !scope.cancelled && scope.deadline_generation == generation
            });
            if valid && deadline > now {
                break;
            }
            self.deadlines.pop();
            if valid {
                self.scopes.get_mut(&id).unwrap().cancelled = true;
                changed = true;
            }
        }
        if changed {
            self.wake_cancelled();
        }
    }

    fn spawn(&mut self, py: Python<'_>, coro: Py<PyAny>, context: Py<PyAny>, nursery: Option<usize>, scopes: Vec<usize>) -> PyResult<()> {
        let id = self.next_task;
        self.next_task += 1;
        let send = coro.bind(py).getattr("send")?.unbind();
        let context_run = context.bind(py).getattr("run")?.unbind();
        self.tasks.insert(id, Task {
            coro, send, context_run, nursery, scopes, status: Status::Ready, started: false, generation: 0,
            join_group: None,
            shield_next: false,
            park_cancel: None,
        });
        if let Some(group) = nursery {
            self.scopes.get_mut(&group).unwrap().children += 1;
        }
        self.ready.push_back(id);
        Ok(())
    }

    fn wake_timers(&mut self) {
        let now = Instant::now();
        while let Some(&Reverse((deadline, id, generation))) = self.timers.peek() {
            let valid = self.tasks.get(&id).is_some_and(|task| {
                task.status == Status::Sleeping && task.generation == generation
            });
            if valid && deadline > now {
                break;
            }
            self.timers.pop();
            if valid {
                self.enqueue(id);
            }
        }
    }
}

#[pyclass(unsendable)]
pub(crate) struct Runtime {
    state: RefCell<State>,
    origin: Instant,
}

impl Runtime {
    fn deadline_instant(&self, deadline: f64) -> PyResult<Option<Instant>> {
        if deadline.is_nan() {
            return Err(PyValueError::new_err("deadline must not be NaN"));
        }
        if deadline == f64::INFINITY {
            return Ok(None);
        }
        if deadline <= 0.0 {
            return Ok(Some(self.origin));
        }
        let duration = Duration::try_from_secs_f64(deadline)
            .map_err(|_| PyValueError::new_err("invalid deadline"))?;
        Ok(Some(self.origin.checked_add(duration)
            .ok_or_else(|| PyValueError::new_err("deadline overflow"))?))
    }
}

#[pymethods]
impl Runtime {
    #[new]
    fn new() -> Self {
        Self { state: RefCell::new(State::default()), origin: Instant::now() }
    }

    fn current_time(&self) -> f64 {
        self.origin.elapsed().as_secs_f64()
    }

    fn current_task_id(&self) -> PyResult<usize> {
        self.state.borrow().current()
    }

    fn wake_parked(&self, id: usize) -> bool {
        let mut state = self.state.borrow_mut();
        if !state.tasks.get(&id).is_some_and(|task| task.status == Status::Parked) {
            return false;
        }
        state.task_mut(id).shield_next = true;
        state.enqueue(id);
        true
    }

    fn resource_counts(&self) -> (usize, usize, usize, usize) {
        let state = self.state.borrow();
        (state.tasks.len(), state.scopes.len(), state.timers.len(), state.deadlines.len())
    }

    fn open_scope(&self, shield: bool, deadline: f64) -> PyResult<usize> {
        let deadline = self.deadline_instant(deadline)?;
        let mut state = self.state.borrow_mut();
        let task = state.current()?;
        let scope = state.next_scope;
        state.next_scope += 1;
        state.scopes.insert(scope, Scope { cancelled: false, shield, active: true, deadline_generation: 0, children: 0, waiter: None, errors: Vec::new() });
        state.task_mut(task).scopes.push(scope);
        if deadline.is_some() {
            state.set_deadline(scope, deadline);
        }
        Ok(scope)
    }

    fn set_deadline(&self, scope: usize, deadline: f64) -> PyResult<()> {
        let deadline = self.deadline_instant(deadline)?;
        self.state.borrow_mut().set_deadline(scope, deadline);
        Ok(())
    }

    fn set_shield(&self, scope: usize, shield: bool) {
        let mut state = self.state.borrow_mut();
        state.scopes.get_mut(&scope).unwrap().shield = shield;
        if !shield {
            state.wake_cancelled();
        }
    }

    fn close_scope(&self, scope: usize) -> PyResult<bool> {
        let mut state = self.state.borrow_mut();
        let task = state.current()?;
        if state.task(task).scopes.last() != Some(&scope) || state.scopes[&scope].children != 0 {
            return Err(PyRuntimeError::new_err("scope closed out of order"));
        }
        state.task_mut(task).scopes.pop();
        let entry = state.scopes.remove(&scope).unwrap();
        let cancelled = entry.cancelled;
        drop(state);
        drop(entry);
        Ok(cancelled)
    }

    fn cancel(&self, scope: usize) {
        self.state.borrow_mut().cancel(scope);
    }

    fn cancelled(&self, scope: usize) -> bool {
        self.state.borrow().scopes[&scope].cancelled
    }

    fn is_cancelled(&self) -> PyResult<bool> {
        let state = self.state.borrow();
        Ok(state.effective_cancel(state.current()?).is_some())
    }

    fn spawn(&self, py: Python<'_>, group: usize, coro: Py<PyAny>, context: Py<PyAny>) -> PyResult<()> {
        let mut state = self.state.borrow_mut();
        let task = state.current()?;
        let mut scopes = state.task(task).scopes.clone();
        let end = scopes.iter().position(|&id| id == group)
            .ok_or_else(|| PyRuntimeError::new_err("nursery is not active in current task"))?;
        scopes.truncate(end + 1);
        state.spawn(py, coro, context, Some(group), scopes)
    }

    fn errors(&self, py: Python<'_>, group: usize) -> PyResult<Py<PyAny>> {
        let errors = std::mem::take(&mut self.state.borrow_mut().scopes.get_mut(&group).unwrap().errors);
        Ok(PyList::new(py, errors)?.into_any().unbind())
    }

    fn run(&self, py: Python<'_>, coro: Py<PyAny>, context: Py<PyAny>, cancelled: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        self.state.borrow_mut().spawn(py, coro, context, None, Vec::new())?;
        loop {
            let next = {
                let mut state = self.state.borrow_mut();
                if let Some(result) = state.root.take() {
                    return result;
                }
                state.expire_deadlines();
                state.wake_timers();
                state.compact_heaps();
                state.ready.pop_front()
            };
            let Some(id) = next else {
                let deadline = {
                    let state = self.state.borrow();
                    [state.timers.peek().map(|entry| entry.0.0),
                     state.deadlines.peek().map(|entry| entry.0.0)]
                        .into_iter().flatten().min()
                };
                let Some(deadline) = deadline else {
                    return Err(PyRuntimeError::new_err("deadlocked runtime"));
                };
                py.detach(|| std::thread::sleep(deadline.saturating_duration_since(Instant::now())));
                continue;
            };
            let (coro, send, context_run, cancellation) = {
                let mut state = self.state.borrow_mut();
                let join_group = state.task(id).join_group;
                let cancellation = if state.task(id).shield_next {
                    None
                } else if let Some(scope) = state.task(id).park_cancel {
                    Some(scope)
                } else if state.task(id).started && join_group.is_none() {
                    state.effective_cancel(id)
                } else {
                    None
                };
                let task = state.task_mut(id);
                task.status = Status::Running;
                task.started = true;
                let coro = task.coro.clone_ref(py);
                let send = task.send.clone_ref(py);
                let context_run = task.context_run.clone_ref(py);
                task.join_group = None;
                task.shield_next = false;
                task.park_cancel = None;
                if let Some(group) = join_group {
                    state.scopes.get_mut(&group).unwrap().waiter = None;
                }
                state.current = Some(id);
                (coro, send, context_run, cancellation)
            };
            // Nursery joins are shielded until their children are finished.
            // A join is resumed normally, then the Python nursery propagates
            // the original exception or checks cancellation after cleanup.
            let coroutine = coro.bind(py);
            let context_run = context_run.bind(py);
            let result = if let Some(scope) = cancellation {
                let exception = cancelled.call1((scope,))?;
                context_run.call1((coroutine.getattr("throw")?, exception))
            } else {
                context_run.call1((send, py.None()))
            };
            let mut state = self.state.borrow_mut();
            state.current = None;
            match result {
                Ok(value) => {
                    let trap = value.extract::<PyRef<'_, Trap>>()
                        .map_err(|_| PyRuntimeError::new_err("unsupported awaitable"))?;
                    match trap.kind {
                        0 => state.enqueue(id),
                        1 => {
                            if state.effective_cancel(id).is_some() || trap.delay <= 0.0 {
                                state.enqueue(id);
                            } else {
                                let task = state.task_mut(id);
                                task.status = Status::Sleeping;
                                task.generation += 1;
                                let generation = task.generation;
                                if trap.delay.is_finite() {
                                    let duration = Duration::try_from_secs_f64(trap.delay)
                                        .map_err(|_| PyValueError::new_err("invalid sleep duration"))?;
                                    let deadline = Instant::now().checked_add(duration)
                                        .ok_or_else(|| PyValueError::new_err("sleep duration overflow"))?;
                                    state.timers.push(Reverse((deadline, id, generation)));
                                }
                            }
                        }
                        2 => {
                            state.task_mut(id).join_group = Some(trap.group);
                            let scope = state.scopes.get_mut(&trap.group).unwrap();
                            scope.waiter = Some(id);
                            if scope.children == 0 {
                                state.enqueue(id);
                            } else {
                                state.task_mut(id).status = Status::Joining(trap.group);
                            }
                        }
                        3 => {
                            if let Some(scope) = state.effective_cancel(id) {
                                state.task_mut(id).park_cancel = Some(scope);
                                state.enqueue(id);
                            } else {
                                state.task_mut(id).status = Status::Parked;
                            }
                        }
                        4 => {
                            state.task_mut(id).shield_next = true;
                            state.enqueue(id);
                        }
                        _ => return Err(PyRuntimeError::new_err("unknown trap")),
                    }
                }
                Err(error) => {
                    let result = if error.is_instance_of::<PyStopIteration>(py) {
                        Ok(error.value(py).getattr("value")?.unbind())
                    } else {
                        Err(error)
                    };
                    let task = state.tasks.remove(&id).expect("task exists");
                    if let Some(group) = task.nursery {
                        if let Err(error) = result {
                            if !error.value(py).is_instance(cancelled)? {
                                state.scopes.get_mut(&group).unwrap().errors.push(error.into_value(py).into_any());
                                state.cancel(group);
                            }
                        }
                        let scope = state.scopes.get_mut(&group).unwrap();
                        scope.children -= 1;
                        if scope.children == 0 {
                            if let Some(waiter) = scope.waiter {
                                state.enqueue(waiter);
                            }
                        }
                    } else {
                        state.root = Some(result);
                    }
                    drop(state);
                    drop(task);
                }
            }
        }
    }
}
