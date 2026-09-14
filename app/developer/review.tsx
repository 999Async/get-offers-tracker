export const dimensions = ["fact_support", "usefulness", "jd_fit"] as const;
type Dimension = typeof dimensions[number];
type Label = "pass" | "fail" | "pending" | "n/a";
export type CaseReview = Record<Dimension, Label>;
export type Review = {
  binding: "missing" | "invalid" | "verified";
  status: "pending" | "rejected" | "reviewed";
  hash: string | null;
  dimensions: Partial<Record<Dimension, { passed: number; failed: number; pending: number; not_applicable: number; reviewed: number; pass_rate: number | null }>>;
};
export type ReviewComparison = {
  review_bindings: { baseline: Review["binding"]; challenger: Review["binding"] };
  review_hashes: { baseline: string | null; challenger: string | null };
  human_review_deltas: Partial<Record<Dimension, { paired_reviewed_cases: number; excluded_pending_or_na: number; pass_rate_delta: number | null }>>;
};
const names: Record<Dimension, string> = { fact_support: "事实依据", usefulness: "可用性", jd_fit: "岗位匹配" };
const labels: Record<Label, string> = { pass: "通过", fail: "失败", pending: "待审核", "n/a": "不适用" };
export function reviewStatus(review: Review) {
  if (review.binding === "missing") return "审核表未提供";
  if (review.binding === "invalid") return "审核表无效";
  return { pending: "部分或全部待审核", rejected: "审核含失败", reviewed: "评分已录入" }[review.status];
}
const percent = (value: number) => (value * 100).toLocaleString("zh-CN", { maximumFractionDigits: 1 });

export function ReviewResults({ review, cases }: { review: Review; cases: { case_id: string; review: CaseReview | null }[] }) {
  return <section className="developer-detail" aria-label="人工审核结果">
    <h3>人工审核结果 · {reviewStatus(review)}</h3>
    {review.binding === "missing" ? <p className="developer-note">将本次实验目录中的 <code>review.csv</code> 另存为 <code>reviewed.csv</code>，填写最后五列后刷新。来源列需保持原样。</p>
      : review.binding === "invalid" ? <p className="developer-error" role="alert">审核表格式无效或与报告不匹配，评分未纳入统计。请检查 reviewed.csv 的来源列、评分标签、审核人及失败说明。</p>
      : <>
        <p className="developer-note">审核表已与报告及逐例输出绑定。评分由本机操作者录入，审核身份未认证；此页不展示审核人和备注。通过率仅统计“通过 + 失败”，待审核与不适用另列。</p>
        <p className="developer-note">审核指纹 <code>{review.hash}</code></p>
        <div className="developer-table" role="region" aria-label="审核统计，可横向滚动" tabIndex={0}><table><caption>按审核维度统计</caption><thead><tr><th>维度</th><th>通过</th><th>失败</th><th>待审核</th><th>不适用</th><th>已评分</th><th>通过率</th></tr></thead><tbody>{dimensions.map(d => {
          const value = review.dimensions[d];
          return value && <tr key={d}><th scope="row">{names[d]}</th><td>{value.passed}</td><td>{value.failed}</td><td>{value.pending}</td><td>{value.not_applicable}</td><td>{value.reviewed}</td><td>{value.pass_rate == null ? "未评分" : `${percent(value.pass_rate)}%`}</td></tr>;
        })}</tbody></table></div>
        <details className="developer-review-cases"><summary>查看逐例评分</summary><div className="developer-table" role="region" aria-label="逐例评分，可横向滚动" tabIndex={0}><table><caption>序号对应上方自动检查结果</caption><thead><tr><th>用例</th>{dimensions.map(d => <th key={d}>{names[d]}</th>)}</tr></thead><tbody>{cases.map(c => <tr key={c.case_id}><th scope="row">{c.case_id}</th>{dimensions.map(d => <td key={d}>{c.review ? labels[c.review[d]] : "未提供"}</td>)}</tr>)}</tbody></table></div></details>
      </>}
  </section>;
}

export function PairedReviews({ comparison }: { comparison: ReviewComparison }) {
  if (comparison.review_bindings.baseline !== "verified" || comparison.review_bindings.challenger !== "verified") {
    const binding = { missing: "未提供", invalid: "无效", verified: "已绑定" };
    return <p className="developer-note">人工评分未比较：基线审核表{binding[comparison.review_bindings.baseline]}，候选审核表{binding[comparison.review_bindings.challenger]}。两份审核表均有效时才计算评分差值。</p>;
  }
  return <>
    <p className="developer-note">人工评分按同一用例配对，仅纳入两侧均为通过或失败的评分。正值表示候选通过率更高；零个有效配对时不计算差值。</p>
    <div className="developer-table" role="region" aria-label="审核配对比较，可横向滚动" tabIndex={0}><table><caption>人工评分差值（候选 − 基线）</caption><thead><tr><th>维度</th><th>有效配对</th><th>排除的待审核 / 不适用</th><th>通过率变化</th></tr></thead><tbody>{dimensions.map(d => {
      const value = comparison.human_review_deltas[d];
      return value && <tr key={d}><th scope="row">{names[d]}</th><td>{value.paired_reviewed_cases}</td><td>{value.excluded_pending_or_na}</td><td>{value.pass_rate_delta == null ? "未比较" : `${value.pass_rate_delta > 0 ? "+" : ""}${percent(value.pass_rate_delta)} 个百分点`}</td></tr>;
    })}</tbody></table></div>
    <details className="developer-review-cases"><summary>本次比较使用的审核指纹</summary><p className="developer-note">基线 <code>{comparison.review_hashes.baseline}</code><br />候选 <code>{comparison.review_hashes.challenger}</code></p></details>
  </>;
}
