"""Helpers shared by the stats services: pagination, window blocks and pre/post comparisons."""
from __future__ import annotations

import math
from dataclasses import dataclass

Z95 = 1.959963984540054


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page(items: list, total: int, p: PageParams) -> dict:
    return {"items": items, "page": p.page, "page_size": p.page_size, "total": total,
            "total_pages": math.ceil(total / p.page_size) if total else 0}


def h(poss, opp_poss) -> float | None:
    """Sampling factor of a net rating: Var = K·h, h = 1/poss + 1/opp_poss."""
    return 1 / poss + 1 / opp_poss if poss and opp_poss else None


def window(row: dict, prefix: str, k: float | None, fields: tuple[str, ...]) -> dict | None:
    """Pull the `prefix_*` columns of a joined row into one block; None when the window has no row."""
    if row.get(f"{prefix}_poss") is None:
        return None
    out = {f: row.get(f"{prefix}_{f}") for f in fields}
    hh = h(out.get("poss"), out.get("opp_poss"))
    if k is not None and "net_rating" in out:
        out["net_rating_sampling_sd"] = math.sqrt(k * hh) if hh else None
    return out


def change(pre: dict | None, post: dict | None, k: float | None) -> dict | None:
    if pre is None or post is None:
        return None
    d = {m: (post[m] - pre[m]) if post.get(m) is not None and pre.get(m) is not None else None
         for m in ("off_rating", "def_rating", "net_rating")}
    hp, hq = h(pre.get("poss"), pre.get("opp_poss")), h(post.get("poss"), post.get("opp_poss"))
    sd = math.sqrt(k * (hp + hq)) if k is not None and hp and hq else None
    d["net_rating_sampling_sd"] = sd
    d["exceeds_noise"] = None if sd is None or d["net_rating"] is None else bool(abs(d["net_rating"]) > Z95 * sd)
    return d


def like_pattern(text: str) -> str:
    """Escape LIKE wildcards in user input, so 'a_b%' matches literally."""
    return "%" + text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
