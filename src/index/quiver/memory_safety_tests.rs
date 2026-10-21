//! 原生测试、TSan 与 Miri 共用的并发邻接表安全契约回归。

use super::*;

#[test]
fn memory_safety_locked_row_updates_publish_complete_neighbors() {
    let adjacency = ConcurrentFlatAdj::new(4, 5);
    let locks = StripedSpinLocks::new(4, 2);
    std::thread::scope(|scope| {
        for worker in 0..2u32 {
            let adjacency = &adjacency;
            let locks = &locks;
            scope.spawn(move || {
                for _ in 0..8 {
                    let guard = locks.lock(0);
                    // 两个线程竞争同一行；持锁期间读取必须看见本次完整写入。
                    let neighbors = if worker == 0 { [1, 2] } else { [2, 3] };
                    adjacency.set_neighbors_with_guard(&guard, &neighbors);
                    std::thread::yield_now();
                    assert_eq!(adjacency.neighbors_with_guard(&guard), neighbors);
                }
            });
        }
    });
    let snapshot = adjacency.neighbors_locked(0, &locks);
    assert!(snapshot == [1, 2] || snapshot == [2, 3]);
    let mut frozen = FlatAdj::new(5);
    adjacency.freeze_into_flat(&mut frozen);
    assert_eq!(frozen.neighbors(0), snapshot);
    for node in 1..4 {
        assert!(frozen.neighbors(node).is_empty());
    }
}

#[test]
fn memory_safety_distinct_rows_and_capacity_survive_freeze() {
    let adjacency = ConcurrentFlatAdj::new(4, 4);
    let locks = StripedSpinLocks::new(4, 2);
    std::thread::scope(|scope| {
        for node in 0..4u32 {
            let adjacency = &adjacency;
            let locks = &locks;
            scope.spawn(move || {
                let guard = locks.lock(node);
                let neighbors = (0..4).filter(|&other| other != node).collect::<Vec<_>>();
                adjacency.set_neighbors_with_guard(&guard, &neighbors);
                assert_eq!(adjacency.neighbors_with_guard(&guard), neighbors);
                // 满行追加必须保持容量和已有内容；先清空后追加覆盖边界槽位。
                adjacency.push_neighbor_raw(node, node);
                assert_eq!(adjacency.neighbors_with_guard(&guard), neighbors);
                adjacency.set_neighbors_with_guard(&guard, &[]);
                for &neighbor in &neighbors {
                    adjacency.push_neighbor_raw(node, neighbor);
                }
            });
        }
    });
    let mut frozen = FlatAdj::new(4);
    adjacency.freeze_into_flat(&mut frozen);
    for node in 0..4u32 {
        let expected = (0..4).filter(|&other| other != node).collect::<Vec<_>>();
        assert_eq!(frozen.neighbors(node), expected);
    }
}
