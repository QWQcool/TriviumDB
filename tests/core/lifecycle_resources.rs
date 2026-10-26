use serde_json::json;
use std::path::{Path, PathBuf};
use std::time::Duration;
use triviumdb::database::{Config, StorageMode};
use triviumdb::storage::wal::SyncMode;
use triviumdb::{Database, TriviumError, VectorType};

fn directory(name: &str) -> PathBuf {
    static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
    let root = std::env::temp_dir().join(format!(
        "tdb 生命周期 {name}-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    std::fs::create_dir(&root).unwrap();
    root
}

fn assert_released(root: &Path) {
    #[cfg(windows)]
    for entry in std::fs::read_dir(root).unwrap() {
        use std::os::windows::fs::OpenOptionsExt;
        let path = entry.unwrap().path();
        if path.is_file() {
            std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .share_mode(0)
                .open(&path)
                .unwrap_or_else(|error| panic!("关闭后仍占用 {}：{error}", path.display()));
        }
    }
    let moved = root.with_extension("moved");
    std::fs::rename(root, &moved).expect("关闭后必须允许立即移动完整目录");
    std::fs::rename(&moved, root).unwrap();
}

fn run_close<T: VectorType + serde::Serialize + serde::de::DeserializeOwned>(name: &str) {
    for mode in [StorageMode::Mmap, StorageMode::Rom] {
        for asynchronous in [false, true] {
            let root = directory(name);
            let path = root.join("sample.tdb");
            let mut db = Database::<T>::open_with_config(
                &path.to_string_lossy(),
                Config {
                    dim: 4,
                    storage_mode: mode,
                    auto_build_quiver: false,
                    ..Default::default()
                },
            )
            .unwrap();
            db.insert_with_id(1, &[T::from_f32(1.0); 4], json!({"正文":"关闭回归"}))
                .unwrap();
            db.index_text(1, "关闭回归").unwrap();
            db.build_text_index().unwrap();
            if asynchronous {
                assert!(db.close_timeout(Duration::from_secs(5)).unwrap());
            } else {
                db.close().unwrap();
            }
            assert_released(&root);
            let mut reopened = Database::<T>::open(&path.to_string_lossy(), 4).unwrap();
            assert_eq!(reopened.node_count().unwrap(), 1);
            reopened.close().unwrap();
            std::fs::remove_dir_all(&root).unwrap();
            std::hint::black_box(db);
        }
    }
}

#[test]
fn 三种后端关闭后保留对象仍释放完整文件组() {
    run_close::<f32>("f32");
    run_close::<half::f16>("f16");
    run_close::<u64>("u64");
}

#[test]
fn 发布manifest后无变更关闭保持制品逐字节不变() {
    for asynchronous in [false, true] {
        let root = directory("manifest");
        let path = root.join("sample.tdb");
        let mut db = Database::<f32>::open(&path.to_string_lossy(), 4).unwrap();
        db.insert(&[1.0; 4], json!({})).unwrap();
        db.publish_generation_manifest("关闭制品").unwrap();
        let before = std::fs::read_dir(&root)
            .unwrap()
            .filter(|entry| {
                !entry
                    .as_ref()
                    .unwrap()
                    .path()
                    .to_string_lossy()
                    .ends_with(".lock")
            })
            .map(|entry| {
                let path = entry.unwrap().path();
                let data = std::fs::read(&path).unwrap();
                (path, data)
            })
            .collect::<Vec<_>>();
        if asynchronous {
            assert!(db.close_timeout(Duration::from_secs(5)).unwrap());
        } else {
            db.close().unwrap();
        }
        for (path, data) in &before {
            assert_eq!(std::fs::read(path).unwrap(), *data);
        }
        // 再次以可写模式打开当前格式，纯读取和关闭仍须保持已发布内容。
        let mut reopened = Database::<f32>::open_with_config(
            &path.to_string_lossy(),
            Config {
                dim: 4,
                auto_build_quiver: false,
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(reopened.node_count().unwrap(), 1);
        reopened.close().unwrap();
        for (path, data) in before {
            assert_eq!(std::fs::read(path).unwrap(), data);
        }
        let mut reader = Database::<f32>::open_immutable(&path.to_string_lossy(), 4).unwrap();
        assert_eq!(reader.node_count().unwrap(), 1);
        reader.close().unwrap();
        assert_released(&root);
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[test]
fn 已关闭数据库拒绝进入分组提交闭包() {
    let root = directory("closed-group");
    let mut db = Database::<f32>::open(&root.join("sample.tdb").to_string_lossy(), 4).unwrap();
    db.close().unwrap();
    let mut called = false;
    assert!(matches!(
        db.group_commit(|_| {
            called = true;
        }),
        Err(TriviumError::DatabaseClosed)
    ));
    assert!(!called);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn 关闭后所有数据读取返回关闭错误且诊断仍可读() {
    let root = directory("closed-reads");
    let mut db = Database::<f32>::open(&root.join("sample.tdb").to_string_lossy(), 4).unwrap();
    db.insert_with_id(1, &[1.0; 4], json!({})).unwrap();
    db.close().unwrap();
    macro_rules! closed {
        ($value:expr) => {
            assert!(matches!($value, Err(TriviumError::DatabaseClosed)));
        };
    }
    closed!(db.get(1));
    closed!(db.get_payload(1));
    closed!(db.get_edges(1));
    closed!(db.get_edge(1, 2, "关联"));
    closed!(db.get_incoming_edges(1, None));
    closed!(db.contains(1));
    closed!(db.node_count());
    closed!(db.all_node_ids());
    closed!(db.get_all_ids());
    closed!(db.neighbors(1, 1));
    closed!(db.neighbors_with_labels(1, 1, None));
    closed!(db.shortest_path(1, 2, 3, None));
    closed!(db.graph_stats());
    closed!(db.validate_graph());
    closed!(db.list_indexes());
    closed!(db.list_unique_indexes());
    closed!(db.index_info());
    closed!(db.clear_search_state());
    closed!(db.set_hook(triviumdb::NoopHook));
    assert_eq!(db.dim(), 4);
    assert_eq!(db.shutdown_status().phase, triviumdb::ShutdownPhase::Closed);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn 分组闭包内关闭立即报错且不阻塞原同步组() {
    let root = directory("group-close");
    let mut db = Database::<f32>::open(&root.join("sample.tdb").to_string_lossy(), 4).unwrap();
    db.group_commit(|db| {
        assert!(db.close().is_err());
        assert!(db.request_shutdown().is_err());
        db.insert_with_id(1, &[1.0; 4], json!({})).unwrap();
    })
    .unwrap();
    db.close().unwrap();
    assert_released(&root);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn 检查点后文本与属性索引变化必须在关闭时落盘() {
    let root = directory("dirty-index");
    let path = root.join("sample.tdb");
    let mut db = Database::<f32>::open(&path.to_string_lossy(), 4).unwrap();
    db.insert_with_id(1, &[1.0; 4], json!({"类别":"回归"}))
        .unwrap();
    db.flush().unwrap();
    db.index_text(1, "检查点 checkpoint 正文").unwrap();
    db.build_text_index().unwrap();
    db.create_index("类别").unwrap();
    db.close().unwrap();
    let reopened = Database::<f32>::open_with_config(
        &path.to_string_lossy(),
        Config {
            dim: 4,
            load_text_index: true,
            auto_build_quiver: false,
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(reopened.list_indexes().unwrap(), vec!["类别"]);
    assert!(
        !reopened
            .search_hybrid(
                Some("checkpoint"),
                None,
                &triviumdb::SearchConfig {
                    enable_text_hybrid_search: true,
                    min_score: 0.0,
                    ..Default::default()
                }
            )
            .unwrap()
            .is_empty()
    );
    drop(reopened);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn 分组提交异常子进程() {
    let Ok(path) = std::env::var("TDB_GROUP_UNWIND_CHILD") else {
        return;
    };
    let mut db = Database::<f32>::open_with_config(
        &path,
        Config {
            dim: 4,
            sync_mode: SyncMode::Full,
            auto_build_quiver: false,
            ..Default::default()
        },
    )
    .unwrap();
    db.insert_with_id(1, &[1.0; 4], json!({})).unwrap();
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _ = db.group_commit(|_| panic!("模拟调用方异常展开"));
    }));
    db.insert_with_id(2, &[2.0; 4], json!({})).unwrap();
    assert!(
        db.group_commit(|db| db.insert_with_id(3, &[3.0; 4], json!({})))
            .unwrap()
            .0
            .is_ok()
    );
    // 绕过析构，独立验证已经确认的 Full 写入可以恢复。
    std::process::exit(0);
}

#[test]
fn 分组异常后确认的Full写入跨进程恢复() {
    let root = directory("unwind");
    let path = root.join("sample.tdb");
    let executable = std::env::current_exe().unwrap();
    // Cargo 的仿真启动参数不会自动传给测试内部创建的子进程。
    let mut command = if std::env::var_os("TRIVIUM_TEST_QEMU_AARCH64").is_some() {
        let mut command = std::process::Command::new("qemu-aarch64");
        command
            .arg("-L")
            .arg("/usr/aarch64-linux-gnu")
            .arg(executable);
        command
    } else {
        std::process::Command::new(executable)
    };
    let status = command
        .args([
            "--exact",
            "lifecycle_resources::分组提交异常子进程",
            "--nocapture",
        ])
        .env("TDB_GROUP_UNWIND_CHILD", &path)
        .status()
        .unwrap();
    assert!(
        status.success(),
        "分组提交异常子进程启动或执行失败：{status}"
    );
    let mut db = Database::<f32>::open(&path.to_string_lossy(), 4).unwrap();
    for id in 1..=3 {
        assert!(
            db.contains(id).unwrap(),
            "Full 确认写入的节点 {id} 必须恢复"
        );
    }
    db.close().unwrap();
    std::fs::remove_dir_all(root).unwrap();
}
