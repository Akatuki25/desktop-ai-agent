// Tauri application library entry point.
//
// Phase 0 keeps things minimal: open the main window configured in
// tauri.conf.json. The Python daemon is spawned from a separate module
// that will land alongside session/chat plumbing.

pub fn run() {
    tauri::Builder::default()
        .setup(|_app| Ok(()))
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
