"""Build a field × field PPMI co-occurrence matrix from defs.jsonl."""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from math import log
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, lil_matrix, save_npz, load_npz

from cobble.experimental.aggregates.io import extract_paragraph, parse_extent, read_jsonl

logger = logging.getLogger(__name__)

INFRA_PREFIXES = ("9999-",)


def _is_infra(para: str) -> bool:
    return any(para.startswith(p) for p in INFRA_PREFIXES)


def build_ppmi_matrix(
    defs_path: Path,
    canonical_map: dict[str, str] | None = None,
    min_fields_per_para: int = 3,
    min_occurrences: int = 5,
    min_cooccurrences: int = 3,
) -> tuple[csr_matrix, list[str], list[dict], dict]:
    """Build a symmetric PPMI matrix from paragraph–field co-occurrences.

    Returns *(matrix, field_list, paragraph_list, stats)*.
    """
    cmap = canonical_map or {}

    def canon(field: str) -> str:
        return cmap.get(field, field)

    para_fields: dict[tuple[str, str], set[str]] = defaultdict(set)
    field_to_raw: dict[str, set[str]] = defaultdict(set)

    for row in read_jsonl(defs_path):
        program = row.get("program", "")
        node = row["node"]
        para = extract_paragraph(node)
        if _is_infra(para):
            continue

        para_key = (program, para)
        parsed = parse_extent(row["extent"])
        if parsed is None:
            continue
        raw_field = parsed[0]
        field = canon(raw_field)

        para_fields[para_key].add(field)
        field_to_raw[field].add(raw_field)

        for d in row.get("definers", []):
            d_para = extract_paragraph(d)
            if not _is_infra(d_para):
                para_fields[(program, d_para)].add(field)

    para_fields = {
        k: v for k, v in para_fields.items() if len(v) >= min_fields_per_para
    }
    n_paras = len(para_fields)
    logger.info("matrix: %d paragraphs after filtering", n_paras)

    field_freq: Counter = Counter()
    for fields in para_fields.values():
        for f in fields:
            field_freq[f] += 1

    valid = {f for f, c in field_freq.items() if c >= min_occurrences}
    field_list = sorted(valid)
    field_idx = {f: i for i, f in enumerate(field_list)}
    n_fields = len(field_list)
    logger.info("matrix: %d fields (min %d occurrences)", n_fields, min_occurrences)

    pair_count: Counter = Counter()
    for fields in para_fields.values():
        fl = sorted(fields & valid)
        for i in range(len(fl)):
            for j in range(i + 1, len(fl)):
                pair_count[(fl[i], fl[j])] += 1

    mat = lil_matrix((n_fields, n_fields), dtype=np.float32)
    nnz = 0
    for (a, b), count in pair_count.items():
        if count < min_cooccurrences:
            continue
        pa = field_freq[a] / n_paras
        pb = field_freq[b] / n_paras
        pab = count / n_paras
        pmi = log(pab / (pa * pb)) / log(2)
        if pmi > 0:
            ia, ib = field_idx[a], field_idx[b]
            mat[ia, ib] = pmi
            mat[ib, ia] = pmi
            nnz += 2

    result = mat.tocsr()
    logger.info("matrix: %d × %d, %d non-zeros", n_fields, n_fields, result.nnz)

    para_list = [{"program": p, "paragraph": q} for p, q in sorted(para_fields.keys())]
    stats = {
        "n_paragraphs": n_paras,
        "n_fields": n_fields,
        "nnz": result.nnz,
        "min_fields_per_para": min_fields_per_para,
        "min_occurrences": min_occurrences,
        "min_cooccurrences": min_cooccurrences,
    }
    return result, field_list, para_list, stats


def save_matrix(
    matrix: csr_matrix,
    field_list: list[str],
    para_list: list[dict],
    stats: dict,
    matrix_path: Path,
    meta_path: Path,
) -> None:
    save_npz(matrix_path, matrix)
    meta = {"fields": field_list, "paragraphs": para_list, **stats}
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("matrix: saved to %s + %s", matrix_path, meta_path)


def load_matrix(
    matrix_path: Path, meta_path: Path
) -> tuple[csr_matrix, list[str], dict]:
    mat = load_npz(matrix_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return mat, meta["fields"], meta
