mod file_ops;
mod chat;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .plugin(tauri_plugin_fs::init())
    .plugin(tauri_plugin_dialog::init())
    .manage(chat::ChatState::new())
    .invoke_handler(tauri::generate_handler![
      file_ops::ingest_files,
      file_ops::run_compress,
      file_ops::run_convert,
      file_ops::convert_targets,
      chat::start_chat_backend,
      chat::send_message,
      chat::stop_chat_backend,
      chat::set_root,
      chat::get_settings,
      chat::set_setting,
      chat::list_convos,
      chat::load_convo,
      chat::new_convo,
      chat::rename_convo,
      chat::delete_convo
    ])
    .setup(|app| {
      #[cfg(debug_assertions)]
      {
        use tauri::Manager;
        let window = app.get_webview_window("main").unwrap();
        window.open_devtools();
      }
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
