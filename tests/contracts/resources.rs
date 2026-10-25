//! Rust/Python/Node 共用的资源配额与关闭回收契约。

use serde_json::{Value, json};
use triviumdb::database::Config;
use triviumdb::{
    Database, ResourceLimits, ResourceRuntime, ResourceStats, TriviumError, VectorType,
};

fn check(stats: ResourceStats, expected: &Value) {
    let actual = serde_json::to_value(stats).unwrap();
    for (field, value) in expected.as_object().unwrap() {
        assert_eq!(&actual[field], value, "{field}");
    }
    assert_eq!(actual["active_tasks"], 0);
    assert_eq!(actual["reserved_workspace_bytes"], 0);
    assert!(actual["allocated_worker_threads"].as_u64().unwrap() <= 2);
    assert!(actual["peak_worker_threads"].as_u64().unwrap() <= 2);
}

fn run<T: VectorType + serde::Serialize + serde::de::DeserializeOwned>(case: &Value, dtype: &str) {
    let dir = std::env::temp_dir().join(format!(
        "triviumdb_resource_contract_{}_{dtype}",
        std::process::id()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    let path = |name: &str| {
        dir.join(format!("{name}.tdb"))
            .to_string_lossy()
            .into_owned()
    };
    let mb = 1024 * 1024;
    let runtime = ResourceRuntime::new(ResourceLimits {
        maintenance_memory_limit: case["runtime"]["maintenance_memory_limit_mb"]
            .as_u64()
            .unwrap() as usize
            * mb,
        memory_limit: case["runtime"]["memory_limit_mb"].as_u64().unwrap() as usize * mb,
        max_threads: case["runtime"]["max_threads"].as_u64().unwrap() as usize,
        max_active_tasks: case["runtime"]["max_active_tasks"].as_u64().unwrap() as usize,
    })
    .unwrap();
    let config = |memory: &Value| Config {
        dim: case["database"]["dim"].as_u64().unwrap() as usize,
        memory_limit: memory.as_u64().unwrap() as usize * mb,
        auto_build_quiver: false,
        ..Default::default()
    };
    let vector = case["vector"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| T::from_f32(value.as_f64().unwrap() as f32))
        .collect::<Vec<_>>();
    let mut first = Database::<T>::open_with_runtime(
        &path("first"),
        config(&case["database"]["memory_limit_mb"]),
        runtime.clone(),
    )
    .unwrap();
    let mut second = Database::<T>::open_with_runtime(
        &path("second"),
        config(&case["database"]["memory_limit_mb"]),
        runtime.clone(),
    )
    .unwrap();
    check(runtime.stats(), &case["expected"]["opened"]);
    assert!(matches!(
        Database::<T>::open_with_runtime(
            &path("rejected"),
            config(&case["overbook_mb"]),
            runtime.clone()
        ),
        Err(TriviumError::ResourceBudgetExceeded {
            resource: "memory_bytes",
            ..
        })
    ));
    assert!(!std::path::Path::new(&path("rejected")).exists());
    assert!(!std::path::Path::new(&format!("{}.lock", path("rejected"))).exists());
    check(runtime.stats(), &case["expected"]["opened"]);
    first
        .set_memory_limit(case["resize_mb"].as_u64().unwrap() as usize * mb)
        .unwrap();
    check(runtime.stats(), &case["expected"]["resized"]);
    assert!(matches!(
        second.set_memory_limit(case["failed_resize_mb"].as_u64().unwrap() as usize * mb),
        Err(TriviumError::ResourceBudgetExceeded { .. })
    ));
    check(runtime.stats(), &case["expected"]["resized"]);
    first
        .set_memory_limit(case["database"]["memory_limit_mb"].as_u64().unwrap() as usize * mb)
        .unwrap();
    first
        .insert_with_id(101, &vector, json!({"owner": "first"}))
        .unwrap();
    second
        .insert_with_id(202, &vector, json!({"owner": "second"}))
        .unwrap();
    assert_eq!(first.search_exact(&vector, 1).unwrap()[0].id, 101);
    assert_eq!(second.search_exact(&vector, 1).unwrap()[0].id, 202);
    first.close().unwrap();
    check(runtime.stats(), &case["expected"]["closed_one"]);
    assert!(matches!(
        first.insert(&vector, json!({})),
        Err(TriviumError::DatabaseClosed)
    ));
    let mut replacement = Database::<T>::open_with_runtime(
        &path("replacement"),
        config(&case["replacement_mb"]),
        runtime.clone(),
    )
    .unwrap();
    check(runtime.stats(), &case["expected"]["replaced"]);
    second.close().unwrap();
    replacement.close().unwrap();
    check(runtime.stats(), &case["expected"]["closed_all"]);
}

#[test]
fn 共享资源json契约覆盖三种向量后端() {
    let case: Value = serde_json::from_str(include_str!("resource_cases.json")).unwrap();
    assert_eq!(case["schema_version"], 1);
    run::<f32>(&case, "f32");
    run::<half::f16>(&case, "f16");
    run::<u64>(&case, "u64");
}
