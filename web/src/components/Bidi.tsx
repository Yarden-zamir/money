/**
 * Text that mixes scripts, laid out so neither script reorders the other.
 *
 * A commit subject is built from a template and a name the person chose, so a Hebrew bucket
 * name lands in the middle of an English sentence full of numbers. The bidi algorithm then
 * resolves the neutral characters *between* them — the spaces, the arrow — to the Hebrew
 * run's direction and lays the numbers out right to left. "מכולת 0.00 → 2000.00" renders as
 * "2000.00 → 0.00 מכולת": the same characters, the assignment backwards.
 *
 * Isolating each right-to-left run fixes it at the source. Inside `<bdi>` the run is opaque
 * to the algorithm — it cannot claim the neutrals on either side of it — while still being
 * laid out right to left internally, which is what keeps the Hebrew itself correct.
 *
 * Doing this in the markup rather than by putting U+2068 into the commit message keeps the
 * repo readable on its own terms. The data is meant to make sense without this app, and a
 * commit subject carrying invisible control characters is a worse artefact than one that
 * needs a client to lay it out.
 */

type Class = "rtl" | "ltr" | "neutral";

function classify(character: string): Class {
  const code = character.codePointAt(0) ?? 0;

  if (
    (code >= 0x0590 && code <= 0x05ff) || // Hebrew
    (code >= 0x0600 && code <= 0x06ff) || // Arabic
    (code >= 0x0700 && code <= 0x074f) || // Syriac
    (code >= 0x0780 && code <= 0x07bf) || // Thaana
    (code >= 0xfb1d && code <= 0xfdff) || // Hebrew and Arabic presentation forms
    (code >= 0xfe70 && code <= 0xfeff)
  ) {
    return "rtl";
  }

  // Digits count as left-to-right rather than neutral. They are the thing being protected:
  // an amount that follows a Hebrew name must stay outside the isolate, or it ends up laid
  // out inside it and reads backwards.
  const isLetter = character.toLowerCase() !== character.toUpperCase();
  const isDigit = code >= 0x30 && code <= 0x39;
  return isLetter || isDigit ? "ltr" : "neutral";
}

/**
 * Split into runs, where a right-to-left run keeps the neutrals *inside* it.
 *
 * The inner spaces matter: splitting "בית עסק" at its space would isolate each word
 * separately, and two isolated boxes in an English sentence are placed left to right — which
 * reverses a Hebrew phrase while looking, character for character, entirely correct. A
 * neutral belongs to the right-to-left run only when right-to-left text resumes after it.
 */
export function bidiRuns(text: string): { text: string; rtl: boolean }[] {
  const characters = [...text];
  const classes = characters.map(classify);

  // A neutral is part of the surrounding right-to-left text when it is enclosed by it.
  const inRun = classes.map((cls) => cls === "rtl");
  for (let index = 0; index < classes.length; index += 1) {
    if (classes[index] !== "neutral" || !inRun[index - 1]) continue;

    let ahead = index;
    while (ahead < classes.length && classes[ahead] === "neutral") ahead += 1;
    if (classes[ahead] === "rtl") {
      for (let fill = index; fill < ahead; fill += 1) inRun[fill] = true;
    }
  }

  const runs: { text: string; rtl: boolean }[] = [];
  characters.forEach((character, index) => {
    const rtl = inRun[index] ?? false;
    const last = runs[runs.length - 1];
    if (last && last.rtl === rtl) last.text += character;
    else runs.push({ text: character, rtl });
  });
  return runs;
}

export function Bidi({ text, className }: { text: string; className?: string }) {
  const runs = bidiRuns(text);

  // Nothing to isolate: keep the DOM as plain as it was.
  if (!runs.some((run) => run.rtl)) return <span className={className}>{text}</span>;

  return (
    <span className={className}>
      {runs.map((run, index) => (run.rtl ? <bdi key={index}>{run.text}</bdi> : run.text))}
    </span>
  );
}
