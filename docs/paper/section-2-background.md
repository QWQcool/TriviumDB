# 2. Background and Notation

## 2.1 QuIVer's 2-bit encoding

Each vector `v ∈ R^d` (assumed unit-norm) is encoded into two bit planes:

```
pos(v)    = (v_j > 0)                 the sign plane
strong(v) = (|v_j| > mean_j |v_j|)    the magnitude plane
```

The engine's distance for build/prune/upper layers is the 6-class **weighted** distance; its L0 query
navigation uses a plain-Hamming **cheap** distance. We use the following two forms throughout, and verified
them against `src/index/bq.rs` bit-for-bit (`bq2_code_ceiling.py::verify_identities`; asserted
max |analytic − bitwise| = 0):

```
pos    : p = (v > 0)                      (strict ⇒ 0 falls in the negative half-plane)
strong : s = (|v| > mean|v|)              (per-vector threshold τ)
cheap  : D(a,b) = (|p_a| + |s_a|) − 2(<p_a,p_b> + <s_a,s_b>)       ascending = nearer
weighted: S(a,b) = <w_a, w_b>,   w = (2p − 1)·(1 + s) ∈ {−2,−1,+1,+2}   descending = nearer
```

The identity `w = (2p−1)(1+s)` is the reason the sign plane matters so much: if `p ≡ 0` then
`w = −(1 + s)` and the score degenerates into a function of the *magnitude* statistics of the two codes
(§6.1). This is a restatement of the paper's Finding 1 in closed form, not a new finding.

## 2.2 What the paper already establishes

| The paper's statement | Our position |
|---|---|
| **Finding 1**: recall is governed by the data distribution, not by dimension; on SIFT/GIST the values lie in a narrow positive band, so the sign plane loses discriminative power | **We reproduce and agree.** We quantify it as `sign_info` (§6.2) and use it as a triage quantity; we claim no priority. |
| **Finding 2**: no hard recall ceiling; recall rises monotonically with `ef` on all 12 datasets | Agreed. Our earlier "SIFT ceiling 47.21 %" phrasing referred to a *practical* `ef` budget and is withdrawn. |
| **Finding 3**: applicability is a continuous gradient, reported as four tiers (<15 %, 32–42 %, 71–78 %, >88 %) | Agreed as *description*. Our §5 shows the tiers are **not** a competitiveness ordering. |
| **Finding 4**: two necessary conditions — low effective rank (to create a detectable angular gap) and contrastive geometry (to organise the gap into semantic neighbourhoods) | Agreed; our Random-Sphere (§6.4) is the same phenomenon, now with HNSW as an external witness. |
| **§6 Practical compatibility test**: ≈10 K samples, BQ-ranked vs float32-ranked top-K overlap, > ~50 % ⇒ compatible | We implement it as written and report the three specification gaps and their measured cost (§7). |

## 2.3 Baselines

We measure, on every task, the same five reference points in a single process: **hnswlib**, **FAISS-HNSW**,
**USearch**, **FAISS IVF-Flat**, and **`faiss_exact`** (exact float32 search). The last one is not a baseline
but a *protocol instrument*: it reveals tie floors. On Wolt-CLIP-1M it scores only **90.09 %**, so that
dataset's recall cannot be compared with datasets whose exact search returns 99.9–100 %.

## 2.4 Relationship to rotation-based quantizers

Rotation-based quantizers (randomised rotations as in RaBitQ, learned rotations as in OPQ, product
quantization) address the *anisotropy* of the embedding cloud, and a rotation would also revive a constant
sign plane. We do not claim that translation ("centring") dominates them, and we did not run the head-to-head
(§9.2, L12). We choose translation for a different reason: it is the minimal intervention whose
**applicability is decided by the same statistic that detects the problem** — and it requires no rotation
matrix, no training, and no change to the index. The retrievability post-processing literature
(all-but-the-top family) has used centring for other purposes; our contribution here is the decision rule and
the quantification, not the transform.
