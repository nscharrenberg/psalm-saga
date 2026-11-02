# Paper draft

The paper sections as Markdown, with formulas in LaTeX math (`$…$` inline, `$$…$$` display;
rendered by GitHub, GitLab, VS Code, Obsidian, Typora and pandoc). The living version is the
Claude Doc; these files are snapshots of it.

1. [Introduction](01-introduction.md)
2. [Background and related work](02-background.md)
3. [Methodology](03-methodology.md)
4. [Experimental setup](04-experimental-setup.md)
5. [Discussion: assumptions and limitations](05-discussion.md) (results and discussion to follow)
6. [Ethics and reproducibility statements](06-statements.md)

Appendix A: [Measures](07-appendix.md)

LaTeX (IEEEtran): [latex/](latex/) — every table in IEEEtran form, with a compile check.

To build a PDF: `pandoc docs/paper/0*.md -o paper.pdf --pdf-engine=xelatex` (Mermaid diagrams
need the `mermaid-filter` pandoc filter or a pre-rendered image).
