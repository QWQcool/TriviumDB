# Draft: note to the QuIVer authors + endorsement request (NOT SENT)

> Use as-is or trim. Two parts: **A** the cover note (send with the PDF), **B** the arXiv endorsement request
> (only if arXiv asks you for an endorsement when you start the cs.DB submission).

---

## A. Cover note

**Subject:** Independent evaluation of QuIVer — preprint + artifact repository (and five upstream reports)

Dear QuIVer authors,

We have prepared an independent evaluation of QuIVer and are posting it as an arXiv preprint (cs.DB,
cross-listed cs.IR): *“Applicability Is Not Competitiveness: An Independent Evaluation and a Data-Side Repair
for BQ-Native Graph Indexing”* — the full PDF is attached.

**What we found, in one paragraph.** We reproduce 11 of your 12 Table 11 rows within ±1.84 pp; the RedCaps
row is the exception, for a protocol reason rather than a numeric one (see below). We then measure what the
table does not: where competitor curves exist, three of the four tiers are dominated by plain HNSW — on
several rows your recall *ceiling* sits below the baseline's *lowest* operating point, so the curves cannot
intersect. The bottom tier mixes three different failures: an encoder-side failure that is repairable (the
sign plane is globally constant), a task-side failure that is not (Random-Sphere; every HNSW implementation
also collapses, and so does IVF-Flat), and a capacity failure (`coco_nomic`) where the bit budget, not the
distribution, is binding — at 4 bits per dimension every collapse row measures ≥ 94.6 %. On the probe in §6,
the three unstated specifications (which BQ distance, how many samples, which instrument) have measurable
consequences: implemented with your own default metric it calls Random-Sphere “compatible” (53.9 %) on a
dataset whose measured recall is 0.91 %, while taking the weaker of the two metrics removes the false positive
without changing any other verdict. Finally, the collapse that remains is repairable **from the data side**:
one centring step takes GIST-960 from 2.10 % to 39.74 % and SIFT-128 from 15.77 % to 30.64 % at `ef=64`
(isotropic control +0.03 pp), and a *task-preserving* seeded rotation does better still on a dead sign plane
(GIST-960 60.22 %) while a navigation-metric switch adds up to +21.8 pp exactly where the sign plane is alive.

**What we are not claiming.** We do not claim the paper is wrong — its mechanism (the sign plane of
non-negative embeddings carries no information) is the one we measure and reproduce. We propose no new
quantizer, we do not claim a single scalar predicts recall (our two attempts failed and are reported as
failures), and we retract three of our own intermediate claims in the audit trail.

**Artifacts.** Everything is reproducible from
`github.com/QWQcool/TriviumDB`, branch `research/quiver2-pipnn-rabitq-tsng`: `results/**` (including the 290
raw stdout logs the paper cites), the patched switches (default-off, bit-identical when unset) and
`patches/f1-nav-weighted.patch`.

**Five small upstream reports** (drafted, with evidence, nothing filed behind your back): the L0 beam search
uses plain Hamming while build/prune use the weighted BQ distance (three call sites; a default-off patch makes
them consistent, and the effect is fully predicted by `sign_info`); the three probe specifications above; two
vector→code paths that must share any transform (we hit this and it made SIFT read 0.01 %); the RedCaps
sampling protocol; and two defaults/doc nits (`m = 16` vs the paper's 32, `α = 1.2`, a README table number).

**One request.** If any of the above looks wrong to you, we would genuinely like to know before we finalise —
corrections are cheap now, and we will credit them in the paper.

Best regards,
Chengcheng Li — Beyondsoft — qq1330494624@outlook.com

---

## B. Endorsement request (only if arXiv asks)

**Subject:** arXiv cs.DB endorsement request — preprint on BQ-native graph indexing

Dear ⟨name⟩,

arXiv is asking me for an endorsement for a first submission to **cs.DB**. The paper is *“Applicability Is Not
Competitiveness: An Independent Evaluation and a Data-Side Repair for BQ-Native Graph Indexing”* — an
independent evaluation of QuIVer's 2-bit sign–magnitude graph index on the authors' released implementation,
with all artifacts and raw logs in a public repository. arXiv will send you the endorsement request by e-mail;
entering the code there is all that is needed. Thank you either way.

Chengcheng Li — Beyondsoft — qq1330494624@outlook.com

---

## C. arXiv endorsement — what to expect (short version)

* Endorsement is decided **per author, per category** by arXiv, based on your own submission history in that
  category. If you have never submitted to `cs.DB`, arXiv very likely asks for it; if you have submitted
  elsewhere in cs.*, you may be auto-endorsed — the submission form tells you immediately.
* You **can start** the submission without an endorser: the metadata/form is filled in, but the paper stays
  **incomplete / not announced** until the endorsement code arrives. So: start it early, request the code, and
  finish afterwards.
* The endorsement request does not have to go to the authors you evaluate — **any** `cs.DB` author with recent
  submissions can endorse (a colleague, a co-author of a related paper, etc.). If nobody is available, an
  alternative is to submit to a category where you are already endorsed (e.g. `cs.LG`/`cs.IR` as primary) and
  cross-list `cs.DB`.
