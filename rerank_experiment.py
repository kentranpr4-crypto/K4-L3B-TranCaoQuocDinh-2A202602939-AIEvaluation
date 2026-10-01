"""Compare retrieval scores before and after question-based reranking."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from domain_assistant import BM25Retriever, load_corpus
from template import RAGASEvaluator, rerank_by_overlap


CASE_IDS = ("M02", "M06", "M07", "H01", "H05")
ROOT = Path(__file__).resolve().parent


def load_contexts(actual_path: Path, questions: dict[str, dict]) -> tuple[str, dict[str, list[str]]]:
    if actual_path.is_file():
        artifact = json.loads(actual_path.read_text(encoding="utf-8"))
        if artifact.get("corpus_id") != "orbittech-customer-support-v1":
            raise ValueError("Actual-answer artifact uses a different corpus")
        answers = {item["id"]: item for item in artifact["answers"]}
        contexts = {}
        for case_id in CASE_IDS:
            item = answers[case_id]
            if item["question"] != questions[case_id]["question"]:
                raise ValueError(f"Question differs between artifacts for {case_id}")
            contexts[case_id] = [chunk["text"] for chunk in item["retrieved_contexts"]]
        return str(actual_path), contexts

    corpus_id, chunks = load_corpus(ROOT / "data/technology_store")
    if corpus_id != "orbittech-customer-support-v1":
        raise ValueError("Corpus does not match the golden dataset")
    retriever = BM25Retriever(chunks)
    return "local BM25 retrieval (top_k=5; actual answers unavailable)", {
        case_id: [chunk.text for chunk in retriever.retrieve(questions[case_id]["question"], 5)]
        for case_id in CASE_IDS
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--actual",
        type=Path,
        default=ROOT / "artifacts/actual_answers.json",
        help="Use recorded retrieved contexts when the artifact exists",
    )
    args = parser.parse_args()

    golden = json.loads((ROOT / "golden_dataset.json").read_text(encoding="utf-8"))
    questions = {item["id"]: item for item in golden["qa_pairs"]}
    source, contexts_by_id = load_contexts(args.actual, questions)
    evaluator = RAGASEvaluator()
    rows = []
    for case_id in CASE_IDS:
        pair = questions[case_id]
        contexts = contexts_by_id[case_id]
        reranked = rerank_by_overlap(contexts, pair["question"])
        if Counter(reranked) != Counter(contexts):
            raise ValueError(f"Reranking changed the retrieved set for {case_id}")
        expected = pair["expected_answer"]
        rows.append((
            case_id,
            evaluator.evaluate_context_recall(contexts, expected),
            evaluator.evaluate_context_recall(reranked, expected),
            evaluator.evaluate_context_precision(contexts, expected),
            evaluator.evaluate_context_precision(reranked, expected),
        ))

    print(f"Source: {source}")
    print("Rerank query: question; reference answer is used only for scoring.")
    print("| ID | Recall before | Recall after | Precision before | Precision after | Delta Precision |")
    print("|---|---:|---:|---:|---:|---:|")
    for case_id, recall_before, recall_after, precision_before, precision_after in rows:
        print(
            f"| {case_id} | {recall_before:.3f} | {recall_after:.3f} | "
            f"{precision_before:.3f} | {precision_after:.3f} | "
            f"{precision_after - precision_before:+.3f} |"
        )
    count = len(rows)
    averages = [sum(row[index] for row in rows) / count for index in range(1, 5)]
    print(
        f"| **Avg** | {averages[0]:.3f} | {averages[1]:.3f} | "
        f"{averages[2]:.3f} | {averages[3]:.3f} | "
        f"{averages[3] - averages[2]:+.3f} |"
    )


if __name__ == "__main__":
    main()
