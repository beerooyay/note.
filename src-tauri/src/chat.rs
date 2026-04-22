use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;

use tauri::{AppHandle, Emitter};

pub struct ChatState {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
}

impl ChatState {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            stdin: Mutex::new(None),
        }
    }
}

fn find_note() -> Result<(PathBuf, PathBuf), String> {
    let mut roots = Vec::new();

    if let Ok(env) = std::env::var("NOTE_PY_DIR") {
        roots.push(PathBuf::from(env));
    }
    if let Ok(dir) = std::env::current_dir() {
        roots.push(dir);
    }
    if let Ok(exe) = std::env::current_exe() {
        let mut cur = exe.parent().map(|p| p.to_path_buf());
        for _ in 0..6 {
            if let Some(path) = cur {
                roots.push(path.clone());
                cur = path.parent().map(|p| p.to_path_buf());
            }
        }
    }
    roots.push(PathBuf::from("/Users/beerooyay/dev/note-app"));

    for root in roots {
        let script = root.join("note.py");
        if script.is_file() {
            return Ok((root, script));
        }
    }

    Err("could not locate note.py".to_string())
}

#[tauri::command]
pub fn start_chat_backend(
    app_handle: AppHandle,
    state: tauri::State<ChatState>,
) -> Result<(), String> {
    let mut child_guard = state.child.lock().map_err(|_| "mutex poisoned")?;
    if child_guard.is_some() {
        return Ok(());
    }

    let (root, script) = find_note()?;

    let mut child = Command::new("python3")
        .arg(script)
        .arg("--stream")
        .current_dir(root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to spawn note.py: {}", e))?;

    let stdout = child.stdout.take().ok_or("no stdout")?;
    let stderr = child.stderr.take().ok_or("no stderr")?;
    let stdin = child.stdin.take().ok_or("no stdin")?;

    let app_out = app_handle.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines().map_while(Result::ok) {
            if let Some(token) = line.strip_prefix("TOKEN:") {
                let _ = app_out.emit("chat:token", format!("{}\n", token));
            } else if let Some(stats) = line.strip_prefix("STATS:") {
                let _ = app_out.emit("chat:stats", stats.to_string());
            } else if let Some(settings) = line.strip_prefix("SETTINGS:") {
                let _ = app_out.emit("chat:settings", settings.to_string());
            } else if let Some(convos) = line.strip_prefix("CONVOS:") {
                let _ = app_out.emit("chat:convos", convos.to_string());
            } else if let Some(loaded) = line.strip_prefix("LOADED:") {
                let _ = app_out.emit("chat:loaded", loaded.to_string());
            } else if line == "DONE" {
                let _ = app_out.emit("chat:done", ());
            }
        }
    });

    let app_err = app_handle.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines().map_while(Result::ok) {
            let _ = app_err.emit("chat:err", line);
        }
    });

    *child_guard = Some(child);
    *state.stdin.lock().map_err(|_| "mutex poisoned")? = Some(stdin);
    Ok(())
}

#[tauri::command]
pub fn send_message(message: String, state: tauri::State<ChatState>) -> Result<(), String> {
    let mut stdin_guard = state.stdin.lock().map_err(|_| "mutex poisoned")?;
    let stdin = stdin_guard.as_mut().ok_or("backend not started")?;
    writeln!(stdin, "{}", message).map_err(|e| e.to_string())?;
    stdin.flush().map_err(|e| e.to_string())?;
    Ok(())
}

fn write_line(state: &tauri::State<ChatState>, line: &str) -> Result<(), String> {
    let mut stdin_guard = state.stdin.lock().map_err(|_| "mutex poisoned")?;
    let stdin = stdin_guard.as_mut().ok_or("backend not started")?;
    writeln!(stdin, "{}", line).map_err(|e| e.to_string())?;
    stdin.flush().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn set_root(path: String, state: tauri::State<ChatState>) -> Result<(), String> {
    write_line(&state, &format!("/root {}", path))
}

#[tauri::command]
pub fn get_settings(state: tauri::State<ChatState>) -> Result<(), String> {
    write_line(&state, "/settings")
}

#[tauri::command]
pub fn set_setting(key: String, value: String, state: tauri::State<ChatState>) -> Result<(), String> {
    write_line(&state, &format!("/set {} {}", key, value))
}

#[tauri::command]
pub fn list_convos(state: tauri::State<ChatState>) -> Result<(), String> {
    write_line(&state, "/convos")
}

#[tauri::command]
pub fn load_convo(id: i64, state: tauri::State<ChatState>) -> Result<(), String> {
    write_line(&state, &format!("/load {}", id))
}

#[tauri::command]
pub fn new_convo(state: tauri::State<ChatState>) -> Result<(), String> {
    write_line(&state, "/new")
}

#[tauri::command]
pub fn rename_convo(id: i64, title: String, state: tauri::State<ChatState>) -> Result<(), String> {
    let clean = title.replace('\n', " ").trim().to_string();
    if clean.is_empty() { return Ok(()); }
    write_line(&state, &format!("/rename {} {}", id, clean))
}

#[tauri::command]
pub fn delete_convo(id: i64, state: tauri::State<ChatState>) -> Result<(), String> {
    write_line(&state, &format!("/delete {}", id))
}

#[tauri::command]
pub fn stop_chat_backend(state: tauri::State<ChatState>) -> Result<(), String> {
    let mut child_guard = state.child.lock().map_err(|_| "mutex poisoned")?;
    if let Some(mut child) = child_guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    *state.stdin.lock().map_err(|_| "mutex poisoned")? = None;
    Ok(())
}
