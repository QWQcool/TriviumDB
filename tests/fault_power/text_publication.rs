//! 文本发布提交点前后强杀，核对正文、关键词及已提交 WAL 数据。

use super::*;
use serde_json::json;
use std::time::{Duration, Instant};
use triviumdb::database::{Config, StorageMode};
use triviumdb::index::text::TextIndexDocument;

fn open(root: &std::path::Path, rom: bool) -> Database<f32> {
    Database::open_with_config(
        &root.join("data.tdb").to_string_lossy(),
        Config {
            dim: 4,
            storage_mode: if rom {
                StorageMode::Rom
            } else {
                StorageMode::Mmap
            },
            load_text_index: true,
            auto_build_quiver: false,
            sync_mode: triviumdb::storage::wal::SyncMode::Full,
            ..Default::default()
        },
    )
    .unwrap()
}

fn text_count(db: &Database<f32>, kind: &str, query: &str) -> usize {
    db.tql_nodes(&format!(
        "TEXT {kind} \"{query}\" TOP 10 AS hits WITH hits RETURN hits"
    ))
    .unwrap()
    .len()
}

#[test]
fn __text_publication_child() {
    let Ok(root) = std::env::var("TDB_TEXT_POWER_ROOT") else {
        return;
    };
    let root = std::path::PathBuf::from(root);
    let after = std::env::var("TDB_TEXT_POWER_AFTER").unwrap() == "1";
    let rom = std::env::var("TDB_TEXT_POWER_ROM").unwrap() == "1";
    let pause = pause_at(if after {
        ConcurrencyPoint::AfterPublicationCommitted
    } else {
        ConcurrencyPoint::AfterSidecarsPersisted
    });
    let work_root = root.clone();
    let worker = std::thread::spawn(move || {
        let mut db = open(&work_root, rom);
        db.insert_with_id(3, &[0., 0., 1., 0.], json!({"id":3}))
            .unwrap();
        db.rebuild_text_index(&[
            TextIndexDocument {
                id: 1,
                text: "updated".into(),
                keywords: vec!["新别名".into()],
            },
            TextIndexDocument {
                id: 2,
                text: "survivor".into(),
                keywords: vec![],
            },
            TextIndexDocument {
                id: 3,
                text: "inserted".into(),
                keywords: vec![],
            },
        ])
        .unwrap();
        db.flush().unwrap();
    });
    pause.wait_until_arrived();
    std::fs::write(root.join("ready"), "已到达发布阶段").unwrap();
    worker.join().unwrap();
}

#[test]
fn 文本发布强杀后恢复确定正文关键词及全部WAL节点() {
    for rom in [false, true] {
        for after in [false, true] {
            let root = std::env::temp_dir().join(format!(
                "tdb-text-power-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
            std::fs::create_dir(&root).unwrap();
            let mut db = open(&root, rom);
            db.insert_with_id(1, &[1., 0., 0., 0.], json!({"id":1}))
                .unwrap();
            db.insert_with_id(2, &[0., 1., 0., 0.], json!({"id":2}))
                .unwrap();
            db.index_text(1, "original").unwrap();
            db.index_keyword(1, "旧别名").unwrap();
            db.index_text(2, "survivor").unwrap();
            db.close().unwrap();
            let mut child = child_command()
                .args([
                    "--exact",
                    "text_publication::__text_publication_child",
                    "--nocapture",
                ])
                .env("TDB_TEXT_POWER_ROOT", &root)
                .env("TDB_TEXT_POWER_AFTER", if after { "1" } else { "0" })
                .env("TDB_TEXT_POWER_ROM", if rom { "1" } else { "0" })
                .spawn()
                .unwrap();
            let deadline = Instant::now() + Duration::from_secs(30);
            while !root.join("ready").exists() {
                assert!(
                    child.try_wait().unwrap().is_none(),
                    "文本发布子进程提前退出"
                );
                if Instant::now() >= deadline {
                    child.kill().unwrap();
                    child.wait().unwrap();
                    panic!("文本发布子进程未到达断点");
                }
                std::thread::sleep(Duration::from_millis(5));
            }
            child.kill().unwrap();
            child.wait().unwrap();
            if rom && after {
                let damaged = root.with_extension("damaged");
                std::fs::create_dir(&damaged).unwrap();
                for entry in std::fs::read_dir(&root).unwrap() {
                    let entry = entry.unwrap();
                    std::fs::copy(entry.path(), damaged.join(entry.file_name())).unwrap();
                }
                let path = damaged.join("data.tdb");
                let mut bytes = std::fs::read(&path).unwrap();
                let offset = u64::from_le_bytes(bytes[34..42].try_into().unwrap()) as usize;
                bytes[offset] ^= 1;
                std::fs::write(&path, &bytes).unwrap();
                let result = Database::<f32>::open(&path.to_string_lossy(), 4);
                assert!(
                    matches!(result, Err(triviumdb::TriviumError::CorruptedFile(reason)) if reason.contains("已提交 Rom"))
                );
                assert_eq!(std::fs::read(&path).unwrap(), bytes);
                assert!(damaged.join("data.tdb.publish").exists());
                for entry in std::fs::read_dir(&damaged).unwrap() {
                    std::fs::remove_file(entry.unwrap().path()).unwrap();
                }
                std::fs::remove_dir(&damaged).unwrap();
            }
            for _ in 0..2 {
                let mut db = open(&root, rom);
                assert_eq!(db.node_count().unwrap(), 3);
                assert_eq!(db.get_payload(3).unwrap().unwrap(), json!({"id":3}));
                assert_eq!(text_count(&db, "BM25", "survivor"), 1);
                assert_eq!(
                    text_count(&db, "BM25", if after { "updated" } else { "original" }),
                    1
                );
                assert_eq!(
                    text_count(&db, "BM25", if after { "original" } else { "updated" }),
                    0
                );
                assert_eq!(
                    text_count(&db, "AC", if after { "新别名" } else { "旧别名" }),
                    1
                );
                assert_eq!(
                    text_count(&db, "AC", if after { "旧别名" } else { "新别名" }),
                    0
                );
                assert_eq!(text_count(&db, "BM25", "inserted"), usize::from(after));
                db.flush().unwrap();
                db.close().unwrap();
            }
            // 目录由测试独占创建，仅清理直接子文件。
            for entry in std::fs::read_dir(&root).unwrap() {
                std::fs::remove_file(entry.unwrap().path()).unwrap();
            }
            std::fs::remove_dir(&root).unwrap();
        }
    }
}
