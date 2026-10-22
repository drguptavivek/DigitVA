use std::path::PathBuf;
use std::thread;
use std::time::Duration;

use digitva_icd11::{
    DEFAULT_ICD11_RELEASE, Icd11Engine, Icd11RuntimeConfig, ensure_runtime_bundle,
    install_embedded_bridge_dll,
};

fn main() -> anyhow::Result<()> {
    let mut bind_url =
        std::env::var("DIGITVA_ICD11_BIND").unwrap_or_else(|_| "http://127.0.0.1:8382".to_string());

    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut idx = 0;
    while idx < args.len() {
        match args[idx].as_str() {
            "--bind" if idx + 1 < args.len() => {
                bind_url = args[idx + 1].clone();
                idx += 2;
            }
            "--port" if idx + 1 < args.len() => {
                bind_url = format!("http://127.0.0.1:{}", args[idx + 1]);
                idx += 2;
            }
            "--help" | "-h" => {
                println!(
                    "digitva-icd11-server [--bind http://127.0.0.1:8382] [--port 8382]\n\
                     Native Rust in-process DLL host for WHO ICD-11 2.6.0 + DORIS 1.2.0\n\
                     DIGITVA_ICD11_RUNTIME_DIR=<dir>: bootstrap/verify the WHO runtime there"
                );
                return Ok(());
            }
            _ => idx += 1,
        }
    }

    let cfg = match std::env::var_os("DIGITVA_ICD11_RUNTIME_DIR") {
        Some(root) => runtime_config_in(PathBuf::from(root), bind_url)?,
        None => Icd11RuntimeConfig::discover_with_bind(&bind_url)?,
    };
    let engine = Icd11Engine::init_global(cfg)?;
    println!(
        "digitva-icd11-server listening on {} (release {})",
        engine.base_url(),
        engine.default_release()
    );

    loop {
        thread::sleep(Duration::from_secs(3600));
    }
}

/// Bootstrap (first start) or reuse the WHO runtime under `root` (`icdapi/` + `data/`),
/// SHA-256 verified. Used by the server container, whose root is a named volume.
///
/// The bridge is rewritten from the embedded bytes first: `ensure_runtime_bundle` keeps an
/// existing bridge, so a stale one would fail its pin on every start (digitva-ke83.12).
///
/// `ensure_runtime_bundle` only checks that marker files exist, so a first start killed
/// mid-download would fail verification on every restart; on failure, wipe and fetch once more.
fn runtime_config_in(root: PathBuf, bind_url: String) -> anyhow::Result<Icd11RuntimeConfig> {
    install_embedded_bridge_dll(&root.join("icdapi"))?;
    let (bundle_dir, data_dir) = match ensure_runtime_bundle(&root) {
        Ok(dirs) => dirs,
        Err(err) => {
            eprintln!(
                "WHO runtime under {} failed verification ({err}); re-downloading",
                root.display()
            );
            for sub in ["icdapi", "data"] {
                let dir = root.join(sub);
                if dir.exists() {
                    std::fs::remove_dir_all(&dir)?;
                }
            }
            install_embedded_bridge_dll(&root.join("icdapi"))?;
            ensure_runtime_bundle(&root)?
        }
    };
    Ok(Icd11RuntimeConfig {
        bundle_dir,
        data_dir,
        bind_url,
        default_release: DEFAULT_ICD11_RELEASE.to_string(),
    })
}
