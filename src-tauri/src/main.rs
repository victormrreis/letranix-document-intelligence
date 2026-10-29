#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // The independently launched loopback service owns processing and persistence.
    // No filesystem or shell IPC capabilities are granted to the webview.
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("Unable to start LETRANIX desktop window");
}
