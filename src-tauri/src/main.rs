#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! Desktop shell. The loopback Python service owns processing and persistence; this
//! process only makes sure it is running and shows it in a window. The webview gets
//! no filesystem, shell or IPC capabilities.

use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread::sleep;
use std::time::{Duration, Instant};

const ADDRESS: &str = "127.0.0.1:8795";

/// True when a LETRANIX service (not some other program) answers on the port.
fn service_ready() -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(&ADDRESS.parse().unwrap(), Duration::from_millis(300))
    else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let request = format!("GET /api/health HTTP/1.1\r\nHost: {ADDRESS}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut body = String::new();
    let _ = stream.read_to_string(&mut body);
    body.starts_with("HTTP/1.1 200") && body.contains("\"product\":\"LETRANIX\"")
}

/// Project root: LETRANIX_HOME, or the nearest ancestor of the executable with a .venv.
fn project_root() -> Option<PathBuf> {
    if let Ok(home) = std::env::var("LETRANIX_HOME") {
        return Some(PathBuf::from(home));
    }
    let exe = std::env::current_exe().ok()?;
    exe.ancestors()
        .find(|dir| python_in(dir).is_some() && dir.join("letranix").is_dir())
        .map(Path::to_path_buf)
}

fn python_in(root: &Path) -> Option<PathBuf> {
    [".venv/Scripts/python.exe", ".venv/bin/python"]
        .iter()
        .map(|p| root.join(p))
        .find(|p| p.is_file())
}

fn start_service() -> Option<Child> {
    let root = project_root()?;
    let python = std::env::var("LETRANIX_PYTHON").map(PathBuf::from).ok().or_else(|| python_in(&root))?;
    let mut command = Command::new(python);
    command
        .args(["-m", "letranix", "serve"])
        .current_dir(&root)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let child = command.spawn().ok()?;
    let started = Instant::now();
    while started.elapsed() < Duration::from_secs(60) {
        if service_ready() {
            break;
        }
        sleep(Duration::from_millis(250));
    }
    Some(child)
}

fn main() {
    // Reuse a running service; otherwise start one and own its lifetime.
    let child = if service_ready() { None } else { start_service() };
    if child.is_none() && !service_ready() {
        eprintln!("LETRANIX service not reachable on {ADDRESS}; start it with `python -m letranix serve`.");
    }
    let owned = Mutex::new(child);
    tauri::Builder::default()
        .build(tauri::generate_context!())
        .expect("Unable to start LETRANIX desktop window")
        .run(move |_, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(mut c) = owned.lock().unwrap().take() {
                    let _ = c.kill();
                    let _ = c.wait();
                }
            }
        });
}
