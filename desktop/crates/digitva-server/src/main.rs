use digitva_db::OfflineDatabase;
use digitva_server::{build_router, AppState};
use std::net::SocketAddr;
use std::path::PathBuf;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
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
        });

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
    axum::serve(listener, app).await?;
    Ok(())
}
