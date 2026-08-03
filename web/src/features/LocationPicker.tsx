import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { nearbyPlacesOptions, searchPlacesOptions } from "@/api/@tanstack/react-query.gen";
import type { NearbyPlaceResponse } from "@/api/types.gen";
import { Button, Input } from "@/components/Form";
import { Icon } from "@/components/Icon";
import type { Coords } from "./useSuggestion";

export type PickedPlace = { lat: number; lon: number; name: string | null; provider_id?: string };

/**
 * Choosing where an entry happened.
 *
 * The device fix answers "where am I now", which is right at a till and wrong for everything
 * else — yesterday's lunch, a shop you have left, an online order that belongs nowhere. This
 * is the manual path: move the map, and the pin is where the money went.
 *
 * **Tiles come from OpenStreetMap, names come from Google.** They are different problems.
 * Drawing a map needs no key and OSM does it well; naming venues in Israel is where OSM was
 * judged inadequate, and Google Places already answers that through our own backend — which
 * is the only way it can, since the Places key must never reach a browser.
 *
 * 🟠 OSM's tile policy asks that heavy use go elsewhere. A household budget is nowhere near
 * that, but if this app ever has many users, the fix is a paid tile host (MapTiler, Stadia) —
 * a URL and a key, not a rewrite, because Leaflet does not care where a tile came from.
 */
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

/** Tel Aviv, used only when there is no fix and nothing has been picked yet. */
const FALLBACK: Coords = { lat: 32.0853, lon: 34.7818 };

/**
 * Leaflet's default marker is three PNGs it resolves relative to the stylesheet, which the
 * bundler rewrites and the CDN fallback then fails to find — the classic "marker is a broken
 * image" bug. A div with our own styling has no such dependency and themes correctly.
 */
const PIN = L.divIcon({
  className: "",
  html: '<span class="block size-4 rounded-full border-2 border-white bg-brand shadow-lg"></span>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

export function LocationPicker({
  coords,
  initial,
  onPick,
  onCancel,
}: {
  coords: Coords | null;
  initial: PickedPlace | null;
  onPick: (place: PickedPlace) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const marker = useRef<L.Marker | null>(null);

  const start = initial
    ? { lat: initial.lat, lon: initial.lon }
    : (coords ?? FALLBACK);

  const [centre, setCentre] = useState<Coords>(start);
  const [name, setName] = useState(initial?.name ?? "");
  const [providerId, setProviderId] = useState(initial?.provider_id);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!container.current || map.current) return;

    const instance = L.map(container.current, {
      center: [start.lat, start.lon],
      zoom: 16,
      // The picker lives inside a dialog that scrolls. Scroll-to-zoom would eat the page
      // scroll the moment the pointer crossed the map; pinch and the +/- control still work.
      scrollWheelZoom: false,
      attributionControl: true,
    });
    L.tileLayer(TILES, { attribution: ATTRIBUTION, maxZoom: 19 }).addTo(instance);

    const pin = L.marker([start.lat, start.lon], { icon: PIN, draggable: true }).addTo(instance);

    // Two ways to move it, because they suit different hands: drag the pin, or tap the map.
    pin.on("dragend", () => {
      const { lat, lng } = pin.getLatLng();
      setCentre({ lat, lon: lng });
      setProviderId(undefined); // it is no longer the venue that was picked
    });
    instance.on("click", (event: L.LeafletMouseEvent) => {
      pin.setLatLng(event.latlng);
      setCentre({ lat: event.latlng.lat, lon: event.latlng.lng });
      setProviderId(undefined);
    });

    map.current = instance;
    marker.current = pin;

    // The picker opens at the bottom of a long form, which on a phone is past the fold: the
    // button appears to do nothing. Bring it into view rather than expecting a scroll.
    container.current.scrollIntoView({ block: "nearest", behavior: "smooth" });

    // A map created inside a container that was not yet laid out measures itself as zero and
    // renders one grey tile. Re-measuring after the browser has painted is the documented fix.
    requestAnimationFrame(() => instance.invalidateSize());

    return () => {
      instance.remove();
      map.current = null;
      marker.current = null;
    };
    // Runs once: `start` is the opening position, and re-centring on every state change would
    // fight the person dragging the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Venues at wherever the pin currently is, so a point can be given a name. */
  const nearby = useQuery({
    ...nearbyPlacesOptions({ query: { lat: centre.lat, lon: centre.lon } }),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const found = useQuery({
    ...searchPlacesOptions({
      query: { q: debounced, ...(coords ? { lat: coords.lat, lon: coords.lon } : {}) },
    }),
    enabled: debounced.length > 1,
    staleTime: 5 * 60_000,
    retry: false,
  });

  /** Choosing a venue moves the pin to it — the venue's position, not the phone's. */
  const choose = (place: NearbyPlaceResponse) => {
    setName(place.name);
    setProviderId(place.id);
    setCentre({ lat: place.lat, lon: place.lon });
    marker.current?.setLatLng([place.lat, place.lon]);
    map.current?.panTo([place.lat, place.lon]);
    setQuery("");
  };

  const results = debounced.length > 1 ? (found.data ?? []) : (nearby.data ?? []);

  return (
    <div className="space-y-3">
      <div
        ref={container}
        className="h-64 w-full overflow-hidden rounded-card border border-line"
        // Leaflet positions tiles itself and its controls are laid out in physical
        // coordinates, so the map is always LTR whatever the page direction.
        dir="ltr"
      />

      <p className="text-xs text-ink-muted">{t("place.pickHint")}</p>

      <Input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t("place.searchPlaceholder")}
        aria-label={t("place.search")}
      />

      {results.length > 0 && (
        <ul className="max-h-40 divide-y divide-line overflow-y-auto rounded-lg border border-line">
          {results.map((place) => (
            <li key={place.id}>
              <button
                type="button"
                onClick={() => choose(place)}
                className={`flex w-full items-center gap-2 p-2.5 text-start text-sm transition ${
                  providerId === place.id ? "bg-brand-soft" : "hover:bg-surface"
                }`}
              >
                <Icon name="target" className="size-3.5 shrink-0 text-ink-muted" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{place.name}</span>
                  {place.address && (
                    <span className="block truncate text-xs text-ink-muted">{place.address}</span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <Input
        value={name}
        onChange={(event) => {
          setName(event.target.value);
          setProviderId(undefined); // a typed name is not Google's name for this point
        }}
        placeholder={t("place.namePlaceholder")}
        aria-label={t("place.name")}
      />

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          className="min-h-9 px-3"
          onClick={() =>
            onPick({
              lat: centre.lat,
              lon: centre.lon,
              name: name.trim() || null,
              ...(providerId ? { provider_id: providerId } : {}),
            })
          }
        >
          {t("place.use")}
        </Button>
        <Button type="button" variant="ghost" className="min-h-9 px-3" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        {coords && (
          <Button
            type="button"
            variant="quiet"
            className="min-h-9 px-3"
            onClick={() => {
              marker.current?.setLatLng([coords.lat, coords.lon]);
              map.current?.panTo([coords.lat, coords.lon]);
              setCentre(coords);
              setProviderId(undefined);
            }}
          >
            <Icon name="target" className="size-3.5" />
            {t("place.useDevice")}
          </Button>
        )}
      </div>
    </div>
  );
}
