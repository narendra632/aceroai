import { useEffect, useState } from "react";

/* A media query as state, for the cases CSS cannot cover.
 *
 * Written because of a real bug: the Learn panel rendered twice on a wide screen. The
 * inline panel was `hidden lg:block` and the Sheet's wrapper was `lg:hidden`, which looks
 * correct — but a Radix Sheet renders through a **portal** into document.body, so it is no
 * longer a descendant of that wrapper and the class never applies to it. Both panels drew.
 *
 * Anything portalled has escaped its CSS ancestors, so the decision to render it has to be
 * made in JavaScript rather than hidden with a class.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window === "undefined" ? false : window.matchMedia(query).matches,
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange(); // resync in case the width changed between render and effect
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}
