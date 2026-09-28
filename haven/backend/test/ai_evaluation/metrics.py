"""
metrics.py — pure standard-library classification metrics for the HAVEN AI
evaluation harness. NO numpy / sklearn (they are not installable in the build
sandbox), so every number here is computed from first principles and is exactly
reproducible.

Provides:
  * confusion_matrix(y_true, y_pred, labels)         -> dict[true][pred] = count
  * per_class_report(y_true, y_pred, labels)         -> per-label P/R/F1/support
  * macro / weighted / micro averages + overall accuracy
  * binary_report(y_true, y_pred, positive_label)    -> P/R/F1 + FPR/FNR + counts
  * text formatters for a confusion matrix and a per-class table

These operate on already-predicted labels; the harness (run_eval.py) is what
actually calls the deterministic subsystems. Keeping scoring separate from
prediction means the metrics are trivially auditable in isolation.
"""
from __future__ import annotations


def _safe_div(num: float, den: float) -> float:
    return (num / den) if den else 0.0


def confusion_matrix(y_true, y_pred, labels):
    """Return cm[true_label][pred_label] = count. Unlisted labels are ignored
    from the axes but still counted if they appear (added defensively)."""
    lab = list(labels)
    seen = set(lab)
    for y in list(y_true) + list(y_pred):
        if y not in seen:
            lab.append(y)
            seen.add(y)
    cm = {t: {p: 0 for p in lab} for t in lab}
    for t, p in zip(y_true, y_pred):
        cm[t][p] += 1
    return cm, lab


def per_class_report(y_true, y_pred, labels):
    """One-vs-rest precision/recall/F1/support for each label, plus macro,
    weighted, and micro averages and overall accuracy. All from raw counts."""
    cm, lab = confusion_matrix(y_true, y_pred, labels)
    total = len(y_true)
    correct = sum(cm[l][l] for l in lab)
    rows = {}
    for l in lab:
        tp = cm[l][l]
        fp = sum(cm[t][l] for t in lab if t != l)
        fn = sum(cm[l][p] for p in lab if p != l)
        support = sum(cm[l][p] for p in lab)
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        rows[l] = {"precision": precision, "recall": recall, "f1": f1,
                   "support": support, "tp": tp, "fp": fp, "fn": fn}
    present = [l for l in lab if rows[l]["support"] > 0]
    n_present = len(present) or 1
    macro = {k: _safe_div(sum(rows[l][k] for l in present), n_present)
             for k in ("precision", "recall", "f1")}
    wsupport = sum(rows[l]["support"] for l in present) or 1
    weighted = {k: _safe_div(sum(rows[l][k] * rows[l]["support"] for l in present), wsupport)
                for k in ("precision", "recall", "f1")}
    accuracy = _safe_div(correct, total)
    return {"per_class": rows, "labels": lab, "macro": macro, "weighted": weighted,
            "accuracy": accuracy, "n": total, "correct": correct,
            "micro": {"precision": accuracy, "recall": accuracy, "f1": accuracy}}


def binary_report(y_true, y_pred, positive_label):
    """Full binary metrics treating `positive_label` as the positive class.
    Reports recall (sensitivity), precision, F1, specificity, and — critically
    for a safety system — FPR (false-alarm rate) and FNR (missed-crisis rate)."""
    tp = fp = tn = fn = 0
    for t, p in zip(y_true, y_pred):
        t_pos = (t == positive_label)
        p_pos = (p == positive_label)
        if t_pos and p_pos:
            tp += 1
        elif not t_pos and p_pos:
            fp += 1
        elif not t_pos and not p_pos:
            tn += 1
        else:
            fn += 1
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)          # sensitivity / true-positive rate
    specificity = _safe_div(tn, tn + fp)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {"positive_label": positive_label, "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": precision, "recall": recall, "specificity": specificity,
            "f1": f1, "fpr": _safe_div(fp, fp + tn), "fnr": _safe_div(fn, fn + tp),
            "accuracy": _safe_div(tp + tn, tp + fp + tn + fn), "n": tp + fp + tn + fn}


def _pct(x: float) -> str:
    return f"{100 * x:6.2f}%"


def format_confusion(cm, lab, title="Confusion matrix (rows=true, cols=pred)"):
    w = max([len(str(l)) for l in lab] + [5])
    head = " " * (w + 2) + "".join(f"{str(l)[:w]:>{w+2}}" for l in lab)
    lines = [title, head]
    for t in lab:
        row = f"{str(t):>{w}} |" + "".join(f"{cm[t][p]:>{w+2}}" for p in lab)
        lines.append(row)
    return "\n".join(lines)


def format_multiclass(report, title="Per-class metrics"):
    lab = [l for l in report["labels"] if report["per_class"][l]["support"] > 0]
    w = max([len(str(l)) for l in lab] + [12])
    lines = [title,
             f"{'label':>{w}} {'precision':>10} {'recall':>10} {'f1':>10} {'support':>8}"]
    for l in lab:
        r = report["per_class"][l]
        lines.append(f"{str(l):>{w}} {_pct(r['precision']):>10} {_pct(r['recall']):>10} "
                     f"{_pct(r['f1']):>10} {r['support']:>8}")
    m, wa = report["macro"], report["weighted"]
    lines.append(f"{'macro avg':>{w}} {_pct(m['precision']):>10} {_pct(m['recall']):>10} "
                 f"{_pct(m['f1']):>10} {report['n']:>8}")
    lines.append(f"{'weighted avg':>{w}} {_pct(wa['precision']):>10} {_pct(wa['recall']):>10} "
                 f"{_pct(wa['f1']):>10} {report['n']:>8}")
    lines.append(f"accuracy = {_pct(report['accuracy'])}  ({report['correct']}/{report['n']})")
    return "\n".join(lines)
