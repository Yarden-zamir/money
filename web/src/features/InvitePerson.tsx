import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  inviteCollaboratorMutation,
  listCollaboratorsOptions,
  searchGithubUsersOptions,
} from "@/api/@tanstack/react-query.gen";
import type { BudgetSummary, UserOption } from "@/api/types.gen";
import { Button, Card, FormError, Input } from "@/components/Form";
import { ErrorState, Loading } from "@/components/States";

/**
 * Invites someone to the budget, for real.
 *
 * Adding a row to the member list never gave anyone access — repo access is the actual
 * permission — so the two steps had to be done in different places and it was easy to do
 * only one. This does both: it sends a GitHub invitation *and* adds them as a member, and
 * shows who currently has access including invitations still pending.
 */
export function InvitePerson({ budget }: { budget: BudgetSummary }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [chosen, setChosen] = useState<UserOption | null>(null);

  // GitHub's user search is rate limited, so it runs on a pause in typing rather than on
  // every keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const results = useQuery({
    ...searchGithubUsersOptions({ query: { q: debounced } }),
    enabled: debounced.length > 1 && !chosen,
    retry: false,
  });

  const collaborators = useQuery({
    ...listCollaboratorsOptions({ path: { budget: budget.slug } }),
    retry: false,
  });

  const invite = useMutation({
    ...inviteCollaboratorMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries();
      setQuery("");
      setChosen(null);
    },
  });

  const send = () => {
    const login = chosen?.login ?? query.trim();
    if (!login) return;
    invite.mutate({
      path: { budget: budget.slug },
      body: { login, name: chosen?.name ?? null, person: null },
    });
  };

  return (
    <div className="space-y-3">
      {budget.can_write && (
        <div className="relative">
          <span className="mb-1.5 block text-xs font-medium text-ink-muted">
            {t("members.invite")}
          </span>

          <div className="flex flex-wrap gap-2">
            <Input
              fullWidth={false}
              className="ltr-field w-full sm:max-w-xs"
              placeholder={t("members.githubPlaceholder")}
              value={chosen ? chosen.login : query}
              onChange={(event) => {
                setChosen(null);
                setQuery(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  send();
                }
              }}
            />
            <Button
              type="button"
              disabled={!(chosen?.login ?? query.trim()) || invite.isPending}
              onClick={send}
            >
              {invite.isPending ? t("members.inviting") : t("members.sendInvite")}
            </Button>
          </div>

          {/* Suggestions confirm the account exists before an invitation is sent, so a typo
              is a visible "no such user" rather than an invite that goes nowhere. */}
          {!chosen && debounced.length > 1 && (
            <div className="absolute z-10 mt-1 w-full max-w-sm overflow-hidden rounded-xl border border-line bg-card shadow-lg">
              {results.isPending ? (
                <p className="p-3 text-sm text-ink-muted">{t("common.loading")}</p>
              ) : (results.data ?? []).length === 0 ? (
                <p className="p-3 text-sm text-ink-muted">{t("members.noUsers")}</p>
              ) : (
                <ul className="max-h-64 divide-y divide-line overflow-y-auto">
                  {(results.data ?? []).map((user) => (
                    <li key={user.login}>
                      <button
                        type="button"
                        className="flex w-full items-center gap-2 p-2 text-start hover:bg-surface"
                        onClick={() => {
                          setChosen(user);
                          setQuery(user.login);
                        }}
                      >
                        {user.avatar_url && (
                          <img
                            src={user.avatar_url}
                            alt=""
                            className="size-7 shrink-0 rounded-full"
                          />
                        )}
                        <span className="min-w-0">
                          <span className="ltr-field block truncate text-sm">{user.login}</span>
                          {user.name && (
                            <span className="block truncate text-xs text-ink-muted">
                              {user.name}
                            </span>
                          )}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <FormError error={invite.error} />
        </div>
      )}

      <div>
        <span className="mb-1.5 block text-xs font-medium text-ink-muted">
          {t("members.access")}
        </span>

        {collaborators.isPending ? (
          <Loading />
        ) : collaborators.isError ? (
          <ErrorState onRetry={() => void collaborators.refetch()} />
        ) : (
          <Card className="divide-y divide-line">
            {collaborators.data.map((person) => (
              <div key={`${person.login}-${String(person.invited)}`} className="flex items-center gap-2 p-2.5 sm:px-4">
                {person.avatar_url && (
                  <img src={person.avatar_url} alt="" className="size-7 shrink-0 rounded-full" />
                )}
                <span className="ltr-field min-w-0 flex-1 truncate text-sm">{person.login}</span>

                {person.invited && (
                  <span className="shrink-0 rounded-full bg-warning/15 px-2 py-0.5 text-[11px] text-warning">
                    {t("members.pending")}
                  </span>
                )}
                {!person.is_member && !person.invited && (
                  <span className="shrink-0 rounded-full bg-line px-2 py-0.5 text-[11px] text-ink-muted">
                    {t("members.notAMember")}
                  </span>
                )}
                <span className="shrink-0 text-[11px] text-ink-muted">{person.permission}</span>
              </div>
            ))}
          </Card>
        )}
      </div>
    </div>
  );
}
