import argparse
import json
from pathlib import Path
import re
import sys


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _num_sort_key(value: str):
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, value)


def _punct_signature(text: str, punct_chars: str) -> str:
    # Only closing punctuation we want to keep identical to EN.
    return "".join(ch for ch in text if ch in punct_chars)


def _escape_signature(text: str) -> str:
    # Signature for sequences that must be preserved exactly in meaning:
    # - embedded double quotes (represented as \" in raw JSON)
    # - newlines (represented as \n in raw JSON)
    # We compare order and count, independent of translation length.
    out = []
    for ch in text:
        if ch == "\"":
            out.append("Q")
        elif ch == "\n":
            out.append("N")
    return "".join(out)


def _has_double_escaped_sequences(text: str) -> bool:
    # These indicate wrong escaping in the JSON source (e.g. "\\n" instead of "\n").
    return ("\\n" in text) or ("\\\"" in text)


_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+")


_ES_HINT_WORDS = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "de",
    "del",
    "que",
    "y",
    "en",
    "por",
    "para",
    "con",
    "sin",
    "pero",
    "porque",
    "como",
    "cuando",
    "donde",
    "qué",
    "cómo",
    "cuándo",
    "dónde",
    "no",
    "sí",
    "yo",
    "tú",
    "tu",
    "usted",
    "ustedes",
    "mi",
    "mis",
    "me",
    "te",
    "se",
    "lo",
    "le",
    "les",
    "ya",
    "aquí",
    "ahora",
    "hoy",
    "también",
    "entrenador",
    "carrera",
    "entrenamiento",
    "misión",
    "mision",
    "archivo",
    "nivel",
    "bonificación",
    "bonificacion",
}


_EN_HINT_WORDS = {
    "the",
    "and",
    "or",
    "but",
    "because",
    "so",
    "if",
    "then",
    "when",
    "where",
    "what",
    "how",
    "why",
    "not",
    "yes",
    "no",
    "i",
    "i'm",
    "im",
    "you",
    "your",
    "you're",
    "youre",
    "we",
    "we're",
    "were",
    "me",
    "my",
    "mine",
    "our",
    "ours",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "this",
    "that",
    "it's",
    "its",
    "is",
    "are",
    "was",
    "be",
    "have",
    "has",
    "will",
    "can",
    "can't",
    "cant",
    "don't",
    "dont",
    "won't",
    "wont",
    "trainer",
    "mission",
    "archive",
    "level",
}


def _lang_scores(text: str) -> tuple[int, int]:
    """Return (es_score, en_score) for a given text."""
    lowered = text.lower()

    es_score = 0
    en_score = 0

    # Strong character hints
    if "¿" in text or "¡" in text:
        es_score += 3
    if any(ch in text for ch in "áéíóúüñÁÉÍÓÚÜÑ"):
        es_score += 1
    if "Entrenador" in text or "entrenador" in lowered:
        es_score += 3
    if "Trainer" in text or "trainer" in lowered:
        en_score += 3
    if "'" in text:
        en_score += 1

    # Stopword-ish hints
    words = [w.lower() for w in _WORD_RE.findall(text)]
    for w in words:
        if w in _ES_HINT_WORDS:
            es_score += 1
        if w in _EN_HINT_WORDS:
            en_score += 1

    # Extra boosts for very common English patterns
    if " i'm " in f" {lowered} ":
        en_score += 1
    if " don't " in f" {lowered} ":
        en_score += 1
    if " can't " in f" {lowered} ":
        en_score += 1

    return es_score, en_score


def _guess_lang(text: str) -> str:
    es_score, en_score = _lang_scores(text)

    # Thresholds chosen to reduce false positives on short interjections.
    if es_score >= en_score + 3 and es_score >= 4:
        return "es"
    if en_score >= es_score + 3 and en_score >= 4:
        return "en"
    return "unknown"


def _write_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.write("\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audita localized_data/character_system_text_dict.json (ES) contra el archivo EN "
            "para asegurar que no se añadan/quiten signos de cierre, y que se conserven "
            "comillas internas y saltos de línea (\\\" y \\n)."
        )
    )
    parser.add_argument(
        "--es",
        type=Path,
        default=Path("localized_data/character_system_text_dict.json"),
        help="Ruta al JSON español.",
    )
    parser.add_argument(
        "--en",
        type=Path,
        default=Path("localized_data/EN/character_system_text_dict_english.json"),
        help="Ruta al JSON inglés (solo lectura).",
    )
    parser.add_argument(
        "--character",
        type=str,
        default=None,
        help="Limita la auditoría a un ID de personaje (clave de primer nivel), p.ej. 1106.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Máximo de discrepancias a imprimir.",
    )
    parser.add_argument(
        "--punct",
        type=str,
        default="!?",
        help=(
            "Conjunto de signos de cierre a comparar. Por defecto '!?'. "
            "Usa '?' para auditar solo preguntas."
        ),
    )
    parser.add_argument(
        "--summary",
        type=int,
        default=0,
        help="Imprime un resumen de discrepancias por personaje (top N). 0 = no imprimir.",
    )
    parser.add_argument(
        "--report-swaps",
        action="store_true",
        help=(
            "Reporta entradas candidatas a estar invertidas (EN parece español y ES parece inglés)."
        ),
    )
    parser.add_argument(
        "--apply-swaps",
        action="store_true",
        help=(
            "Aplica automáticamente el swap ES↔EN en las entradas detectadas como invertidas "
            "y reescribe ambos archivos. Requiere --yes."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirma operaciones de escritura (usado con --apply-swaps).",
    )
    parser.add_argument(
        "--show-text",
        action="store_true",
        help="Imprime también el texto EN/ES completo en cada discrepancia.",
    )

    args = parser.parse_args(argv)

    es_data = _load_json(args.es)
    en_data = _load_json(args.en)

    missing = []
    mismatches = []
    double_escaped = []
    swap_candidates = []

    all_outer_keys = sorted(set(es_data.keys()) | set(en_data.keys()), key=_num_sort_key)
    for outer_key in all_outer_keys:
        if args.character is not None and outer_key != args.character:
            continue

        es_inner = es_data.get(outer_key)
        en_inner = en_data.get(outer_key)

        if not isinstance(es_inner, dict) or not isinstance(en_inner, dict):
            if outer_key not in es_data:
                missing.append((outer_key, "<ALL>", "Falta en ES"))
            elif outer_key not in en_data:
                missing.append((outer_key, "<ALL>", "Falta en EN"))
            else:
                missing.append((outer_key, "<ALL>", "Estructura distinta (no dict)"))
            continue

        all_inner_keys = sorted(set(es_inner.keys()) | set(en_inner.keys()), key=_num_sort_key)
        for inner_key in all_inner_keys:
            if inner_key not in es_inner:
                missing.append((outer_key, inner_key, "Falta en ES"))
                continue
            if inner_key not in en_inner:
                missing.append((outer_key, inner_key, "Falta en EN"))
                continue

            es_text = es_inner[inner_key]
            en_text = en_inner[inner_key]
            if not isinstance(es_text, str) or not isinstance(en_text, str):
                continue

            if args.report_swaps or args.apply_swaps:
                # Detect swapped-language entries (high-confidence only)
                en_lang = _guess_lang(en_text)
                es_lang = _guess_lang(es_text)
                if en_lang == "es" and es_lang == "en":
                    swap_candidates.append((outer_key, inner_key, en_text, es_text))
                    if args.apply_swaps:
                        es_inner[inner_key], en_inner[inner_key] = en_text, es_text
                        es_text, en_text = en_text, es_text

            if _has_double_escaped_sequences(es_text):
                double_escaped.append((outer_key, inner_key, r"ES contiene \\n o \\\""))

            reasons = []

            en_punct = _punct_signature(en_text, args.punct)
            es_punct = _punct_signature(es_text, args.punct)
            if en_punct != es_punct:
                reasons.append(f"punct_sig EN={en_punct!r} ES={es_punct!r}")

            en_esc = _escape_signature(en_text)
            es_esc = _escape_signature(es_text)
            if en_esc != es_esc:
                reasons.append(f"esc_sig EN={en_esc!r} ES={es_esc!r}")

            # Redundant but clearer counts for quick spotting.
            if "?" in args.punct and en_text.count("?") != es_text.count("?"):
                reasons.append(f"? EN={en_text.count('?')} ES={es_text.count('?')}")
            if "!" in args.punct and en_text.count("!") != es_text.count("!"):
                reasons.append(f"! EN={en_text.count('!')} ES={es_text.count('!')}")
            if en_text.count("\n") != es_text.count("\n"):
                reasons.append(f"\\n EN={en_text.count('\n')} ES={es_text.count('\n')}")
            if en_text.count('"') != es_text.count('"'):
                reasons.append(f"\" EN={en_text.count('"')} ES={es_text.count('"')}")

            if reasons:
                mismatches.append((outer_key, inner_key, reasons, en_text, es_text))

    total_mismatch = len(mismatches)
    total_missing = len(missing)
    total_double_escaped = len(double_escaped)
    total_swaps = len(swap_candidates)

    print("== Audit character_system_text_dict ==")
    print(f"ES: {args.es}")
    print(f"EN: {args.en}")
    if args.character is not None:
        print(f"Filtro character: {args.character}")
    print(f"Discrepancias: {total_mismatch}")
    print(f"Claves faltantes: {total_missing}")
    print(f"Doble-escape detectado (ES): {total_double_escaped}")
    if args.report_swaps or args.apply_swaps:
        print(f"Candidatas swap (EN↔ES): {total_swaps}")

    if args.apply_swaps:
        if not args.yes:
            print("\n[Abortado] --apply-swaps requiere --yes para escribir archivos.")
            return 2
        if swap_candidates:
            _write_json(args.es, es_data)
            _write_json(args.en, en_data)
            print(f"\n[OK] Swaps aplicados y archivos reescritos: {total_swaps}")
        else:
            print("\n[OK] No se detectaron swaps para aplicar.")

    if args.summary and mismatches:
        counts: dict[str, int] = {}
        for outer_key, _inner_key, _reasons, _en_text, _es_text in mismatches:
            counts[outer_key] = counts.get(outer_key, 0) + 1
        top = sorted(counts.items(), key=lambda kv: (-kv[1], _num_sort_key(kv[0])))[: args.summary]
        print("\n-- Resumen por personaje (top) --")
        for outer_key, count in top:
            print(f"{outer_key}: {count}")

    if args.report_swaps and swap_candidates:
        print("\n-- Candidatas swap (primeros casos) --")
        for outer_key, inner_key, en_text, es_text in swap_candidates[: args.limit]:
            print(f"{outer_key}/{inner_key}: EN_lang='es' ES_lang='en'")
            if args.show_text:
                print("  EN:", en_text)
                print("  ES:", es_text)

    if double_escaped:
        print("\n-- Doble-escape (primeros casos) --")
        for outer_key, inner_key, msg in double_escaped[: args.limit]:
            print(f"{outer_key}/{inner_key}: {msg}")

    if missing:
        print("\n-- Claves faltantes (primeros casos) --")
        for outer_key, inner_key, msg in missing[: args.limit]:
            print(f"{outer_key}/{inner_key}: {msg}")

    if mismatches:
        print("\n-- Discrepancias (primeros casos) --")
        for outer_key, inner_key, reasons, en_text, es_text in mismatches[: args.limit]:
            print(f"{outer_key}/{inner_key}: " + "; ".join(reasons))
            if args.show_text:
                print("  EN:", en_text)
                print("  ES:", es_text)

    return 1 if (mismatches or missing or double_escaped) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
