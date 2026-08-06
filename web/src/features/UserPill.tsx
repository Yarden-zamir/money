import { useState } from "react";
import { useTranslation } from "react-i18next";

import { MemberDot } from "@/components/FunderBars";
import { actingAs, setActingAs } from "@/lib/actingAs";
import { nameFor } from "@/lib/members";
import { useBudget } from "./useBudget";

/**
 * Who this browser is speaking for.
 *
 * Always shows the current member, because in a budget where several people's figures sit
 * side by side, "whose ready-to-assign is this" needs an answer that is on screen rather than
 * inferred.
 *
 * It also switches, which is a testing affordance: driving the app as each of several
 * placeholder members shows how a shared budget behaves without needing four GitHub accounts.
 * Only members with **no GitHub login** are offered, and the server enforces that
 * independently — a request naming a real account is refused with a 403, so this list being
 * wrong could never become an impersonation. Commits keep the signed-in person as author
 * either way.
 */
export function UserPill() {
  const { t } = useTranslation();
  const { budget } = useBudget();
  const [open, setOpen] = useState(false);

  if (!budget) return null;

  const current = actingAs() ?? budget.me;
  if (!current) return null;

  // A placeholder is somebody nobody can sign in as, which is exactly what makes standing in
  // for them harmless.
  const placeholders = budget.members.filter((member) => !member.github);
  const canSwitch = placeholders.length > 0;

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        onClick={() => canSwitch && setOpen(!open)}
        aria-haspopup={canSwitch || undefined}
        aria-expanded={canSwitch ? open : undefined}
        title={actingAs() ? t("people.actingAs", { name: nameFor(current, budget.members) }) : undefined}
        className={`flex h-9 items-center gap-1.5 rounded-lg border border-line px-2.5 text-xs ${
          canSwitch ? "hover:bg-surface" : "cursor-default"
        } ${actingAs() ? "border-brand text-brand" : "text-ink-muted"}`}
      >
        <MemberDot person={current} members={budget.members} />
        <span className="max-w-24 truncate">{nameFor(current, budget.members)}</span>
      </button>

      {open && (
        <span className="absolute top-full z-30 mt-1 w-52 rounded-lg border border-line bg-card p-1 shadow-lg end-0">
          <span className="block px-2 py-1 text-[11px] text-ink-muted">{t("people.switch")}</span>

          <Choice
            label={nameFor(budget.me ?? "", budget.members) || t("people.me")}
            person={budget.me ?? ""}
            members={budget.members}
            active={!actingAs()}
            onPick={() => setActingAs(null)}
          />
          {placeholders.map((member) => (
            <Choice
              key={member.person}
              label={member.name}
              person={member.person}
              members={budget.members}
              active={actingAs() === member.person}
              onPick={() => setActingAs(member.person)}
            />
          ))}
        </span>
      )}
    </span>
  );
}

function Choice({
  label,
  person,
  members,
  active,
  onPick,
}: {
  label: string;
  person: string;
  members: { person: string; name: string; github?: string | null }[];
  active: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onPick}
      className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-start text-xs transition ${
        active ? "bg-brand-soft text-brand" : "hover:bg-surface"
      }`}
    >
      <MemberDot person={person} members={members} />
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </button>
  );
}
