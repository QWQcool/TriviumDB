//! Mmap/Rom、文本/属性/图与冷载荷的快照往返检查。

use triviumdb::Database;
use triviumdb::database::{Config, StorageMode};
use triviumdb::storage::snapshot::{restore_snapshot, verify_snapshot};

#[test]
fn 两种存储模式的完整索引快照恢复后事实一致() {
    for (index, mode) in [StorageMode::Mmap, StorageMode::Rom]
        .into_iter()
        .enumerate()
    {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "tdb_snapshot_modes_{}_{nonce}_{index}",
            std::process::id()
        ));
        std::fs::create_dir(&root).unwrap();
        let mut db = Database::<f32>::open_with_config(
            &root.join("live.tdb").to_string_lossy(),
            Config {
                dim: 3,
                storage_mode: mode,
                load_text_index: true,
                auto_build_quiver: false,
                ..Default::default()
            },
        )
        .unwrap();
        for id in 1..=32u64 {
            db.insert_with_id(
                id,
                &[id as f32, 2.0, 3.0],
                serde_json::json!({"id": id, "name": format!("entity-{id}")}),
            )
            .unwrap();
            db.index_text(id, "快照全文检索测试").unwrap();
            db.index_keyword(id, "快照").unwrap();
            if id > 1 {
                db.link(id - 1, id, "next", 1.0).unwrap();
            }
        }
        db.build_text_index().unwrap();
        db.create_unique_index("name").unwrap();
        db.build_quiver_index(None).unwrap();
        let snapshot = root.join("snapshot");
        db.create_snapshot(&snapshot.to_string_lossy(), "all-indexes")
            .unwrap();
        db.delete(2).unwrap();
        let restored = root.join("restored");
        restore_snapshot(&snapshot.to_string_lossy(), &restored.to_string_lossy()).unwrap();
        let mut reader = Database::<f32>::open_with_config(
            &restored.join("database.tdb").to_string_lossy(),
            Config {
                dim: 3,
                access_mode: triviumdb::database::AccessMode::Immutable,
                load_text_index: true,
                auto_build_quiver: false,
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(reader.node_count(), 32);
        for id in 1..=32u64 {
            let node = reader.get(id).unwrap();
            assert_eq!(node.vector, vec![id as f32, 2.0, 3.0]);
            assert_eq!(
                node.payload,
                serde_json::json!({"id": id, "name": format!("entity-{id}")})
            );
            if id < 32 {
                assert_eq!(reader.get_edges(id)[0].target_id, id + 1);
            }
        }
        assert_eq!(
            reader
                .indexed_lookup(&[("name".into(), serde_json::json!("entity-2"))], 10)
                .unwrap(),
            vec![2]
        );
        assert_eq!(
            reader
                .tql(r#"TEXT AC "快照" TOP 32 AS hits WITH hits RETURN hits"#)
                .unwrap()
                .len(),
            32
        );
        reader.close().unwrap();
        verify_snapshot(&restored.to_string_lossy()).unwrap();
        db.close().unwrap();
    }
}
