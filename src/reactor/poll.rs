//! Level-triggered Unix readiness reactor. Registration ownership is per task.
use std::collections::HashMap;
use std::io;
use std::time::Duration;

#[derive(Default)]
pub(crate) struct PollReactor {
    slots: HashMap<i32, [Option<usize>; 2]>,
}

impl PollReactor {
    pub fn is_empty(&self) -> bool { self.slots.is_empty() }

    pub fn register(&mut self, fd: i32, write: bool, task: usize) -> io::Result<bool> {
        if fd < 0 {
            return Err(io::Error::from_raw_os_error(libc::EBADF));
        }
        let slot = &mut self.slots.entry(fd).or_default()[write as usize];
        if slot.is_some() { return Ok(false); }
        *slot = Some(task);
        Ok(true)
    }

    pub fn remove(&mut self, fd: i32, write: bool, task: usize) {
        if let Some(slots) = self.slots.get_mut(&fd) {
            if slots[write as usize] == Some(task) {
                slots[write as usize] = None;
            }
            if slots.iter().all(Option::is_none) { self.slots.remove(&fd); }
        }
    }

    pub fn close(&mut self, fd: i32) -> Vec<usize> {
        self.slots.remove(&fd).into_iter().flatten().flatten().collect()
    }

    pub fn wait(&mut self, timeout: Option<Duration>) -> io::Result<Vec<(usize, bool)>> {
        let mut fds: Vec<_> = self.slots.iter().map(|(&fd, slots)| libc::pollfd {
            fd,
            events: (if slots[0].is_some() { libc::POLLIN } else { 0 })
                | (if slots[1].is_some() { libc::POLLOUT } else { 0 }),
            revents: 0,
        }).collect();
        let millis = timeout.map_or(-1, |d| {
            d.as_nanos().div_ceil(1_000_000).min(i32::MAX as u128) as i32
        });
        // SAFETY: poll receives a valid contiguous mutable buffer for this call.
        let count = unsafe { libc::poll(fds.as_mut_ptr(), fds.len() as libc::nfds_t, millis) };
        if count < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::Interrupted { return Ok(Vec::new()); }
            return Err(error);
        }
        let mut ready = Vec::with_capacity(count as usize);
        for fd in fds.into_iter().filter(|fd| fd.revents != 0) {
            let closed = fd.revents & libc::POLLNVAL != 0;
            let both = closed || fd.revents & (libc::POLLERR | libc::POLLHUP) != 0;
            if let Some(slots) = self.slots.get_mut(&fd.fd) {
                for (index, flag) in [libc::POLLIN, libc::POLLOUT].into_iter().enumerate() {
                    if both || fd.revents & flag != 0 {
                        if let Some(task) = slots[index].take() { ready.push((task, closed)); }
                    }
                }
                if slots.iter().all(Option::is_none) { self.slots.remove(&fd.fd); }
            }
        }
        Ok(ready)
    }
}
