//! Mmap 多文件发布的撤销日志；先保留旧代，再允许替换正式文件。
//!
//! 日志与备份只供可写打开恢复，不能用来掩盖没有发布日志的文件损坏。
//! 恢复复制而不消耗备份，直到所有恢复文件 fsync 后才移除日志，支持恢复途中再次断电。

use super::*;
use crate::storage::fs::sync_parent_directory;
use std::io::Read;

const SUFFIXES: [&str; 3] = ["", ".vec", ".flush_ok"];
// 魔数(4) + 版本(1) + 目标代(8) + 三个文件的存在标记/长度/CRC(39) + 日志 CRC(4)。
const JOURNAL_SIZE: usize = 56;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct SavedFile {
    present: bool,
    size: u64,
    crc: u32,
}

fn journal_path(path: &str) -> String {
    format!("{path}.publish")
}

fn backup_path(path: &str, index: usize) -> String {
    format!("{path}.publish.{index}")
}

pub(super) fn pending(path: &str) -> bool {
    Path::new(&journal_path(path)).exists()
}

/// 同一句柄重试时沿用已校验的旧代备份，不能把半发布的新文件再次当作旧代备份。
pub(super) fn resume(path: &str) -> Result<bool> {
    if !pending(path) {
        return Ok(false);
    }
    match recover(path, false) {
        Err(TriviumError::RecoveryRequired { .. }) => Ok(true),
        Ok(_) => {
            cleanup(path)?;
            Ok(false)
        }
        Err(error) => Err(error),
    }
}

fn identity(path: &str) -> Result<SavedFile> {
    match std::fs::metadata(path) {
        Ok(meta) => Ok(SavedFile {
            present: true,
            size: meta.len(),
            crc: file_crc32(path)?,
        }),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(SavedFile {
            present: false,
            size: 0,
            crc: 0,
        }),
        Err(error) => Err(error.into()),
    }
}

fn copy_synced(source: &str, destination: &str) -> Result<()> {
    let temporary = format!("{destination}.tmp");
    let mut source = File::open(source)?;
    let mut output = File::create(&temporary)?;
    // 固定大小的流式复制，不把整库读入堆；不能用硬链接备份会追加写入的 .vec。
    std::io::copy(&mut source, &mut output)?;
    output.sync_all()?;
    drop(output);
    robust_rename_and_sync(Path::new(&temporary), Path::new(destination))?;
    Ok(())
}

pub(super) fn begin(path: &str, generation: u64) -> Result<()> {
    let mut bytes = [0u8; JOURNAL_SIZE];
    bytes[..4].copy_from_slice(b"TPUB");
    bytes[4] = 1;
    bytes[5..13].copy_from_slice(&generation.to_le_bytes());
    for (index, suffix) in SUFFIXES.iter().enumerate() {
        let source = format!("{path}{suffix}");
        let saved = identity(&source)?;
        if saved.present {
            #[cfg(feature = "test-hooks")]
            crate::test_hooks::io_result(crate::test_hooks::IoPoint::PublicationBackupCopy)?;
            copy_synced(&source, &backup_path(path, index))?;
        }
        let offset = 13 + index * 13;
        bytes[offset] = u8::from(saved.present);
        bytes[offset + 1..offset + 9].copy_from_slice(&saved.size.to_le_bytes());
        bytes[offset + 9..offset + 13].copy_from_slice(&saved.crc.to_le_bytes());
    }
    let crc = crc32fast::hash(&bytes[..JOURNAL_SIZE - 4]);
    bytes[JOURNAL_SIZE - 4..].copy_from_slice(&crc.to_le_bytes());
    let journal = journal_path(path);
    let temporary = format!("{journal}.tmp");
    let mut output = File::create(&temporary)?;
    output.write_all(&bytes)?;
    #[cfg(feature = "test-hooks")]
    crate::test_hooks::io_result(crate::test_hooks::IoPoint::PublicationJournalSync)?;
    output.sync_all()?;
    drop(output);
    #[cfg(feature = "test-hooks")]
    crate::test_hooks::io_result(crate::test_hooks::IoPoint::PublicationJournalRename)?;
    robust_rename_and_sync(Path::new(&temporary), Path::new(&journal))?;
    #[cfg(feature = "test-hooks")]
    crate::test_hooks::hit(crate::test_hooks::ConcurrencyPoint::AfterPublicationPrepared);
    Ok(())
}

fn decode(bytes: &[u8]) -> Result<(u64, [SavedFile; 3])> {
    if bytes.len() != JOURNAL_SIZE
        || &bytes[..4] != b"TPUB"
        || bytes[4] != 1
        || crc32fast::hash(&bytes[..52]) != read_u32_le(bytes, 52, "发布日志 CRC")?
    {
        return Err(TriviumError::CorruptedFile(
            "发布恢复日志格式或 CRC 无效".into(),
        ));
    }
    let generation = read_u64_le(bytes, 5, "发布目标代")?;
    if generation == 0 {
        return Err(TriviumError::CorruptedFile("发布目标代不能为零".into()));
    }
    let mut files = [SavedFile {
        present: false,
        size: 0,
        crc: 0,
    }; 3];
    for (index, saved) in files.iter_mut().enumerate() {
        let offset = 13 + index * 13;
        *saved = SavedFile {
            present: bytes[offset] == 1,
            size: read_u64_le(bytes, offset + 1, "备份长度")?,
            crc: read_u32_le(bytes, offset + 9, "备份 CRC")?,
        };
        if bytes[offset] > 1 || (!saved.present && (saved.size != 0 || saved.crc != 0)) {
            return Err(TriviumError::CorruptedFile("发布备份几何信息无效".into()));
        }
    }
    Ok((generation, files))
}

/// 返回是否回滚了未提交的文件；只读路径只检查，不创建、删除或修改文件。
pub(crate) fn recover(path: &str, writable: bool) -> Result<bool> {
    let journal = journal_path(path);
    let mut input = match File::open(&journal) {
        Ok(input) => input,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error.into()),
    };
    if input.metadata()?.len() != JOURNAL_SIZE as u64 {
        return Err(TriviumError::CorruptedFile("发布恢复日志长度无效".into()));
    }
    let mut bytes = [0u8; JOURNAL_SIZE];
    input.read_exact(&mut bytes)?;
    drop(input);
    let (generation, files) = decode(&bytes)?;
    let marker = flush_ok_path_from_db(path);
    if read_marker_generation(&marker) == Some(generation) {
        if !validate_flush_marker(
            &marker,
            path,
            &vec_path_from_db(path),
            &payload_path_for_generation(path, generation),
        ) {
            // marker 已提交后，即使新代损坏也不能回退；WAL 可能已清空。
            return Err(TriviumError::CorruptedFile(
                "已提交发布代的事实文件损坏".into(),
            ));
        }
        if writable {
            cleanup(path)?;
        }
        return Ok(false);
    }
    // 只接受仍指向旧代的 marker，拒绝把任意损坏的提交标记当作未提交发布。
    if identity(&marker)? != files[2] {
        return Err(TriviumError::CorruptedFile(
            "发布提交标记与恢复日志不匹配".into(),
        ));
    }
    let expected_generation = match read_marker_generation(&marker) {
        Some(previous) => previous.checked_add(1),
        None => Some(1),
    };
    if expected_generation != Some(generation) {
        return Err(TriviumError::CorruptedFile(
            "发布目标代与旧提交标记不连续".into(),
        ));
    }
    for (index, saved) in files.iter().enumerate() {
        if saved.present && identity(&backup_path(path, index))? != *saved {
            return Err(TriviumError::CorruptedFile("发布恢复备份缺失或损坏".into()));
        }
    }
    if !writable {
        return Err(TriviumError::RecoveryRequired { wal_path: journal });
    }
    // 所有备份通过校验后才恢复正式文件；备份保留到恢复提交完成。
    for (index, suffix) in SUFFIXES.iter().enumerate() {
        let destination = format!("{path}{suffix}");
        if files[index].present {
            #[cfg(feature = "test-hooks")]
            crate::test_hooks::io_result(crate::test_hooks::IoPoint::PublicationRestoreCopy)?;
            copy_synced(&backup_path(path, index), &destination)?;
        } else {
            match std::fs::remove_file(&destination) {
                Ok(()) => sync_parent_directory(Path::new(&destination))?,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
        }
        #[cfg(feature = "test-hooks")]
        crate::test_hooks::hit(crate::test_hooks::ConcurrencyPoint::AfterPublicationRestore);
    }
    cleanup(path)?;
    Ok(true)
}

pub(super) fn cleanup(path: &str) -> Result<()> {
    let journal = journal_path(path);
    std::fs::remove_file(&journal)?;
    // 日志的删除先持久化，才能删除其引用的备份；否则断电可能留下有日志、无备份的状态。
    sync_parent_directory(Path::new(&journal))?;
    for index in 0..SUFFIXES.len() {
        std::fs::remove_file(backup_path(path, index)).ok();
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn 发布日志拒绝截断_未知版本_无效存在位与损坏crc() {
        // 固定布局的独立字节 oracle，不能由生产编码器生成。
        let mut bytes = [0u8; JOURNAL_SIZE];
        bytes[..5].copy_from_slice(b"TPUB\x01");
        bytes[5] = 1;
        let crc = crc32fast::hash(&bytes[..52]);
        bytes[52..].copy_from_slice(&crc.to_le_bytes());
        assert!(decode(&bytes).is_ok());
        for length in 0..JOURNAL_SIZE {
            assert!(decode(&bytes[..length]).is_err());
        }
        for offset in 0..JOURNAL_SIZE {
            let mut corrupt = bytes;
            corrupt[offset] ^= 1;
            assert!(decode(&corrupt).is_err());
        }
        for (offset, value) in [(4, 2), (5, 0), (13, 2), (14, 1)] {
            let mut corrupt = bytes;
            corrupt[offset] = value;
            let crc = crc32fast::hash(&corrupt[..52]);
            corrupt[52..].copy_from_slice(&crc.to_le_bytes());
            assert!(decode(&corrupt).is_err());
        }
    }
}
