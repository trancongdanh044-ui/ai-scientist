"""Unit test các lưới chắn chất lượng: công thức, tài liệu tham khảo, số liệu thực nghiệm, BibTeX.
KHÔNG cần mạng/API key.   Chạy: python -m unittest tests.test_units -v"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tools import scholar_search as ss  # noqa: E402
from src.tools.arxiv_search import Paper  # noqa: E402
from src.tools.bibliography import assign_keys, protect_title, to_bibtex  # noqa: E402
from src.tools.experiments import (  # noqa: E402
    ExperimentResults, ResultsError, ablation_grid, allowed_numbers, count_missing, grid_table_tex,
    load_results, performance_grid, placeholder_grid, sensitivity_data, stats_grid,
    strip_unsupported_numbers,
)
from src.tools.latex_utils import process_sections, render_latex  # noqa: E402


def latex_of(text, keys=frozenset()):
    res = process_sections({"s": text}, set(keys))
    return render_latex(res.preps["s"]), res


class MathTests(unittest.TestCase):
    def test_display_math_normalised_to_numbered_equation(self):
        out, _ = latex_of("Intro $$a = b^2$$ and \\[ c = d \\] end.")
        self.assertEqual(out.count("\\begin{equation}"), 2)
        self.assertNotIn("$$", out)
        self.assertNotIn("\\[", out)

    def test_multiline_display_becomes_align(self):
        out, _ = latex_of("$$ a &= b \\\\ c &= d $$")
        self.assertIn("\\begin{align}", out)

    def test_broken_math_is_replaced_not_propagated(self):
        out, res = latex_of("Bad $\\frac{a}{b$ and good $x_i^2$ and \\[ \\left( x \\]")
        self.assertIn("$x_i^2$", out)
        self.assertEqual(len(res.bad_math), 2)
        self.assertNotIn("$\\frac{a}{b$", out)
        self.assertIn("\\texttt{", out)

    def test_unknown_command_is_caught(self):
        _, res = latex_of("\\[ x = \\notacommand{y} \\]")
        self.assertEqual(len(res.bad_math), 1)

    def test_currency_and_percent_are_escaped(self):
        out, _ = latex_of("It costs $5 and $10 for 50% of runs & more.")
        self.assertIn("\\$5 and \\$10", out)
        self.assertIn("50\\%", out)
        self.assertIn("\\&", out)

    def test_math_with_special_chars_is_fixed(self):
        out, res = latex_of("Rate $p = 5% + 3$ here.")
        self.assertFalse(res.bad_math)
        self.assertIn("5\\%", out)

    def test_dash_line_in_equation_is_not_a_bullet(self):
        out, _ = latex_of("Loss:\n$$\n- \\log p(x)\n$$")
        self.assertNotIn("\\item", out)

    def test_unknown_refs_dropped_known_kept(self):
        out, _ = latex_of("\\begin{equation} a=b \\label{eq:ok} \\end{equation} See Eq.~\\eqref{eq:ok}, "
                          "Eq.~\\eqref{eq:ghost}.")
        self.assertIn("\\eqref{eq:ok}", out)
        self.assertNotIn("ghost", out)

    def test_unknown_text_commands_cannot_break_compilation(self):
        out, _ = latex_of("Costs \\u2265 5 and \\madeup{x} but \\textbf{bold} and \\cite{k} stay.", {"k"})
        self.assertNotIn("\\madeup", out)
        self.assertNotIn("\\u2265", out)
        self.assertIn("\\textbf{bold}", out)
        self.assertIn("\\cite{k}", out)

    def test_math_symbol_in_prose_becomes_math(self):
        out, _ = latex_of("Gain \\geq 5 for \\alpha users.")
        self.assertIn("$\\geq$", out)
        self.assertIn("$\\alpha$", out)

    def test_fake_citations_removed(self):
        out, res = latex_of("Known \\cite{good} and unknown \\cite{bad}.", {"good"})
        self.assertIn("\\cite{good}", out)
        self.assertNotIn("bad}", out)
        self.assertEqual(res.removed_cites, ["bad"])


def _paper(title, year, doi="", citations=0, abstract="abs", **kw):
    return Paper(title=title, authors=["A B"], abstract=abstract, url=f"https://x/{title}",
                 published=f"{year}-01-01", doi=doi, citations=citations, **kw)


class ScholarTests(unittest.TestCase):
    def test_merge_dedupes_filters_year_and_ranks(self):
        a = _paper("Deep Models for X", 2023, doi="10.1/a", citations=50, source="semanticscholar",
                   venue="Proc. A", kind="conference")
        a_dup = _paper("Deep models for X!", 2023, doi="10.1/a", citations=70, source="openalex", abstract="")
        old = _paper("Ancient Method", 2010, doi="10.1/old", citations=9999)
        noabs = _paper("No Abstract Paper", 2024, doi="10.1/n", abstract="")
        noid = Paper(title="No Source", authors=[], abstract="x", url="", published="2024-01-01")
        out = ss.merge_and_rank([("semanticscholar", [a, old, noabs, noid]), ("openalex", [a_dup])],
                                min_year=2021, top_n=5)
        titles = [p.title for p in out]
        self.assertEqual(titles[0], "Deep Models for X")
        self.assertEqual(sum(1 for p in out if p.doi == "10.1/a"), 1)
        self.assertEqual(out[0].citations, 70)          # gộp: lấy số trích dẫn lớn hơn
        self.assertNotIn("Ancient Method", titles)      # lọc theo năm
        self.assertNotIn("No Source", titles)           # không có DOI/URL -> bỏ

    def test_parsers_handle_real_response_shapes(self):
        s2 = {"data": [{"title": "T1", "authors": [{"name": "Ann Lee"}], "year": 2023, "abstract": "abs",
                        "venue": "NeurIPS Conference", "externalIds": {"DOI": "10.5/x"},
                        "citationCount": 4, "url": "https://s2/1", "publicationTypes": ["Conference"],
                        "publicationDate": "2023-05-02"}]}
        oa = {"results": [{"title": "T2", "authorships": [{"author": {"display_name": "Bo Li"}}],
                           "publication_year": 2022, "doi": "https://doi.org/10.6/Y",
                           "primary_location": {"landing_page_url": "https://oa/2", "source":
                                                {"display_name": "Journal Z", "type": "journal"}},
                           "cited_by_count": 3, "abstract_inverted_index": {"Hello": [0], "world": [1]},
                           "publication_date": "2022-01-05"}]}
        cr = {"message": {"items": [{"DOI": "10.7/Z", "title": ["T3"], "author": [{"given": "C", "family": "D"}],
                                     "issued": {"date-parts": [[2024, 3]]}, "container-title": ["Proc. Q"],
                                     "type": "proceedings-article", "abstract": "<jats:p>Abs text</jats:p>",
                                     "is-referenced-by-count": 1, "URL": "https://doi.org/10.7/Z"}]}}
        with patch.object(ss, "_http_get_json", side_effect=[s2, oa, cr]):
            p1 = ss._semantic_scholar("q", 5, 2021)[0]
            p2 = ss._openalex("q", 5, 2021)[0]
            p3 = ss._crossref("q", 5, 2021)[0]
        self.assertEqual((p1.doi, p1.kind, p1.year), ("10.5/x", "conference", 2023))
        self.assertEqual((p2.doi, p2.abstract, p2.venue), ("10.6/y", "Hello world", "Journal Z"))
        self.assertEqual((p3.kind, p3.abstract, p3.year), ("conference", "Abs text", 2024))

    def test_dead_sources_do_not_crash(self):
        import asyncio
        with patch.object(ss, "_http_get_json", return_value=None), \
             patch.object(ss, "_arxiv_sync", side_effect=RuntimeError("down")):
            papers, report = asyncio.run(ss.search_literature(["q"], 5, 2021))
        self.assertEqual(papers, [])
        self.assertEqual(set(report.failed_sources), set(ss.SOURCES))


class ConfigPathTests(unittest.TestCase):
    def test_config_in_topic_folder_resolves_results_and_outputs_next_to_it(self):
        import os
        from src.config import load_config
        base = Path(tempfile.mkdtemp(prefix="topic_"))
        (base / "config.yaml").write_text(
            "llm: {model: m, temperature: 0.5, max_tokens: 100}\n"
            "research: {topic: T, num_papers: 3, max_hypotheses: 1}\n"
            "output: {dir: outputs, latex_template: x}\n"
            "paper: {results_file: results.json}\n", encoding="utf-8")
        old = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "x" * 30
        try:
            cfg = load_config(str(base / "config.yaml"))
        finally:
            if old is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old
        self.assertEqual(Path(cfg.paper.results_file), (base / "results.json").resolve())
        self.assertEqual(Path(cfg.output.dir), (base / "outputs").resolve())


class BibTests(unittest.TestCase):
    def test_protect_title_keeps_acronyms(self):
        t = protect_title("Adapting BERT with LoRA for Vietnamese NLP")
        self.assertIn("{BERT}", t)
        self.assertIn("{LoRA}", t)
        self.assertIn("{NLP}", t)

    def test_entry_types_and_doi(self):
        ps = assign_keys([
            _paper("Journal Paper", 2023, doi="10.1/j", venue="J. Tests", kind="journal"),
            _paper("Conf Paper", 2022, doi="10.1/c", venue="Proc. Tests", kind="conference"),
            _paper("Pre Print", 2024, arxiv_id="2401.00001", kind="preprint"),
        ])
        bib = to_bibtex(ps)
        self.assertIn("@article{", bib)
        self.assertIn("journal = {J. Tests}", bib)
        self.assertIn("@inproceedings{", bib)
        self.assertIn("booktitle = {Proc. Tests}", bib)
        self.assertIn("arXiv preprint arXiv:2401.00001", bib)
        self.assertEqual(bib.count("doi = {"), 2)


class ExperimentTests(unittest.TestCase):
    def _res(self):
        return ExperimentResults(
            ["D1"], ["Acc", "Lat"],
            [{"name": "Base", "scores": {"D1": {"Acc": {"mean": 0.91, "std": 0.004}, "Lat": 120.0}}},
             {"name": "Ours", "proposed": True, "scores": {"D1": {"Acc": {"mean": 0.93, "std": 0.003}, "Lat": 80.0}}}],
            {"Lat": False},
            significance=[{"dataset": "D1", "metric": "Acc", "baseline": "Base", "test": "t", "p": 0.004}],
            raw={"x": [0.91, 0.004, 0.93, 0.003, 120.0, 80.0, 0.004]})

    def test_best_bold_mean_std_and_dagger(self):
        (header, rows), daggers = performance_grid(self._res())
        self.assertTrue(daggers)
        self.assertEqual(rows[1][1][0], "0.930 ± 0.003†")      # mean ± std + dấu † (p < 0.05)
        self.assertTrue(rows[1][1][1])                          # Ours có Acc tốt nhất
        self.assertTrue(rows[1][2][1])                          # Ours có Latency thấp nhất (higher_is_better=False)
        self.assertFalse(rows[0][1][1])
        tex = grid_table_tex((header, rows), "cap", "tab:t")
        self.assertIn("$\\pm$", tex)
        self.assertIn("$^{\\dagger}$", tex)

    def test_no_dagger_without_significance(self):
        r = self._res()
        r.significance = []
        _, daggers = performance_grid(r)
        self.assertFalse(daggers)

    def test_guard_removes_invented_numbers_only(self):
        al = allowed_numbers(self._res())
        text = ("Ours reaches 0.93 on D1 (Table 1). It beats Base by 2.2%. RQ2 follows. "
                "It also gains 87.5% and uses 3 seeds on 55,187 users.")
        out, removed = strip_unsupported_numbers(text, al)
        self.assertIn("0.93", out)
        self.assertIn("2.2%", out)            # chênh lệch tính từ dữ liệu thật
        self.assertIn("RQ2", out)
        self.assertNotIn("87.5", out)
        self.assertNotIn("55,187", out)
        self.assertEqual(len(removed), 1)

    def test_load_results_validation(self):
        base = {"datasets": ["D"], "metrics": ["A"], "methods": [{"name": "M", "scores": {"D": {"A": 0.5}}}]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.json"
            self.assertIsNone(load_results(p))
            p.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ResultsError):
                load_results(p)
            bad = json.loads(json.dumps(base))
            bad["methods"][0]["scores"]["D"]["A"] = "high"
            p.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ResultsError):
                load_results(p)
            bad = {**base, "significance": [{"dataset": "D", "metric": "A", "baseline": "ghost", "p": 0.1}]}
            p.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ResultsError):
                load_results(p)
            bad = {**base, "sensitivity": {"values": [1, 2], "series": [{"name": "s", "values": [0.1]}]}}
            p.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ResultsError):
                load_results(p)
            good = {**base, "ablation": {"variants": [{"name": "v", "scores": {"A": 0.4}}]},
                    "sensitivity": {"parameter": "k", "metric": "A", "values": [1, 2],
                                    "series": [{"name": "s", "values": [0.1, 0.2]}]},
                    "dataset_stats": [{"name": "D", "fields": {"N": 1000}}]}
            p.write_text(json.dumps(good), encoding="utf-8")
            r = load_results(p)
            self.assertEqual(ablation_grid(r)[1][0][1][0], "0.400")
            self.assertEqual(sensitivity_data(r)[1], [1, 2])
            self.assertEqual(stats_grid(r)[1][0][1][0], "1,000")

    def test_example_file_is_refused_as_real_results(self):
        ex = Path(__file__).resolve().parent.parent / "results.example.json"
        with self.assertRaises(ResultsError):
            load_results(ex)

    def test_placeholder_grid_has_no_tbd_text(self):
        grid = placeholder_grid([{"metric": "F1 & Accuracy", "baseline": "Full FT"}])
        self.assertEqual(count_missing(grid), 4)
        tex = grid_table_tex(grid, "cap", "tab:t")
        self.assertNotIn("TBD", tex)
        self.assertIn("--", tex)


if __name__ == "__main__":
    unittest.main()
