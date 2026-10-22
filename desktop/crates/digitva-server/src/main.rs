use digitva_db::OfflineDatabase;
use digitva_server::{build_router, AppState};
use std::net::SocketAddr;
use std::path::PathBuf;

/// The WHO bundle's runtimeconfig asks .NET for server GC (one heap per core: 2.1 GB resident
/// against 654 MB with workstation GC). A station serves one computer, so it runs workstation GC
/// unless the operator set `DOTNET_gcServer` themselves. Set before any thread starts: the engine
/// loads .NET into this process later and reads the variable then.
fn main() -> anyhow::Result<()> {
    if std::env::var_os("DOTNET_gcServer").is_none() {
        // SAFETY: no other thread exists yet (the tokio runtime is built below).
        unsafe { std::env::set_var("DOTNET_gcServer", "0") };
    }
    tokio::runtime::Builder::new_multi_thread().enable_all().build()?.block_on(serve())
}

async fn serve() -> anyhow::Result<()> {
    let db_path = std::env::var("DIGITVA_DB_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("./digitva-offline-phc.sqlite"));

    let resource_dir = std::env::var("DIGITVA_RESOURCE_DIR")
        .map(PathBuf::from)
        .ok()
        .or_else(|| {
            let candidate = PathBuf::from("./resource");
            if candidate.exists() {
                Some(candidate)
            } else {
                None
            }
        });

    let port: u16 = std::env::var("DIGITVA_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(18420);

    let web_dist_dir = std::env::var("DIGITVA_WEB_DIST_DIR")
        .map(PathBuf::from)
        .ok()
        .or_else(|| {
            for candidate in [
                PathBuf::from("./web-dist"),
                PathBuf::from("../mobile/digitva-collect/dist"),
            ] {
                if candidate.join("index.html").is_file() {
                    return Some(candidate);
                }
            }
            None
        })
        // Absolute: the WHO engine changes the working directory while it starts.
        .map(|dir| dir.canonicalize().unwrap_or(dir));

    let db = OfflineDatabase::open_file(&db_path, resource_dir)?;
    let state = match std::env::var("DIGITVA_LAUNCH_TOKEN")
        .ok()
        .filter(|s| !s.trim().is_empty())
    {
        Some(tok) => AppState::with_launch_token(db, tok),
        None => AppState::new(db),
    }
    .with_web_dist_dir(web_dist_dir);
    let app = build_router(state);

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    println!("DigitVA Offline PHC Server listening on http://{addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;
    // The WHO ICD-11 engine's .NET host keeps foreground threads alive: leave explicitly.
    std::process::exit(0);
}

/// Ctrl-C or SIGTERM. Once the WHO engine has started, its .NET host lifetime takes these
/// signals over and they no longer reach here; the launcher must stop the station with SIGKILL.
async fn shutdown_signal() {
    let ctrl_c = tokio::signal::ctrl_c();
    #[cfg(unix)]
    {
        let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("install SIGTERM handler");
        tokio::select! {
            _ = ctrl_c => {}
            _ = term.recv() => {}
        }
    }
    #[cfg(not(unix))]
    let _ = ctrl_c.await;
}
