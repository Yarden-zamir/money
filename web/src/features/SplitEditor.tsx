import { useTranslation } from "react-i18next";

import type { BucketOutput, Member } from "@/api/types.gen";
import { Button, Input, Select } from "@/components/Form";

/**
 * Edits the two halves of an entry independently: who paid, and who bears it out of which
 * bucket. Keeping them separate is what lets one record serve both the envelope budget and
 * the shared-expense balance, so the editor shows both and refuses to guess.
 *
 * Amounts are kept as strings the whole way. They are decimals on the wire and the backend
 * checks that each side sums to the entry total; parsing them into JS numbers here would
 * reintroduce exactly the drift that is being avoided.
 */

export type ShareRow = { person: string; amount: string; bucket: string };
export type PaidRow = { person: string; amount: string };

function sum(values: string[]): number {
  return values.reduce((total, value) => total + (Number(value) || 0), 0);
}

function Balance({ actual, expected, label }: { actual: number; expected: number; label: string }) {
  // Compared at 2 decimal places because that is the precision the backend stores; a
  // difference smaller than an agora is not a real difference.
  const ok = Math.abs(actual - expected) < 0.005;
  return (
    <span className={`text-xs ${ok ? "text-ink-muted" : "text-negative"}`}>
      {label}: <span className="numeric">{actual.toFixed(2)}</span> /{" "}
      <span className="numeric">{expected.toFixed(2)}</span>
    </span>
  );
}

export function SplitEditor({
  members,
  buckets,
  total,
  shares,
  paidBy,
  onSharesChange,
  onPaidByChange,
  showBuckets,
}: {
  members: Member[];
  buckets: BucketOutput[];
  total: string;
  shares: ShareRow[];
  paidBy: PaidRow[];
  onSharesChange: (rows: ShareRow[]) => void;
  onPaidByChange: (rows: PaidRow[]) => void;
  showBuckets: boolean;
}) {
  const { t } = useTranslation();
  const expected = Number(total) || 0;

  const firstPerson = members[0]?.person ?? "";

  return (
    <div className="mt-3 grid gap-4 sm:grid-cols-2">
      <section>
        <header className="mb-2 flex items-center gap-2">
          <h3 className="text-xs font-medium text-ink-muted">{t("entries.paidBy")}</h3>
          <Balance
            label={t("entries.total")}
            actual={sum(paidBy.map((row) => row.amount))}
            expected={expected}
          />
        </header>

        {paidBy.map((row, index) => (
          <div key={index} className="mb-2 flex gap-2">
            <Select
              value={row.person}
              onChange={(event) =>
                onPaidByChange(
                  paidBy.map((r, i) => (i === index ? { ...r, person: event.target.value } : r)),
                )
              }
            >
              {members.map((member) => (
                <option key={member.person} value={member.person}>
                  {member.name}
                </option>
              ))}
            </Select>
            <Input
              fullWidth={false}
              className="numeric ltr-field w-full sm:w-28"
              inputMode="decimal"
              value={row.amount}
              onChange={(event) =>
                onPaidByChange(
                  paidBy.map((r, i) => (i === index ? { ...r, amount: event.target.value } : r)),
                )
              }
            />
            {paidBy.length > 1 && (
              <Button
                type="button"
                variant="quiet"
                onClick={() => onPaidByChange(paidBy.filter((_, i) => i !== index))}
              >
                ×
              </Button>
            )}
          </div>
        ))}

        <Button
          type="button"
          variant="quiet"
          onClick={() => onPaidByChange([...paidBy, { person: firstPerson, amount: "" }])}
        >
          + {t("entries.addPayer")}
        </Button>
      </section>

      <section>
        <header className="mb-2 flex items-center gap-2">
          <h3 className="text-xs font-medium text-ink-muted">{t("entries.bears")}</h3>
          <Balance
            label={t("entries.total")}
            actual={sum(shares.map((row) => row.amount))}
            expected={expected}
          />
        </header>

        {shares.map((row, index) => (
          <div key={index} className="mb-2 flex gap-2">
            <Select
              value={row.person}
              onChange={(event) =>
                onSharesChange(
                  shares.map((r, i) => (i === index ? { ...r, person: event.target.value } : r)),
                )
              }
            >
              {members.map((member) => (
                <option key={member.person} value={member.person}>
                  {member.name}
                </option>
              ))}
            </Select>
            <Input
              fullWidth={false}
              className="numeric ltr-field w-full sm:w-24"
              inputMode="decimal"
              value={row.amount}
              onChange={(event) =>
                onSharesChange(
                  shares.map((r, i) => (i === index ? { ...r, amount: event.target.value } : r)),
                )
              }
            />
            {showBuckets && (
              <Select
                value={row.bucket}
                onChange={(event) =>
                  onSharesChange(
                    shares.map((r, i) => (i === index ? { ...r, bucket: event.target.value } : r)),
                  )
                }
              >
                <option value="">—</option>
                {buckets.map((bucket) => (
                  <option key={bucket.id} value={bucket.id}>
                    {bucket.name}
                  </option>
                ))}
              </Select>
            )}
            {shares.length > 1 && (
              <Button
                type="button"
                variant="quiet"
                onClick={() => onSharesChange(shares.filter((_, i) => i !== index))}
              >
                ×
              </Button>
            )}
          </div>
        ))}

        <Button
          type="button"
          variant="quiet"
          onClick={() =>
            onSharesChange([...shares, { person: firstPerson, amount: "", bucket: "" }])
          }
        >
          + {t("entries.addShare")}
        </Button>
      </section>
    </div>
  );
}

/** Even split of `total` across everyone, with the rounding remainder on the first person. */
export function evenSplit(members: Member[], total: string, bucket: string): ShareRow[] {
  const expected = Number(total) || 0;
  if (members.length === 0) return [];

  const each = Math.round((expected / members.length) * 100) / 100;
  return members.map((member, index) => ({
    person: member.person,
    amount: (index === 0
      ? Math.round((expected - each * (members.length - 1)) * 100) / 100
      : each
    ).toFixed(2),
    bucket,
  }));
}
