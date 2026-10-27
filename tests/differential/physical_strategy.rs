#![cfg(feature = "test-hooks")]

use super::canonical::canonicalize_rows;
use triviumdb::database::Database;
use triviumdb::test_hooks::{QueryExecutionStrategy, force_query_strategy};

fn database() -> (super::support::TestDir, Database<f32>) {
    let root = super::support::TestDir::new("physical_strategy");
    let path = root.file("sample.tdb");
    let reference = super::model::RefDatabase::fixture(48);
    let mut database = Database::<f32>::open(&path, 3).unwrap();
    super::matrix::seed(&mut database, &reference);
    (root, database)
}

#[test]
fn ForceSerial与ForceParallel执行结果一致() {
    let (_root, database) = database();
    let query = "FIND {rank: {$gte: 0}} AS seed WITH seed WHERE seed.active == true RETURN seed, seed.rank AS rank ORDER BY seed.rank DESC LIMIT 12";
    let serial = {
        let _guard = force_query_strategy(QueryExecutionStrategy::ForceSerial);
        canonicalize_rows(database.tql_values(query).unwrap(), true)
    };
    let parallel = {
        let _guard = force_query_strategy(QueryExecutionStrategy::ForceParallel);
        canonicalize_rows(database.tql_values(query).unwrap(), true)
    };
    assert_eq!(parallel, serial);
}

#[test]
fn ExpandRank融合与拆分物理路径结果一致() {
    let (_root, database) = database();
    let query = "FIND {rank: 0} AS seed WITH seed EXPAND seed [:related*1..4] AS related RANK related BY VECTOR [1, 1, 0] TOP 3 RETURN related";
    let fused = canonicalize_rows(database.tql_values(query).unwrap(), true);
    let split = {
        let _guard = force_query_strategy(QueryExecutionStrategy::DisableFusion);
        canonicalize_rows(database.tql_values(query).unwrap(), true)
    };
    assert_eq!(split, fused);
}
