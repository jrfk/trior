use std::{io, os::fd::{AsRawFd, FromRawFd, OwnedFd}, time::Duration};

pub(super) struct Kernel {
    fd: OwnedFd,
}

impl Kernel {
    pub fn new() -> io::Result<Self> {
        let fd = unsafe { libc::kqueue() };
        if fd < 0 { return Err(io::Error::last_os_error()); }
        let fd = unsafe { OwnedFd::from_raw_fd(fd) };
        if unsafe { libc::fcntl(fd.as_raw_fd(), libc::F_SETFD, libc::FD_CLOEXEC) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self { fd })
    }

    pub fn update(&mut self, fd: i32, old: u8, new: u8, token: usize) -> io::Result<()> {
        for (bit, filter) in [(1, libc::EVFILT_READ), (2, libc::EVFILT_WRITE)] {
            if old & bit == new & bit { continue; }
            let change = libc::kevent {
                ident: fd as libc::uintptr_t,
                filter,
                flags: if new & bit != 0 { libc::EV_ADD | libc::EV_ENABLE } else { libc::EV_DELETE },
                fflags: 0,
                data: 0,
                udata: token as *mut libc::c_void,
            };
            let rc = unsafe { libc::kevent(self.fd.as_raw_fd(), &change, 1,
                std::ptr::null_mut(), 0, std::ptr::null()) };
            if rc < 0 {
                let error = io::Error::last_os_error();
                if new & bit == 0 && matches!(error.raw_os_error(), Some(libc::ENOENT | libc::EBADF)) {
                    continue;
                }
                return Err(error);
            }
        }
        Ok(())
    }

    pub fn wait(&mut self, timeout: Option<Duration>) -> io::Result<Vec<(usize, u8)>> {
        let mut events: [libc::kevent; 256] = unsafe { std::mem::zeroed() };
        let timeout = timeout.map(|d| libc::timespec {
            tv_sec: d.as_secs().min(libc::time_t::MAX as u64) as libc::time_t,
            tv_nsec: d.subsec_nanos() as libc::c_long,
        });
        let timeout_ptr = timeout.as_ref().map_or(std::ptr::null(), |t| t as *const _);
        let count = unsafe { libc::kevent(self.fd.as_raw_fd(), std::ptr::null(), 0,
            events.as_mut_ptr(), events.len() as i32, timeout_ptr) };
        if count < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::Interrupted { return Ok(Vec::new()); }
            return Err(error);
        }
        Ok(events[..count as usize].iter().map(|event| {
            let mask = if event.filter == libc::EVFILT_READ { 1 } else { 2 };
            (event.udata as usize, mask)
        }).collect())
    }
}
