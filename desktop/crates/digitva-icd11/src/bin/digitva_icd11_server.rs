use std::thread;
use std::time::Duration;

use digitva_icd11::{Icd11Engine, Icd11RuntimeConfig};

fn main() -> anyhow::Result<()> {
    let mut bind_url = std::env::var("DIGITVA_ICD11_BIND")
        .unwrap_or_else(|_| "http://127.0.0.1:8382".to_string());

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
                     Native Rust in-process DLL host for WHO ICD-11 2.6.0 + DORIS 1.2.0"
                );
                return Ok(());
            }
            _ => idx += 1,
        }
    }

    let cfg = Icd11RuntimeConfig::discover_with_bind(&bind_url)?;
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
