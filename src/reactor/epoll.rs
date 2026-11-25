use std::{io, os::fd::{AsRawFd, FromRawFd, OwnedFd}, time::Duration};

pub(super) struct Kernel {
    fd: OwnedFd,
}

impl Kernel {
    pub fn new() -> io::Result<Self> {
        let fd = unsafe { libc::epoll_create1(libc::EPOLL_CLOEXEC) };
        if fd < 0 { return Err(io::Error::last_os_error()); }
        Ok(Self { fd: unsafe { OwnedFd::from_raw_fd(fd) } })
    }

    pub fn update(&mut self, fd: i32, old: u8, new: u8, token: usize) -> io::Result<()> {
        let op = match (old, new) {
            (0, _) => libc::EPOLL_CTL_ADD,
            (_, 0) => libc::EPOLL_CTL_DEL,
            _ => libc::EPOLL_CTL_MOD,
        };
        let mut event = libc::epoll_event {
            events: ((if new & 1 != 0 { libc::EPOLLIN } else { 0 })
                | (if new & 2 != 0 { libc::EPOLLOUT } else { 0 })) as u32,
            u64: token as u64,
        };
        let rc = unsafe { libc::epoll_ctl(self.fd.as_raw_fd(), op, fd, &mut event) };
        if rc < 0 {
            let error = io::Error::last_os_error();
            if new == 0 && matches!(error.raw_os_error(), Some(libc::ENOENT | libc::EBADF)) {
                return Ok(());
            }
            return Err(error);
        }
        Ok(())
    }

    pub fn wait(&mut self, timeout: Option<Duration>) -> io::Result<Vec<(usize, u8)>> {
        let mut events = [libc::epoll_event { events: 0, u64: 0 }; 256];
        let millis = timeout.map_or(-1, |d| d.as_nanos().div_ceil(1_000_000).min(i32::MAX as u128) as i32);
        let count = unsafe { libc::epoll_wait(self.fd.as_raw_fd(), events.as_mut_ptr(), events.len() as i32, millis) };
        if count < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::Interrupted { return Ok(Vec::new()); }
            return Err(error);
        }
        Ok(events[..count as usize].iter().map(|event| {
            let flags = event.events as i32;
            let mask = if flags & (libc::EPOLLERR | libc::EPOLLHUP) != 0 { 3 }
                else { u8::from(flags & libc::EPOLLIN != 0) | (u8::from(flags & libc::EPOLLOUT != 0) << 1) };
            (event.u64 as usize, mask)
        }).collect())
    }
}
