//! Native readiness backend, with poll retained as a comparison/fallback.
mod poll;
#[cfg(target_os = "linux")]
mod epoll;
#[cfg(target_os = "macos")]
mod kqueue;
#[cfg(target_os = "linux")]
use epoll::Kernel;
#[cfg(target_os = "macos")]
use kqueue::Kernel;

use std::{io, time::Duration};

#[derive(Default)]
pub(crate) struct Reactor {
    poll: poll::PollReactor,
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    native: Option<native::NativeReactor>,
    initialized: bool,
}

impl Reactor {
    pub fn is_empty(&self) -> bool {
        #[cfg(any(target_os = "linux", target_os = "macos"))]
        if let Some(native) = &self.native { return native.is_empty(); }
        self.poll.is_empty()
    }

    pub fn register(&mut self, fd: i32, write: bool, task: usize) -> io::Result<bool> {
        if !self.initialized {
            #[cfg(any(target_os = "linux", target_os = "macos"))]
            if std::env::var("TRIOR_REACTOR").as_deref() != Ok("poll") {
                self.native = Some(native::NativeReactor::new()?);
            }
            self.initialized = true;
        }
        #[cfg(any(target_os = "linux", target_os = "macos"))]
        if let Some(native) = &mut self.native { return native.register(fd, write, task); }
        self.poll.register(fd, write, task)
    }

    pub fn remove(&mut self, fd: i32, write: bool, task: usize) {
        #[cfg(any(target_os = "linux", target_os = "macos"))]
        if let Some(native) = &mut self.native { native.remove(fd, write, task); return; }
        self.poll.remove(fd, write, task);
    }

    pub fn close(&mut self, fd: i32) -> Vec<usize> {
        #[cfg(any(target_os = "linux", target_os = "macos"))]
        if let Some(native) = &mut self.native { return native.close(fd); }
        self.poll.close(fd)
    }

    pub fn wait(&mut self, timeout: Option<Duration>) -> io::Result<Vec<(usize, bool)>> {
        #[cfg(any(target_os = "linux", target_os = "macos"))]
        if let Some(native) = &mut self.native { return native.wait(timeout); }
        self.poll.wait(timeout)
    }
}

#[cfg(any(target_os = "linux", target_os = "macos"))]
mod native {
    use super::Kernel;
    use std::{collections::HashMap, io, time::Duration};

    #[derive(Clone, Copy, Default)]
    struct Slot {
        tasks: [Option<usize>; 2],
        token: usize,
    }

    impl Slot {
        fn mask(self) -> u8 {
            u8::from(self.tasks[0].is_some()) | (u8::from(self.tasks[1].is_some()) << 1)
        }
    }

    pub(super) struct NativeReactor {
        kernel: Kernel,
        slots: HashMap<i32, Slot>,
        tokens: HashMap<usize, i32>,
        next_token: usize,
        pending_error: Option<io::Error>,
    }

    impl NativeReactor {
        pub fn new() -> io::Result<Self> {
            Ok(Self { kernel: Kernel::new()?, slots: HashMap::new(), tokens: HashMap::new(),
                next_token: 1, pending_error: None })
        }

        pub fn is_empty(&self) -> bool { self.slots.is_empty() && self.pending_error.is_none() }

        fn update(&mut self, fd: i32, old: Slot, new: Slot) -> io::Result<()> {
            self.kernel.update(fd, old.mask(), new.mask(), new.token)?;
            if new.mask() == 0 {
                self.slots.remove(&fd);
                self.tokens.remove(&old.token);
            } else {
                self.slots.insert(fd, new);
                self.tokens.insert(new.token, fd);
            }
            Ok(())
        }

        pub fn register(&mut self, fd: i32, write: bool, task: usize) -> io::Result<bool> {
            if fd < 0 { return Err(io::Error::from_raw_os_error(libc::EBADF)); }
            let old = self.slots.get(&fd).copied().unwrap_or_default();
            let mut new = old;
            if new.tasks[write as usize].is_some() { return Ok(false); }
            if old.mask() == 0 {
                new.token = self.next_token;
                self.next_token = self.next_token.checked_add(1)
                    .ok_or_else(|| io::Error::other("reactor token exhausted"))?;
            }
            new.tasks[write as usize] = Some(task);
            self.update(fd, old, new)?;
            Ok(true)
        }

        fn discard(&mut self, fd: i32, old: Slot, new: Slot) {
            if let Err(error) = self.update(fd, old, new) {
                // A failed mutation cannot leave a stale registration re-used.
                self.pending_error = Some(error);
                self.slots.remove(&fd);
                self.tokens.remove(&old.token);
            }
        }

        pub fn remove(&mut self, fd: i32, write: bool, task: usize) {
            if let Some(old) = self.slots.get(&fd).copied() {
                if old.tasks[write as usize] != Some(task) { return; }
                let mut new = old;
                new.tasks[write as usize] = None;
                self.discard(fd, old, new);
            }
        }

        pub fn close(&mut self, fd: i32) -> Vec<usize> {
            let Some(old) = self.slots.get(&fd).copied() else { return Vec::new(); };
            self.discard(fd, old, Slot { tasks: [None; 2], token: old.token });
            old.tasks.into_iter().flatten().collect()
        }

        pub fn wait(&mut self, timeout: Option<Duration>) -> io::Result<Vec<(usize, bool)>> {
            if let Some(error) = self.pending_error.take() { return Err(error); }
            let events = self.kernel.wait(timeout)?;
            let mut ready = Vec::with_capacity(events.len());
            for (token, mask) in events {
                let Some(&fd) = self.tokens.get(&token) else { continue; };
                let old = self.slots[&fd];
                let mut new = old;
                for direction in 0..2 {
                    if mask & (1 << direction) != 0 {
                        if let Some(task) = new.tasks[direction].take() { ready.push((task, false)); }
                    }
                }
                if new.mask() != old.mask() {
                    self.update(fd, old, new)?;
                }
            }
            Ok(ready)
        }
    }
}
