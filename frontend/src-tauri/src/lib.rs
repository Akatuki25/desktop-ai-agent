//! Tauri application shell.
//!
//! Phase 0 wiring: on startup spawn the Python agent daemon as a child
//! process, read its first stdout line to learn the bound WebSocket
//! port, then expose that + the shared auth token to the frontend via
//! the `daemon_info` command.
//!
//! The daemon is resolved in dev mode by looking for
//! `<repo>/agent/.venv/Scripts/python.exe` relative to this crate's
//! manifest dir. Production bundling will bring its own path later.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{Manager, RunEvent};
use uuid::Uuid;

#[derive(Clone, serde::Serialize)]
struct DaemonInfo {
    port: u16,
    token: String,
}

struct DaemonHandle(Mutex<Option<Child>>);

#[tauri::command]
fn daemon_info(state: tauri::State<DaemonInfo>) -> DaemonInfo {
    state.inner().clone()
}

fn resolve_python() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dev_venv = manifest
        .join("..")
        .join("..")
        .join("agent")
        .join(".venv")
        .join("Scripts")
        .join("python.exe");
    if dev_venv.exists() {
        return dev_venv;
    }
    PathBuf::from("python")
}

fn spawn_daemon(token: &str) -> std::io::Result<(u16, Child)> {
    let python = resolve_python();
    eprintln!("[tauri] spawning daemon: {}", python.display());

    // Inherit LLAMA_SERVER_URL / LLAMA_SERVER_BIN / LLAMA_MODEL /
    // AGENT_DATA_DIR from the shell that started Tauri (activate.ps1
    // sets these). std::process::Command already inherits the parent
    // environment by default on Windows, so no explicit env() calls
    // are required here — this comment exists only to make the
    // dependency explicit.
    let mut child = Command::new(&python)
        .args(["-m", "agent", "--port", "0", "--token", token])
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::Other, "daemon stdout missing"))?;
    let mut reader = BufReader::new(stdout);
    let mut line = String::new();
    reader.read_line(&mut line)?;
    let line = line.trim().to_string();
    eprintln!("[tauri] daemon ready line: {}", line);

    let ready: serde_json::Value = serde_json::from_str(&line)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
    let port = ready["port"]
        .as_u64()
        .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::InvalidData, "no port in ready event"))?
        as u16;

    // Drain the rest of stdout in a background thread so pipe
    // backpressure never stalls the daemon.
    std::thread::spawn(move || {
        let mut buf = String::new();
        loop {
            buf.clear();
            match reader.read_line(&mut buf) {
                Ok(0) => break,
                Ok(_) => eprintln!("[daemon] {}", buf.trim_end()),
                Err(_) => break,
            }
        }
    });

    Ok((port, child))
}

pub fn run() {
    let token = Uuid::new_v4().simple().to_string();

    tauri::Builder::default()
        .setup({
            let token = token.clone();
            move |app| {
                let (port, child) = spawn_daemon(&token).map_err(|e| {
                    eprintln!("[tauri] failed to spawn agent daemon: {e}");
                    Box::<dyn std::error::Error>::from(format!(
                        "failed to spawn agent daemon: {e}"
                    ))
                })?;
                app.manage(DaemonInfo {
                    port,
                    token: token.clone(),
                });
                app.manage(DaemonHandle(Mutex::new(Some(child))));
                Ok(())
            }
        })
        .invoke_handler(tauri::generate_handler![daemon_info])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(handle) = app.try_state::<DaemonHandle>() {
                    if let Ok(mut guard) = handle.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                }
            }
        });
}
