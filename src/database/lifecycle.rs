//! 可观测、可重试的关闭协议；超时只结束等待，不撤销正在持久化的任务。

use super::*;
use crate::storage::compaction::ScheduledMaintenance;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ShutdownPhase {
    Open,
    Draining,
    Flushing,
    Failed,
    Closed,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct ShutdownStatus {
    pub phase: ShutdownPhase,
    pub active_operations: usize,
    pub last_error: Option<String>,
}

impl<T: VectorType> Database<T> {
    pub fn shutdown_status(&self) -> ShutdownStatus {
        let state = lock_or_recover(&self.lifecycle.0);
        ShutdownStatus {
            phase: state.shutdown_phase,
            active_operations: state.active_operations,
            last_error: state.shutdown_last_error.clone(),
        }
    }

    /// 拒绝新操作并登记关闭任务。已有操作和后台维护先排空，完成后才释放文件锁。
    pub fn request_shutdown(&mut self) -> Result<ShutdownStatus> {
        reject_hook_reentrant_write()?;
        let mut state = lock_or_recover(&self.lifecycle.0);
        if state.lifecycle == DatabaseLifecycle::Closed
            || state.shutdown_job.is_some()
            || state.shutdown_error.is_some()
        {
            drop(state);
            return Ok(self.shutdown_status());
        }
        let previous = state.lifecycle;
        state.lifecycle = DatabaseLifecycle::Closing;
        state.shutdown_phase = ShutdownPhase::Draining;
        state.shutdown_last_error = None;
        if let Some(background) = &self.compaction {
            background.request_stop();
        }
        let background = self.compaction.take();
        let work = Arc::new(CloseWork {
            background,
            memtable: self.memtable.clone(),
            wal: self.wal.clone(),
            file_lock: self._lock_file.clone(),
            lifecycle: self.lifecycle.clone(),
            path: self.db_path.clone(),
            mode: self.storage_mode,
            access: self.access_mode,
            result: Mutex::new(None),
            #[cfg(feature = "test-hooks")]
            io_failure: crate::test_hooks::current_io_failure(),
        });
        let ready_work = work.clone();
        let completed_work = work.clone();
        let scheduled = ScheduledMaintenance::schedule(
            self.resource_runtime.clone(),
            move || {
                lock_or_recover(&ready_work.lifecycle.0).active_operations == 0
                    && !ready_work
                        .background
                        .as_ref()
                        .is_some_and(|b| b.is_running())
            },
            move || work.execute(),
            move || completed_work.complete(),
        );
        match scheduled {
            Ok(job) => state.shutdown_job = Some(job),
            Err(error) => {
                state.lifecycle = previous;
                state.shutdown_phase = if previous == DatabaseLifecycle::Open {
                    ShutdownPhase::Open
                } else {
                    ShutdownPhase::Failed
                };
                return Err(error);
            }
        }
        drop(state);
        Ok(self.shutdown_status())
    }

    /// 返回 true 表示关闭完成，false 表示等待期限耗尽；false 后任务仍持有数据和锁。
    pub fn close_timeout(&mut self, timeout: Duration) -> Result<bool> {
        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or_else(|| TriviumError::InvalidInput("关闭等待期限超出时钟范围".into()))?;
        self.request_shutdown()?;
        self.wait_for_shutdown(Some(deadline))
    }

    pub(super) fn wait_for_shutdown(&self, deadline: Option<Instant>) -> Result<bool> {
        let mut state = lock_or_recover(&self.lifecycle.0);
        loop {
            if state.lifecycle == DatabaseLifecycle::Closed {
                return Ok(true);
            }
            if let Some(error) = state.shutdown_error.take() {
                return Err(error);
            }
            if let Some(deadline) = deadline {
                let remaining = deadline.saturating_duration_since(Instant::now());
                if remaining.is_zero() {
                    return Ok(false);
                }
                state = self
                    .lifecycle
                    .1
                    .wait_timeout(state, remaining)
                    .unwrap_or_else(|e| e.into_inner())
                    .0;
            } else {
                state = self
                    .lifecycle
                    .1
                    .wait(state)
                    .unwrap_or_else(|e| e.into_inner());
            }
        }
    }
}

struct CloseWork<T: VectorType> {
    background: Option<CompactionThread>,
    memtable: Arc<RwLock<MemTable<T>>>,
    wal: Arc<Mutex<Wal>>,
    file_lock: Arc<Mutex<Option<std::fs::File>>>,
    lifecycle: Arc<(Mutex<LifecycleState>, Condvar)>,
    path: String,
    mode: StorageMode,
    access: AccessMode,
    result: Mutex<Option<Result<()>>>,
    #[cfg(feature = "test-hooks")]
    io_failure: Option<crate::test_hooks::IoPoint>,
}

impl<T: VectorType> CloseWork<T> {
    fn execute(&self) -> Result<bool> {
        lock_or_recover(&self.lifecycle.0).shutdown_phase = ShutdownPhase::Flushing;
        #[cfg(feature = "test-hooks")]
        let _injection = self.io_failure.map(crate::test_hooks::fail_io_at);
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> Result<()> {
            let mut mt = write_or_recover(&self.memtable);
            if self.access == AccessMode::ReadWrite {
                file_format::save(&mut mt, &self.path, self.mode)?;
                lock_or_recover(&self.wal).clear()?;
            }
            mt.release_resource_storage();
            lock_or_recover(&self.file_lock).take();
            Ok(())
        }))
        .unwrap_or_else(|_| {
            Err(TriviumError::ShutdownFailed {
                reason: "关闭工作发生异常展开".into(),
            })
        });
        let failed = result.is_err();
        *lock_or_recover(&self.result) = Some(result);
        if failed {
            Err(TriviumError::ShutdownFailed {
                reason: "关闭未完成，可读取状态并重试".into(),
            })
        } else {
            Ok(true)
        }
    }

    fn complete(&self) {
        let result = lock_or_recover(&self.result).take().unwrap_or_else(|| {
            Err(TriviumError::ShutdownFailed {
                reason: "关闭任务未提供完成结果".into(),
            })
        });
        let mut state = lock_or_recover(&self.lifecycle.0);
        match result {
            Ok(()) => {
                state.lifecycle = DatabaseLifecycle::Closed;
                state.shutdown_phase = ShutdownPhase::Closed;
            }
            Err(error) => {
                state.shutdown_phase = ShutdownPhase::Failed;
                state.shutdown_last_error = Some(error.to_string());
                state.shutdown_error = Some(error);
            }
        }
        state.shutdown_job.take();
        self.lifecycle.1.notify_all();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::resources::{ResourceLimits, ResourceRuntime};
    use std::sync::mpsc;

    fn open() -> (Database<f32>, ResourceRuntime) {
        static NONCE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
        let path = std::env::temp_dir().join(format!(
            "tdb_shutdown_{}_{}.tdb",
            std::process::id(),
            NONCE.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        let runtime = ResourceRuntime::new(ResourceLimits {
            memory_limit: 64 * 1024 * 1024,
            maintenance_memory_limit: 8 * 1024 * 1024,
            max_threads: 1,
            max_active_tasks: 1,
        })
        .unwrap();
        let mut db = Database::open_with_runtime(
            &path.to_string_lossy(),
            Config {
                dim: 3,
                memory_limit: 8 * 1024 * 1024,
                auto_build_quiver: false,
                ..Default::default()
            },
            runtime.clone(),
        )
        .unwrap();
        db.insert_with_id(1, &[1.0, 0.0, 0.0], serde_json::json!({"state": "saved"}))
            .unwrap();
        (db, runtime)
    }

    struct Gate {
        entered: mpsc::Sender<()>,
        release: Mutex<mpsc::Receiver<()>>,
    }
    impl SearchHook for Gate {
        fn on_pre_search(&self, _: &mut Vec<f32>, _: &mut SearchConfig, _: &mut HookContext) {
            self.entered.send(()).unwrap();
            self.release
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(10))
                .unwrap();
        }
    }

    #[test]
    fn 关闭超时并丢弃包装对象仍保护排空任务与文件锁() {
        let (mut db, runtime) = open();
        let path = db.db_path.clone();
        let (entered, arrived) = mpsc::channel();
        let (release, wait) = mpsc::channel();
        db.set_hook(Gate {
            entered,
            release: Mutex::new(wait),
        });
        let handle = db.search_handle();
        let query = std::thread::spawn(move || {
            handle.search_batch(
                &[vec![1.0, 0.0, 0.0]],
                &SearchConfig {
                    top_k: 1,
                    expand_depth: 0,
                    ..Default::default()
                },
                &BatchSearchConfig::default(),
            )
        });
        arrived.recv_timeout(Duration::from_secs(10)).unwrap();
        assert!(!db.close_timeout(Duration::from_millis(10)).unwrap());
        assert_eq!(db.shutdown_status().phase, ShutdownPhase::Draining);
        assert!(matches!(
            db.insert(&[0.0, 1.0, 0.0], serde_json::json!({})),
            Err(TriviumError::DatabaseClosed)
        ));
        assert!(matches!(
            Database::<f32>::open(&path, 3),
            Err(TriviumError::DatabaseLocked(_))
        ));
        drop(db);
        assert!(matches!(
            Database::<f32>::open(&path, 3),
            Err(TriviumError::DatabaseLocked(_))
        ));
        release.send(()).unwrap();
        assert_eq!(query.join().unwrap().unwrap()[0][0].id, 1);
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            match Database::<f32>::open(&path, 3) {
                Ok(mut reopened) => {
                    assert!(reopened.contains(1));
                    reopened.close().unwrap();
                    break;
                }
                Err(TriviumError::DatabaseLocked(_)) => {
                    assert!(Instant::now() < deadline, "排空后未释放文件锁");
                    std::thread::sleep(Duration::from_millis(2));
                }
                Err(error) => panic!("重新打开失败：{error}"),
            }
        }
        assert_eq!(runtime.stats().attached_databases, 0);
        assert_eq!(runtime.stats().active_maintenance_tasks, 0);
    }

    #[test]
    fn 其他库前台占满名额时仍可关闭空闲库() {
        let (mut first, runtime) = open();
        let second_path = format!("{}.second", first.db_path);
        let mut second = Database::<f32>::open_with_runtime(
            &second_path,
            Config {
                dim: 3,
                memory_limit: 8 * 1024 * 1024,
                ..Default::default()
            },
            runtime.clone(),
        )
        .unwrap();
        let (entered, arrived) = mpsc::channel();
        let (release, wait) = mpsc::channel();
        first.set_hook(Gate {
            entered,
            release: Mutex::new(wait),
        });
        let handle = first.search_handle();
        let worker = std::thread::spawn(move || {
            handle.search_batch(
                &[vec![1.0, 0.0, 0.0]],
                &SearchConfig::default(),
                &BatchSearchConfig::default(),
            )
        });
        arrived.recv_timeout(Duration::from_secs(10)).unwrap();
        let closed = second.close_timeout(Duration::from_secs(2));
        release.send(()).unwrap();
        worker.join().unwrap().unwrap();
        assert!(closed.unwrap());
        assert_eq!(second.shutdown_status().phase, ShutdownPhase::Closed);
        assert_eq!(runtime.stats().active_maintenance_tasks, 0);
        first.close().unwrap();
    }
}
