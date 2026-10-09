# 作废：给「QuIVer 原作者」的说明信（本文件不再需要）

> **2026-10-09 作废。** 作者本人就是 QuIVer 的合著者（arXiv:2605.02171，作者 Wenxuan Xiao、Peidong Zhu、
> Zhiyou Wang、Chengcheng Li，长沙大学），**没有"原作者"可以写信**。原先的内容（cover letter 草稿）已无意义，
> 保留在 git 历史里。
>
> 原来的两件事改为：
> 1. **上游 5 条报告 → 自家修复清单**：`docs/research/upstream-issue-draft.md` 里的 5 条（L0 导航度量、
>    probe 三条规格、两个 vector→code path、RedCaps 采样规则、默认值与文档）现在应该当作**我们自己仓库/论文的
>    TODO** 去修，而不是发给别人。论文正文已相应改写（§1.1 自审披露、§4.4 "我们会把规则定下来"）。
> 2. **作者关系披露**：论文 §1.1 / §12.4 / §10-L17 已写明"这是自审而非第三方评估"，标题与文件名也已去掉
>    "independent"。这是投稿前最重要的一条，不能回退。

## 仍然有用的一节：arXiv endorsement 流程

**大概率不需要**：arXiv 的 endorsement 是按「作者 × 分类」自动判定的，你已在 cs.DB 有已公告的论文
（arXiv:2605.02171）⇒ 同类别通常自动获得资格。直接开始投稿即可，表单会立刻告知。

若仍被要求（或换用新账号、新邮箱投稿）：

* **可以先开始**：元数据/文件都能上传，但论文会停在 *incomplete / 不予公告*，直到有人输入担保码 ——
  也就是说"先提交、后补担保"在形式上可行，但没有担保不会被公布。
* **担保人不必是特定的人**：任何在 cs.DB 有近期公告的作者都行（同事、合作者）。
* **退路**：把主分类换成你已有资格的类别（如 cs.LG / cs.IR），再 cross-list cs.DB。

（历史模板：请求邮件一句话版本 —— "arXiv asks me for an endorsement for a first cs.DB submission; the paper is
an author-side re-examination of our own BQ-native graph index with all artifacts and raw logs public; the
endorsement request will arrive by e-mail and entering the code is all that is needed."）
