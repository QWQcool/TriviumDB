//! 快照目录提交点前后的真实子进程强杀。

use super::*;
use std::time::{Duration, Instant};
use triviumdb::storage::snapshot::verify_snapshot;

#[test]
fn __snapshot_power_child() {
    let Ok(root) = std::env::var("TDB_SNAPSHOT_POWER_ROOT") else {
        return;
    };
    let root = std::path::PathBuf::from(root);
    let point = if std::env::var("TDB_SNAPSHOT_POWER_AFTER").unwrap() == "1" {
        ConcurrencyPoint::AfterSnapshotPublish
    } else {
        ConcurrencyPoint::BeforeSnapshotPublish
    };
    let pause = pause_at(point);
    let work_root = root.clone();
    let worker = std::thread::spawn(move || {
        let mut db =
            Database::<f32>::open(&work_root.join("live.tdb").to_string_lossy(), 4).unwrap();
        db.insert_with_id(
            1,
            &[1.0, 2.0, 3.0, 4.0],
            serde_json::json!({"generation": "exact"}),
        )
        .unwrap();
        db.create_snapshot(&work_root.join("snapshot").to_string_lossy(), "power")
            .unwrap();
    });
    pause.wait_until_arrived();
    std::fs::write(root.join("ready"), b"ready").unwrap();
    worker.join().unwrap();
}

#[test]
fn 快照提交点强杀后要么无目标要么完整可恢复() {
    for after in [false, true] {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("tdb_snapshot_power_{}_{nonce}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        let mut child = child_command()
            .args(["--exact", "snapshot::__snapshot_power_child", "--nocapture"])
            .env("TDB_SNAPSHOT_POWER_ROOT", &root)
            .env("TDB_SNAPSHOT_POWER_AFTER", if after { "1" } else { "0" })
            .spawn()
            .unwrap();
        let deadline = Instant::now() + Duration::from_secs(20);
        while !root.join("ready").exists() {
            assert!(child.try_wait().unwrap().is_none(), "快照子进程提前结束");
            if Instant::now() >= deadline {
                child.kill().unwrap();
                child.wait().unwrap();
                panic!("快照子进程未到达提交点");
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        child.kill().unwrap();
        child.wait().unwrap();
        let snapshot = root.join("snapshot");
        if after {
            assert_eq!(
                verify_snapshot(&snapshot.to_string_lossy())
                    .unwrap()
                    .node_count,
                1
            );
        } else {
            assert!(!snapshot.exists());
            let mut source =
                Database::<f32>::open(&root.join("live.tdb").to_string_lossy(), 4).unwrap();
            source
                .create_snapshot(&snapshot.to_string_lossy(), "retry")
                .unwrap();
            source.close().unwrap();
        }
        let mut reader =
            Database::<f32>::open_immutable(&snapshot.join("database.tdb").to_string_lossy(), 4)
                .unwrap();
        assert_eq!(reader.node_count(), 1);
        assert_eq!(
            reader.get_payload(1).unwrap(),
            serde_json::json!({"generation": "exact"})
        );
        assert_eq!(reader.get(1).unwrap().vector, vec![1.0, 2.0, 3.0, 4.0]);
        reader.close().unwrap();
    }
}
