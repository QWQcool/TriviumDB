#![allow(non_snake_case)]
//! 按领域聚合的集成测试入口。

#[cfg(feature = "test-hooks")]
mod deterministic_failpoint;
mod io_fault;
#[cfg(feature = "test-hooks")]
mod retained_publication;
mod sector_tearing;
#[cfg(feature = "test-hooks")]
mod text_publication;
mod wal_midwrite;

#[cfg(feature = "test-hooks")]
mod snapshot_shutdown;

#[cfg(feature = "test-hooks")]
mod lifecycle_resources;
