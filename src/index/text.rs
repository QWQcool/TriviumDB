//! 稀疏文本召回索引：Aho-Corasick 精确关键词 + BM25 2-Gram。
//!
//! 关键词目录负责高精度锚点，BM25 维护词频、文档长度和全局统计，两路结果由上层
//! 混合检索管线融合。快照包含独立魔数/版本；增删节点必须同步
//! 清理所有 posting，防止 tombstone 文档在重启后重新出现。

use crate::node::NodeId;
use aho_corasick::{AhoCorasick, AhoCorasickBuilder, MatchKind};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::io::{BufReader, BufWriter};
use std::path::Path;
use std::sync::OnceLock;

const TEXT_INDEX_MAGIC: &[u8; 4] = b"TIDX";
pub const TEXT_INDEX_VERSION: u32 = 2;

#[derive(Serialize)]
struct TextIndexSnapshotRef<'a> {
    keyword_to_nodes: &'a HashMap<String, Vec<NodeId>>,
    bm25_tf: &'a HashMap<String, HashMap<NodeId, usize>>,
    doc_lengths: &'a HashMap<NodeId, usize>,
}

#[derive(Deserialize)]
struct TextIndexSnapshot {
    keyword_to_nodes: HashMap<String, Vec<NodeId>>,
    bm25_tf: HashMap<String, HashMap<NodeId, usize>>,
    doc_lengths: HashMap<NodeId, usize>,
}

struct CompiledKeywords {
    matcher: AhoCorasick,
    keywords: Vec<String>,
}

/// 综合文本搜索引擎：AC自动机 (精准关键词触发) + BM25 (大段落兜底打分)
///
/// 作为一个可选项，它与稠密向量搜索（Dense）形成完全互补，
/// 构成了 TriviumDB 的 混合检索（Hybrid Search）闭环机制。
#[derive(Default)]
pub struct TextIndex {
    // === 1. AC 自动机（特征锚点） ===
    // 用于精确捕获非常短、但置信度极高的指代特征词
    ac_matcher: OnceLock<Option<CompiledKeywords>>,
    keyword_to_nodes: HashMap<String, Vec<NodeId>>,
    // 只记录注册过关键词的节点，删除无关键词节点时不扫描整个词典。
    keyword_nodes: HashSet<NodeId>,

    // === 2. BM25 稀疏倒排索引 ===
    // 基于 2-Gram 滑动窗口的轻量级实现，兼容中英无分词器环境
    // Term -> NodeId -> TF (Term Frequency)
    bm25_tf: HashMap<String, HashMap<NodeId, usize>>,
    // Document Lengths (节点对应的文档长度)
    doc_lengths: HashMap<NodeId, usize>,
    avg_dl: f32,
    total_docs: usize,
    total_tokens: u128,
}

fn tokenize(text: &str) -> Vec<String> {
    let lowered = text.to_lowercase();
    let mut tokens = Vec::new();
    let mut word = String::new();
    let mut cjk_run = Vec::new();

    let flush_word = |word: &mut String, tokens: &mut Vec<String>| {
        if !word.is_empty() {
            tokens.push(std::mem::take(word));
        }
    };
    let flush_cjk = |run: &mut Vec<char>, tokens: &mut Vec<String>| {
        match run.len() {
            0 => {}
            1 => tokens.push(run[0].to_string()),
            _ => tokens.extend(run.windows(2).map(|pair| pair.iter().collect())),
        }
        run.clear();
    };

    for ch in lowered.chars() {
        if ch.is_ascii_alphanumeric() {
            flush_cjk(&mut cjk_run, &mut tokens);
            word.push(ch);
        } else if ('\u{3400}'..='\u{9fff}').contains(&ch)
            || ('\u{3040}'..='\u{30ff}').contains(&ch)
            || ('\u{ac00}'..='\u{d7af}').contains(&ch)
        {
            flush_word(&mut word, &mut tokens);
            cjk_run.push(ch);
        } else {
            flush_word(&mut word, &mut tokens);
            flush_cjk(&mut cjk_run, &mut tokens);
        }
    }
    flush_word(&mut word, &mut tokens);
    flush_cjk(&mut cjk_run, &mut tokens);
    tokens
}

impl TextIndex {
    pub fn new() -> Self {
        Self::default()
    }

    /// 清空并准备重建
    pub fn clear(&mut self) {
        self.ac_matcher.take();
        self.keyword_to_nodes.clear();
        self.keyword_nodes.clear();
        self.bm25_tf.clear();
        self.doc_lengths.clear();
        self.avg_dl = 0.0;
        self.total_docs = 0;
        self.total_tokens = 0;
    }

    /// 注册一个高权重短元特征汇聚点（精准提取并置信度极高）
    pub fn add_keyword(&mut self, id: NodeId, keyword: &str) {
        let kw = keyword.to_lowercase();
        if kw.is_empty() {
            return;
        }
        let new_keyword = !self.keyword_to_nodes.contains_key(&kw);
        self.keyword_nodes.insert(id);
        let nodes = self.keyword_to_nodes.entry(kw).or_default();
        if let Err(position) = nodes.binary_search(&id) {
            nodes.insert(position, id);
        }
        if new_keyword {
            self.ac_matcher.take();
        }
    }

    /// 注册一段长文本：拉丁字母/数字按词切分，CJK文本使用字符2-Gram。
    pub fn add_text(&mut self, id: NodeId, text: &str) {
        let tokens = tokenize(text);
        self.remove_document(id);
        if tokens.is_empty() {
            return;
        }

        let mut local_tf = HashMap::new();
        for token in &tokens {
            *local_tf.entry(token.clone()).or_insert(0) += 1;
        }

        let dl = tokens.len();
        self.doc_lengths.insert(id, dl);
        self.total_tokens += dl as u128;

        for (token, tf) in local_tf {
            self.bm25_tf.entry(token).or_default().insert(id, tf);
        }
        self.refresh_statistics();
    }

    fn refresh_statistics(&mut self) {
        self.total_docs = self.doc_lengths.len();
        self.avg_dl = if self.total_docs == 0 {
            0.0
        } else {
            self.total_tokens as f32 / self.total_docs as f32
        };
    }

    fn remove_document(&mut self, id: NodeId) {
        if let Some(length) = self.doc_lengths.remove(&id) {
            self.total_tokens -= length as u128;
            self.bm25_tf.retain(|_, documents| {
                documents.remove(&id);
                !documents.is_empty()
            });
            self.refresh_statistics();
        }
    }

    /// 清理节点的正文、关键词与统计；重复删除保持幂等。
    pub fn remove_node(&mut self, id: NodeId) {
        self.remove_document(id);
        if !self.keyword_nodes.remove(&id) {
            return;
        }
        let before = self.keyword_to_nodes.len();
        self.keyword_to_nodes.retain(|_, nodes| {
            nodes.retain(|node| *node != id);
            !nodes.is_empty()
        });
        if before != self.keyword_to_nodes.len() {
            self.ac_matcher.take();
        }
    }

    /// 加载历史快照时清理已删除节点，并规范化关键词 posting。
    pub(crate) fn retain_nodes(&mut self, keep: impl Fn(NodeId) -> bool) {
        self.doc_lengths.retain(|id, _| keep(*id));
        self.bm25_tf.retain(|_, documents| {
            documents.retain(|id, _| self.doc_lengths.contains_key(id));
            !documents.is_empty()
        });
        self.keyword_to_nodes.retain(|keyword, nodes| {
            nodes.retain(|id| keep(*id));
            nodes.sort_unstable();
            nodes.dedup();
            !keyword.is_empty() && !nodes.is_empty()
        });
        self.keyword_nodes = self.keyword_to_nodes.values().flatten().copied().collect();
        self.ac_matcher.take();
        self.total_tokens = self
            .doc_lengths
            .values()
            .map(|length| *length as u128)
            .sum();
        self.refresh_statistics();
    }

    /// 全量构建索引 (编译 AC，计算平均文档长度与频次基数)
    pub fn build(&mut self) {
        self.rebuild_runtime();
    }

    pub(crate) fn try_build(&mut self) -> crate::error::Result<()> {
        self.rebuild_runtime();
        if !self.keyword_to_nodes.is_empty() && self.compiled_keywords().is_none() {
            return Err(crate::error::TriviumError::InvalidInput(
                "关键词自动机构建失败".into(),
            ));
        }
        Ok(())
    }

    fn rebuild_runtime(&mut self) {
        self.compiled_keywords();
        self.total_tokens = self
            .doc_lengths
            .values()
            .map(|length| *length as u128)
            .sum();
        self.refresh_statistics();
    }

    fn compiled_keywords(&self) -> Option<&CompiledKeywords> {
        self.ac_matcher
            .get_or_init(|| {
                let mut keywords: Vec<_> = self.keyword_to_nodes.keys().cloned().collect();
                keywords.sort_by(|a, b| b.len().cmp(&a.len()).then_with(|| a.cmp(b)));
                if keywords.is_empty() {
                    return None;
                }
                AhoCorasickBuilder::new()
                    .match_kind(MatchKind::LeftmostLongest)
                    .build(&keywords)
                    .ok()
                    .map(|matcher| CompiledKeywords { matcher, keywords })
            })
            .as_ref()
    }

    pub fn is_empty(&self) -> bool {
        self.keyword_to_nodes.is_empty() && self.bm25_tf.is_empty()
    }

    pub fn estimated_memory_bytes(&self) -> usize {
        let keywords = self
            .keyword_to_nodes
            .iter()
            .map(|(term, ids)| term.capacity() + ids.capacity() * std::mem::size_of::<NodeId>())
            .sum::<usize>();
        let bm25 = self
            .bm25_tf
            .iter()
            .map(|(term, docs)| {
                term.capacity()
                    + docs.capacity()
                        * (std::mem::size_of::<NodeId>() + std::mem::size_of::<usize>())
            })
            .sum::<usize>();
        let compiled = self
            .ac_matcher
            .get()
            .and_then(Option::as_ref)
            .map_or(0, |compiled| {
                compiled.matcher.memory_usage()
                    + compiled.keywords.capacity() * std::mem::size_of::<String>()
                    + compiled
                        .keywords
                        .iter()
                        .map(String::capacity)
                        .sum::<usize>()
            });
        keywords
            + bm25
            + compiled
            + self.keyword_nodes.capacity() * std::mem::size_of::<NodeId>()
            + self.doc_lengths.capacity()
                * (std::mem::size_of::<NodeId>() + std::mem::size_of::<usize>())
    }

    pub fn save_to_file(&self, path: &Path) -> std::io::Result<()> {
        if self.is_empty() {
            if path.exists() {
                std::fs::remove_file(path)?;
            }
            return Ok(());
        }
        let tmp = path.with_extension("text.tmp");
        let mut writer = BufWriter::new(std::fs::File::create(&tmp)?);
        use std::io::Write;
        writer.write_all(TEXT_INDEX_MAGIC)?;
        writer.write_all(&TEXT_INDEX_VERSION.to_le_bytes())?;
        bincode::serialize_into(
            &mut writer,
            &TextIndexSnapshotRef {
                keyword_to_nodes: &self.keyword_to_nodes,
                bm25_tf: &self.bm25_tf,
                doc_lengths: &self.doc_lengths,
            },
        )
        .map_err(std::io::Error::other)?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        drop(writer);
        crate::storage::fs::robust_rename_and_sync(&tmp, path)
    }

    pub fn load_from_file(path: &Path) -> std::io::Result<Self> {
        use std::io::Read;
        let mut reader = BufReader::new(std::fs::File::open(path)?);
        let mut magic = [0u8; 4];
        reader.read_exact(&mut magic)?;
        if &magic != TEXT_INDEX_MAGIC {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "TextIndex 魔数无效",
            ));
        }
        let mut version = [0u8; 4];
        reader.read_exact(&mut version)?;
        if u32::from_le_bytes(version) != TEXT_INDEX_VERSION {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "TextIndex 版本不受支持",
            ));
        }
        let snapshot: TextIndexSnapshot =
            bincode::deserialize_from(reader).map_err(std::io::Error::other)?;
        let mut index = Self {
            ac_matcher: OnceLock::new(),
            keyword_to_nodes: snapshot.keyword_to_nodes,
            keyword_nodes: HashSet::new(),
            bm25_tf: snapshot.bm25_tf,
            doc_lengths: snapshot.doc_lengths,
            avg_dl: 0.0,
            total_docs: 0,
            total_tokens: 0,
        };
        index.retain_nodes(|_| true);
        Ok(index)
    }

    /// 执行 BM25 检索，返回命中节点的原始相似度得分
    pub fn search_bm25(&self, query: &str, k1: f32, b: f32) -> HashMap<NodeId, f32> {
        let mut results = HashMap::new();
        if self.total_docs == 0 {
            return results;
        }

        let mut tokens = tokenize(query);
        if tokens.is_empty() {
            return results;
        }

        tokens.sort_unstable();
        tokens.dedup();

        let n = self.total_docs as f32;
        let avg_dl = self.avg_dl;

        for token in tokens {
            if let Some(docs) = self.bm25_tf.get(&token) {
                let df = docs.len() as f32;
                // IDF 平滑 (BM25 标准)
                let idf = ((n - df + 0.5) / (df + 0.5) + 1.0).ln();

                for (&id, &tf) in docs {
                    let dl = *self.doc_lengths.get(&id).unwrap_or(&0) as f32;
                    let tf_f32 = tf as f32;
                    // Okapi BM25 打分公式
                    let tf_norm =
                        (tf_f32 * (k1 + 1.0)) / (tf_f32 + k1 * (1.0 - b + b * dl / avg_dl));
                    *results.entry(id).or_insert(0.0) += idf * tf_norm;
                }
            }
        }
        results
    }

    /// 执行 AC 自动机精准锚点激发
    pub fn search_ac(&self, query: &str) -> HashMap<NodeId, f32> {
        let mut results = HashMap::new();
        if let Some(compiled) = self.compiled_keywords() {
            let query_lower = query.to_lowercase();
            for mat in compiled.matcher.find_iter(&query_lower) {
                let kw = &compiled.keywords[mat.pattern()];
                if let Some(nodes) = self.keyword_to_nodes.get(kw) {
                    for &id in nodes {
                        *results.entry(id).or_insert(0.0) += 1.0;
                    }
                }
            }
        }
        results
    }
}
