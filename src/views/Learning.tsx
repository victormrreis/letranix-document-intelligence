import { useEffect, useState } from "react";
import { FlaskConical, Trash2 } from "lucide-react";
import { api, post } from "../api";
import { useShared } from "../App";
import type { Evaluation, Rule } from "../types";
import { Empty, PageHeader, useAction } from "../ui";

const KIND_HELP: Record<string, string> = {
  alias: "New label for the field",
  "value-map": "Recurring value correction",
  "char-map": "Recurring character confusion",
};

const pct = (n: number) => `${(n * 100).toFixed(1)}%`;

export default function Learning() {
  const { templates, settings } = useShared();
  const { busy, run } = useAction();
  const [rules, setRules] = useState<Rule[]>([]);
  const [report, setReport] = useState<Evaluation | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    api<Rule[]>("/learning/rules")
      .then(setRules)
      .catch(() => {});
    api<Evaluation | null>("/learning/evaluation")
      .then(setReport)
      .catch(() => {});
  }, [tick]);
  const name = (id: string) => templates.find((t) => t.id === id)?.name ?? id;
  const minSupport = settings?.values["learning.min_support"];

  return (
    <>
      <PageHeader
        title="Learning from review"
        subtitle={`Approved reviews produce correction rules. A rule becomes active after ${minSupport} confirming document(s) (Settings) and is disabled automatically when reviewers contradict it more often than they confirm it. The document-type classifier is retrained from approved documents.`}
      />
      <section className="panel">
        <div className="panel-head">
          <h2>
            <FlaskConical size={18} /> Measured effect
          </h2>
          <button
            className="primary"
            disabled={busy}
            onClick={() =>
              run(
                async () =>
                  setReport(await post<Evaluation>("/learning/evaluation")),
                "Evaluation finished.",
              )
            }
          >
            {busy ? "Running…" : "Run evaluation"}
          </button>
        </div>
        {!report ? (
          <p className="muted">
            Runs the learning loop on generated synthetic documents in a
            temporary workspace: train on one split, choose the activation
            threshold on a second, report on a third. Your workspace is not
            modified.
          </p>
        ) : (
          <>
            <div className="compare">
              {(
                [
                  ["Field accuracy", "field_accuracy"],
                  ["Document type accuracy", "template_accuracy"],
                  ["Values invented", "invented_values"],
                ] as const
              ).map(([label, key]) => (
                <div key={key}>
                  <span>{label}</span>
                  <strong>
                    {key === "invented_values"
                      ? report.test_before_learning[key]
                      : pct(report.test_before_learning[key])}
                    {" → "}
                    {key === "invented_values"
                      ? report.test_after_learning[key]
                      : pct(report.test_after_learning[key])}
                  </strong>
                </div>
              ))}
            </div>
            <p className="muted small">
              {report.method} Train {report.splits.train} / validation{" "}
              {report.splits.validation} / test {report.splits.test} documents;
              activation threshold chosen on validation:{" "}
              {report.min_support_chosen}. Rules active:{" "}
              {Object.entries(report.rules_active)
                .map(([k, v]) => `${v} ${k}`)
                .join(", ")}
              . {report.test_after_learning.fields_evaluated} field values
              scored · ran {report.seconds}s · {report.generated}.
            </p>
          </>
        )}
      </section>
      <section className="panel">
        <h2>Rules ({rules.length})</h2>
        {rules.length === 0 ? (
          <Empty icon={<FlaskConical size={28} />} title="No rules yet">
            Correct a field during review and approve: LETRANIX records the
            correction and derives a rule from it.
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Field</th>
                  <th>Rule</th>
                  <th className="num">Confirmed</th>
                  <th className="num">Contradicted</th>
                  <th className="num">Applied</th>
                  <th>State</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id}>
                    <td>{name(r.template_id)}</td>
                    <td>
                      <code>{r.field}</code>
                    </td>
                    <td>
                      <span className="muted small">{KIND_HELP[r.kind]}</span>
                      <br />
                      {r.kind === "alias" ? (
                        <code>“{r.pattern}:”</code>
                      ) : (
                        <code>
                          {r.pattern} → {r.replacement}
                        </code>
                      )}
                    </td>
                    <td className="num">{r.support}</td>
                    <td className="num">{r.rejected}</td>
                    <td className="num">{r.applied}</td>
                    <td>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={!!r.enabled}
                          onChange={(e) =>
                            run(async () => {
                              await api(`/learning/rules/${r.id}`, {
                                method: "PATCH",
                                body: JSON.stringify({
                                  enabled: e.target.checked,
                                }),
                              });
                              setTick((t) => t + 1);
                            })
                          }
                        />
                        {r.active
                          ? "active"
                          : r.enabled
                            ? "collecting evidence"
                            : "disabled"}
                      </label>
                    </td>
                    <td>
                      <button
                        className="icon ghost"
                        aria-label="Delete rule"
                        onClick={() =>
                          run(async () => {
                            await api(`/learning/rules/${r.id}`, {
                              method: "DELETE",
                            });
                            setTick((t) => t + 1);
                          }, "Rule deleted.")
                        }
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
