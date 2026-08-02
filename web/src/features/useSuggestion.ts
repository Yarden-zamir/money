import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { nearbyPlacesOptions, suggestEntryOptions } from "@/api/@tanstack/react-query.gen";

export type Coords = { lat: number; lon: number };

/**
 * The device's position, asked for once and only when it is wanted.
 *
 * Geolocation is requested when someone opens the add-entry form, never in the background —
 * the permission prompt should arrive attached to the thing it is for. A refusal is a normal
 * outcome, not an error: everything downstream works without it, just with weaker guesses.
 */
export function useCoords(enabled: boolean): {
  coords: Coords | null;
  state: "idle" | "asking" | "ready" | "denied";
} {
  const [coords, setCoords] = useState<Coords | null>(null);
  const [state, setState] = useState<"idle" | "asking" | "ready" | "denied">("idle");

  useEffect(() => {
    if (!enabled || state !== "idle" || !("geolocation" in navigator)) return;

    setState("asking");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCoords({ lat: position.coords.latitude, lon: position.coords.longitude });
        setState("ready");
      },
      () => setState("denied"),
      // A cached fix from the last few minutes is plenty for "which shop is this", and much
      // faster than waiting for a fresh high-accuracy lock indoors.
      { maximumAge: 300_000, timeout: 8_000, enableHighAccuracy: false },
    );
  }, [enabled, state]);

  return { coords, state };
}

/**
 * What this person is probably about to record.
 *
 * Re-queried as the payee changes, because naming one narrows the pool the place and time
 * signals draw from — that chaining is the whole point, so a suggestion is not computed once
 * and then left stale.
 */
export function useSuggestion({
  budget,
  enabled,
  payee,
  coords,
}: {
  budget: string;
  enabled: boolean;
  payee: string;
  coords: Coords | null;
}) {
  const [debounced, setDebounced] = useState(payee);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(payee.trim()), 250);
    return () => clearTimeout(timer);
  }, [payee]);

  return useQuery({
    ...suggestEntryOptions({
      path: { budget },
      query: {
        ...(debounced ? { payee: debounced } : {}),
        ...(coords ? { lat: coords.lat, lon: coords.lon } : {}),
        at: new Date().toISOString(),
      },
    }),
    enabled: enabled && Boolean(budget),
    retry: false,
  });
}

/** Venues around the device, so the first visit to a place does not need typing. */
export function useNearbyPlaces(coords: Coords | null) {
  return useQuery({
    ...nearbyPlacesOptions({ query: { lat: coords?.lat ?? 0, lon: coords?.lon ?? 0 } }),
    enabled: Boolean(coords),
    retry: false,
    // A place does not move, so there is no reason to ask again while the form is open.
    staleTime: 5 * 60_000,
  });
}
