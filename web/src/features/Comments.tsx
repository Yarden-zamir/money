import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addCommentMutation,
  deleteCommentMutation,
  listCommentsOptions,
  listCommentsQueryKey,
} from "@/api/@tanstack/react-query.gen";
import type { BudgetSummary, Comment } from "@/api/types.gen";
import { MemberDot } from "@/components/FunderBars";
import { FormError } from "@/components/Form";
import { Icon } from "@/components/Icon";
import { actingAs } from "@/lib/actingAs";
import { colourFor, nameFor } from "@/lib/members";

/**
 * The conversation under an entry, laid out as chat.
 *
 * Chat rather than a list of annotations because that is what the messages are: "did you
 * keep the receipt?" — "yes, attached". Your own messages sit at the inline end, everyone
 * else's at the start, the way every messaging app people already use does it, so nobody
 * has to read the author line to know who is talking.
 *
 * "Live" is polling: the thread refetches every few seconds while it is open, faster than
 * the app's ten-second poll because a reply is being waited for. A sent message is shown
 * at once and confirmed by the response, which returns the whole thread — so a reply that
 * crossed with yours appears in the same round trip.
 */
const LIVE_INTERVAL = 4_000;

export function Comments({ entryId, budget }: { entryId: string; budget: BudgetSummary }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const me = actingAs() ?? budget.me;
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  const key = listCommentsQueryKey({ path: { budget: budget.slug, entry_id: entryId } });
  const thread = useQuery({
    ...listCommentsOptions({ path: { budget: budget.slug, entry_id: entryId } }),
    refetchInterval: LIVE_INTERVAL,
  });

  const send = useMutation({
    ...addCommentMutation(),
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<{ entry_id: string; comments: Comment[] }>(key);
      if (previous && me) {
        queryClient.setQueryData(key, {
          ...previous,
          comments: [
            ...previous.comments,
            {
              id: "pending",
              author: me,
              at: new Date().toISOString(),
              text: variables.body.text,
            },
          ],
        });
      }
      return { previous };
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous);
    },
    onSuccess: (result) => {
      queryClient.setQueryData(key, result);
      // Badges on the ledger and the history feed both change; everything else is cheap.
      void queryClient.invalidateQueries({ predicate: (query) => query.queryKey !== key });
    },
  });

  const remove = useMutation({
    ...deleteCommentMutation(),
    onSuccess: (result) => {
      queryClient.setQueryData(key, result);
      void queryClient.invalidateQueries({ predicate: (query) => query.queryKey !== key });
    },
  });

  const comments = thread.data?.comments ?? [];

  // Keep the newest message in view, as a chat does, without scrolling the page itself.
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [comments.length]);

  const submit = () => {
    const text = draft.trim();
    if (!text || send.isPending) return;
    setDraft("");
    send.mutate({ path: { budget: budget.slug, entry_id: entryId }, body: { text } });
  };

  return (
    <div className="flex max-h-96 flex-col">
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pe-1">
        {thread.isPending && (
          <p className="text-xs text-ink-muted">{t("common.loading")}</p>
        )}
        {thread.isSuccess && comments.length === 0 && (
          <p className="rounded-lg bg-sunken p-3 text-xs text-ink-muted">{t("comments.empty")}</p>
        )}
        {comments.map((comment) => (
          <Bubble
            key={comment.id}
            comment={comment}
            mine={comment.author === me}
            pending={comment.id === "pending"}
            members={budget.members}
            locale={i18n.language}
            onDelete={
              comment.author === me && comment.id !== "pending" && budget.can_write
                ? () => {
                    if (window.confirm(t("comments.confirmDelete"))) {
                      remove.mutate({
                        path: { budget: budget.slug, entry_id: entryId, comment_id: comment.id },
                      });
                    }
                  }
                : undefined
            }
          />
        ))}
        <div ref={bottom} />
      </div>

      {budget.can_write && (
        <form
          className="mt-2 flex items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <textarea
            className="control min-h-11 flex-1 resize-none py-2.5 leading-snug"
            rows={1}
            value={draft}
            placeholder={t("comments.placeholder")}
            aria-label={t("comments.placeholder")}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends, as in chat. Shift+Enter is the newline.
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
          />
          <button
            type="submit"
            disabled={!draft.trim() || send.isPending}
            aria-label={t("comments.send")}
            title={t("comments.send")}
            className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-brand text-on-brand transition hover:opacity-90 disabled:opacity-40"
          >
            <Icon name="send" className="size-5" directional />
          </button>
        </form>
      )}
      <FormError error={send.error ?? remove.error} />
    </div>
  );
}

function Bubble({
  comment,
  mine,
  pending,
  members,
  locale,
  onDelete,
}: {
  comment: Comment;
  mine: boolean;
  pending: boolean;
  members: BudgetSummary["members"];
  locale: string;
  onDelete?: () => void;
}) {
  const { t } = useTranslation();
  const when = new Date(comment.at);
  const stamp = Number.isNaN(when.getTime())
    ? ""
    : new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(when);

  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={`group max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
          mine ? "rounded-ee-md bg-brand-soft text-ink" : "rounded-es-md bg-sunken"
        } ${pending ? "opacity-60" : ""}`}
        style={mine ? undefined : { borderInlineStart: `3px solid ${colourFor(comment.author, members)}` }}
      >
        <div className="mb-0.5 flex items-center gap-1.5 text-[11px] text-ink-muted">
          {!mine && <MemberDot person={comment.author} members={members} />}
          <span className="font-medium">
            {mine ? t("comments.you") : nameFor(comment.author, members)}
          </span>
          <span className="numeric">{stamp}</span>
          {onDelete && (
            <button
              type="button"
              onClick={onDelete}
              aria-label={t("comments.delete")}
              title={t("comments.delete")}
              className="ms-1 opacity-0 transition hover:text-negative focus:opacity-100 group-hover:opacity-100"
            >
              <Icon name="close" className="size-3" />
            </button>
          )}
        </div>
        {/* A message is written in whichever script its author thinks in, so its base
            direction comes from its own first strong character rather than the page: an
            English sentence in a Hebrew thread otherwise lands its full stop at the start.
            Plain text, not <Bidi>: that component isolates runs for template-plus-name
            strings, and `dir="auto"` skips isolated runs when choosing a direction, which
            left a Hebrew sentence with a number in it laid out left to right. */}
        <div dir="auto" className="whitespace-pre-wrap break-words">
          {comment.text}
        </div>
      </div>
    </div>
  );
}
