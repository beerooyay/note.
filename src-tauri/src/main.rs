// prevents IDE warnings about dead code
#[cfg_attr(mobile, tauri::mobile_entry_point)]
fn main() {
  note_app::run()
}